"""Golden-file tests for the Indiana IGC per-skin detail parser.

Fixture: the real January 2024 monthly revenue workbook. Expected values
hand-checked against the "Detail of Sports Wagering Tax" sheet.
"""

from pathlib import Path

import pandas as pd
import pytest

from ggr.parse.indiana import parse_workbook
from ggr.schema import TIDY_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "in_2024-01.xlsx"


@pytest.fixture(scope="module")
def ind() -> pd.DataFrame:
    return parse_workbook(FIXTURE, 2024, 1, "https://example.test/in")


def test_schema(ind):
    assert list(ind.columns) == TIDY_COLUMNS
    assert (ind["state"] == "IN").all()
    assert (ind["product"] == "osb").all()
    assert ind["operator_canonical"].notna().all()
    assert (ind["period_end"] == pd.Timestamp("2024-01-31")).all()


def test_draftkings_skin_january_2024(ind):
    dk = ind[ind["operator_canonical"] == "draftkings"]
    assert len(dk) == 1
    assert dk["operator_raw"].iloc[0].startswith("AS - ")  # Ameristar licence
    assert dk["handle"].iloc[0] == pytest.approx(179_778_365)
    assert dk["gross_revenue"].iloc[0] == pytest.approx(18_743_497.99)


def test_fanduel_skin_january_2024(ind):
    fd = ind[ind["operator_canonical"] == "fanduel"]
    assert fd["handle"].iloc[0] == pytest.approx(159_595_239)
    assert fd["gross_revenue"].iloc[0] == pytest.approx(23_242_266)


def test_retail_and_aggregate_rows_excluded(ind):
    # Only "XX - domain" skin rows are emitted — no Retail/Adjustments/
    # Taxable AGR rows, and no casino-level rows.
    assert ind["operator_raw"].str.match(r"^[A-Z]{2,4}\s*-\s*\S").all()
    assert not ind["operator_raw"].str.contains("Retail|Taxable|Adjust", case=False).any()


def test_both_column_groups_parsed(ind):
    # Northern and Southern licensee groups both contribute skins.
    assert len(ind) >= 10


def test_month_mismatch_raises():
    with pytest.raises(ValueError, match="doesn't state march 2024"):
        parse_workbook(FIXTURE, 2024, 3, "https://example.test/in")
