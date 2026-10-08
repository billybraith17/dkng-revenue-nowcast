"""NY parser edge cases on synthetic workbooks reproducing real-file hostility:
shifted columns per sheet, blank future weeks, duplicated zero blocks,
negative-GGR weeks, and missing headers.
"""

import datetime as dt

import openpyxl
import pytest

from ggr.parse.ny import parse_workbook


def _make_workbook(tmp_path, sheets):
    """sheets: list of (title, header_row_cells, data_rows)."""
    wb = openpyxl.Workbook()
    for i, (title, header, data) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        ws.append(["some regulator boilerplate"])
        ws.append([])
        ws.append(header)
        for row in data:
            ws.append(row)
    path = tmp_path / "ny_synthetic.xlsx"
    wb.save(path)
    return path


HDR_A = ["Week-Ending", "Handle", None, "GGR"]
HDR_B = ["Week-Ending", None, "Handle", None, None, "GGR"]  # shifted, like FY 26-27


def test_columns_located_per_sheet(tmp_path):
    path = _make_workbook(
        tmp_path,
        [
            ("FY 23-24", HDR_A, [[dt.datetime(2024, 1, 7), 100.0, None, 10.0]]),
            ("FY 24-25", HDR_B, [[dt.datetime(2024, 4, 7), None, 200.0, None, None, 20.0]]),
        ],
    )
    df = parse_workbook(path, "DraftKings", "https://example.test")
    assert len(df) == 2
    assert df.set_index("period_end").loc["2024-01-07", "handle"] == 100.0
    assert df.set_index("period_end").loc["2024-04-07", "gross_revenue"] == 20.0


def test_blank_future_weeks_skipped_and_period_start_derived(tmp_path):
    path = _make_workbook(
        tmp_path,
        [
            (
                "FY 25-26",
                HDR_A,
                [
                    [dt.datetime(2026, 3, 29), 100.0, None, 10.0],
                    [dt.datetime(2026, 4, 5), None, None, None],  # pre-filled future week
                    ["Total", 100.0, None, 10.0],  # summary row, not a date
                ],
            )
        ],
    )
    df = parse_workbook(path, "DraftKings", "https://example.test")
    assert len(df) == 1
    assert df["period_start"].iloc[0] == dt.datetime(2026, 3, 23)


def test_negative_ggr_week_kept(tmp_path):
    path = _make_workbook(
        tmp_path,
        [("FY 23-24", HDR_A, [[dt.datetime(2023, 12, 3), 500.0, None, -42.5]])],
    )
    df = parse_workbook(path, "DraftKings", "https://example.test")
    assert df["gross_revenue"].iloc[0] == -42.5


def test_duplicate_zero_block_dropped(tmp_path):
    week = dt.datetime(2024, 4, 7)
    path = _make_workbook(
        tmp_path,
        [
            ("FY 24-25", HDR_A, [[week, 300.0, None, 30.0]]),
            ("FY 24-25 (2)", HDR_A, [[week, 0.0, None, 0.0]]),  # zero duplicate block
        ],
    )
    df = parse_workbook(path, "DraftKings", "https://example.test")
    assert len(df) == 1
    assert df["handle"].iloc[0] == 300.0


def test_conflicting_nonzero_duplicates_raise(tmp_path):
    week = dt.datetime(2024, 4, 7)
    path = _make_workbook(
        tmp_path,
        [
            ("FY 24-25", HDR_A, [[week, 300.0, None, 30.0]]),
            ("FY 24-25 (2)", HDR_A, [[week, 999.0, None, 99.0]]),
        ],
    )
    with pytest.raises(ValueError, match="conflicting non-zero rows"):
        parse_workbook(path, "DraftKings", "https://example.test")


def test_missing_header_raises(tmp_path):
    path = _make_workbook(
        tmp_path,
        [("FY 23-24", ["Week Ending (renamed!)", "Handle", None, "GGR"], [])],
    )
    with pytest.raises(ValueError, match="no Week-Ending/Handle/GGR header"):
        parse_workbook(path, "DraftKings", "https://example.test")


def test_unknown_operator_raises(tmp_path):
    path = _make_workbook(
        tmp_path,
        [("FY 23-24", HDR_A, [[dt.datetime(2024, 1, 7), 1.0, None, 1.0]])],
    )
    with pytest.raises(ValueError, match="unknown operator"):
        parse_workbook(path, "Some Future Sportsbook LLC", "https://example.test")
