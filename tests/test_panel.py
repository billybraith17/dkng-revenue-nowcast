"""Availability clock, month pro-rating, as-of views, and imputation."""

import pandas as pd
import pytest

from ggr.panel import as_of_view, build_panel, impute_month


def _frame(rows):
    return pd.DataFrame(rows)


def _monthly(state, start, end, gross, operator="draftkings", lag_check=None):
    return {
        "state": state,
        "period_start": pd.Timestamp(start),
        "period_end": pd.Timestamp(end),
        "operator_raw": operator,
        "operator_canonical": operator,
        "product": "osb",
        "gross_revenue": gross,
    }


def test_monthly_piece_availability_uses_state_lag():
    panel = build_panel(
        {"IN": _frame([_monthly("IN", "2024-01-01", "2024-01-31", 100.0)])}
    )
    assert len(panel) == 1
    # IN lag is 14 days after period end
    assert panel["available_from"].iloc[0] == pd.Timestamp("2024-02-14")
    assert panel["revenue"].iloc[0] == 100.0
    assert panel["days"].iloc[0] == 31


def test_weekly_row_split_across_months():
    # Week Mon 2024-01-29 .. Sun 2024-02-04: 3 days in Jan, 4 in Feb.
    panel = build_panel(
        {"NY": _frame([_monthly("NY", "2024-01-29", "2024-02-04", 700.0)])}
    )
    jan = panel[panel["month_end"] == "2024-01-31"]
    feb = panel[panel["month_end"] == "2024-02-29"]
    assert jan["revenue"].iloc[0] == pytest.approx(300.0)
    assert feb["revenue"].iloc[0] == pytest.approx(400.0)
    # Both pieces become available when the *week* publishes (end + 8 days).
    assert (panel["available_from"] == pd.Timestamp("2024-02-12")).all()


def test_non_dk_rows_excluded():
    panel = build_panel(
        {
            "IN": _frame(
                [
                    _monthly("IN", "2024-01-01", "2024-01-31", 100.0),
                    _monthly("IN", "2024-01-01", "2024-01-31", 999.0, operator="fanduel"),
                ]
            )
        }
    )
    assert panel["revenue"].sum() == 100.0


def test_as_of_view_excludes_unpublished():
    panel = build_panel(
        {
            "IN": _frame(
                [
                    _monthly("IN", "2024-01-01", "2024-01-31", 100.0),
                    _monthly("IN", "2024-02-01", "2024-02-29", 200.0),
                ]
            )
        }
    )
    view = as_of_view(panel, pd.Timestamp("2024-02-20"))  # Feb publishes Mar 14
    assert list(view["month_end"]) == [pd.Timestamp("2024-01-31")]
    later = as_of_view(panel, pd.Timestamp("2024-03-14"))
    assert len(later) == 2


def test_partial_month_scaled_but_launch_month_not():
    weeks = []
    # Launch month: first week starts mid-June — must NOT be scaled up.
    weeks.append(_monthly("NY", "2024-06-17", "2024-06-23", 70.0))
    weeks.append(_monthly("NY", "2024-06-24", "2024-06-30", 70.0))
    # July: four full weeks published, last few days' week not yet published.
    for start in ("2024-07-01", "2024-07-08", "2024-07-15", "2024-07-22"):
        s = pd.Timestamp(start)
        weeks.append(_monthly("NY", s, s + pd.Timedelta(days=6), 70.0))
    panel = build_panel({"NY": _frame(weeks)})
    view = as_of_view(panel, pd.Timestamp("2024-08-06"))  # July 29 week unpublished
    june = view[view["month_end"] == "2024-06-30"]["revenue"].iloc[0]
    july = view[view["month_end"] == "2024-07-31"]["revenue"].iloc[0]
    assert june == pytest.approx(140.0)  # launch month: no scaling
    assert july == pytest.approx(280.0 * 31 / 28)  # 28 of 31 days observed
    assert not view[view["month_end"] == "2024-07-31"]["complete"].iloc[0]


def test_as_of_view_counts_shared_week_days_once():
    # Two operators (draftkings + post-2022 golden_nugget) share one week:
    # revenue sums, but day coverage must not double — if the shared week
    # counted as 14 days, July's partial-month scaling would be wrong.
    rows = [
        _monthly("NY", "2024-06-24", "2024-06-30", 70.0),  # launch month
        _monthly("NY", "2024-07-01", "2024-07-07", 70.0),
        _monthly("NY", "2024-07-01", "2024-07-07", 30.0, operator="golden_nugget"),
    ]
    panel = build_panel({"NY": _frame(rows)})
    view = as_of_view(panel, pd.Timestamp("2024-12-31"))
    july = view[view["month_end"] == "2024-07-31"].iloc[0]
    assert july["revenue"] == pytest.approx((70.0 + 30.0) * 31 / 7)
    assert not july["complete"]


def test_impute_month_share_of_references():
    view = pd.DataFrame(
        {
            "state": ["NY", "NJ", "NY", "NJ", "NY"],
            "month_end": pd.to_datetime(
                ["2024-01-31", "2024-01-31", "2024-02-29", "2024-02-29", "2024-03-31"]
            ),
            "revenue": [100.0, 50.0, 200.0, 100.0, 300.0],
            "complete": True,
        }
    )
    # NJ was half of NY in both observed months → March imputed at 150.
    assert impute_month(view, "NJ", pd.Timestamp("2024-03-31")) == pytest.approx(150.0)


def test_impute_month_raises_without_references():
    view = pd.DataFrame(
        {
            "state": ["NJ"],
            "month_end": [pd.Timestamp("2024-01-31")],
            "revenue": [50.0],
            "complete": True,
        }
    )
    with pytest.raises(ValueError, match="no reference states"):
        impute_month(view, "NJ", pd.Timestamp("2024-02-29"))


def test_impute_month_raises_without_history():
    view = pd.DataFrame(
        {
            "state": ["NY"],
            "month_end": [pd.Timestamp("2024-03-31")],
            "revenue": [300.0],
            "complete": True,
        }
    )
    with pytest.raises(ValueError, match="no history"):
        impute_month(view, "NJ", pd.Timestamp("2024-03-31"))


def test_build_panel_raises_on_no_dk_rows():
    with pytest.raises(ValueError, match="no DK-attributable"):
        build_panel(
            {"IN": _frame([_monthly("IN", "2024-01-01", "2024-01-31", 1.0, "fanduel")])}
        )
