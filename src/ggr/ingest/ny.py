"""New York — mobile sports wagering weekly reports (the crown jewel source).

The NY State Gaming Commission publishes one cumulative XLSX per mobile licensee
(sheet per April–March fiscal year, weekly handle and GGR back to launch week
ending 2022-01-09). Landing URLs are stable per operator and redirect to a dated
file that moves on every weekly re-upload, so we resolve the redirect and cache
by final URL — each weekly publication is kept as its own immutable artifact.

Run ``uv run python -m ggr.ingest.ny`` to refresh and write
data/processed/ny_weekly.parquet.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ggr import cache
from ggr.config import DATA_PROCESSED
from ggr.parse.ny import parse_workbook

BASE = "https://www.gaming.ny.gov"

# All mobile licensees ever live in NY. Retail sportsbooks (casino lounges) are
# reported under the casinos' own pages and are excluded — immaterial vs mobile.
MOBILE_OPERATORS = {
    "ballybet": "BallyBet",
    "betmgm": "BetMGM",
    "caesars-sport-book": "Caesars Sportsbook",
    "draftkings-sport-book": "DraftKings",
    "fanatics": "Fanatics",
    "fanduel": "FanDuel",
    "resorts-world-bet": "Resorts World Bet",
    "rush-street-interactive": "Rush Street Interactive NY",
    "wynn-interactive": "Wynn Interactive",
}


def landing_url(slug: str) -> str:
    return f"{BASE}/{slug}-weekly-report-excel"


def fetch_operator(slug: str) -> Path:
    return cache.fetch(cache.resolve(landing_url(slug)), subdir="ny")


def build() -> pd.DataFrame:
    frames = []
    for slug, operator_raw in MOBILE_OPERATORS.items():
        path = fetch_operator(slug)
        frames.append(parse_workbook(path, operator_raw, landing_url(slug)))
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    df = build()
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "ny_weekly.parquet"
    df.to_parquet(out, index=False)
    by_op = (
        df.groupby("operator_canonical")
        .agg(weeks=("period_end", "count"), ggr=("gross_revenue", "sum"))
        .sort_values("ggr", ascending=False)
    )
    print(by_op.assign(ggr=lambda d: (d["ggr"] / 1e6).round(1)).to_string())
    print(f"\nwrote {len(df)} operator-weeks to {out}")


if __name__ == "__main__":
    main()
