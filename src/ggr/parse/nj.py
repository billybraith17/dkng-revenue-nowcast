"""Parser for NJ DGE monthly sports wagering tax return PDFs.

Each monthly PDF is a stack of per-licensee tax returns (one to two pages
each): the licensee name sits directly above "MONTHLY SPORTS WAGERING TAX
RETURN FOR THE MONTH OF {MONTH} {YEAR}", followed by a Retail section and an
Online section of numbered lines. We take the Online section's "Monthly
Online Sports Wagering Gross Revenue" line — matched by label, not line
number, and carefully excluding the near-identical "Year-to-Date …",
"Last Month's …" and "Monthly Taxable …" lines.

PDF text-extraction quirks handled here (all seen in real files):
- digits with stray internal spaces ("1 4,357,001");
- parenthesised negatives ("(29,927)") — a bad-hold month, kept negative;
- "-" meaning zero;
- the same licensee filing twice in one month (Tropicana) — summed;
- the stated month is cross-checked against the month the caller requested.

NJ reports gross revenue only (no handle, no online promo split), and revenue
is per *licensee*: skins blend (the plan's known NJ caveat). Resorts Digital
≈ DraftKings, Meadowlands ≈ FanDuel, Borgata ≈ BetMGM; the rest keep entity
slugs — see ggr.operators for the mapping rationale.
"""

from __future__ import annotations

import datetime as dt
import re
from calendar import monthrange
from pathlib import Path

import pandas as pd
import pdfplumber

from ggr.operators import canonicalize_dated
from ggr.schema import tidy_frame

# The title and the month sit on separate extracted lines. Variants seen:
# "FOR THE MONTH OF JUNE 2024", "… OF JUNE, 2018", "FOR THE MONTH ENDED
# JANUARY, 2020" (Ocean), and mid-month launch returns like "FOR THE PERIOD
# OF JANUARY 26-31, 2019" (Hard Rock).
RETURN_TITLE = "MONTHLY SPORTS WAGERING TAX RETURN"
# (?:\s+OF)* because "FOR THE MONTH OF OF FEBRUARY 2026" appears in the wild.
RETURN_MONTH = re.compile(
    r"FOR THE (?:MONTH|PERIOD)(?:\s+ENDED)?(?:\s+OF)*\s+([A-Z]+)[\s\d\-–,]*?(\d{4})?$",
    re.MULTILINE,
)
# The monthly-gross line inside the ONLINE section. Matching is
# section-scoped, not label-scoped, because the label wording changed four
# times (2018 "Current Month Internet …" → "Monthly Internet …" → "Monthly
# Online Sports Wagering …" → 2026 "Monthly Online Sportsbook …") AND some
# filings mislabel the internet section's lines as "Retail" (Ocean, June
# 2019) — only the section heading is trustworthy. The Year-to-Date /
# Last Month's / Taxable / Adjustments lines can't match this pattern.
ONLINE_VALUE = re.compile(
    r"^\d+\s+(?:Monthly|Current Month)\s+(?:Retail\s+|Internet\s+|Online\s+)?"
    r"(?:Sports Wagering|Sportsbook) Gross Revenue\s+\$?\s*(.+?)\s*$"
)


# Misspellings that appear in real filings; anything else still fails loudly.
MONTH_MISSPELLINGS = {"JANAURY": "JANUARY"}

ONLINE_SECTION_MARKERS = (
    "SPORTS WAGERING - INTERNET",
    "SPORTS WAGERING - ONLINE",
    "ONLINE SPORTSBOOK",
)


def _online_section(lines: list[str]) -> list[str] | None:
    """Lines from the online-section heading onward, or None if no section."""
    for i, ln in enumerate(lines):
        if any(marker in ln.upper() for marker in ONLINE_SECTION_MARKERS):
            return lines[i:]
    return None


def _number(text: str) -> float:
    text = text.replace(" ", "").replace("$", "").replace(",", "").strip()
    if text in ("", "-"):
        return 0.0
    if text.startswith("(") and text.endswith(")"):
        return -float(text[1:-1])
    return float(text)


def parse_pdf(path: Path, year: int, month: int, source_url: str) -> pd.DataFrame:
    fetched_at = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    expected_month = f"{dt.date(year, month, 1):%B} {year}".upper()

    # A return spans its header page plus any following continuation pages
    # (the online section often spills past the retail section's page), so
    # group pages by header before extracting values.
    returns: list[tuple[str, list[str]]] = []  # (licensee, all lines of the return)
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = text.splitlines()
            # From Jan 2024 each licensee also files an "ONLINE SPORTS
            # WAGERING SKIN DETAIL REPORT" page (per-skin split!). Skipped
            # here so it doesn't double-count as a continuation page —
            # parsing it for true operator-level NJ data is a planned
            # enhancement.
            if "SKIN DETAIL REPORT" in text.upper():
                continue
            header_idx = next(
                (i for i, ln in enumerate(lines) if RETURN_TITLE in ln.upper()), None
            )
            if header_idx is None:
                if not returns:
                    raise ValueError(f"{path.name}: continuation page before any return header")
                if returns[-1][1] is not None:
                    returns[-1][1].extend(lines)
                continue
            stated = RETURN_MONTH.search(text.upper())
            if stated is None:
                raise ValueError(f"{path.name}: return page without a month statement")
            # Some returns omit the year ("FOR THE MONTH OF DECEMBER", Hard
            # Rock 2022) — the month must always match, the year when present.
            stated_month, stated_year = stated.group(1), stated.group(2)
            stated_month = MONTH_MISSPELLINGS.get(stated_month, stated_month)
            expected_name, expected_year = expected_month.split()
            if stated_month != expected_name or (stated_year and stated_year != expected_year):
                raise ValueError(
                    f"{path.name}: return is for {stated_month} {stated_year}, "
                    f"expected {expected_month}"
                )
            if header_idx == 0:
                raise ValueError(f"{path.name}: licensee line missing above return header")
            # ~2019-2021 files include separate returns titled
            # "… TAX RETURN - RETAIL"; those legitimately have no online line.
            if "RETAIL" in lines[header_idx].upper().split(RETURN_TITLE)[-1]:
                returns.append((lines[header_idx - 1].strip(), None))
                continue
            returns.append((lines[header_idx - 1].strip(), list(lines)))

    by_licensee: dict[str, float] = {}
    for licensee, lines in returns:
        if lines is None:  # retail-only return ("… TAX RETURN - RETAIL")
            continue
        online_lines = _online_section(lines)
        if online_lines is None:
            # Pre-launch returns (e.g. Ocean, June 2019 has no internet
            # section at all) — genuinely retail-only, not an extraction failure.
            continue
        online = [m for ln in online_lines if (m := ONLINE_VALUE.match(ln))]
        if len(online) != 1:
            raise ValueError(
                f"{path.name}: expected 1 online gross revenue line for "
                f"{licensee!r}, found {len(online)}"
            )
        by_licensee[licensee] = by_licensee.get(licensee, 0.0) + _number(online[0].group(1))

    if not by_licensee:
        raise ValueError(f"{path.name}: no sports wagering returns found")

    period_start = dt.date(year, month, 1)
    period_end = dt.date(year, month, monthrange(year, month)[1])
    df = tidy_frame(
        [
            {
                "state": "NJ",
                "period_start": period_start,
                "period_end": period_end,
                "operator_raw": licensee,
                "operator_canonical": canonicalize_dated(licensee, "NJ", period_end),
                "product": "osb",
                "gross_revenue": gross,
                "source_url": source_url,
                "fetched_at": fetched_at,
            }
            for licensee, gross in by_licensee.items()
        ]
    )
    unknown = df.loc[df["operator_canonical"].isna(), "operator_raw"].unique()
    if len(unknown):
        raise ValueError(f"{path.name}: unknown operators {sorted(unknown)} — add to ggr.operators")
    return df.sort_values("operator_raw").reset_index(drop=True)
