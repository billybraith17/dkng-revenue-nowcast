"""Cache behavior tests — network is faked, filesystem is tmp_path."""

import json
from types import SimpleNamespace

import pytest

from ggr import cache


@pytest.fixture()
def fake_net(tmp_path, monkeypatch):
    """Redirect the cache to tmp_path and count fake downloads."""
    calls = []

    def _fake_get(url):
        calls.append(url)
        return SimpleNamespace(content=b"payload-1", headers={"content-type": "text/plain"})

    monkeypatch.setattr(cache, "DATA_RAW", tmp_path)
    monkeypatch.setattr(cache, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(cache, "_get", _fake_get)
    return calls


def test_fetch_downloads_once_then_hits_cache(fake_net):
    p1 = cache.fetch("https://example.test/report.xlsx", subdir="xx")
    p2 = cache.fetch("https://example.test/report.xlsx", subdir="xx")
    assert p1 == p2
    assert p1.read_bytes() == b"payload-1"
    assert len(fake_net) == 1


def test_force_refetches(fake_net):
    cache.fetch("https://example.test/report.xlsx")
    cache.fetch("https://example.test/report.xlsx", force=True)
    assert len(fake_net) == 2


def test_manifest_appends_one_row_per_download(fake_net, tmp_path):
    cache.fetch("https://example.test/a.xlsx")
    cache.fetch("https://example.test/a.xlsx")  # cache hit — no new row
    cache.fetch("https://example.test/b.xlsx")
    rows = [json.loads(ln) for ln in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert {r["url"] for r in rows} == {"https://example.test/a.xlsx", "https://example.test/b.xlsx"}
    assert all(r["sha256"] and r["fetched_at"] for r in rows)


def test_distinct_urls_get_distinct_files(fake_net):
    p1 = cache.fetch("https://example.test/2024/report.xlsx")
    p2 = cache.fetch("https://example.test/2025/report.xlsx")
    assert p1 != p2  # same basename, different URL hash prefix


def test_local_name_keeps_basename_and_is_stable():
    n1 = cache._local_name("https://example.test/dir/My%20Report.xlsx?rev=abc")
    n2 = cache._local_name("https://example.test/dir/My%20Report.xlsx?rev=abc")
    assert n1 == n2
    assert n1.endswith("_My Report.xlsx")


def test_local_name_handles_bare_domain():
    assert cache._local_name("https://example.test/").endswith("_index.html")
