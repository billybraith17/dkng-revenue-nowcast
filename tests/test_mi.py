"""Golden-file tests for the Michigan MGCB parser.

The fixture is the real Internet-Sports-Betting---2025.xlsx (Wayback snapshot
2025-12-14, data through October 2025, plus the embedded 2024 comparison
sheet). Expected values are read straight off the published sheet.
"""

from pathlib import Path

import pandas as pd
import pytest

from ggr.ingest.mi import combine
from ggr.parse.mi import parse_workbook
from ggr.schema import TIDY_COLUMNS

FIXTURE = Path(__file__).parent / "fixtures" / "mi_isb_2025.xlsx"
# Internet-Sports-Betting---2026.xlsx, Wayback snapshot 2026-10-31: data
# through September 2026 plus the 2025 comparison sheet. From this file on
# MGCB prints current brand names over most columns.
FIXTURE_2026 = Path(__file__).parent / "fixtures" / "mi_isb_2026.xlsx"


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


@pytest.fixture(scope="module")
def mi26() -> pd.DataFrame:
    return parse_workbook(FIXTURE_2026, "osb", "https://example.test/mi26")


def _one(df, slug_or_raw, period_end, column="operator_raw"):
    row = df[(df[column] == slug_or_raw) & (df["period_end"] == period_end)]
    assert len(row) == 1
    return row.iloc[0]


def test_draftkings_2026_golden(mi26):
    # Cells read off the DraftKings (Bay Mills) column of the 2026 sheet.
    jan = _one(mi26, "DraftKings", "2026-01-31")
    assert jan["handle"] == pytest.approx(144_780_006.54)
    assert jan["gross_revenue"] == pytest.approx(16_184_347.48)
    assert jan["adjusted_revenue"] == pytest.approx(11_626_891.25)
    sep = _one(mi26, "DraftKings", "2026-09-30")
    assert sep["handle"] == pytest.approx(153_715_531.63)
    assert sep["gross_revenue"] == pytest.approx(14_241_569.84)
    assert sep["adjusted_revenue"] == pytest.approx(6_742_652.88)


def test_2026_comparison_sheet_completes_2025(mi26):
    # November and December 2025 are missing from the 2025 fixture.
    nov = _one(mi26, "DraftKings", "2025-11-30")
    assert nov["gross_revenue"] == pytest.approx(23_794_452.52)
    dec = _one(mi26, "DraftKings", "2025-12-31")
    assert dec["gross_revenue"] == pytest.approx(21_545_210.52)
    assert mi26["period_end"].max() == pd.Timestamp("2026-09-30")


def test_2026_relabelled_columns_are_known(mi26):
    names = mi26[mi26["period_end"] == "2026-09-30"].set_index("operator_raw")
    assert len(names) == 15
    assert names.loc["NeoGames", "operator_canonical"] == "nyx"
    assert names.loc["BetPARX", "operator_canonical"] == "parx"
    assert names.loc["Strive Platform", "operator_canonical"] == "pala"
    assert names.loc["NeoGames", "gross_revenue"] == pytest.approx(93_466.62)


def test_later_file_wins_whole_month_despite_relabel(mi, mi26):
    # The 2025 file calls the Hannahville column "TwinSpires"; the 2026 file's
    # 2025 sheet calls it "Hard Rock". Matching on name would keep both.
    merged = combine([mi.assign(_file_year=2025), mi26.assign(_file_year=2026)])
    oct25 = merged[merged["period_end"] == "2025-10-31"]
    assert len(oct25) == 15
    assert "Hard Rock" in set(oct25["operator_raw"])
    assert "TwinSpires" not in set(oct25["operator_raw"])
    assert not merged.duplicated(["period_end", "operator_raw"]).any()
    assert "_file_year" not in merged.columns
    # 2024 exists only in the 2025 file and must survive.
    assert len(merged[merged["period_end"] == "2024-01-31"]) == 15


def test_combine_order_of_frames_does_not_matter(mi, mi26):
    a = combine([mi.assign(_file_year=2025), mi26.assign(_file_year=2026)])
    b = combine([mi26.assign(_file_year=2026), mi.assign(_file_year=2025)])
    pd.testing.assert_frame_equal(a, b)


def test_combine_takes_revised_value_from_later_file(mi):
    later = mi[mi["period_end"] == "2025-01-31"].copy()
    later["gross_revenue"] = later["gross_revenue"] + 1.0
    merged = combine([mi.assign(_file_year=2025), later.assign(_file_year=2026)])
    row = _one(merged, "betmgm", "2025-01-31", column="operator_canonical")
    assert row["gross_revenue"] == pytest.approx(10_281_961.01 + 1.0)


def test_combine_raises_if_later_file_drops_an_operator(mi):
    later = mi[(mi["period_end"] == "2025-01-31") & (mi["operator_canonical"] != "betmgm")]
    with pytest.raises(ValueError, match="fewer operators"):
        combine([mi.assign(_file_year=2025), later.assign(_file_year=2026)])


# Internet-Gaming---2026.xlsx, Wayback snapshot 2026-10-31.
FIXTURE_IGAMING_2026 = Path(__file__).parent / "fixtures" / "mi_igaming_2026.xlsx"


@pytest.fixture(scope="module")
def mi26_igaming() -> pd.DataFrame:
    return parse_workbook(FIXTURE_IGAMING_2026, "igaming", "https://example.test/mi26-igaming")


def test_draftkings_igaming_2026_golden(mi26_igaming):
    # Cells read off the DraftKings (Bay Mills) column: gross receipts and
    # adjusted gross receipts. Internet gaming has no handle.
    jan = _one(mi26_igaming, "DraftKings", "2026-01-31")
    assert jan["gross_revenue"] == pytest.approx(45_479_177.75)
    assert jan["adjusted_revenue"] == pytest.approx(43_660_010.64)
    assert pd.isna(jan["handle"])
    sep = _one(mi26_igaming, "DraftKings", "2026-09-30")
    assert sep["gross_revenue"] == pytest.approx(44_759_520.78)
    assert sep["adjusted_revenue"] == pytest.approx(42_969_139.95)
    assert (mi26_igaming["product"] == "igaming").all()
    assert mi26_igaming["operator_canonical"].notna().all()


def test_draftkings_igaming_november_2025_is_as_printed(mi26_igaming):
    # About half the neighbouring months. That is what the sheet says; the
    # parser must not be "fixed" to make it look normal.
    nov = _one(mi26_igaming, "DraftKings", "2025-11-30")
    assert nov["gross_revenue"] == pytest.approx(19_987_902.15)
    assert nov["adjusted_revenue"] == pytest.approx(18_788_628.02)


def test_igaming_2026_unpublished_months_absent(mi26_igaming):
    assert mi26_igaming["period_end"].max() == pd.Timestamp("2026-09-30")
    assert len(mi26_igaming[mi26_igaming["period_end"] == "2026-09-30"]) == 15


def test_2026_has_two_caesars_columns_and_both_survive(mi26):
    sep = mi26[(mi26["period_end"] == "2026-09-30") & (mi26["operator_canonical"] == "caesars")]
    assert set(sep["operator_raw"]) == {"Caesars/WSOP", "Caesars Horshoe"}


def test_relabelled_hannahville_values_are_unchanged(mi, mi26):
    old = _one(mi, "TwinSpires", "2025-10-31")
    new = _one(mi26, "Hard Rock", "2025-10-31")
    for column in ("handle", "gross_revenue", "adjusted_revenue"):
        assert new[column] == pytest.approx(old[column])


def _frame(file_year, product, month_end, operators, gross=1.0):
    return pd.DataFrame(
        {
            "state": "MI",
            "product": product,
            "period_end": pd.Timestamp(month_end),
            "operator_raw": operators,
            "operator_canonical": [o.lower() for o in operators],
            "gross_revenue": gross,
            "_file_year": file_year,
        }
    )


def test_combine_single_file_passes_through():
    out = combine([_frame(2025, "osb", "2025-01-31", ["B", "A"])])
    assert list(out["operator_raw"]) == ["A", "B"]
    assert "_file_year" not in out.columns


def test_combine_products_are_resolved_independently():
    # Sports betting has a 2026 file, internet gaming does not: gaming's 2025
    # rows must survive although a later file exists for the other product.
    out = combine(
        [
            _frame(2025, "osb", "2025-01-31", ["A"], gross=1.0),
            _frame(2026, "osb", "2025-01-31", ["A"], gross=2.0),
            _frame(2025, "igaming", "2025-01-31", ["A"], gross=5.0),
        ]
    )
    assert out.set_index("product")["gross_revenue"].to_dict() == {"osb": 2.0, "igaming": 5.0}


def test_combine_latest_of_three_files_wins():
    out = combine(
        [
            _frame(2026, "osb", "2025-01-31", ["A"], gross=3.0),
            _frame(2024, "osb", "2025-01-31", ["A"], gross=1.0),
            _frame(2025, "osb", "2025-01-31", ["A"], gross=2.0),
        ]
    )
    assert list(out["gross_revenue"]) == [3.0]


def test_combine_allows_later_file_to_add_an_operator():
    out = combine(
        [
            _frame(2025, "osb", "2025-01-31", ["A"]),
            _frame(2026, "osb", "2025-01-31", ["A", "B"]),
        ]
    )
    assert list(out["operator_raw"]) == ["A", "B"]


def test_combine_same_count_different_names_takes_later_names():
    out = combine(
        [
            _frame(2025, "osb", "2025-01-31", ["A", "Old"]),
            _frame(2026, "osb", "2025-01-31", ["A", "New"]),
        ]
    )
    assert list(out["operator_raw"]) == ["A", "New"]


def test_combine_raises_if_widest_file_is_not_the_latest():
    # The middle file is the widest; the newest still has to match it.
    with pytest.raises(ValueError, match="fewer operators"):
        combine(
            [
                _frame(2024, "osb", "2025-01-31", ["A"]),
                _frame(2025, "osb", "2025-01-31", ["A", "B"]),
                _frame(2026, "osb", "2025-01-31", ["A"]),
            ]
        )


def test_combine_months_only_in_an_old_file_survive():
    out = combine(
        [
            _frame(2025, "osb", "2024-12-31", ["A"]),
            _frame(2026, "osb", "2025-01-31", ["A"]),
        ]
    )
    assert list(out["period_end"]) == [pd.Timestamp("2024-12-31"), pd.Timestamp("2025-01-31")]


def test_combine_empty_input_raises():
    with pytest.raises(ValueError):
        combine([])


def test_files_table_has_both_products_for_every_year():
    from ggr.ingest.mi import FILES

    years = sorted({year for _, year in FILES})
    assert years == list(range(2021, 2027))
    for year in years:
        assert ("osb", year) in FILES and ("igaming", year) in FILES
    assert len(set(FILES.values())) == len(FILES)
