"""Immutable raw-artifact cache.

Every remote artifact is fetched at most once and stored under ``data/raw/<subdir>/``,
keyed by a hash of its URL, so re-runs never re-hit source sites and parsers always
work from bytes identical to what was published. A ``manifest.jsonl`` records every
fetch (URL, path, content hash, timestamp).

Refetches with ``force=True`` never destroy history: if the new bytes differ, the
old file is renamed to ``<name>.v<mtime>`` first, so every publication vintage
survives (regulators revise recent months) and the un-suffixed path is always the
latest. Identical bytes are a silent no-op.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ggr.config import DATA_RAW, REQUEST_INTERVAL, USER_AGENT

# Some state sites (njoag.gov listing pages; michigan.gov, see ggr.wayback)
# blanket-403 any non-browser User-Agent. Where a *listing page* is the only
# thing blocked, we fetch it with a browser profile and keep the identifying
# UA for the actual data files; the manifest records which UA was used.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

MANIFEST = DATA_RAW / "manifest.jsonl"

_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    wait = _last_request_at + REQUEST_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=30))
def _get(url: str, browser_ua: bool = False) -> httpx.Response:
    _throttle()
    ua = BROWSER_USER_AGENT if browser_ua else USER_AGENT
    with httpx.Client(headers={"User-Agent": ua}, follow_redirects=True, timeout=60) as client:
        response = client.get(url)
        response.raise_for_status()
        return response


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=30))
def _post(url: str, data: dict) -> httpx.Response:
    _throttle()
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=120
    ) as client:
        response = client.post(url, data=data)
        response.raise_for_status()
        return response


def resolve(url: str) -> str:
    """Follow redirects and return the final URL without downloading the body.

    Landing URLs like gaming.ny.gov/...-weekly-report-excel redirect to a dated
    file path that changes on every re-upload; caching by the final URL keeps
    each published artifact as its own immutable cache entry.
    """
    _throttle()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60) as client:
        response = client.head(url, follow_redirects=True)
        response.raise_for_status()
        return str(response.url)


def _local_name(url: str) -> str:
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    basename = unquote(Path(urlparse(url).path).name) or "index.html"
    return f"{key}_{basename}"


def cached_path(url: str, subdir: str = "") -> Path:
    return DATA_RAW / subdir / _local_name(url)


def _store(path: Path, content: bytes, meta: dict) -> Path:
    """Write an artifact, preserving any differing prior version as a vintage."""
    if path.exists():
        if path.read_bytes() == content:
            return path
        stamp = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%dT%H%M%S")
        vintage = path.with_name(f"{path.name}.v{stamp}")
        path.rename(vintage)
        meta = meta | {"superseded": str(vintage.relative_to(DATA_RAW))}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as f:
        row = meta | {
            "path": str(path.relative_to(DATA_RAW)),
            "sha256": hashlib.sha256(content).hexdigest(),
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
        f.write(json.dumps(row) + "\n")
    return path


def fetch(url: str, subdir: str = "", force: bool = False, browser_ua: bool = False) -> Path:
    """Return the local path for ``url``, downloading it only if not already cached."""
    path = cached_path(url, subdir)
    if path.exists() and not force:
        return path
    response = _get(url, browser_ua=browser_ua)
    meta = {"url": url, "content_type": response.headers.get("content-type")}
    if browser_ua:
        meta["ua"] = "browser"
    return _store(path, response.content, meta)


def fetch_post(url: str, data: dict, name: str, subdir: str = "", force: bool = False) -> Path:
    """Like fetch(), for POST endpoints (e.g. ASP.NET form apps).

    The cache key is the caller-supplied ``name`` (URL hashing can't key a POST
    body); the manifest row records the form data — minus framework token
    fields (__VIEWSTATE etc.) — for provenance.
    """
    path = DATA_RAW / subdir / name
    if path.exists() and not force:
        return path
    response = _post(url, data)
    return _store(
        path,
        response.content,
        {
            "url": url,
            "post_data": {k: v for k, v in data.items() if not k.startswith("__")},
            "content_type": response.headers.get("content-type"),
        },
    )
