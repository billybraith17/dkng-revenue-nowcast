"""Golden-file and edge-case tests for the IGB accrual detail CSV parser.

The fixture is the real January 2024 accrual Detail Report. DraftKings
(Casino Queen, Inc.) golden values are the sums of the raw tier 1 + tier 2
handle/payout cells across the Professional/College sport-level rows,
hand-checked against the CSV text.
"""

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from ggr.parse.il import _number, month_range, parse_csv
from ggr.schema import TIDY_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "il_detail_2024-01.csv"

DK_HANDLE = 211_598_913.07 + 154_051_305.70 + 62_929_754.72 + 18_031_406.78
DK_PAYOUT = 188_711_893.75 + 135_914_393.54 + 60_236_272.50 + 17_524_266.97


@pytest.fixture(scope="module")
def il() -> pd.DataFrame:
    return parse_csv(FIXTURE, 2024, 1, "https://example.test/il")


def test_schema(il):
    assert list(il.columns) == TIDY_COLUMNS
    assert (il["state"] == "IL").all()
    assert (il["product"] == "osb").all()
    assert il["operator_canonical"].notna().all()


def test_draftkings_january_2024(il):
    dk = il[il["operator_raw"] == "Casino Queen, Inc."]
    assert len(dk) == 1
    assert dk["operator_canonical"].iloc[0] == "draftkings"
    assert dk["handle"].iloc[0] == pytest.approx(DK_HANDLE)
    assert dk["gross_revenue"].iloc[0] == pytest.approx(DK_HANDLE - DK_PAYOUT)
    assert dk["period_end"].iloc[0] == pd.Timestamp("2024-01-31")


def test_only_online_rows_no_totals(il):
    # 'Total' pseudo-licensee rows and in-person rows must not leak through
    assert not il["operator_raw"].str.lower().eq("total").any()
    assert (il.groupby("operator_raw").size() == 1).all()


def test_par_a_dice_is_betmgm_in_2024(il):
    pad = il[il["operator_raw"].str.contains("Par-A-Dice")]
    assert pad["operator_canonical"].iloc[0] == "betmgm"


def test_era_override_fanduel_in_2021():
    text = FIXTURE.read_text().replace("January 2024", "January 2021")
    fake = FIXTURE.parent / "_tmp_il_2021.csv"
    fake.write_text(text)
    try:
        df = parse_csv(fake, 2021, 1, "https://example.test/il")
    finally:
        fake.unlink()
    pad = df[df["operator_raw"].str.contains("Par-A-Dice")]
    assert pad["operator_canonical"].iloc[0] == "fanduel"


def test_month_mismatch_raises():
    with pytest.raises(ValueError, match="expected 'March 2024'"):
        parse_csv(FIXTURE, 2024, 3, "https://example.test/il")


def test_number_cleaning():
    assert _number("1,234.56") == pytest.approx(1234.56)
    assert _number("(500.00)") == -500.0
    assert _number("") == 0.0


def test_csv_with_no_online_rows_gives_empty_frame(tmp_path):
    text = (
        '"Completed Events Detail"\n"January 2021"\n\n'
        '"Sport Level","Location Type","Licensee","Tier 1 Wagers","Tier 1 Handle",'
        '"Tier 1 Payout","Tier 2 Wagers","Tier 2 Handle","Tier 2 Payout",\n'
        'Professional,In-Person Wagering,"Some Casino","1","100.00","90.00","0","0.00","0.00",\n'
    )
    path = tmp_path / "il_detail_2021-01.csv"
    path.write_text(text)
    df = parse_csv(path, 2021, 1, "https://example.test/il")
    assert df.empty
    assert list(df.columns) == TIDY_COLUMNS


def test_month_range_excludes_current_month():
    months = month_range((2020, 6), dt.date(2020, 9, 15))
    assert months == [(2020, 6), (2020, 7), (2020, 8)]
    assert month_range((2020, 6), dt.date(2020, 6, 20)) == []
