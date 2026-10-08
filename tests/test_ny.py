"""Golden-file tests for the NY weekly parser.

The fixture is the real DraftKings cumulative workbook frozen on 2026-07-16.
Expected values are hand-checked against the published reports (launch week
ending 2022-01-09: $38,505,012.83 handle, $7,026,956 GGR — the widely reported
NY mobile launch numbers).
"""

from pathlib import Path

import pandas as pd
import pytest

from ggr.parse.ny import parse_workbook
from ggr.schema import TIDY_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "ny_draftkings_weekly.xlsx"


@pytest.fixture(scope="module")
def dk() -> pd.DataFrame:
    return parse_workbook(FIXTURE, "DraftKings", "https://example.test/dk")


def test_schema(dk):
    assert list(dk.columns) == TIDY_COLUMNS
    assert (dk["state"] == "NY").all()
    assert (dk["product"] == "osb").all()
    assert (dk["operator_canonical"] == "draftkings").all()


def test_launch_week(dk):
    launch = dk[dk["period_end"] == "2022-01-09"]
    assert len(launch) == 1
    assert launch["handle"].iloc[0] == pytest.approx(38_505_012.83)
    assert launch["gross_revenue"].iloc[0] == pytest.approx(7_026_956.00)
    assert launch["period_start"].iloc[0] == pd.Timestamp("2022-01-03")


def test_continuous_weekly_series(dk):
    assert not dk["period_end"].duplicated().any()
    gaps = dk["period_end"].sort_values().diff().dropna()
    assert (gaps == pd.Timedelta(days=7)).all()
    assert len(dk) >= 235  # weeks from 2022-01-09 through the 2026-07 freeze


def test_no_future_prefill_rows(dk):
    assert dk["period_end"].max() <= pd.Timestamp("2026-07-16")
    assert dk[["handle", "gross_revenue"]].notna().all().all()
