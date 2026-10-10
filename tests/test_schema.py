import pandas as pd
import pytest

from ggr.schema import TIDY_COLUMNS, tidy_frame


def _row(**overrides) -> dict:
    base = {
        "state": "NY",
        "period_start": "2024-01-01",
        "period_end": "2024-01-07",
        "operator_raw": "DraftKings",
        "operator_canonical": "draftkings",
        "product": "osb",
        "handle": 1000.0,
        "gross_revenue": 100.0,
        "source_url": "https://example.test",
        "fetched_at": "2026-07-16T00:00:00",
    }
    return base | overrides


def test_missing_columns_filled_with_none():
    df = tidy_frame([_row()])
    assert list(df.columns) == TIDY_COLUMNS
    assert df["promo_credits"].isna().all()
    assert df["adjusted_revenue"].isna().all()


def test_unknown_column_raises():
    with pytest.raises(ValueError, match="unknown columns.*typo_col"):
        tidy_frame([_row(typo_col=1)])


def test_dates_and_numerics_coerced():
    df = tidy_frame([_row(handle="1234.5", gross_revenue=None)])
    assert df["period_end"].dtype.kind == "M"
    assert df["handle"].iloc[0] == pytest.approx(1234.5)
    assert pd.isna(df["gross_revenue"].iloc[0])


def test_non_numeric_value_raises():
    with pytest.raises((ValueError, TypeError)):
        tidy_frame([_row(handle="#REF!")])


def test_negative_revenue_preserved():
    df = tidy_frame([_row(gross_revenue=-50_000.0)])
    assert df["gross_revenue"].iloc[0] == -50_000.0


def test_empty_rows_give_empty_frame_with_schema():
    df = tidy_frame([])
    assert list(df.columns) == TIDY_COLUMNS
    assert df.empty
