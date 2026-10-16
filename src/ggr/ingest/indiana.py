"""Indiana — IGC monthly revenue workbooks, per-skin online sports detail.

One XLSX per month at a fully predictable URL
(``in.gov/igc/files/reports/{year}/{year}-{month:02d}-Revenue.xlsx``), sports
wagering since September 2019. A month that 404s is unpublished if recent
(IGC posts ~2 weeks after month end) and an error if old.

Run ``uv run python -m ggr.ingest.indiana`` to write
data/processed/in_monthly.parquet.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pandas as pd

from ggr import cache
from ggr.config import DATA_PROCESSED
from ggr.parse.il import month_range
from ggr.parse.indiana import parse_workbook

URL_PATTERN = "https://www.in.gov/igc/files/reports/{year}/{year}-{month:02d}-Revenue.xlsx"
# Retail launched Sep 2019, online (DraftKings first) in October — the Sep
# file has no skin rows, so the online-only scope starts at October.
FIRST_MONTH = (2019, 10)
UNPUBLISHED_GRACE_DAYS = 75


def build() -> pd.DataFrame:
    frames = []
    for year, month in month_range(FIRST_MONTH, dt.date.today()):
        url = URL_PATTERN.format(year=year, month=month)
        try:
            path = cache.fetch(url, subdir="in")
        except httpx.HTTPStatusError as e:
            age = (dt.date.today() - dt.date(year, month, 1)).days
            if e.response.status_code == 404 and age < UNPUBLISHED_GRACE_DAYS:
                print(f"note: {year}-{month:02d} not yet published, skipping")
                continue
            raise
        frames.append(parse_workbook(path, year, month, url))
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    df = build()
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "in_monthly.parquet"
    df.to_parquet(out, index=False)
    summary = (
        df.groupby("operator_canonical")
        .agg(months=("period_end", "count"), gross=("gross_revenue", "sum"))
        .sort_values("gross", ascending=False)
        .head(14)
    )
    print(summary.assign(gross=lambda d: (d["gross"] / 1e6).round(1)).to_string())
    print(f"\nrange: {df.period_end.min():%Y-%m} → {df.period_end.max():%Y-%m}")
    print(f"wrote {len(df)} skin-months to {out}")


if __name__ == "__main__":
    main()
