"""Ground truth: DKNG quarterly revenue from SEC EDGAR XBRL company facts.

DraftKings has filed under two CIKs — 1772757 (the SPAC-era entity, quarterly data
back to 2019 with original filing dates) and 1883685 (the post-May-2022 holdco).
Both are pulled and merged: values are taken from the latest filing (restatements
win), while ``first_filed`` keeps the earliest date each period's revenue appeared
in EDGAR. Q4 is never filed as a discrete period, so it is derived as FY minus
the three other quarters and carries the 10-K's filing date. A Q1 that was only
ever filed inside a half-year total (2019) is derived as H1 minus Q2.

Revenue becomes public in the earnings press release, which DraftKings furnishes
on an 8-K (item 2.02). The 8-K can reach EDGAR the morning after an evening
release, and EDGAR does not record the release time, so ``earnings_date`` is the
earliest day the release can have gone out (see ``_release_date``). The backtest's
clock is the earlier of it and ``first_filed``.

Run ``uv run python -m ggr.ingest.edgar`` to re-download the SEC files and write
data/processed/ground_truth_dkng.csv.
"""

from __future__ import annotations

import datetime as dt
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
HALF_YEAR_DAYS = (170, 195)
YEAR_DAYS = (330, 400)

EARNINGS_ITEM = "2.02"  # 8-K item "Results of Operations and Financial Condition"
MARKET_TZ = "America/New_York"
MARKET_CLOSE = dt.time(16, 0)
EARNINGS_WINDOW_DAYS = 100  # a quarter's release falls within this many days of its end


def load_companyfacts(cik: int, force: bool = False) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    return json.loads(fetch(url, subdir="edgar", force=force).read_text())


def load_submissions(cik: int, force: bool = False) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    return json.loads(fetch(url, subdir="edgar", force=force).read_text())


def _release_date(form: str, accepted: str, report: str) -> pd.Timestamp:
    """Earliest day the results in an 8-K can have been released.

    EDGAR records when it accepted the 8-K (UTC), not when the press release
    went out. DraftKings has released after the market close and furnished the
    8-K the next morning (Q4 2024, Q3 2025), so an 8-K accepted before the
    4pm ET close is dated to the previous business day; one accepted at or
    after the close is dated to that day. This errs early for a release made
    the same morning (Q1 2022).

    A plain 8-K's report date is the event date and is used if earlier still.
    An amendment (8-K/A) repeats the original event's report date, so it is
    ignored there.
    """
    accepted_et = pd.to_datetime(accepted, utc=True).tz_convert(MARKET_TZ)
    day = accepted_et.tz_localize(None).normalize()
    if accepted_et.time() < MARKET_CLOSE:
        day = day - pd.offsets.BDay(1)
    if form == "8-K" and report:
        day = min(day, pd.Timestamp(report))
    return day


def earnings_release_dates(submissions: dict) -> list[pd.Timestamp]:
    """Release dates of the 8-Ks furnishing results (item 2.02) in one filer's index."""
    filings = submissions["filings"]
    if filings.get("files"):
        raise ValueError("filing index is paginated; older 8-Ks would be missed")
    recent = filings["recent"]
    dates = []
    for form, accepted, report, items in zip(
        recent["form"],
        recent["acceptanceDateTime"],
        recent["reportDate"],
        recent["items"],
        strict=True,
    ):
        if form not in ("8-K", "8-K/A"):
            continue
        if EARNINGS_ITEM not in [item.strip() for item in items.split(",")]:
            continue
        dates.append(_release_date(form, accepted, report))
    return sorted(dates)


def _earnings_date(period_end: pd.Timestamp, releases: list[pd.Timestamp]) -> pd.Timestamp:
    """First results release after a quarter ends, or NaT if none is on file."""
    limit = period_end + pd.Timedelta(days=EARNINGS_WINDOW_DAYS)
    for date in releases:
        if period_end < date <= limit:
            return date
    return pd.NaT


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
    """Quarterly revenue with first-filed and earnings-release dates.

    Q4 is derived from FY minus Q1-Q3; a missing Q1 from H1 minus Q2.
    """
    facts = pd.concat([_revenue_facts(load_companyfacts(c, force)) for c in ciks])
    releases = sorted(d for c in ciks for d in earnings_release_dates(load_submissions(c, force)))

    quarters = _dedupe(facts[facts["days"].between(*QUARTER_DAYS)])
    halves = _dedupe(facts[facts["days"].between(*HALF_YEAR_DAYS)])
    years = _dedupe(facts[facts["days"].between(*YEAR_DAYS)])

    quarters["year"] = quarters["end"].dt.year
    quarters["q"] = quarters["end"].dt.quarter
    quarters["derived"] = False

    q1_rows = []
    first_halves = halves[(halves["start"].dt.month == 1) & (halves["end"].dt.month == 6)]
    for _, h1 in first_halves.iterrows():
        year = h1["end"].year
        in_year = quarters[quarters["year"] == year]
        q2 = in_year[in_year["q"] == 2]
        if len(q2) == 1 and not (in_year["q"] == 1).any():
            q1_rows.append(
                {
                    "start": pd.Timestamp(year=year, month=1, day=1),
                    "end": pd.Timestamp(year=year, month=3, day=31),
                    "val": h1["val"] - q2["val"].iloc[0],
                    # Known once both the half-year and Q2 figures are filed.
                    "first_filed": max(h1["first_filed"], q2["first_filed"].iloc[0]),
                    "year": year,
                    "q": 1,
                    "derived": True,
                }
            )
    quarters = pd.concat([quarters, pd.DataFrame(q1_rows)], ignore_index=True)

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
    df["earnings_date"] = [_earnings_date(end, releases) for end in df["end"]]
    return df[["quarter", "start", "end", "val", "first_filed", "earnings_date", "derived"]].rename(
        columns={"start": "period_start", "end": "period_end", "val": "revenue_usd"}
    )


def main() -> None:
    df = quarterly_revenue(force=True)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "ground_truth_dkng.csv"
    df.to_csv(out, index=False)
    print(df.to_string(index=False))
    print(f"\nwrote {len(df)} quarters to {out}")


if __name__ == "__main__":
    main()
