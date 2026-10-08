"""Immutable raw-artifact cache.

Every remote artifact is fetched at most once and stored under ``data/raw/<subdir>/``,
keyed by a hash of its URL, so re-runs never re-hit source sites and parsers always
work from bytes identical to what was published. A ``manifest.jsonl`` records every
fetch (URL, path, content hash, timestamp) — refetches with ``force=True`` append a
new manifest row rather than erasing history, which is how regulator data revisions
stay auditable.
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

MANIFEST = DATA_RAW / "manifest.jsonl"

_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    wait = _last_request_at + REQUEST_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=30))
def _get(url: str) -> httpx.Response:
    _throttle()
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60
    ) as client:
        response = client.get(url)
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


def fetch(url: str, subdir: str = "", force: bool = False) -> Path:
    """Return the local path for ``url``, downloading it only if not already cached."""
    path = cached_path(url, subdir)
    if path.exists() and not force:
        return path

    response = _get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as f:
        f.write(
            json.dumps(
                {
                    "url": url,
                    "path": str(path.relative_to(DATA_RAW)),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "content_type": response.headers.get("content-type"),
                    "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                }
            )
            + "\n"
        )
    return path
