"""Golden-file tests for the Michigan MGCB parser.

The fixture is the real Internet-Sports-Betting---2025.xlsx (Wayback snapshot
2025-12-14, data through October 2025, plus the embedded 2024 comparison
sheet). Expected values are read straight off the published sheet.
"""

from pathlib import Path

import pandas as pd
import pytest

from ggr.parse.mi import parse_workbook
from ggr.schema import TIDY_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "mi_isb_2025.xlsx"


@pytest.fixture(scope="module")
def mi() -> pd.DataFrame:
    return parse_workbook(FIXTURE, "osb", "https://example.test/mi")


def test_schema(mi):
    assert list(mi.columns) == TIDY_COLUMNS
    assert (mi["state"] == "MI").all()
    assert (mi["product"] == "osb").all()
    assert mi["operator_canonical"].notna().all()


def test_betmgm_january_2025(mi):
    row = mi[(mi["operator_canonical"] == "betmgm") & (mi["period_end"] == "2025-01-31")]
    assert len(row) == 1
    assert row["handle"].iloc[0] == pytest.approx(76_202_716.46)
    assert row["gross_revenue"].iloc[0] == pytest.approx(10_281_961.01)
    assert row["adjusted_revenue"].iloc[0] == pytest.approx(7_128_677.78)


def test_fanduel_january_2025(mi):
    row = mi[(mi["operator_canonical"] == "fanduel") & (mi["period_end"] == "2025-01-31")]
    assert row["handle"].iloc[0] == pytest.approx(218_250_546.75)


def test_covers_both_sheet_years(mi):
    years = mi["period_end"].dt.year.unique()
    assert set(years) == {2024, 2025}
    assert mi["period_end"].max() == pd.Timestamp("2025-10-31")


def test_unpublished_months_absent(mi):
    nov = mi[(mi["period_end"] == "2025-11-30")]
    assert nov.empty
