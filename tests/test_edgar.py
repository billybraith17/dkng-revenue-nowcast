"""EDGAR ground-truth logic on synthetic company facts (no network)."""

import pandas as pd
import pytest

from ggr.ingest import edgar


def _fact(start, end, val, filed, form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


def _facts_doc(entries, concept="RevenueFromContractWithCustomerExcludingAssessedTax"):
    return {"facts": {"us-gaap": {concept: {"units": {"USD": entries}}}}}


@pytest.fixture()
def patched(monkeypatch):
    def _patch(doc_by_cik):
        monkeypatch.setattr(edgar, "load_companyfacts", lambda cik, force=False: doc_by_cik[cik])

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
