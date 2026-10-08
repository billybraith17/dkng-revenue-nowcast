"""The tidy schema every state parser emits.

One row per (state, period, operator, product). ``period_start``/``period_end`` are
inclusive dates so weekly (NY) and monthly (everyone else) data share one table.
Monetary columns are USD. ``gross_revenue`` is GGR as the regulator defines it;
``promo_credits`` and ``adjusted_revenue`` are filled only where the state reports
them (PA, MI) — basis differences across states are handled downstream, not here.
"""

from __future__ import annotations

import pandas as pd

TIDY_COLUMNS = [
    "state",  # two-letter code, e.g. "NY"
    "period_start",
    "period_end",
    "operator_raw",  # exactly as printed in the filing
    "operator_canonical",  # via ggr.operators.canonicalize
    "product",  # "osb" | "igaming" | "retail"
    "handle",
    "gross_revenue",
    "promo_credits",
    "adjusted_revenue",
    "source_url",
    "fetched_at",
]


def tidy_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a schema-conforming frame, failing loudly on unknown keys."""
    df = pd.DataFrame(rows)
    unknown = set(df.columns) - set(TIDY_COLUMNS)
    if unknown:
        raise ValueError(f"rows contain unknown columns: {sorted(unknown)}")
    for col in TIDY_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[TIDY_COLUMNS]
    df["period_start"] = pd.to_datetime(df["period_start"])
    df["period_end"] = pd.to_datetime(df["period_end"])
    for col in ("handle", "gross_revenue", "promo_credits", "adjusted_revenue"):
        df[col] = pd.to_numeric(df[col])
    return df
