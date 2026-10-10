"""Parser for IGB sports wagering accrual "Detail Report" CSVs (one per month).

Rows are (sport level, location type, licensee) with tier 1 (straight) and
tier 2 (parlay) wagers/handle/payout. We keep Online Wagering rows, skip the
pre-aggregated Total rows, and sum across sport levels and tiers:

    handle        = Σ tier1_handle + tier2_handle
    gross_revenue = handle − Σ payouts   (IGB reports no promo split)

The file's own month header is cross-checked against the month the caller
requested — the report app silently returns whatever range it likes if a form
regression ever slips in, and that must fail loudly, not corrupt a month.
"""

from __future__ import annotations

import csv
import datetime as dt
from calendar import monthrange
from pathlib import Path

import pandas as pd

from ggr.operators import canonicalize_dated
from ggr.schema import tidy_frame

EXPECTED_HEADER = ["Sport Level", "Location Type", "Licensee"]


def _number(text: str) -> float:
    text = text.strip().replace(",", "").replace("$", "")
    if not text:
        return 0.0
    if text.startswith("(") and text.endswith(")"):
        return -float(text[1:-1])
    return float(text)


def parse_csv(path: Path, year: int, month: int, source_url: str) -> pd.DataFrame:
    fetched_at = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    rows = list(csv.reader(path.read_text(errors="replace").splitlines()))

    stated = " ".join(cell for row in rows[:4] for cell in row)
    expected = f"{dt.date(year, month, 1):%B %Y}"
    if expected not in stated:
        raise ValueError(f"{path.name}: expected {expected!r} in report header, got {stated[:120]!r}")

    header_idx = next(
        (i for i, row in enumerate(rows) if row[: len(EXPECTED_HEADER)] == EXPECTED_HEADER), None
    )
    if header_idx is None:
        raise ValueError(f"{path.name}: detail header row not found")

    by_licensee: dict[str, dict[str, float]] = {}
    for row in rows[header_idx + 1 :]:
        if len(row) < 9 or row[1] != "Online Wagering":
            continue
        sport, _, licensee = row[0], row[1], row[2].strip()
        if sport.lower() == "total" or licensee.lower() == "total":
            continue
        agg = by_licensee.setdefault(licensee, {"handle": 0.0, "payout": 0.0})
        agg["handle"] += _number(row[4]) + _number(row[7])
        agg["payout"] += _number(row[5]) + _number(row[8])

    period_start = dt.date(year, month, 1)
    period_end = dt.date(year, month, monthrange(year, month)[1])
    tidy_rows = [
        {
            "state": "IL",
            "period_start": period_start,
            "period_end": period_end,
            "operator_raw": licensee,
            "operator_canonical": canonicalize_dated(licensee, "IL", period_end),
            "product": "osb",
            "handle": agg["handle"],
            "gross_revenue": agg["handle"] - agg["payout"],
            "source_url": source_url,
            "fetched_at": fetched_at,
        }
        for licensee, agg in by_licensee.items()
    ]
    df = tidy_frame(tidy_rows) if tidy_rows else tidy_frame([])
    if len(df):
        unknown = df.loc[df["operator_canonical"].isna(), "operator_raw"].unique()
        if len(unknown):
            raise ValueError(
                f"{path.name}: unknown operators {sorted(unknown)} — add to ggr.operators"
            )
    return df.sort_values("operator_raw").reset_index(drop=True) if len(df) else df


def month_range(start: tuple[int, int], end_exclusive: dt.date) -> list[tuple[int, int]]:
    """(year, month) pairs from start through the last fully completed month."""
    months = []
    year, month = start
    while dt.date(year, month, 1) < end_exclusive.replace(day=1):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months
