"""Source-priority and same-slug aggregation for the Iowa ingest.

Pins the fix for a silent-loss bug: dedupe keyed on canonical slug was
dropping two of Wild Rose's three casinos (one company, one slug) every
month of the casino-table era.
"""

import pandas as pd

from ggr.ingest.ia import _prefer_and_aggregate
from ggr.schema import TIDY_COLUMNS


def _row(raw, slug, gross, handle=None, period="2020-11-30", prio=0, src="archive"):
    return {
        "state": "IA",
        "period_start": "2020-11-01",
        "period_end": pd.Timestamp(period),
        "operator_raw": raw,
        "operator_canonical": slug,
        "product": "osb",
        "handle": handle,
        "gross_revenue": gross,
        "source_url": f"https://example.test/{src}",
        "fetched_at": "2026-07-17T00:00:00",
        "_src": src,
        "_prio": prio,
    }


def test_same_slug_entities_are_summed_not_deduped():
    df = _prefer_and_aggregate(
        pd.DataFrame(
            [
                _row("Wild Rose - Clinton", "wild_rose", 100.0, 1000.0),
                _row("Wild Rose - Emmetsburg", "wild_rose", 200.0, 2000.0),
                _row("Wild Rose - Jefferson", "wild_rose", 300.0, 3000.0),
                _row("Q Casino", "q_casino", 50.0, 500.0),
            ]
        )
    )
    wr = df[df["operator_canonical"] == "wild_rose"]
    assert len(wr) == 1
    assert wr["gross_revenue"].iloc[0] == 600.0
    assert wr["handle"].iloc[0] == 6000.0
    assert "Clinton" in wr["operator_raw"].iloc[0]
    assert "Jefferson" in wr["operator_raw"].iloc[0]
    assert df[df["operator_canonical"] == "q_casino"]["gross_revenue"].iloc[0] == 50.0


def test_earlier_source_wins_whole_month_slug():
    df = _prefer_and_aggregate(
        pd.DataFrame(
            [
                _row("Wild Rose - Clinton", "wild_rose", 100.0, prio=0, src="fy-archive"),
                _row("Wild Rose - Jefferson", "wild_rose", 300.0, prio=0, src="fy-archive"),
                _row("Wild Rose - Clinton", "wild_rose", 999.0, prio=5, src="monthly"),
            ]
        )
    )
    assert len(df) == 1
    assert df["gross_revenue"].iloc[0] == 400.0  # archive rows only, summed


def test_missing_values_stay_missing_not_zero():
    df = _prefer_and_aggregate(
        pd.DataFrame([_row("Q Casino", "q_casino", 50.0, handle=None)])
    )
    assert pd.isna(df["handle"].iloc[0])
    assert df["gross_revenue"].iloc[0] == 50.0


def test_schema_columns_restored():
    df = _prefer_and_aggregate(pd.DataFrame([_row("Q Casino", "q_casino", 50.0)]))
    assert list(df.columns) == TIDY_COLUMNS
    assert df["promo_credits"].isna().all()


def test_distinct_periods_not_merged():
    df = _prefer_and_aggregate(
        pd.DataFrame(
            [
                _row("Wild Rose - Clinton", "wild_rose", 100.0, period="2020-11-30"),
                _row("Wild Rose - Clinton", "wild_rose", 150.0, period="2020-12-31"),
            ]
        )
    )
    assert len(df) == 2
    assert sorted(df["gross_revenue"]) == [100.0, 150.0]
