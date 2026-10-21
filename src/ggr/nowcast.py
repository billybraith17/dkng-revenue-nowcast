"""Walk-forward nowcast of DKNG quarterly revenue from covered-state data.

Each target quarter uses only information public before its ``first_filed``
date:

1. Covered revenue ``C_q``: DK-attributable state revenue for the quarter as
   of the day before ``first_filed``, with months not yet published (mostly
   IL) imputed by ``ggr.panel.impute_month``.
2. Fit ``log R = a + b·log C + c·t`` on earlier quarters already filed by
   then. The trend term absorbs slow drift in the R/C ratio.
3. Predict, and wrap the point in an interval from the empirical quantile of
   previous walk-forward absolute percentage errors (split-conformal flavour;
   needs a few prior errors, so early targets have no interval).

Baselines the model must beat:

- seasonal-naive: R̂_q = R_{q-4} x (R_{q-1} / R_{q-5}) — last year's quarter
  scaled by recent growth.
- fixed-scalar: R̂_q = median(R/C over training) x C_q — coverage with no
  regression at all.

Robustness check: the same regression in levels, ``R = a + b·C + c·t``.

``surprise_hit``: whether the model calls actual revenue landing above or below
the seasonal-naive estimate (not analyst consensus).

Two simplifications, neither leaking the target: training quarters use the
latest EDGAR values, so a restatement would back-propagate (none material to
date); and state launch months come from the full panel, since launch dates
were announced in advance.

Run ``uv run python -m ggr.nowcast`` to print the backtest table and write
``data/processed/nowcast_backtest.csv``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ggr.coverage import PROCESSED, STATE_FILES
from ggr.panel import as_of_view, build_panel, impute_month

FIRST_TARGET = "2022Q1"  # first quarter with New York, the largest state
MIN_TRAIN_QUARTERS = 8
MIN_ERRORS_FOR_INTERVAL = 4
INTERVAL_COVERAGE = 0.8


def quarter_month_ends(quarter: str) -> list[pd.Timestamp]:
    period = pd.Period(quarter, freq="Q-DEC")
    return [
        (period.asfreq("M", "start") + i).end_time.normalize() for i in range(3)
    ]


def covered_quarter(
    panel: pd.DataFrame, quarter: str, as_of: pd.Timestamp
) -> tuple[float, int]:
    """(covered revenue C_q as of ``as_of``, number of imputed state-months).

    States enter once launched (first month with any DK data in the full
    panel); their unpublished months inside the quarter are imputed. Months
    before a state's launch contribute zero, not an imputation.
    """
    view = as_of_view(panel, as_of)
    first_month = panel.groupby("state")["month_end"].min()
    observed = view.set_index(["state", "month_end"])["revenue"]

    total, n_imputed = 0.0, 0
    for state, launch in first_month.items():
        for month_end in quarter_month_ends(quarter):
            if month_end < launch:
                continue
            if (state, month_end) in observed.index:
                total += observed[(state, month_end)]
            else:
                total += impute_month(view, state, month_end)
                n_imputed += 1
    return total, n_imputed


def fit_predict(
    train_c: np.ndarray, train_r: np.ndarray, train_t: np.ndarray,
    target_c: float, target_t: float,
) -> float:
    """OLS of log R on [1, log C, t]; returns the point prediction for R."""
    x = np.column_stack([np.ones(len(train_c)), np.log(train_c), train_t])
    coef, *_ = np.linalg.lstsq(x, np.log(train_r), rcond=None)
    return float(np.exp(coef[0] + coef[1] * np.log(target_c) + coef[2] * target_t))


def fit_predict_levels(
    train_c: np.ndarray, train_r: np.ndarray, train_t: np.ndarray,
    target_c: float, target_t: float,
) -> float:
    """OLS of R on [1, C, t] in levels; the robustness check on the log form."""
    x = np.column_stack([np.ones(len(train_c)), train_c, train_t])
    coef, *_ = np.linalg.lstsq(x, train_r, rcond=None)
    return float(coef[0] + coef[1] * target_c + coef[2] * target_t)


def _quarter_index(quarter: str) -> int:
    period = pd.Period(quarter, freq="Q-DEC")
    return period.year * 4 + period.quarter


def walk_forward(panel: pd.DataFrame, ground_truth: pd.DataFrame) -> pd.DataFrame:
    """One row per target quarter: prediction, actual, baselines, interval."""
    gt = ground_truth.copy()
    gt["first_filed"] = pd.to_datetime(gt["first_filed"])
    gt = gt.sort_values("quarter").reset_index(drop=True)
    reported = gt.set_index("quarter")["revenue_usd"]

    rows = []
    errors: list[float] = []  # walk-forward |pct error|s, for the intervals
    for target in gt.itertuples():
        if target.quarter < FIRST_TARGET:
            continue
        as_of = target.first_filed - pd.Timedelta(days=1)
        train = gt[(gt["first_filed"] <= as_of) & (gt["quarter"] < target.quarter)]
        if len(train) < MIN_TRAIN_QUARTERS:
            continue

        covered = {
            q: covered_quarter(panel, q, as_of)
            for q in [*train["quarter"], target.quarter]
        }
        target_c, target_imputed = covered[target.quarter]
        fit_args = dict(
            train_c=np.array([covered[q][0] for q in train["quarter"]]),
            train_r=train["revenue_usd"].to_numpy(),
            train_t=np.array([_quarter_index(q) for q in train["quarter"]], float),
            target_c=target_c,
            target_t=float(_quarter_index(target.quarter)),
        )
        prediction = fit_predict(**fit_args)
        levels = fit_predict_levels(**fit_args)

        ratios = fit_args["train_r"] / fit_args["train_c"]
        scalar_baseline = float(np.median(ratios) * target_c)

        period = pd.Period(target.quarter, freq="Q-DEC")
        lags = {k: str(period - k) for k in (1, 4, 5)}
        if all(q in reported.index and q in set(train["quarter"]) for q in lags.values()):
            naive = reported[lags[4]] * reported[lags[1]] / reported[lags[5]]
        else:
            naive = np.nan

        if len(errors) >= MIN_ERRORS_FOR_INTERVAL:
            width = float(np.quantile(errors, INTERVAL_COVERAGE))
            low, high = prediction * (1 - width), prediction * (1 + width)
        else:
            low = high = np.nan

        actual = target.revenue_usd
        rows.append(
            {
                "quarter": target.quarter,
                "as_of": as_of.date(),
                "covered_revenue": target_c,
                "n_imputed_state_months": target_imputed,
                "prediction": prediction,
                "actual": actual,
                "pct_error": prediction / actual - 1,
                "naive": naive,
                "naive_pct_error": naive / actual - 1 if pd.notna(naive) else np.nan,
                "scalar": scalar_baseline,
                "scalar_pct_error": scalar_baseline / actual - 1,
                "levels": levels,
                "levels_pct_error": levels / actual - 1,
                "interval_low": low,
                "interval_high": high,
                "in_interval": bool(low <= actual <= high) if pd.notna(low) else None,
                "surprise_hit": (
                    bool((prediction > naive) == (actual > naive))
                    if pd.notna(naive)
                    else None
                ),
            }
        )
        errors.append(abs(prediction / actual - 1))
    return pd.DataFrame(rows)


def summarize(backtest: pd.DataFrame) -> pd.Series:
    with_naive = backtest[backtest["naive_pct_error"].notna()]
    with_interval = backtest[backtest["in_interval"].notna()]
    return pd.Series(
        {
            "quarters": len(backtest),
            "model_mape": backtest["pct_error"].abs().mean(),
            "model_bias": backtest["pct_error"].mean(),
            "naive_mape": with_naive["naive_pct_error"].abs().mean(),
            "scalar_mape": backtest["scalar_pct_error"].abs().mean(),
            "levels_mape": backtest["levels_pct_error"].abs().mean(),
            "surprise_hit_rate": with_naive["surprise_hit"].mean(),
            "interval_coverage": (
                with_interval["in_interval"].mean() if len(with_interval) else np.nan
            ),
        }
    )


def main() -> None:
    frames = {
        state: pd.read_parquet(PROCESSED / name) for state, name in STATE_FILES.items()
    }
    ground_truth = pd.read_csv(PROCESSED / "ground_truth_dkng.csv")
    panel = build_panel(frames)
    backtest = walk_forward(panel, ground_truth)
    backtest.to_csv(PROCESSED / "nowcast_backtest.csv", index=False)

    display = backtest.copy()
    for col in ("covered_revenue", "prediction", "actual", "naive", "scalar",
                "levels", "interval_low", "interval_high"):
        display[col] = (display[col] / 1e6).round(0)
    for col in ("pct_error", "naive_pct_error", "scalar_pct_error", "levels_pct_error"):
        display[col] = (display[col] * 100).round(1)
    print(
        display[
            [
                "quarter", "as_of", "covered_revenue", "n_imputed_state_months",
                "prediction", "actual", "pct_error", "naive_pct_error",
                "scalar_pct_error", "levels_pct_error", "interval_low", "interval_high",
                "in_interval", "surprise_hit",
            ]
        ].to_string(index=False)
    )
    print("\nSummary:")
    summary = summarize(backtest)
    for name, value in summary.items():
        print(f"  {name}: {value:.3f}" if isinstance(value, float) else f"  {name}: {value}")
    print(f"\nWrote {PROCESSED / 'nowcast_backtest.csv'}")


if __name__ == "__main__":
    main()
