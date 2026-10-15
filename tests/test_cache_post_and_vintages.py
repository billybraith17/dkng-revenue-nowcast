"""fetch_post and forced-refetch vintage semantics — network faked."""

import json
from types import SimpleNamespace

import pytest

from ggr import cache


@pytest.fixture()
def fake_net(tmp_path, monkeypatch):
    state = {"content": b"v1", "get_calls": 0, "post_calls": 0}

    def _fake_get(url, browser_ua=False):
        state["get_calls"] += 1
        return SimpleNamespace(content=state["content"], headers={"content-type": "text/csv"})

    def _fake_post(url, data):
        state["post_calls"] += 1
        return SimpleNamespace(content=state["content"], headers={"content-type": "text/csv"})

    monkeypatch.setattr(cache, "DATA_RAW", tmp_path)
    monkeypatch.setattr(cache, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(cache, "_get", _fake_get)
    monkeypatch.setattr(cache, "_post", _fake_post)
    return state


def _manifest_rows(tmp_path):
    return [json.loads(ln) for ln in (tmp_path / "manifest.jsonl").read_text().splitlines()]


def test_fetch_post_caches_by_name(fake_net, tmp_path):
    p1 = cache.fetch_post("https://x.test/app", {"month": "Jan"}, name="jan.csv", subdir="il")
    p2 = cache.fetch_post("https://x.test/app", {"month": "Jan"}, name="jan.csv", subdir="il")
    assert p1 == p2 == tmp_path / "il" / "jan.csv"
    assert fake_net["post_calls"] == 1


def test_fetch_post_manifest_strips_framework_tokens(fake_net, tmp_path):
    cache.fetch_post(
        "https://x.test/app",
        {"__VIEWSTATE": "secret-blob", "SearchStartMonth": "January"},
        name="jan.csv",
    )
    (row,) = _manifest_rows(tmp_path)
    assert row["post_data"] == {"SearchStartMonth": "January"}


def test_force_with_identical_bytes_is_noop(fake_net, tmp_path):
    cache.fetch_post("https://x.test/app", {}, name="jan.csv")
    cache.fetch_post("https://x.test/app", {}, name="jan.csv", force=True)
    assert fake_net["post_calls"] == 2  # refetched...
    assert len(_manifest_rows(tmp_path)) == 1  # ...but no new manifest row
    assert list(tmp_path.glob("jan.csv*")) == [tmp_path / "jan.csv"]


def test_force_with_changed_bytes_preserves_vintage(fake_net, tmp_path):
    cache.fetch_post("https://x.test/app", {}, name="jan.csv")
    fake_net["content"] = b"v2-revised"
    latest = cache.fetch_post("https://x.test/app", {}, name="jan.csv", force=True)

    assert latest.read_bytes() == b"v2-revised"
    vintages = sorted(tmp_path.glob("jan.csv.v*"))
    assert len(vintages) == 1
    assert vintages[0].read_bytes() == b"v1"

    rows = _manifest_rows(tmp_path)
    assert len(rows) == 2
    assert rows[1]["superseded"].startswith("jan.csv.v")


def test_fetch_force_vintage_applies_to_get_too(fake_net, tmp_path):
    cache.fetch("https://x.test/facts.json")
    fake_net["content"] = b"v2"
    cache.fetch("https://x.test/facts.json", force=True)
    assert len(list(tmp_path.glob("*facts.json.v*"))) == 1


def test_browser_ua_recorded_in_manifest(tmp_path, monkeypatch):
    seen = {}

    def _fake_get(url, browser_ua=False):
        seen["browser_ua"] = browser_ua
        return SimpleNamespace(content=b"page", headers={"content-type": "text/html"})

    monkeypatch.setattr(cache, "DATA_RAW", tmp_path)
    monkeypatch.setattr(cache, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(cache, "_get", _fake_get)

    cache.fetch("https://waf.test/listing", browser_ua=True)
    assert seen["browser_ua"] is True
    (row,) = _manifest_rows(tmp_path)
    assert row["ua"] == "browser"

    cache.fetch("https://waf.test/other")
    assert seen["browser_ua"] is False
    assert "ua" not in _manifest_rows(tmp_path)[1]
