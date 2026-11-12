"""EDGAR ground-truth logic on synthetic company facts (no network)."""

import pandas as pd
import pytest

from ggr.ingest import edgar


def _fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def _facts_doc(entries, concept="RevenueFromContractWithCustomerExcludingAssessedTax"):
    return {"facts": {"us-gaap": {concept: {"units": {"USD": entries}}}}}


def _submissions(filings):
    """Filing index in the SEC's column layout from (form, accepted UTC, report, items) rows."""
    cols = list(zip(*filings, strict=True)) if filings else [[], [], [], []]
    keys = ("form", "acceptanceDateTime", "reportDate", "items")
    return {"filings": {"recent": dict(zip(keys, map(list, cols), strict=True)), "files": []}}


@pytest.fixture()
def patched(monkeypatch):
    def _patch(doc_by_cik, submissions_by_cik=None):
        monkeypatch.setattr(edgar, "load_companyfacts", lambda cik, force=False: doc_by_cik[cik])
        monkeypatch.setattr(
            edgar,
            "load_submissions",
            lambda cik, force=False: (submissions_by_cik or {}).get(cik, _submissions([])),
        )

    return _patch


BASE_2023 = [
    _fact("2023-01-01", "2023-03-31", 100.0, "2023-05-01"),
    _fact("2023-04-01", "2023-06-30", 110.0, "2023-08-01"),
    _fact("2023-01-01", "2023-06-30", 210.0, "2023-08-01"),  # H1 YTD — must be excluded
    _fact("2023-07-01", "2023-09-30", 120.0, "2023-11-01"),
    _fact("2023-01-01", "2023-12-31", 430.0, "2024-02-15", form="10-K"),
]


def test_q4_derived_from_fy(patched):
    patched({1: _facts_doc(BASE_2023)})
    df = edgar.quarterly_revenue(ciks=[1])
    q4 = df[df["quarter"] == "2023Q4"].iloc[0]
    assert q4["revenue_usd"] == pytest.approx(430.0 - 330.0)
    assert q4["derived"]
    assert q4["first_filed"] == pd.Timestamp("2024-02-15")  # carries the 10-K date
    assert list(df["quarter"]) == ["2023Q1", "2023Q2", "2023Q3", "2023Q4"]


def test_ytd_periods_excluded(patched):
    patched({1: _facts_doc(BASE_2023)})
    df = edgar.quarterly_revenue(ciks=[1])
    assert 210.0 not in df["revenue_usd"].values


def test_restatement_takes_latest_value_but_earliest_filed(patched):
    entries = BASE_2023 + [_fact("2023-01-01", "2023-03-31", 105.0, "2024-05-01")]
    patched({1: _facts_doc(entries)})
    q1 = edgar.quarterly_revenue(ciks=[1]).set_index("quarter").loc["2023Q1"]
    assert q1["revenue_usd"] == 105.0  # restated value wins
    assert q1["first_filed"] == pd.Timestamp("2023-05-01")  # information clock unchanged


def test_no_q4_when_a_quarter_is_missing(patched):
    entries = [e for e in BASE_2023 if e["val"] != 110.0]  # drop Q2
    patched({1: _facts_doc(entries)})
    df = edgar.quarterly_revenue(ciks=[1])
    assert "2023Q4" not in df["quarter"].values


def test_no_double_q4_if_q4_already_filed(patched):
    entries = BASE_2023 + [_fact("2023-10-01", "2023-12-31", 99.0, "2024-02-15", form="10-K")]
    patched({1: _facts_doc(entries)})
    df = edgar.quarterly_revenue(ciks=[1])
    q4 = df[df["quarter"] == "2023Q4"]
    assert len(q4) == 1
    assert q4["revenue_usd"].iloc[0] == 99.0
    assert not q4["derived"].iloc[0]


def test_same_period_across_two_ciks_deduped(patched):
    doc1 = _facts_doc([_fact("2021-01-01", "2021-03-31", 50.0, "2021-05-07")])
    doc2 = _facts_doc([_fact("2021-01-01", "2021-03-31", 50.0, "2022-05-06")])
    patched({1: doc1, 2: doc2})
    df = edgar.quarterly_revenue(ciks=[1, 2])
    assert len(df) == 1
    assert df["first_filed"].iloc[0] == pd.Timestamp("2021-05-07")  # original filing wins


def test_both_revenue_concepts_merged(patched):
    doc = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerIncludingAssessedTax": {
                    "units": {"USD": [_fact("2022-01-01", "2022-03-31", 70.0, "2022-05-06")]}
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [_fact("2022-01-01", "2022-03-31", 70.0, "2023-05-05")]}
                },
            }
        }
    }
    patched({1: doc})
    df = edgar.quarterly_revenue(ciks=[1])
    assert len(df) == 1
    assert df["first_filed"].iloc[0] == pd.Timestamp("2022-05-06")


# DraftKings' real 2019 facts: no discrete Q1 or Q4 was ever filed, only the
# half-year, nine-month and full-year totals (first tagged in 2020-21 filings).
FACTS_2019 = [
    _fact("2019-01-01", "2019-06-30", 125_482_000.0, "2020-08-14"),
    _fact("2019-04-01", "2019-06-30", 57_390_000.0, "2020-08-14"),
    _fact("2019-01-01", "2019-09-30", 192_496_000.0, "2020-11-13"),
    _fact("2019-07-01", "2019-09-30", 67_014_000.0, "2020-11-13"),
    _fact("2019-01-01", "2019-12-31", 323_410_000.0, "2021-02-26", form="10-K"),
]

# Q2, H1, Q3 and FY for a year with no discrete Q1.
NO_Q1 = [
    _fact("2023-04-01", "2023-06-30", 110.0, "2023-08-01"),
    _fact("2023-01-01", "2023-06-30", 210.0, "2023-08-01"),
    _fact("2023-07-01", "2023-09-30", 120.0, "2023-11-01"),
    _fact("2023-01-01", "2023-12-31", 430.0, "2024-02-15", form="10-K"),
]


def _quarters(patched, entries, submissions=None):
    patched({1: _facts_doc(entries)}, {1: submissions} if submissions else None)
    return edgar.quarterly_revenue(ciks=[1]).set_index("quarter")


# --- Q1 derived from the half-year total -----------------------------------


def test_q1_derived_from_half_year_then_q4_from_fy(patched):
    df = _quarters(patched, FACTS_2019)
    assert list(df.index) == ["2019Q1", "2019Q2", "2019Q3", "2019Q4"]
    assert df.loc["2019Q1", "revenue_usd"] == pytest.approx(68_092_000.0)  # H1 - Q2
    assert df.loc["2019Q1", "derived"]
    assert df.loc["2019Q1", "first_filed"] == pd.Timestamp("2020-08-14")
    assert df.loc["2019Q1", "period_start"] == pd.Timestamp("2019-01-01")
    assert df.loc["2019Q1", "period_end"] == pd.Timestamp("2019-03-31")
    assert df.loc["2019Q4", "revenue_usd"] == pytest.approx(130_914_000.0)  # FY - 9M
    assert df.loc["2019Q4", "first_filed"] == pd.Timestamp("2021-02-26")
    assert not df.loc["2019Q2", "derived"] and not df.loc["2019Q3", "derived"]


def test_q1_not_derived_when_filed(patched):
    q1 = _quarters(patched, BASE_2023).loc["2023Q1"]
    assert q1["revenue_usd"] == 100.0
    assert not q1["derived"]


def test_q1_not_derived_without_q2(patched):
    entries = [e for e in NO_Q1 if e["val"] != 110.0]
    df = _quarters(patched, entries)
    assert list(df.index) == ["2023Q3"]  # no Q1, and so no Q4 either


def test_q1_not_derived_without_half_year_total(patched):
    entries = [e for e in NO_Q1 if e["val"] != 210.0]
    df = _quarters(patched, entries)
    assert list(df.index) == ["2023Q2", "2023Q3"]


def test_second_half_total_does_not_derive_a_q1(patched):
    # A July-December six-month fact is not a first-half total.
    entries = [e for e in NO_Q1 if e["val"] != 210.0]
    entries.append(_fact("2023-07-01", "2023-12-31", 230.0, "2024-02-15", form="10-K"))
    assert "2023Q1" not in _quarters(patched, entries).index


def test_derived_q1_is_known_only_once_both_inputs_are_filed(patched):
    entries = [e for e in NO_Q1 if e["val"] != 210.0]
    entries.append(_fact("2023-01-01", "2023-06-30", 210.0, "2023-09-15"))  # H1 filed later
    assert _quarters(patched, entries).loc["2023Q1", "first_filed"] == pd.Timestamp("2023-09-15")


def test_derived_q1_waits_for_a_late_q2_too(patched):
    entries = [e for e in NO_Q1 if e["val"] != 110.0]
    entries.append(_fact("2023-04-01", "2023-06-30", 110.0, "2023-10-20"))  # Q2 filed later
    assert _quarters(patched, entries).loc["2023Q1", "first_filed"] == pd.Timestamp("2023-10-20")


def test_derived_q1_uses_restated_inputs(patched):
    entries = NO_Q1 + [_fact("2023-01-01", "2023-06-30", 215.0, "2024-08-01")]  # H1 restated
    q1 = _quarters(patched, entries).loc["2023Q1"]
    assert q1["revenue_usd"] == pytest.approx(105.0)
    assert q1["first_filed"] == pd.Timestamp("2023-08-01")  # clock still the first filing


def test_q4_not_derived_when_q3_missing_even_with_derived_q1(patched):
    entries = [e for e in NO_Q1 if e["val"] != 120.0]
    assert list(_quarters(patched, entries).index) == ["2023Q1", "2023Q2"]


def test_derivations_are_per_year(patched):
    df = _quarters(patched, FACTS_2019 + BASE_2023)
    assert df.loc["2019Q1", "derived"] and not df.loc["2023Q1", "derived"]
    assert len(df) == 8


# --- Earnings release dates from results 8-Ks -------------------------------
# Acceptance times are UTC: 20:18Z is 4:18pm in New York in summer, 21:19Z is
# 4:19pm in winter, and 11:02Z-12:02Z is around 7am.


@pytest.mark.parametrize(
    ("form", "accepted", "report", "expected"),
    [
        # Evening 8-K, after the close: released that day (Q1 2023).
        ("8-K", "2023-05-04T20:20:00.000Z", "2023-05-04", "2023-05-04"),
        # Same, in winter time (Q4 2022).
        ("8-K", "2023-02-16T21:19:04.000Z", "2023-02-16", "2023-02-16"),
        # Morning 8-K after an evening release (Q4 2024, released 13 Feb 4:15pm ET).
        ("8-K", "2025-02-14T12:02:40.000Z", "2025-02-14", "2025-02-13"),
        # Morning 8-K after an evening release (Q3 2025, released 6 Nov).
        ("8-K", "2025-11-07T11:35:19.000Z", "2025-11-07", "2025-11-06"),
        # Morning 8-K for a same-morning release (Q1 2022): dated a day early.
        ("8-K", "2022-05-06T11:02:48.000Z", "2022-05-06", "2022-05-05"),
        # Report date a day before the filing agrees with the rule (Q3 2024).
        ("8-K", "2024-11-08T11:45:21.000Z", "2024-11-07", "2024-11-07"),
        # Monday morning: the previous business day is Friday.
        ("8-K", "2024-03-04T12:00:00.000Z", "2024-03-04", "2024-03-01"),
        # Exactly 4:00pm ET counts as after the close; 3:59pm does not.
        ("8-K", "2023-05-04T20:00:00.000Z", "2023-05-04", "2023-05-04"),
        ("8-K", "2023-05-04T19:59:59.000Z", "2023-05-04", "2023-05-03"),
        # Winter: 4:00pm ET is 21:00Z, so 20:30Z is still before the close.
        ("8-K", "2023-02-16T20:30:00.000Z", "2023-02-16", "2023-02-15"),
        # Late-evening UTC that is already the next day in UTC but not in New York.
        ("8-K", "2023-05-05T01:30:00.000Z", "2023-05-04", "2023-05-04"),
        # A report date earlier than the rule's date wins.
        ("8-K", "2023-05-04T20:20:00.000Z", "2023-05-02", "2023-05-02"),
        # A report date later than the rule's date is ignored.
        ("8-K", "2023-05-04T11:00:00.000Z", "2023-05-04", "2023-05-03"),
        # No report date on file.
        ("8-K", "2023-05-04T20:20:00.000Z", "", "2023-05-04"),
        # An amendment's report date is the original event, not the release.
        ("8-K/A", "2020-05-15T11:02:45.000Z", "2020-04-23", "2020-05-14"),
    ],
)
def test_release_date_from_acceptance_time(form, accepted, report, expected):
    assert edgar._release_date(form, accepted, report) == pd.Timestamp(expected)


def test_release_date_is_a_plain_midnight_timestamp():
    date = edgar._release_date("8-K", "2023-05-04T20:20:00.000Z", "2023-05-04")
    assert date.tzinfo is None and date == date.normalize()


def test_earnings_release_dates_keep_results_8ks_only():
    index = _submissions(
        [
            ("8-K", "2023-05-04T20:20:00.000Z", "2023-05-04", "2.02,9.01"),
            ("8-K", "2023-06-01T20:20:00.000Z", "2023-06-01", "5.02"),  # not results
            ("8-K", "2023-06-02T20:20:00.000Z", "2023-06-02", ""),  # no items
            ("8-K", "2023-06-05T20:20:00.000Z", "2023-06-05", "12.02,9.01"),  # not item 2.02
            ("10-Q", "2023-05-05T11:01:47.000Z", "2023-03-31", ""),
            ("4", "2023-05-08T20:20:00.000Z", "2023-05-05", "2.02"),  # wrong form
            ("8-K", "2024-11-08T11:45:21.000Z", "2024-11-07", "1.01, 2.02, 9.01"),  # spaces
            ("8-K/A", "2020-05-15T11:02:45.000Z", "2020-04-23", "2.02,9.01"),
        ]
    )
    assert edgar.earnings_release_dates(index) == [
        pd.Timestamp("2020-05-14"),
        pd.Timestamp("2023-05-04"),
        pd.Timestamp("2024-11-07"),
    ]


def test_earnings_release_dates_empty_index():
    assert edgar.earnings_release_dates(_submissions([])) == []


def test_earnings_release_dates_refuse_a_paginated_index():
    index = _submissions([])
    index["filings"]["files"] = [{"name": "CIK0000000001-submissions-001.json"}]
    with pytest.raises(ValueError, match="paginated"):
        edgar.earnings_release_dates(index)


def test_earnings_release_dates_refuse_ragged_columns():
    index = _submissions([("8-K", "2023-05-04T20:20:00.000Z", "2023-05-04", "2.02")])
    index["filings"]["recent"]["items"].append("2.02")
    with pytest.raises(ValueError):
        edgar.earnings_release_dates(index)


def test_earnings_release_dates_need_the_acceptance_column():
    index = _submissions([("8-K", "2023-05-04T20:20:00.000Z", "2023-05-04", "2.02")])
    del index["filings"]["recent"]["acceptanceDateTime"]
    with pytest.raises(KeyError):
        edgar.earnings_release_dates(index)


@pytest.mark.parametrize(
    ("release", "expected"),
    [
        ("2023-03-31", None),  # on the quarter's last day: not after it
        ("2023-04-01", "2023-04-01"),
        ("2023-07-09", "2023-07-09"),  # day 100: last day of the window
        ("2023-07-10", None),  # day 101: belongs to no release for this quarter
    ],
)
def test_earnings_date_window_edges(release, expected):
    got = edgar._earnings_date(pd.Timestamp("2023-03-31"), [pd.Timestamp(release)])
    assert pd.isna(got) if expected is None else got == pd.Timestamp(expected)


def test_earnings_date_takes_the_first_release_in_the_window():
    releases = [pd.Timestamp(d) for d in ("2023-02-16", "2023-04-20", "2023-05-04")]
    # A preliminary release on 20 April makes revenue public before the main one.
    assert edgar._earnings_date(pd.Timestamp("2023-03-31"), releases) == pd.Timestamp("2023-04-20")
    assert pd.isna(edgar._earnings_date(pd.Timestamp("2023-03-31"), []))


def test_each_quarter_gets_its_own_release(patched):
    index = _submissions(
        [
            ("8-K", "2023-05-04T20:20:00.000Z", "2023-05-04", "2.02,9.01"),
            ("8-K", "2023-08-03T20:17:35.000Z", "2023-08-03", "2.02,9.01"),
            ("8-K", "2024-02-15T21:27:27.000Z", "2024-02-15", "2.02,9.01"),
        ]
    )
    dates = _quarters(patched, BASE_2023, index)["earnings_date"]
    assert dates["2023Q1"] == pd.Timestamp("2023-05-04")
    assert dates["2023Q2"] == pd.Timestamp("2023-08-03")
    assert pd.isna(dates["2023Q3"])  # no release on file within the window
    assert dates["2023Q4"] == pd.Timestamp("2024-02-15")  # derived quarter gets one too


def test_no_releases_on_file_leaves_earnings_date_empty(patched):
    df = _quarters(patched, BASE_2023)
    assert df["earnings_date"].isna().all()
    assert list(df.columns) == [
        "period_start",
        "period_end",
        "revenue_usd",
        "first_filed",
        "earnings_date",
        "derived",
    ]


def test_releases_merged_across_both_ciks(patched):
    old = _submissions([("8-K", "2021-05-07T11:08:45.000Z", "2021-05-07", "2.02,9.01")])
    new = _submissions([("8-K", "2022-05-06T11:02:48.000Z", "2022-05-06", "2.02,9.01")])
    facts_old = _facts_doc([_fact("2021-01-01", "2021-03-31", 50.0, "2021-05-07")])
    facts_new = _facts_doc([_fact("2022-01-01", "2022-03-31", 70.0, "2022-05-06")])
    patched({1: facts_old, 2: facts_new}, {1: old, 2: new})
    dates = edgar.quarterly_revenue(ciks=[1, 2]).set_index("quarter")["earnings_date"]
    assert dates["2021Q1"] == pd.Timestamp("2021-05-06")
    assert dates["2022Q1"] == pd.Timestamp("2022-05-05")


# --- Fetching ---------------------------------------------------------------


def test_sec_urls_and_force_flag(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(url, subdir="", force=False):
        calls.append((url, subdir, force))
        path = tmp_path / "doc.json"
        path.write_text("{}")
        return path

    monkeypatch.setattr(edgar, "fetch", fake_fetch)
    assert edgar.load_companyfacts(1883685) == {}
    assert edgar.load_submissions(1772757, force=True) == {}
    assert calls == [
        ("https://data.sec.gov/api/xbrl/companyfacts/CIK0001883685.json", "edgar", False),
        ("https://data.sec.gov/submissions/CIK0001772757.json", "edgar", True),
    ]


def test_main_redownloads_and_writes_every_column(monkeypatch, tmp_path, capsys):
    forced = []
    monkeypatch.setattr(
        edgar,
        "load_companyfacts",
        lambda cik, force=False: forced.append(force) or _facts_doc(BASE_2023),
    )
    monkeypatch.setattr(
        edgar,
        "load_submissions",
        lambda cik, force=False: (
            forced.append(force)
            or _submissions([("8-K", "2023-05-04T20:20:00.000Z", "2023-05-04", "2.02,9.01")])
        ),
    )
    monkeypatch.setattr(edgar, "DATA_PROCESSED", tmp_path)
    edgar.main()  # both real CIKs are requested; each gets the same synthetic documents
    assert len(forced) == 2 * len(edgar.DKNG_CIKS) and all(forced)  # every file re-downloaded
    written = pd.read_csv(tmp_path / "ground_truth_dkng.csv")
    assert list(written["quarter"]) == ["2023Q1", "2023Q2", "2023Q3", "2023Q4"]
    assert written.loc[0, "earnings_date"] == "2023-05-04"
    assert written["earnings_date"].isna().sum() == 3
    assert "wrote 4 quarters" in capsys.readouterr().out
