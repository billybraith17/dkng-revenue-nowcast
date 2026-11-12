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

from ggr.ingest import il as ingest_il
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


def _fetch_month_force(tmp_path, monkeypatch, cached_text: str | None) -> bool:
    """Run fetch_month for January 2024 (long past the refetch window) and
    return the ``force`` flag it passed to the cache."""
    monkeypatch.setattr(ingest_il, "DATA_RAW", tmp_path)
    if cached_text is not None:
        (tmp_path / "il").mkdir()
        (tmp_path / "il" / "il_detail_2024-01.csv").write_text(cached_text)
    seen = {}

    def fake_fetch_post(url, data, name, subdir, force):
        seen["force"] = force
        return tmp_path / subdir / name

    monkeypatch.setattr(ingest_il.cache, "fetch_post", fake_fetch_post)
    ingest_il.fetch_month(2024, 1, {})
    return seen["force"]


def test_old_cached_report_is_not_refetched(tmp_path, monkeypatch):
    assert _fetch_month_force(tmp_path, monkeypatch, FIXTURE.read_text()) is False


def test_old_cached_html_placeholder_is_refetched(tmp_path, monkeypatch):
    # A month requested before publication is stored as the app's HTML page.
    html = "\r\n\r\n<!DOCTYPE html>\n<html><head><title>Sports Wagering</title></head></html>"
    assert _fetch_month_force(tmp_path, monkeypatch, html) is True


def test_old_uncached_month_is_not_forced(tmp_path, monkeypatch):
    assert _fetch_month_force(tmp_path, monkeypatch, None) is False


def test_recent_month_is_always_refetched(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_il, "DATA_RAW", tmp_path)
    seen = {}
    monkeypatch.setattr(
        ingest_il.cache,
        "fetch_post",
        lambda url, data, name, subdir, force: seen.setdefault("force", force),
    )
    recent = dt.date.today() - dt.timedelta(days=40)
    ingest_il.fetch_month(recent.year, recent.month, {})
    assert seen["force"] is True


@pytest.mark.parametrize(
    "text, expected",
    [
        ('"Completed Events Detail"\n"January 2024"\n', True),
        ('\r\n\r\n"Completed Events Detail"\n', True),
        ("<!DOCTYPE html>\n<html></html>", False),
        ("\r\n\r\n<!doctype html>\n<html></html>", False),
        ("<html><body>Your search returned no revenue results.</body></html>", False),
        ("", False),
        ("   \r\n  ", False),
    ],
)
def test_is_report(tmp_path, text, expected):
    path = tmp_path / "month.csv"
    path.write_text(text)
    assert ingest_il._is_report(path) is expected


def test_real_fixture_is_a_report():
    assert ingest_il._is_report(FIXTURE) is True


HTML_PAGE = (
    "\r\n<!DOCTYPE html>\n<html><body>Your search returned no revenue results.</body></html>"
)


def _fake_app(tmp_path, monkeypatch, months, responses, cached=None):
    """Point the ingest at a fake report app.

    ``responses`` maps a cache name to the text the app returns for it;
    ``cached`` pre-populates the raw cache. Returns the list of names that
    were actually requested from the app.
    """
    monkeypatch.setattr(ingest_il, "DATA_RAW", tmp_path)
    monkeypatch.setattr(ingest_il, "_form_tokens", lambda: {})
    monkeypatch.setattr(ingest_il, "month_range", lambda first, today: months)
    (tmp_path / "il").mkdir()
    for name, text in (cached or {}).items():
        (tmp_path / "il" / name).write_text(text)
    requested = []

    def fake_fetch_post(url, data, name, subdir, force):
        path = tmp_path / subdir / name
        if force or not path.exists():
            requested.append(name)
            path.write_text(responses[name])
        return path

    monkeypatch.setattr(ingest_il.cache, "fetch_post", fake_fetch_post)
    return requested


def test_build_recovers_a_month_cached_before_publication(tmp_path, monkeypatch):
    name = "il_detail_2024-01.csv"
    requested = _fake_app(
        tmp_path,
        monkeypatch,
        months=[(2024, 1)],
        responses={name: FIXTURE.read_text()},
        cached={name: HTML_PAGE},
    )
    df = ingest_il.build()
    assert requested == [name]
    dk = df[df["operator_canonical"] == "draftkings"]
    assert dk["handle"].sum() == pytest.approx(DK_HANDLE)


def test_build_does_not_request_an_old_month_already_cached(tmp_path, monkeypatch):
    name = "il_detail_2024-01.csv"
    requested = _fake_app(
        tmp_path, monkeypatch, months=[(2024, 1)], responses={}, cached={name: FIXTURE.read_text()}
    )
    df = ingest_il.build()
    assert requested == []
    assert len(df) > 0


def test_build_raises_if_an_old_month_is_still_not_a_report(tmp_path, monkeypatch):
    # Re-requested, the app still has nothing: an old month must not be skipped.
    name = "il_detail_2024-01.csv"
    requested = _fake_app(
        tmp_path,
        monkeypatch,
        months=[(2024, 1)],
        responses={name: HTML_PAGE},
        cached={name: HTML_PAGE},
    )
    with pytest.raises(ValueError, match="January 2024"):
        ingest_il.build()
    assert requested == [name]


def test_build_skips_a_recent_unpublished_month_but_keeps_the_rest(tmp_path, monkeypatch, capsys):
    recent = dt.date.today() - dt.timedelta(days=40)
    recent_name = f"il_detail_{recent.year}-{recent.month:02d}.csv"
    old_name = "il_detail_2024-01.csv"
    requested = _fake_app(
        tmp_path,
        monkeypatch,
        months=[(2024, 1), (recent.year, recent.month)],
        responses={old_name: FIXTURE.read_text(), recent_name: HTML_PAGE},
    )
    df = ingest_il.build()
    assert requested == [old_name, recent_name]
    assert set(df["period_end"]) == {pd.Timestamp("2024-01-31")}
    assert "not yet published" in capsys.readouterr().out


def test_build_raises_on_wrong_month_in_an_old_report(tmp_path, monkeypatch):
    # The app answers with a real report for a different month.
    name = "il_detail_2023-12.csv"
    _fake_app(tmp_path, monkeypatch, months=[(2023, 12)], responses={name: FIXTURE.read_text()})
    with pytest.raises(ValueError, match="December 2023"):
        ingest_il.build()
