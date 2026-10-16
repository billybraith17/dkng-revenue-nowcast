"""Parser for Iowa IRGC sports wagering revenue report PDFs.

Two table styles, both column-banded with wrapped header names:

- Casino table (all eras): casinos as columns, RETAIL/INTERNET metric rows.
- "ONLINE SPORTS WAGERING BY OPERATOR" section (~mid-2023 onward): operator
  *entities* as columns ("Crown IA Gaming, LLC" = DraftKings, "Betfair
  Interactive US LLC" = FanDuel, "Hillside (Iowa) LLC" = bet365…) — true
  operator-level data.

When the by-operator section exists we emit it and use the casino table only
as a cross-check (their internet totals must agree); older reports fall back
to casino-licensee rows (skins blend per casino, like NJ).

Extraction is positional (pdfplumber words → lines → bands): a band is the
INTERNET NET RECEIPTS / HANDLE / PAYOUTS rows plus the wrapped name lines
above them; the handle row's dollar values define column x-centers and name
words snap to the nearest center. Fiscal-year archive files are the twelve
monthly reports concatenated behind an FYTD summary (skipped), so one parser
serves both.
"""

from __future__ import annotations

import datetime as dt
import re
from calendar import monthrange
from pathlib import Path

import pandas as pd
import pdfplumber

from ggr.operators import canonicalize
from ggr.schema import tidy_frame

TITLE = re.compile(r"SPORTS WAGERING REVENUE REPORT\s*-+\s*([A-Z]+)\s+(\d{4})")
BY_OPERATOR = re.compile(r"SPORTS WAGERING BY OPERATOR")
MONTH_NUM = {m.upper(): i + 1 for i, m in enumerate(
    "January February March April May June July August September October November December".split()
)}
METRIC_PREFIXES = ("SPORTS WAGERING", "RETAIL", "INTERNET", "STATE TAX")
FOOTNOTE_CHARS = str.maketrans("", "", "¹²³⁴⁵⁶⁷⁸*")
CROSS_CHECK_TOLERANCE = 1.0


def _number(text: str) -> float:
    text = text.replace("$", "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        return -float(text[1:-1])
    return float(text)


def _is_value(text: str) -> bool:
    return text.lstrip("-($").rstrip(")").replace(",", "").replace(".", "").isdigit()


def _cluster_centers(words: list[dict], tolerance: float = 15.0) -> list[float]:
    """Distinct column x-centers from value words, merged within tolerance."""
    centers: list[list[float]] = []
    for mid in sorted((w["x0"] + w["x1"]) / 2 for w in words):
        if centers and mid - centers[-1][-1] <= tolerance:
            centers[-1].append(mid)
        else:
            centers.append([mid])
    return [sum(c) / len(c) for c in centers]


def _snap(words: list[dict], centers: list[float]) -> list[dict | None]:
    """Assign each value word to its column; None where a column is blank."""
    out: list[dict | None] = [None] * len(centers)
    for w in words:
        mid = (w["x0"] + w["x1"]) / 2
        nearest = min(range(len(centers)), key=lambda i: abs(centers[i] - mid))
        if out[nearest] is not None:
            raise ValueError("two values snapped to one column — layout drift")
        out[nearest] = w
    return out


def _lines(page) -> list[list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for w in page.extract_words():
        grouped.setdefault(round(w["top"] / 3), []).append(w)
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in sorted(grouped.items())]


def _line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def _bands(lines: list[list[dict]]) -> list[tuple[list[str], list[float], list[float]]]:
    """(column names, internet receipts, internet handles) per band."""
    bands = []
    name_lines: list[list[dict]] = []
    receipts: list[dict] | None = None
    for line in lines:
        # One file's font extracts the leading "I" of INTERNET as "\"
        text = _line_text(line).upper().replace("\\NTERNET", "INTERNET")
        if "REVENUE REPORT" in text or BY_OPERATOR.search(text):
            continue
        if text.startswith("INTERNET NET RECEIPTS"):
            receipts = [w for w in line if _is_value(w["text"])]
            continue
        if text.startswith("INTERNET HANDLE"):
            if receipts is None:
                raise ValueError("INTERNET HANDLE row without preceding NET RECEIPTS")
            handle_words = [w for w in line if _is_value(w["text"])]
            if not receipts:
                raise ValueError("empty INTERNET NET RECEIPTS row")
            # Blank cells occur (a $0 casino may print no handle at all), so
            # values align to column x-positions, never to list order.
            centers = _cluster_centers(receipts + handle_words)
            rec_by_col = _snap(receipts, centers)
            han_by_col = _snap(handle_words, centers)
            parts: list[list[str]] = [[] for _ in centers]
            for nl in name_lines:
                # Group words into segments at column-gutter-sized gaps so
                # multi-word names travel together instead of drifting
                # word-by-word into neighbouring columns.
                segments: list[list[dict]] = [[nl[0]]]
                for prev, w in zip(nl, nl[1:]):
                    if w["x0"] - prev["x1"] > 6:
                        segments.append([])
                    segments[-1].append(w)
                for seg in segments:
                    mid = (seg[0]["x0"] + seg[-1]["x1"]) / 2
                    nearest = min(range(len(centers)), key=lambda i: abs(centers[i] - mid))
                    parts[nearest].append(" ".join(w["text"] for w in seg))
            # Footnote markers survive extraction as superscript chars, glued
            # digits ("Marquette1") or stray digit tokens ("- 1 Clinton").
            names = [
                re.sub(
                    r"\s+", " ",
                    re.sub(r"(?<=[A-Za-z])\d+|\b\d+\b", "", " ".join(p).translate(FOOTNOTE_CHARS)),
                ).strip()
                for p in parts
            ]
            bands.append(
                (
                    names,
                    [_number(w["text"]) if w else None for w in rec_by_col],
                    [_number(w["text"]) if w else None for w in han_by_col],
                )
            )
            name_lines, receipts = [], None
            continue
        if any(text.startswith(p) for p in METRIC_PREFIXES):
            continue
        if line and not all(_is_value(w["text"]) for w in line):
            name_lines.append(line)
    return bands


def _is_amendment_band(names: list[str]) -> bool:
    joined = " ".join(names).upper()
    return "AMENDMENT" in joined or "AS FOLLOWS" in joined


def parse_report(pages, year: int, month: int, source_url: str, fetched_at: str) -> list[dict]:
    casino_bands, operator_bands = [], []
    for page in pages:
        lines = _lines(page)
        split = next(
            (i for i, ln in enumerate(lines) if BY_OPERATOR.search(_line_text(ln).upper())), None
        )
        if split is None:
            casino_bands += _bands(lines)
        else:
            casino_bands += _bands(lines[:split])
            operator_bands += _bands(lines[split:])
    # Some reports append an amendments footnote table (prior-month
    # corrections restating earlier figures) — not current-month revenue.
    # Revisions reach us through the FY archive refetches instead.
    casino_bands = [b for b in casino_bands if not _is_amendment_band(b[0])]
    operator_bands = [b for b in operator_bands if not _is_amendment_band(b[0])]

    chosen = operator_bands or casino_bands
    if not chosen:
        raise ValueError("no internet bands found")
    if operator_bands:
        operator_total = sum(
            v for _, receipts, _ in operator_bands for v in receipts if v is not None
        )
        named_total = sum(
            r for names, receipts, _ in casino_bands
            for n, r in zip(names, receipts)
            if r is not None and "TOTAL" not in n.upper()
        )
        if abs(named_total - operator_total) > CROSS_CHECK_TOLERANCE:
            raise ValueError(
                f"casino vs operator internet totals differ: {named_total:.2f} "
                f"vs {operator_total:.2f}"
            )

    records = []
    for names, receipts, handles in chosen:
        for name, gross, handle in zip(names, receipts, handles):
            if not name or "TOTAL" in name.upper():
                continue
            if gross is None and handle is None:
                continue
            records.append(
                {
                    "state": "IA",
                    "period_start": dt.date(year, month, 1),
                    "period_end": dt.date(year, month, monthrange(year, month)[1]),
                    "operator_raw": name,
                    "operator_canonical": canonicalize(name),
                    "product": "osb",
                    "handle": handle,
                    "gross_revenue": gross,
                    "source_url": source_url,
                    "fetched_at": fetched_at,
                }
            )
    return records


def _parse_section(section, section_month, source_url, fetched_at, path) -> list[dict]:
    year, month = section_month
    try:
        return parse_report(section, year, month, source_url, fetched_at)
    except ValueError as e:
        raise ValueError(f"{path.name} [{year}-{month:02d}]: {e}") from e


def parse_pdf(path: Path, source_url: str) -> pd.DataFrame:
    """Parse every monthly report in the file (monthly or FY archive)."""
    fetched_at = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    records = []
    with pdfplumber.open(path) as pdf:
        section: list = []
        section_month: tuple[int, int] | None = None
        for page in pdf.pages:
            text = (page.extract_text() or "").upper()
            title = TITLE.search(text)
            if title:
                if section and section_month:
                    records += _parse_section(section, section_month, source_url, fetched_at, path)
                section, section_month = [], None
                if title.group(1) in MONTH_NUM:
                    section_month = (int(title.group(2)), MONTH_NUM[title.group(1)])
            if section_month:
                section.append(page)
        if section and section_month:
            records += _parse_section(section, section_month, source_url, fetched_at, path)

    if not records:
        raise ValueError(f"{path.name}: no monthly report sections found")
    df = tidy_frame(records)
    unknown = df.loc[df["operator_canonical"].isna(), "operator_raw"].unique()
    if len(unknown):
        raise ValueError(f"{path.name}: unknown operators {sorted(unknown)} — add to ggr.operators")
    return df.sort_values(["period_end", "operator_raw"]).reset_index(drop=True)
