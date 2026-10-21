"""State-month panel of DraftKings-attributable revenue with an availability clock.

Walk-forward evaluation needs to know when each number became public, not when
we downloaded it (``fetched_at``). Each state-month is treated as available
``PUBLICATION_LAG_DAYS[state]`` days after the period ends.

Michigan uses michigan.gov's publication schedule, not our Wayback fetch date:
the reports were public on time; only our route to them is delayed.

NY is weekly: each week carries its own availability date and is pro-rated
across month boundaries by day count.
"""

from __future__ import annotations

import pandas as pd

from ggr.coverage import dk_attributable

# Days after period_end at which each report is assumed public.
PUBLICATION_LAG_DAYS = {
    "NY": 8,
    "NJ": 20,
    "PA": 20,
    "IL": 62,
    "MI": 22,
    "IN": 14,
    "IA": 16,
}


def _month_pieces(row) -> list[tuple[pd.Timestamp, float, int]]:
    """(month_end, revenue share, days) for each month a period overlaps."""
    total_days = (row.period_end - row.period_start).days + 1
    pieces = []
    cur = row.period_start
    while cur <= row.period_end:
        month = pd.Period(cur, freq="M")
        seg_end = min(row.period_end, month.end_time.normalize())
        days = (seg_end - cur).days + 1
        pieces.append(
            (month.end_time.normalize(), row.gross_revenue * days / total_days, days)
        )
        cur = seg_end + pd.Timedelta(days=1)
    return pieces


def build_panel(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Piece-level panel: (state, month_end, revenue, days, available_from).

    Monthly states contribute one piece per month; NY contributes one piece per
    (week x month) overlap so a month's availability tracks its weeks.
    """
    records = []
    for state, df in frames.items():
        lag = pd.Timedelta(days=PUBLICATION_LAG_DAYS[state])
        dk = dk_attributable(df)
        dk = dk[dk["gross_revenue"].notna()]
        for row in dk.itertuples():
            for month_end, revenue, days in _month_pieces(row):
                records.append(
                    {
                        "state": state,
                        "month_end": month_end,
                        "revenue": revenue,
                        "days": days,
                        "available_from": row.period_end + lag,
                    }
                )
    panel = pd.DataFrame(records)
    if panel.empty:
        raise ValueError("no DK-attributable rows in any frame")
    return panel


def as_of_view(panel: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """State-month revenue using only pieces published on or before ``as_of``.

    Partially covered months (NY weeks still unpublished) are scaled to a full
    month by covered-day share, except each state's first-ever month, whose
    uncovered early days are pre-launch rather than unpublished.
    """
    avail = panel[panel["available_from"] <= as_of]
    if avail.empty:
        return pd.DataFrame(columns=["state", "month_end", "revenue", "complete"])
    first_month = panel.groupby("state")["month_end"].min()
    # Distinct source periods only: two operators' rows for the same week must
    # not double-count the week's days when judging month coverage.
    days = (
        avail.drop_duplicates(["state", "month_end", "available_from", "days"])
        .groupby(["state", "month_end"])["days"]
        .sum()
    )
    grouped = avail.groupby(["state", "month_end"], as_index=False).agg(
        revenue=("revenue", "sum")
    )
    grouped["days"] = grouped.set_index(["state", "month_end"]).index.map(days)
    grouped["month_days"] = grouped["month_end"].dt.day
    launch = grouped["month_end"] == grouped["state"].map(first_month)
    partial = (grouped["days"] < grouped["month_days"]) & ~launch
    if (grouped["days"] > grouped["month_days"]).any():
        bad = grouped[grouped["days"] > grouped["month_days"]]
        raise ValueError(f"month covered more than once:\n{bad}")
    grouped.loc[partial, "revenue"] *= (
        grouped.loc[partial, "month_days"] / grouped.loc[partial, "days"]
    )
    grouped["complete"] = ~partial
    return grouped[["state", "month_end", "revenue", "complete"]]


def impute_month(
    view: pd.DataFrame, state: str, month_end: pd.Timestamp, window: int = 3
) -> float:
    """Impute a missing state-month from states that did publish it.

    The state's share of the reference states' total is estimated over its
    last ``window`` observed months and applied to the reference total for the
    missing month — sport-calendar seasonality rides in through the reference
    states. Raises when there is nothing to estimate from (fail loud rather
    than fabricate).
    """
    month_rows = view[view["month_end"] == month_end]
    refs = sorted(set(month_rows["state"]) - {state})
    if not refs:
        raise ValueError(f"no reference states published {month_end.date()}")
    ref_total = month_rows[month_rows["state"].isin(refs)]["revenue"].sum()

    wide = view.pivot_table(index="month_end", columns="state", values="revenue")
    if state not in wide.columns:
        raise ValueError(f"no history to impute {state} {month_end.date()}")
    history = wide[wide.index < month_end]
    history = history[history[state].notna() & history[refs].notna().all(axis=1)]
    if history.empty:
        raise ValueError(
            f"no history to impute {state} {month_end.date()} "
            f"against references {refs}"
        )
    tail = history.tail(window)
    share = (tail[state] / tail[refs].sum(axis=1)).mean()
    return float(share * ref_total)
