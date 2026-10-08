import httpx
import pytest

from ggr import wayback


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_latest_snapshot_picks_newest(monkeypatch):
    cdx = (
        "20240101000000 https://x.test/f.xlsx?rev=old\n"
        "20251214231730 https://x.test/f.xlsx?rev=new\n"
        "20250903115812 https://x.test/f.xlsx?rev=mid\n"
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(cdx))
    ts, original = wayback.latest_snapshot("https://x.test/f.xlsx")
    assert ts == "20251214231730"
    assert original == "https://x.test/f.xlsx?rev=new"


def test_latest_snapshot_raises_when_never_archived(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp("\n"))
    with pytest.raises(LookupError):
        wayback.latest_snapshot("https://x.test/missing.xlsx")


def test_raw_url_uses_id_variant():
    url = wayback.raw_url("20251214231730", "https://x.test/f.xlsx?rev=new")
    assert url == "https://web.archive.org/web/20251214231730id_/https://x.test/f.xlsx?rev=new"
