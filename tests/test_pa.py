"""Golden-file tests for the PGCB sports wagering parser.

The fixture is the real FY2022-2023 workbook — deliberately chosen because its
data sheet is mislabeled "FY 2021-22" while containing July 2022+ data, so
these tests also pin the periods-from-header-cells behavior. Expected values
hand-checked against the published sheet (Hollywood Casino, July 2022).
"""

from pathlib import Path

import pandas as pd
import pytest

from ggr.parse.pa import parse_workbook
from ggr.schema import TIDY_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "pa_sports_fy2022-23.xlsx"


@pytest.fixture(scope="module")
def pa() -> pd.DataFrame:
    return parse_workbook(FIXTURE, "https://example.test/pa")


def test_schema(pa):
    assert list(pa.columns) == TIDY_COLUMNS
    assert (pa["state"] == "PA").all()
    assert (pa["product"] == "osb").all()
    assert pa["operator_canonical"].notna().all()


def test_hollywood_july_2022(pa):
    row = pa[(pa["operator_raw"] == "HOLLYWOOD CASINO") & (pa["period_end"] == "2022-07-31")]
    assert len(row) == 1
    row = row.iloc[0]
    assert row["handle"] == pytest.approx(20_089_207.40)
    assert row["gross_revenue"] == pytest.approx(1_907_713.93)
    assert row["promo_credits"] == pytest.approx(490_864.75)
    assert row["adjusted_revenue"] == pytest.approx(1_416_849.18)


def test_periods_come_from_header_not_sheet_name(pa):
    # The data sheet is titled "FY 2021-22" but holds fiscal 2022-23 data.
    assert pa["period_end"].min() == pd.Timestamp("2022-07-31")
    assert pa["period_end"].max() == pd.Timestamp("2023-06-30")
    assert pa["period_end"].dt.year.isin([2022, 2023]).all()


def test_promo_identity_holds(pa):
    # PGCB defines taxable revenue as gross revenue minus promotional credits.
    full = pa.dropna(subset=["gross_revenue", "promo_credits", "adjusted_revenue"])
    assert not full.empty
    residual = (full["gross_revenue"] - full["promo_credits"] - full["adjusted_revenue"]).abs()
    assert residual.max() < 1.0


def test_draftkings_via_meadows_present(pa):
    dk = pa[pa["operator_canonical"] == "draftkings"]
    assert len(dk) == 12  # every month of the fiscal year
    assert set(dk["operator_raw"]) == {"HOLLYWOOD CASINO AT THE MEADOWS"}


def test_grand_total_not_an_operator(pa):
    assert not pa["operator_raw"].str.contains("total", case=False).any()
