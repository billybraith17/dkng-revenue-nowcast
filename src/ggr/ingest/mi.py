"""Michigan — MGCB monthly internet sports betting and internet gaming files.

One cumulative XLSX per calendar year per product, updated monthly around the
10th. Fetched via the Wayback Machine (see ggr.wayback for why). Because each
year's file also contains the prior year as a comparison sheet, the same
(month, operator) can appear in two files; the later file wins so revisions
propagate.

Run ``uv run python -m ggr.ingest.mi`` to write data/processed/mi_monthly.parquet.
"""

from __future__ import annotations

import pandas as pd

from ggr import cache, wayback
from ggr.config import DATA_PROCESSED
from ggr.parse.mi import parse_workbook

BASE = (
    "https://www.michigan.gov/mgcb/-/media/Project/Websites/mgcb/"
    "Detroit-Casino-Revenue-Files/"
)

# Discovery is manual: the WAF blocks the listing page, and filenames changed
# convention twice. Verified against the Wayback CDX index (July 2026).
FILES = {
    ("osb", 2021): "Internet_Sports_Betting_revenue_716520_7.xlsx",
    ("osb", 2022): "Internet_Sports_Betting_-_January_2022_748264_7.xlsx",
    ("osb", 2023): "Internet-Sports-Betting-January-2023.xlsx",
    ("osb", 2024): "Internet-Sports-Betting---2024.xlsx",
    ("osb", 2025): "Internet-Sports-Betting---2025.xlsx",
    ("igaming", 2021): "Internet_Gaming_-_revenue_716517_7.xlsx",
    ("igaming", 2022): "Internet_Gaming_-_Jan_2022_748263_7.xlsx",
    ("igaming", 2023): "Internet-Gaming-January-2023.xlsx",
    ("igaming", 2024): "Internet-Gaming---2024.xlsx",
    ("igaming", 2025): "Internet-Gaming---2025.xlsx",
}


def build() -> pd.DataFrame:
    frames = []
    for (product, file_year), filename in sorted(FILES.items(), key=lambda kv: kv[0][1]):
        timestamp, original = wayback.latest_snapshot(BASE + filename)
        url = wayback.raw_url(timestamp, original)
        df = parse_workbook(cache.fetch(url, subdir="mi"), product, url)
        frames.append(df.assign(_file_year=file_year))
    combined = pd.concat(frames, ignore_index=True).sort_values("_file_year")
    # Key on operator_raw, not canonical: distinct skins can share a canonical
    # brand in the same month (William Hill + Caesars in 2021) and must both
    # survive; this dedupe only collapses the same filing seen in two files.
    combined = combined.drop_duplicates(
        ["state", "product", "period_end", "operator_raw"], keep="last"
    )
    return combined.drop(columns="_file_year").sort_values(
        ["period_end", "product", "operator_canonical"]
    ).reset_index(drop=True)


def main() -> None:
    df = build()
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "mi_monthly.parquet"
    df.to_parquet(out, index=False)
    summary = (
        df.groupby(["product", "operator_canonical"])
        .agg(months=("period_end", "count"), gross=("gross_revenue", "sum"))
        .sort_values("gross", ascending=False)
        .head(12)
    )
    print(summary.assign(gross=lambda d: (d["gross"] / 1e6).round(1)).to_string())
    print(f"\nrange: {df.period_end.min():%Y-%m} → {df.period_end.max():%Y-%m}")
    print(f"wrote {len(df)} operator-months to {out}")


if __name__ == "__main__":
    main()
