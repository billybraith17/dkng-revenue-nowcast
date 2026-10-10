"""Illinois — IGB sports wagering accrual detail CSVs, one POST per month.

The reports live behind an ASP.NET WebForms app (igbapps.illinois.gov) embedded
in the IGB site: a GET collects __VIEWSTATE tokens, then each month is a form
POST returning CSV. Months are cached individually; the trailing three months
are refetched on every run because IGB revises recent figures (accrual basis).

Online wagering began June 2020 (in-person March 2020; we keep online only).

Run ``uv run python -m ggr.ingest.il`` to write data/processed/il_monthly.parquet.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from bs4 import BeautifulSoup

from ggr import cache
from ggr.config import DATA_PROCESSED
from ggr.parse.il import month_range, parse_csv

APP_URL = "https://igbapps.illinois.gov/SportsReports_AEM.aspx"
FIRST_ONLINE_MONTH = (2020, 6)
REFETCH_TRAILING_DAYS = 100


def _form_tokens() -> dict[str, str]:
    page = cache.fetch(APP_URL, subdir="il", force=True)
    soup = BeautifulSoup(page.read_text(errors="ignore"), "lxml")
    return {
        i["name"]: i.get("value", "")
        for i in soup.find_all("input", {"type": "hidden"})
        if i.get("name")
    }


def fetch_month(year: int, month: int, tokens: dict[str, str]) -> tuple:
    month_name = dt.date(year, month, 1).strftime("%B")
    data = tokens | {
        "SearchType": "TypeAccrual",
        "SearchAccrual": "Detail Report",
        "SearchStartMonth": month_name,
        "SearchStartYear": str(year),
        "SearchEndMonth": month_name,
        "SearchEndYear": str(year),
        "ViewType": "ViewCSV",
        "ButtonSearch.x": "10",
        "ButtonSearch.y": "10",
    }
    age_days = (dt.date.today() - dt.date(year, month, 1)).days
    path = cache.fetch_post(
        APP_URL,
        data,
        name=f"il_detail_{year}-{month:02d}.csv",
        subdir="il",
        force=age_days < REFETCH_TRAILING_DAYS,
    )
    return path, f"{APP_URL}#accrual-detail-{year}-{month:02d}"


def build() -> pd.DataFrame:
    tokens = _form_tokens()
    frames = []
    for year, month in month_range(FIRST_ONLINE_MONTH, dt.date.today()):
        path, source_url = fetch_month(year, month, tokens)
        try:
            frames.append(parse_csv(path, year, month, source_url))
        except ValueError:
            # IGB publishes ~1 month in arrears; a recent month returning a
            # non-report page just isn't out yet. Old months must still raise.
            if (dt.date.today() - dt.date(year, month, 1)).days < REFETCH_TRAILING_DAYS:
                print(f"note: {year}-{month:02d} not yet published, skipping")
                continue
            raise
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    df = build()
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "il_monthly.parquet"
    df.to_parquet(out, index=False)
    summary = (
        df.groupby("operator_canonical")
        .agg(months=("period_end", "count"), gross=("gross_revenue", "sum"))
        .sort_values("gross", ascending=False)
    )
    print(summary.assign(gross=lambda d: (d["gross"] / 1e6).round(1)).to_string())
    print(f"\nrange: {df.period_end.min():%Y-%m} → {df.period_end.max():%Y-%m}")
    print(f"wrote {len(df)} operator-months to {out}")


if __name__ == "__main__":
    main()
