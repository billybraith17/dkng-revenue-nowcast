"""Golden-file and unit tests for the Iowa IRGC band parser.

Fixture: the real June 2026 monthly report (casino table + BY OPERATOR
section). Expected values hand-checked against the printed report.
"""

from pathlib import Path

import pandas as pd
import pytest

from ggr.parse.ia import _cluster_centers, _is_amendment_band, _number, _snap, parse_pdf
from ggr.schema import TIDY_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "ia_june2026.pdf"


@pytest.fixture(scope="module")
def ia() -> pd.DataFrame:
    return parse_pdf(FIXTURE, "https://example.test/ia")


def test_schema(ia):
    assert list(ia.columns) == TIDY_COLUMNS
    assert (ia["state"] == "IA").all()
    assert (ia["product"] == "osb").all()
    assert ia["operator_canonical"].notna().all()
    assert (ia["period_end"] == pd.Timestamp("2026-06-30")).all()


def test_draftkings_via_crown_ia(ia):
    dk = ia[ia["operator_canonical"] == "draftkings"]
    assert len(dk) == 1
    assert "Crown" in dk["operator_raw"].iloc[0]
    assert dk["gross_revenue"].iloc[0] == pytest.approx(5_864_678.80)
    assert dk["handle"].iloc[0] == pytest.approx(71_536_404.88)


def test_fanduel_via_betfair(ia):
    fd = ia[ia["operator_canonical"] == "fanduel"]
    assert fd["gross_revenue"].iloc[0] == pytest.approx(4_387_196.32)
    assert fd["handle"].iloc[0] == pytest.approx(44_139_875.95)


def test_negative_month_kept(ia):
    circa = ia[ia["operator_canonical"] == "circa"]
    assert circa["gross_revenue"].iloc[0] == pytest.approx(-2_737.79)


def test_operator_table_wins_over_casino_table(ia):
    # When the BY OPERATOR section exists, casino-licensee rows must not
    # leak in alongside it (that would double-count every dollar).
    assert not ia["operator_canonical"].str.startswith("diamond_jo").any()
    assert not (ia["operator_canonical"] == "wild_rose").any()


def test_number_cleaning():
    assert _number("$1,318,824.43") == pytest.approx(1_318_824.43)
    assert _number("($2,737.79)") == pytest.approx(-2_737.79)
    assert _number("-$45,669.25") == pytest.approx(-45_669.25)


def _word(mid, text="$1.00"):
    return {"x0": mid - 5, "x1": mid + 5, "text": text}


def test_cluster_and_snap_handle_blank_cells():
    receipts = [_word(100), _word(200), _word(300)]
    handles = [_word(101), _word(299)]  # middle column blank
    centers = _cluster_centers(receipts + handles)
    assert len(centers) == 3
    snapped = _snap(handles, centers)
    assert snapped[0] is not None and snapped[2] is not None
    assert snapped[1] is None


def test_snap_refuses_two_values_in_one_column():
    with pytest.raises(ValueError, match="two values snapped"):
        _snap([_word(100), _word(102)], [100.0])


def test_amendment_bands_detected():
    assert _is_amendment_band(["Amendments to published totals", "Harrah's"])
    assert _is_amendment_band(["as follows: Harrah's"])
    assert not _is_amendment_band(["Crown IA Gaming, LLC", "Betfair Interactive US LLC"])
