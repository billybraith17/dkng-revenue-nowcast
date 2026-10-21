"""Covered-quarter assembly, regression, and walk-forward leakage discipline."""

import numpy as np
import pandas as pd
import pytest

from ggr.nowcast import (
    covered_quarter,
    fit_predict,
    fit_predict_levels,
    quarter_month_ends,
    summarize,
    walk_forward,
)


def _panel_row(state, month_end, revenue, available_from, days=30):
    return {
        "state": state,
        "month_end": pd.Timestamp(month_end),
        "revenue": revenue,
        "days": pd.Timestamp(month_end).day,
        "available_from": pd.Timestamp(available_from),
    }


def test_quarter_month_ends():
    assert quarter_month_ends("2024Q1") == [
        pd.Timestamp("2024-01-31"),
        pd.Timestamp("2024-02-29"),
        pd.Timestamp("2024-03-31"),
    ]


def test_covered_quarter_sums_observed_months():
    panel = pd.DataFrame(
        [
            _panel_row("NY", "2024-01-31", 100.0, "2024-02-08"),
            _panel_row("NY", "2024-02-29", 110.0, "2024-03-08"),
            _panel_row("NY", "2024-03-31", 120.0, "2024-04-08"),
        ]
    )
    total, n_imputed = covered_quarter(panel, "2024Q1", pd.Timestamp("2024-05-01"))
    assert total == pytest.approx(330.0)
    assert n_imputed == 0


def test_covered_quarter_imputes_unpublished_month():
    rows = []
    for i, month in enumerate(["2024-01-31", "2024-02-29", "2024-03-31"]):
        rows.append(_panel_row("NY", month, 100.0, f"2024-{i + 2:02d}-08"))
        # IL publishes with a 62-day lag: March lands mid-May.
        rows.append(_panel_row("IL", month, 50.0, f"2024-{i + 3:02d}-15"))
    panel = pd.DataFrame(rows)
    total, n_imputed = covered_quarter(panel, "2024Q1", pd.Timestamp("2024-05-01"))
    # IL March missing; imputed at its steady 50% share of NY = 50.
    assert n_imputed == 1
    assert total == pytest.approx(100.0 * 3 + 50.0 * 3)


def test_covered_quarter_prelaunch_months_are_zero_not_imputed():
    panel = pd.DataFrame(
        [
            _panel_row("NY", "2024-01-31", 100.0, "2024-02-08"),
            _panel_row("NY", "2024-02-29", 100.0, "2024-03-08"),
            _panel_row("NY", "2024-03-31", 100.0, "2024-04-08"),
            # MA launches in February — January is pre-launch, not missing.
            _panel_row("MA", "2024-02-29", 40.0, "2024-03-20"),
            _panel_row("MA", "2024-03-31", 40.0, "2024-04-20"),
        ]
    )
    total, n_imputed = covered_quarter(panel, "2024Q1", pd.Timestamp("2024-05-01"))
    assert total == pytest.approx(380.0)
    assert n_imputed == 0


def test_fit_predict_recovers_exact_relationship():
    # R = 2·C exactly, no trend: prediction should be exact.
    c = np.array([100.0, 150.0, 200.0, 250.0, 300.0])
    r = 2 * c
    t = np.arange(5, dtype=float)
    assert fit_predict(c, r, t, target_c=400.0, target_t=5.0) == pytest.approx(
        800.0, rel=1e-6
    )


def test_fit_predict_levels_recovers_exact_linear_relationship():
    # R = 50 + 2·C + 3·t exactly, with t on the real quarter-index scale.
    c = np.array([100.0, 180.0, 150.0, 260.0, 300.0, 240.0])
    t = 8088.0 + np.arange(6, dtype=float)
    r = 50 + 2 * c + 3 * t
    expected = 50 + 2 * 400.0 + 3 * 8094.0
    assert fit_predict_levels(c, r, t, target_c=400.0, target_t=8094.0) == pytest.approx(
        expected, rel=1e-9
    )


def test_fit_predict_levels_differs_from_log_form_on_curved_data():
    # R = C^0.5 is curved in levels: the log form is exact, levels is not.
    c = np.array([100.0, 400.0, 900.0, 1600.0, 2500.0])
    r = np.sqrt(c)
    t = np.zeros(5)
    assert fit_predict(c, r, t, target_c=3600.0, target_t=0.0) == pytest.approx(60.0)
    assert fit_predict_levels(c, r, t, target_c=3600.0, target_t=0.0) != pytest.approx(
        60.0, rel=1e-3
    )


def _synthetic_world(n_quarters=16, start_year=2020):
    """A world where R = 2.pow(C) exactly; panel months published promptly."""
    quarters, panel_rows, gt_rows = [], [], []
    for i in range(n_quarters):
        year = start_year + i // 4
        q = i % 4 + 1
        quarter = f"{year}Q{q}"
        quarters.append(quarter)
        monthly = 100.0 + 5.0 * i  # slow growth
        for month_end in quarter_month_ends(quarter):
            panel_rows.append(
                _panel_row(
                    "NY", month_end, monthly, month_end + pd.Timedelta(days=8)
                )
            )
        c = monthly * 3
        gt_rows.append(
            {
                "quarter": quarter,
                "revenue_usd": 2.0 * c,
                "first_filed": (
                    pd.Period(quarter, freq="Q-DEC").end_time.normalize()
                    + pd.Timedelta(days=35)
                ).date(),
            }
        )
    return pd.DataFrame(panel_rows), pd.DataFrame(gt_rows)


def test_walk_forward_predicts_and_reports_errors():
    panel, gt = _synthetic_world()
    backtest = walk_forward(panel, gt)
    assert len(backtest) > 0
    # Exact linear world: model should be near-perfect.
    assert backtest["pct_error"].abs().max() < 0.01
    summary = summarize(backtest)
    assert summary["model_mape"] < 0.01
    # R = 2·C is linear too, so the levels check is also near-exact.
    assert backtest["levels_pct_error"].abs().max() < 0.01
    assert summary["levels_mape"] < 0.01


def test_walk_forward_never_uses_unpublished_target_data():
    panel, gt = _synthetic_world()
    # Poison the target quarters' month-3 values with an absurd number that
    # only becomes available AFTER each filing date. If the walk-forward were
    # leaking future data, covered_revenue would explode.
    poison = panel[panel["month_end"] == panel["month_end"].max()].copy()
    poison["revenue"] = 1e12
    poison["available_from"] = pd.Timestamp("2099-01-01")
    clean_backtest = walk_forward(panel, gt)
    poisoned_backtest = walk_forward(pd.concat([panel, poison]), gt)
    # The poisoned rows are unpublished at every as_of, so results match.
    pd.testing.assert_series_equal(
        clean_backtest["covered_revenue"], poisoned_backtest["covered_revenue"]
    )


def test_walk_forward_target_quarter_not_in_training():
    panel, gt = _synthetic_world()
    # Corrupt the final quarter's reported revenue; earlier predictions must
    # be unaffected because that quarter is filed after their as_of dates.
    gt_corrupt = gt.copy()
    gt_corrupt.loc[gt_corrupt.index[-1], "revenue_usd"] *= 100
    a = walk_forward(panel, gt)
    b = walk_forward(panel, gt_corrupt)
    for col in ("prediction", "levels"):
        pd.testing.assert_series_equal(a[col].iloc[:-1], b[col].iloc[:-1])


def test_missing_lag_quarter_disables_naive_not_model():
    # Mirrors the real gap (2019Q4 underivable): the seasonal-naive needs
    # q-1/q-4/q-5, the model does not.
    panel, gt = _synthetic_world()
    gt_holed = gt[gt["quarter"] != "2021Q2"].reset_index(drop=True)
    backtest = walk_forward(panel, gt_holed)
    hit = backtest[backtest["quarter"] == "2022Q2"].iloc[0]  # lag-4 = 2021Q2
    assert np.isnan(hit["naive_pct_error"])
    assert hit["surprise_hit"] is None
    assert np.isfinite(hit["prediction"])
    summary = summarize(backtest)
    assert np.isfinite(summary["model_mape"])


def test_no_predictions_without_enough_training_quarters():
    panel, gt = _synthetic_world(n_quarters=9)  # 2020Q1..2022Q1
    # First eligible target 2022Q1 has only 8 quarters *ended*, but 2021Q4
    # files after 2022Q1's as_of cutoff... shrink further to force emptiness.
    backtest = walk_forward(panel, gt[gt["quarter"] <= "2021Q4"])
    assert backtest.empty


def test_intervals_appear_after_enough_errors_with_quantile_width():
    panel, gt = _synthetic_world()
    backtest = walk_forward(panel, gt)
    # No interval until MIN_ERRORS_FOR_INTERVAL prior walk-forward errors.
    assert backtest["interval_low"].iloc[:4].isna().all()
    with_intervals = backtest[backtest["interval_low"].notna()]
    assert len(with_intervals) > 0
    # Width mechanics: first interval-bearing row uses the 80% quantile of
    # the four prior absolute pct errors, applied symmetrically.
    row = with_intervals.iloc[0]
    prior = backtest["pct_error"].abs().iloc[:4]
    width = float(np.quantile(prior, 0.8))
    assert row["interval_low"] == pytest.approx(row["prediction"] * (1 - width))
    assert row["interval_high"] == pytest.approx(row["prediction"] * (1 + width))
