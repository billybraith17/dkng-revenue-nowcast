"""Coverage computation: quarter allocation, DK attribution, summary math."""

import pandas as pd
import pytest

from ggr.coverage import (
    allocate_to_quarters,
    coverage_summary,
    dk_attributable,
    quarter_completeness,
    split_period,
    state_quarter_table,
)


def _row(
    state="NJ",
    start="2024-01-01",
    end="2024-01-31",
    operator="draftkings",
    product="osb",
    gross=100.0,
    handle=1000.0,
):
    return {
        "state": state,
        "period_start": pd.Timestamp(start),
        "period_end": pd.Timestamp(end),
        "operator_raw": operator,
        "operator_canonical": operator,
        "product": product,
        "handle": handle,
        "gross_revenue": gross,
    }


# --- split_period / allocation ---


def test_month_maps_to_single_quarter():
    assert split_period(pd.Timestamp("2024-02-01"), pd.Timestamp("2024-02-29")) == [
        ("2024Q1", 29)
    ]


def test_straddling_week_prorated_by_days():
    # Thu 2024-03-28 .. Wed 2024-04-03: four days in Q1, three in Q2.
    assert split_period(pd.Timestamp("2024-03-28"), pd.Timestamp("2024-04-03")) == [
        ("2024Q1", 4),
        ("2024Q2", 3),
    ]


def test_allocation_splits_money_by_day_fraction():
    df = pd.DataFrame(
        [_row(state="NY", start="2024-03-28", end="2024-04-03", gross=700.0, handle=7000.0)]
    )
    out = allocate_to_quarters(df).set_index("quarter")
    assert out.loc["2024Q1", "gross_revenue"] == pytest.approx(400.0)
    assert out.loc["2024Q2", "gross_revenue"] == pytest.approx(300.0)
    assert out.loc["2024Q1", "handle"] == pytest.approx(4000.0)


def test_allocation_preserves_totals_and_missing_handle():
    df = pd.DataFrame(
        [_row(state="NY", start="2024-03-28", end="2024-04-03", gross=700.0, handle=None)]
    )
    out = allocate_to_quarters(df)
    assert out["gross_revenue"].sum() == pytest.approx(700.0)
    assert out["handle"].isna().all()


def test_year_boundary_split():
    assert split_period(pd.Timestamp("2023-12-31"), pd.Timestamp("2024-01-06")) == [
        ("2023Q4", 1),
        ("2024Q1", 6),
    ]


def test_period_spanning_three_quarters():
    # Not a real report shape, but the splitter must not assume ≤2 quarters.
    parts = split_period(pd.Timestamp("2024-03-01"), pd.Timestamp("2024-10-15"))
    assert parts == [("2024Q1", 31), ("2024Q2", 91), ("2024Q3", 92), ("2024Q4", 15)]
    assert sum(d for _, d in parts) == (
        pd.Timestamp("2024-10-15") - pd.Timestamp("2024-03-01")
    ).days + 1


def test_single_day_period():
    assert split_period(pd.Timestamp("2024-06-30"), pd.Timestamp("2024-06-30")) == [
        ("2024Q2", 1)
    ]


# --- DK attribution ---


def test_golden_nugget_attributed_only_after_acquisition():
    df = pd.DataFrame(
        [
            _row(operator="golden_nugget", start="2022-04-01", end="2022-04-30"),
            _row(operator="golden_nugget", start="2022-05-01", end="2022-05-31"),
            _row(operator="fanduel"),
        ]
    )
    out = dk_attributable(df)
    assert len(out) == 1
    assert out["period_end"].iloc[0] == pd.Timestamp("2022-05-31")


def test_draftkings_always_attributed():
    df = pd.DataFrame([_row(operator="draftkings", start="2019-01-01", end="2019-01-31")])
    assert len(dk_attributable(df)) == 1


# --- completeness ---


def test_completeness_full_quarter_of_months():
    df = pd.DataFrame(
        [
            _row(start="2024-01-01", end="2024-01-31"),
            _row(start="2024-02-01", end="2024-02-29"),
            _row(start="2024-03-01", end="2024-03-31"),
        ]
    )
    assert quarter_completeness(df)["2024Q1"] == pytest.approx(1.0)


def test_completeness_missing_trailing_month():
    df = pd.DataFrame(
        [
            _row(start="2024-01-01", end="2024-01-31"),
            _row(start="2024-02-01", end="2024-02-29"),
        ]
    )
    assert quarter_completeness(df)["2024Q1"] == pytest.approx(60 / 91)


def test_completeness_counts_each_week_once_across_operators():
    df = pd.DataFrame(
        [
            _row(state="NY", operator=op, start="2024-01-01", end="2024-01-07")
            for op in ("draftkings", "fanduel", "caesars")
        ]
    )
    assert quarter_completeness(df)["2024Q1"] == pytest.approx(7 / 91)


def test_completeness_raises_on_overlapping_periods():
    # Two distinct periods covering the same days would double-count and
    # silently read as "complete" — that's an upstream parser fault, so raise.
    df = pd.DataFrame(
        [
            _row(start="2024-01-01", end="2024-01-31"),
            _row(start="2024-01-15", end="2024-02-14"),
            _row(start="2024-02-01", end="2024-02-29"),
            _row(start="2024-03-01", end="2024-03-31"),
        ]
    )
    with pytest.raises(ValueError, match="overlapping periods"):
        quarter_completeness(df)


# --- state_quarter_table / coverage_summary ---


def _ground_truth():
    return pd.DataFrame(
        {
            "quarter": ["2024Q1"],
            "period_start": ["2024-01-01"],
            "period_end": ["2024-03-31"],
            "revenue_usd": [1000.0],
            "first_filed": ["2024-05-03"],
            "derived": [False],
        }
    )


def test_state_quarter_table_sums_dk_rows_only():
    frames = {
        "NJ": pd.DataFrame(
            [
                _row(start="2024-01-01", end="2024-01-31", gross=100.0),
                _row(start="2024-02-01", end="2024-02-29", gross=110.0),
                _row(start="2024-03-01", end="2024-03-31", gross=120.0),
                _row(start="2024-03-01", end="2024-03-31", operator="fanduel", gross=999.0),
            ]
        )
    }
    out = state_quarter_table(frames)
    assert len(out) == 1
    assert out["dk_gross_revenue"].iloc[0] == pytest.approx(330.0)
    assert out["completeness"].iloc[0] == pytest.approx(1.0)


def test_summary_coverage_ratio_and_partial_flag():
    frames = {
        "NJ": pd.DataFrame(
            [
                _row(start="2024-01-01", end="2024-01-31", gross=100.0),
                _row(start="2024-02-01", end="2024-02-29", gross=110.0),
                # March unpublished: partial quarter.
            ]
        ),
        "MI": pd.DataFrame(
            [
                _row(state="MI", start="2024-01-01", end="2024-01-31", gross=50.0),
                _row(state="MI", start="2024-02-01", end="2024-02-29", gross=50.0),
                _row(state="MI", start="2024-03-01", end="2024-03-31", gross=50.0),
                _row(
                    state="MI",
                    start="2024-03-01",
                    end="2024-03-31",
                    product="igaming",
                    gross=40.0,
                ),
            ]
        ),
    }
    summary = coverage_summary(state_quarter_table(frames), _ground_truth())
    row = summary.iloc[0]
    assert row["observed_osb"] == pytest.approx(360.0)
    assert row["observed_igaming"] == pytest.approx(40.0)
    assert row["observed_total"] == pytest.approx(400.0)
    assert row["coverage_pct"] == pytest.approx(0.4)
    assert row["n_states"] == 2
    assert row["partial_states"] == "NJ"
    assert row["missing_states"] == ""


def test_summary_flags_previously_seen_state_gone_missing():
    frames = {
        "NJ": pd.DataFrame(
            [
                _row(start="2023-12-01", end="2023-12-31", gross=100.0),
                _row(start="2024-01-01", end="2024-01-31", gross=100.0),
                _row(start="2024-02-01", end="2024-02-29", gross=110.0),
                _row(start="2024-03-01", end="2024-03-31", gross=120.0),
            ]
        ),
        # MI appeared in 2023Q4 then stopped publishing: a lag, flag it.
        "MI": pd.DataFrame(
            [_row(state="MI", start="2023-12-01", end="2023-12-31", gross=50.0)]
        ),
        # OH has never appeared, so its absence is pre-launch, not a lag.
        "OH": pd.DataFrame(
            [_row(state="OH", start="2024-06-01", end="2024-06-30", gross=10.0)]
        ),
    }
    summary = coverage_summary(state_quarter_table(frames), _ground_truth())
    row = summary.iloc[0]
    assert row["missing_states"] == "MI"
    assert row["n_states"] == 1


def test_summary_raises_on_unexpected_product():
    frames = {
        "XX": pd.DataFrame(
            [_row(state="XX", start="2024-01-01", end="2024-01-31", product="retail")]
        )
    }
    with pytest.raises(ValueError, match="unexpected products"):
        coverage_summary(state_quarter_table(frames), _ground_truth())


def test_summary_quarter_without_observations():
    ground_truth = _ground_truth()
    frames = {
        "NJ": pd.DataFrame([_row(start="2023-01-01", end="2023-01-31", gross=100.0)])
    }
    summary = coverage_summary(state_quarter_table(frames), ground_truth)
    row = summary.iloc[0]
    assert row["observed_total"] == 0.0
    assert row["coverage_pct"] == 0.0
    assert row["n_states"] == 0
    assert row["partial_states"] == ""
    assert row["missing_states"] == "NJ"
