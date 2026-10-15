"""Golden-file tests for the NJ DGE sports wagering tax-return PDF parser.

Two fixtures, one per format era:

- June 2024 (modern): separate Resorts Digital return (DraftKings), skin
  detail pages to skip, a licensee filing twice (Tropicana), negative months.
- June 2019 (combined era): "TAX RETURN - RETAIL" siblings to skip, and the
  Ocean return whose internet section mislabels its lines as "Retail" — the
  section-scoped parsing this parser exists for.

All expected values hand-checked against the PDFs' printed lines.
"""

from pathlib import Path

import pandas as pd
import pytest

from ggr.parse.nj import _number, parse_pdf
from ggr.schema import TIDY_COLUMNS

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def nj24() -> pd.DataFrame:
    return parse_pdf(FIXTURES / "nj_sports_june2024.pdf", 2024, 6, "https://example.test/nj")


@pytest.fixture(scope="module")
def nj19() -> pd.DataFrame:
    return parse_pdf(FIXTURES / "nj_sports_june2019.pdf", 2019, 6, "https://example.test/nj")


def test_schema(nj24):
    assert list(nj24.columns) == TIDY_COLUMNS
    assert (nj24["state"] == "NJ").all()
    assert (nj24["product"] == "osb").all()
    assert nj24["operator_canonical"].notna().all()
    assert (nj24["period_end"] == pd.Timestamp("2024-06-30")).all()


def test_draftkings_under_resorts_digital(nj24):
    dk = nj24[nj24["operator_canonical"] == "draftkings"]
    assert len(dk) == 1
    assert dk["operator_raw"].iloc[0] == "RESORTS DIGITAL GAMING, LLC"
    assert dk["gross_revenue"].iloc[0] == pytest.approx(14_357_001)


def test_fanduel_under_meadowlands(nj24):
    fd = nj24[nj24["operator_canonical"] == "fanduel"]
    assert fd["gross_revenue"].iloc[0] == pytest.approx(29_342_676)


def test_negative_month_kept(nj24):
    ocean = nj24[nj24["operator_canonical"] == "ocean"]
    assert ocean["gross_revenue"].iloc[0] == pytest.approx(-29_927)


def test_double_filing_summed_once(nj24):
    # Tropicana files two returns in June 2024 (one all-dash, one with value);
    # they must produce a single summed row, not two rows or a double-count.
    trop = nj24[nj24["operator_raw"].str.contains("TROPICANA")]
    assert len(trop) == 1
    assert trop["gross_revenue"].iloc[0] == pytest.approx(2_011_644)


def test_skin_detail_pages_not_double_counted(nj24):
    bally = nj24[nj24["operator_canonical"] == "bally"]
    assert bally["gross_revenue"].iloc[0] == pytest.approx(1_915_362)


def test_dash_means_filed_zero(nj24):
    # Caesars AC files "-" (its online book reports via Tropicana's return);
    # that's a filed zero and must appear as a 0.0 row, not be dropped.
    caesars_ac = nj24[nj24["operator_raw"] == "CAESARS ATLANTIC CITY"]
    assert len(caesars_ac) == 1
    assert caesars_ac["gross_revenue"].iloc[0] == 0.0


def test_month_mismatch_raises():
    with pytest.raises(ValueError, match="expected MARCH 2024"):
        parse_pdf(FIXTURES / "nj_sports_june2024.pdf", 2024, 3, "https://example.test/nj")


def test_2019_combined_era(nj19):
    assert (nj19["period_end"] == pd.Timestamp("2019-06-30")).all()
    dk = nj19[nj19["operator_canonical"] == "draftkings"]
    assert dk["gross_revenue"].iloc[0] == pytest.approx(2_687_946)


def test_2019_mislabeled_internet_section(nj19):
    # Ocean's internet section labels its lines "Retail"; only the section
    # heading identifies the product. $793,682 is the online (William Hill)
    # revenue printed under the mislabeled line.
    ocean = nj19[nj19["operator_canonical"] == "ocean"]
    assert ocean["gross_revenue"].iloc[0] == pytest.approx(793_682)


def test_2019_retail_titled_returns_skipped(nj19):
    # Bally's files a combined return (26,752 online) plus a "- RETAIL" return
    # whose empty internet section must not zero or double the row.
    bally = nj19[nj19["operator_canonical"] == "bally"]
    assert len(bally) == 1
    assert bally["gross_revenue"].iloc[0] == pytest.approx(26_752)


def test_2019_negative_kept(nj19):
    borgata = nj19[nj19["operator_canonical"] == "betmgm"]
    assert borgata["gross_revenue"].iloc[0] == pytest.approx(-32_882)


def test_number_cleaning():
    assert _number("1 4,357,001") == 14_357_001
    assert _number("$ 2 6,752") == 26_752
    assert _number("(29,927)") == -29_927
    assert _number("-") == 0.0
