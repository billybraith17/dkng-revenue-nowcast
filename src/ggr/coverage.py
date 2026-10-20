"""How much of DraftKings' reported revenue do we observe directly?

Aligns the seven state adapters' DK-attributable rows against the EDGAR
ground truth, quarter by quarter, and answers: what share of the revenue
DKNG reports to the SEC shows up in regulator filings we already parse?

- The two sides are measured differently, so the ratio is not expected to
  reach 100%: states publish *gross* gaming revenue (before promotions),
  DKNG reports *net* revenue (after promotions) and includes states and
  products we don't observe (DFS, other states, lottery). It shows how
  much of the target our indicator represents; the nowcast regression
  learns the mapping from one to the other.
- DK-attributable includes Golden Nugget from the 2022-05-05 acquisition
  close. The monthly grain assigns all of May 2022 to DKNG — four
  pre-close days, immaterial.
- NY weeks straddling a quarter boundary are pro-rated by day count.
- Completeness per state-quarter = published days / calendar days, so a
  regulator lagging one month (or NY launching 2022-01-08) shows as a
  partial quarter rather than silently deflating coverage.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROCESSED = Path("data/processed")

STATE_FILES = {
    "NY": "ny_weekly.parquet",
    "MI": "mi_monthly.parquet",
    "PA": "pa_monthly.parquet",
    "IL": "il_monthly.parquet",
    "NJ": "nj_monthly.parquet",
    "IN": "in_monthly.parquet",
    "IA": "ia_monthly.parquet",
}

GNOG_ACQUIRED_FROM = pd.Timestamp("2022-05-31")  # first period_end after the close
COMPLETE_THRESHOLD = 0.999


def dk_attributable(df: pd.DataFrame) -> pd.DataFrame:
    """Rows whose revenue lands in DKNG's income statement."""
    mask = (df["operator_canonical"] == "draftkings") | (
        (df["operator_canonical"] == "golden_nugget")
        & (df["period_end"] >= GNOG_ACQUIRED_FROM)
    )
    return df[mask]


def split_period(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[str, int]]:
    """(quarter label, days) for each calendar quarter a period overlaps."""
    parts = []
    cur = start
    while cur <= end:
        quarter = pd.Period(cur, freq="Q-DEC")
        seg_end = min(end, quarter.end_time.normalize())
        parts.append((str(quarter), (seg_end - cur).days + 1))
        cur = seg_end + pd.Timedelta(days=1)
    return parts


def allocate_to_quarters(df: pd.DataFrame) -> pd.DataFrame:
    """Explode rows across quarters, pro-rating money columns by day overlap.

    Monthly rows land whole in one quarter; only NY weeks ever split.
    """
    records = []
    for row in df.itertuples():
        total_days = (row.period_end - row.period_start).days + 1
        for quarter, days in split_period(row.period_start, row.period_end):
            fraction = days / total_days
            records.append(
                {
                    "quarter": quarter,
                    "state": row.state,
                    "product": row.product,
                    "gross_revenue": row.gross_revenue * fraction
                    if pd.notna(row.gross_revenue)
                    else None,
                    "handle": row.handle * fraction if pd.notna(row.handle) else None,
                }
            )
    return pd.DataFrame(records)


def quarter_completeness(df: pd.DataFrame) -> pd.Series:
    """Published-day share of each quarter, from the full (all-operator) frame.

    Keyed on unique periods so nine NY operator rows count one week once.
    """
    periods = df[["period_start", "period_end"]].drop_duplicates()
    days: dict[str, int] = {}
    for row in periods.itertuples():
        for quarter, d in split_period(row.period_start, row.period_end):
            days[quarter] = days.get(quarter, 0) + d
    out = {}
    for quarter, observed in days.items():
        p = pd.Period(quarter, freq="Q-DEC")
        calendar_days = (p.end_time.normalize() - p.start_time.normalize()).days + 1
        if observed > calendar_days:
            raise ValueError(
                f"{observed} published days counted in {quarter} "
                f"({calendar_days} calendar days) — overlapping periods upstream"
            )
        out[quarter] = observed / calendar_days
    return pd.Series(out, name="completeness")


def state_quarter_table(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per (quarter, state, product): DK-attributable revenue observed."""
    parts = []
    for state, df in frames.items():
        completeness = quarter_completeness(df)
        allocated = allocate_to_quarters(dk_attributable(df))
        if allocated.empty:
            continue
        grouped = (
            allocated.groupby(["quarter", "state", "product"], as_index=False)
            .agg(
                dk_gross_revenue=("gross_revenue", "sum"),
                dk_handle=("handle", lambda s: s.sum(min_count=1)),
            )
        )
        grouped["completeness"] = grouped["quarter"].map(completeness)
        parts.append(grouped)
    return (
        pd.concat(parts, ignore_index=True)
        .sort_values(["quarter", "state", "product"])
        .reset_index(drop=True)
    )


def coverage_summary(
    state_quarter: pd.DataFrame, ground_truth: pd.DataFrame
) -> pd.DataFrame:
    """Per reported DKNG quarter: observed DK revenue and the coverage ratio."""
    unexpected = set(state_quarter["product"]) - {"osb", "igaming"}
    if unexpected:
        raise ValueError(
            f"unexpected products {sorted(unexpected)} — extend coverage_summary "
            "before their revenue silently drops from observed_total"
        )
    by_product = (
        state_quarter.pivot_table(
            index="quarter", columns="product", values="dk_gross_revenue", aggfunc="sum"
        )
        .reindex(columns=["osb", "igaming"])
        .fillna(0.0)
        .rename(columns={"osb": "observed_osb", "igaming": "observed_igaming"})
    )
    partial = (
        state_quarter[state_quarter["completeness"] < COMPLETE_THRESHOLD]
        .groupby("quarter")["state"]
        .agg(lambda s: ",".join(sorted(s.unique())))
        .rename("partial_states")
    )
    n_states = state_quarter.groupby("quarter")["state"].nunique().rename("n_states")
    # A state that has appeared before but has no rows this quarter is a data
    # lag (e.g. MI's Wayback delay), not a pre-launch gap — flag it.
    first_seen = state_quarter.groupby("state")["quarter"].min()
    seen = state_quarter.groupby("quarter")["state"].agg(set)
    missing = pd.Series(
        {
            q: ",".join(
                sorted(
                    s
                    for s, first in first_seen.items()
                    if first <= q and s not in seen.get(q, set())
                )
            )
            for q in ground_truth["quarter"]
        },
        name="missing_states",
    )

    out = ground_truth.merge(by_product, left_on="quarter", right_index=True, how="left")
    out = out.merge(n_states, left_on="quarter", right_index=True, how="left")
    out = out.merge(partial, left_on="quarter", right_index=True, how="left")
    out = out.merge(missing, left_on="quarter", right_index=True, how="left")
    out[["observed_osb", "observed_igaming"]] = out[
        ["observed_osb", "observed_igaming"]
    ].fillna(0.0)
    out["n_states"] = out["n_states"].fillna(0).astype(int)
    out["partial_states"] = out["partial_states"].fillna("")
    out["missing_states"] = out["missing_states"].fillna("")
    out["observed_total"] = out["observed_osb"] + out["observed_igaming"]
    out["coverage_pct"] = out["observed_total"] / out["revenue_usd"]
    return out[
        [
            "quarter",
            "revenue_usd",
            "observed_osb",
            "observed_igaming",
            "observed_total",
            "coverage_pct",
            "n_states",
            "partial_states",
            "missing_states",
        ]
    ]


def main() -> None:
    frames = {
        state: pd.read_parquet(PROCESSED / name) for state, name in STATE_FILES.items()
    }
    ground_truth = pd.read_csv(PROCESSED / "ground_truth_dkng.csv")

    state_quarter = state_quarter_table(frames)
    summary = coverage_summary(state_quarter, ground_truth)

    state_quarter.to_csv(PROCESSED / "coverage_dkng_state_quarter.csv", index=False)
    summary.to_csv(PROCESSED / "coverage_dkng.csv", index=False)

    display = summary.copy()
    for col in ("revenue_usd", "observed_osb", "observed_igaming", "observed_total"):
        display[col] = (display[col] / 1e6).round(1)
    display["coverage_pct"] = (display["coverage_pct"] * 100).round(1)
    display = display.rename(
        columns={
            "revenue_usd": "reported_$m",
            "observed_osb": "osb_$m",
            "observed_igaming": "igaming_$m",
            "observed_total": "observed_$m",
            "coverage_pct": "coverage_%",
        }
    )
    print(display.to_string(index=False))
    print(
        f"\nWrote {PROCESSED / 'coverage_dkng.csv'} and "
        f"{PROCESSED / 'coverage_dkng_state_quarter.csv'}"
    )


if __name__ == "__main__":
    main()
