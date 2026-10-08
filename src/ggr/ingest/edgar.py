"""Ground truth: DKNG quarterly revenue from SEC EDGAR XBRL company facts.

DraftKings has filed under two CIKs — 1772757 (the SPAC-era entity, quarterly data
back to 2019 with original filing dates) and 1883685 (the post-May-2022 holdco).
Both are pulled and merged: values are taken from the latest filing (restatements
win), while ``first_filed`` keeps the earliest date each period's revenue appeared
in EDGAR, which is what the walk-forward backtest must respect. Q4 is never filed
as a discrete period, so it is derived as FY minus the three filed quarters and
carries the 10-K's filing date.

``first_filed`` slightly overstates the information lag: revenue is typically in
an earnings press release a few days before the 10-Q/10-K hits EDGAR. That bias is
conservative (it can only make the nowcast look better-timed than claimed).

Run ``uv run python -m ggr.ingest.edgar`` to write data/processed/ground_truth_dkng.csv.
"""

from __future__ import annotations

import json

import pandas as pd

from ggr.cache import fetch
from ggr.config import DATA_PROCESSED

DKNG_CIKS = [1772757, 1883685]

REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]

QUARTER_DAYS = (70, 110)
YEAR_DAYS = (330, 400)


def load_companyfacts(cik: int, force: bool = False) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    return json.loads(fetch(url, subdir="edgar", force=force).read_text())


def _revenue_facts(facts: dict) -> pd.DataFrame:
    rows = []
    gaap = facts["facts"]["us-gaap"]
    for concept in REVENUE_CONCEPTS:
        if concept not in gaap:
            continue
        for item in gaap[concept]["units"]["USD"]:
            if "start" not in item:
                continue
            rows.append(
                {
                    "start": pd.Timestamp(item["start"]),
                    "end": pd.Timestamp(item["end"]),
                    "val": float(item["val"]),
                    "filed": pd.Timestamp(item["filed"]),
                    "form": item["form"],
                }
            )
    df = pd.DataFrame(rows)
    df["days"] = (df["end"] - df["start"]).dt.days
    return df


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """One row per period: latest-filed value, earliest filed date."""
    grouped = df.groupby(["start", "end"])
    out = grouped.apply(
        lambda g: pd.Series(
            {
                "val": g.sort_values("filed")["val"].iloc[-1],
                "first_filed": g["filed"].min(),
            }
        ),
        include_groups=False,
    ).reset_index()
    return out


def quarterly_revenue(ciks: list[int] = DKNG_CIKS, force: bool = False) -> pd.DataFrame:
    """Quarterly revenue with first-filed dates, Q4 derived from FY minus Q1-Q3."""
    facts = pd.concat([_revenue_facts(load_companyfacts(c, force)) for c in ciks])

    quarters = _dedupe(facts[facts["days"].between(*QUARTER_DAYS)])
    years = _dedupe(facts[facts["days"].between(*YEAR_DAYS)])

    quarters["year"] = quarters["end"].dt.year
    quarters["q"] = quarters["end"].dt.quarter
    quarters["derived"] = False

    q4_rows = []
    for _, fy in years.iterrows():
        year = fy["end"].year
        filed_qs = quarters[(quarters["year"] == year) & (quarters["q"] < 4)]
        if len(filed_qs) == 3 and not (quarters[(quarters["year"] == year)]["q"] == 4).any():
            q4_rows.append(
                {
                    "start": pd.Timestamp(year=year, month=10, day=1),
                    "end": pd.Timestamp(year=year, month=12, day=31),
                    "val": fy["val"] - filed_qs["val"].sum(),
                    "first_filed": fy["first_filed"],
                    "year": year,
                    "q": 4,
                    "derived": True,
                }
            )
    df = pd.concat([quarters, pd.DataFrame(q4_rows)], ignore_index=True)
    df["quarter"] = df["year"].astype(str) + "Q" + df["q"].astype(str)
    df = df.sort_values(["year", "q"]).reset_index(drop=True)
    return df[["quarter", "start", "end", "val", "first_filed", "derived"]].rename(
        columns={"start": "period_start", "end": "period_end", "val": "revenue_usd"}
    )


def main() -> None:
    df = quarterly_revenue()
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "ground_truth_dkng.csv"
    df.to_csv(out, index=False)
    print(df.to_string(index=False))
    print(f"\nwrote {len(df)} quarters to {out}")


if __name__ == "__main__":
    main()
