"""Michigan — MGCB monthly internet sports betting and internet gaming files.

One cumulative XLSX per calendar year per product, updated monthly around the
10th. Fetched via the Wayback Machine (see ggr.wayback for why). Because each
year's file also contains the prior year as a comparison sheet, the same
month can appear in two files; the later file wins so revisions propagate.

Run ``uv run python -m ggr.ingest.mi`` to write data/processed/mi_monthly.parquet.
"""

from __future__ import annotations

import pandas as pd

from ggr import cache, wayback
from ggr.config import DATA_PROCESSED
from ggr.parse.mi import parse_workbook

BASE = "https://www.michigan.gov/mgcb/-/media/Project/Websites/mgcb/Detroit-Casino-Revenue-Files/"

# Discovery is manual: the WAF blocks the listing page, and filenames changed
# convention twice. Verified against the Wayback CDX index (November 2026).
FILES = {
    ("osb", 2021): "Internet_Sports_Betting_revenue_716520_7.xlsx",
    ("osb", 2022): "Internet_Sports_Betting_-_January_2022_748264_7.xlsx",
    ("osb", 2023): "Internet-Sports-Betting-January-2023.xlsx",
    ("osb", 2024): "Internet-Sports-Betting---2024.xlsx",
    ("osb", 2025): "Internet-Sports-Betting---2025.xlsx",
    ("osb", 2026): "Internet-Sports-Betting---2026.xlsx",
    ("igaming", 2021): "Internet_Gaming_-_revenue_716517_7.xlsx",
    ("igaming", 2022): "Internet_Gaming_-_Jan_2022_748263_7.xlsx",
    ("igaming", 2023): "Internet-Gaming-January-2023.xlsx",
    ("igaming", 2024): "Internet-Gaming---2024.xlsx",
    ("igaming", 2025): "Internet-Gaming---2025.xlsx",
    ("igaming", 2026): "Internet-Gaming---2026.xlsx",
}


def combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge per-file frames (each tagged ``_file_year``); the later file wins.

    A month printed in two files is taken whole from the later one. Matching
    rows by operator name is not safe: MGCB relabels columns between files
    (the 2025 file calls the Hannahville column "TwinSpires", the 2026 file's
    2025 sheet calls it "Hard Rock"), which would keep both copies. The later
    file must carry at least as many operators for the month as the earlier
    one, or a dropped column would vanish silently.
    """
    combined = pd.concat(frames, ignore_index=True)
    month = ["product", "period_end"]
    rows = combined.groupby([*month, "_file_year"]).size().rename("n").reset_index()
    latest = rows.loc[rows.groupby(month)["_file_year"].idxmax()]
    widest = rows.groupby(month)["n"].max().rename("n_max").reset_index()
    short = latest.merge(widest, on=month).query("n < n_max")
    if len(short):
        raise ValueError(f"later MI file has fewer operators than an earlier one:\n{short}")
    keep = combined.merge(latest[[*month, "_file_year"]], on=[*month, "_file_year"])
    return (
        keep.drop(columns="_file_year")
        .sort_values(["period_end", "product", "operator_canonical"])
        .reset_index(drop=True)
    )


def build() -> pd.DataFrame:
    frames = []
    for (product, file_year), filename in sorted(FILES.items(), key=lambda kv: kv[0][1]):
        timestamp, original = wayback.latest_snapshot(BASE + filename)
        url = wayback.raw_url(timestamp, original)
        df = parse_workbook(cache.fetch(url, subdir="mi"), product, url)
        frames.append(df.assign(_file_year=file_year))
    return combine(frames)


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
