"""Wayback Machine access for sources whose sites block non-browser clients.

michigan.gov's firewall rejects any non-browser User-Agent, so Michigan is read
from Internet Archive snapshots. Closed years are complete, and each yearly MGCB
file repeats the prior year as a comparison sheet, so revisions carry forward.
Snapshot URLs never change, which fits the immutable raw cache.

Known gap: the current year is only as fresh as the Archive's latest crawl.
"""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ggr.config import USER_AGENT

CDX = "http://web.archive.org/cdx/search/cdx"


# Retry network flakiness only — a LookupError ("never archived") is a final
# answer and must propagate immediately, not burn retries and surface as
# tenacity's RetryError.
@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, max=30),
    reraise=True,
)
def latest_snapshot(url: str) -> tuple[str, str]:
    """Return (timestamp, archived_url) of the newest 200 snapshot of ``url``.

    Uses prefix matching because sites append cache-busting query strings
    (``?rev=...&hash=...``) that Wayback keys on.
    """
    params = {
        "url": url,
        "matchType": "prefix",
        "fl": "timestamp,original",
        "filter": "statuscode:200",
    }
    r = httpx.get(CDX, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    if not lines:
        raise LookupError(f"no Wayback snapshot for {url}")
    timestamp, original = max(lines).split(" ", 1)
    return timestamp, original


def raw_url(timestamp: str, original: str) -> str:
    """URL returning the original archived bytes (the ``id_`` variant)."""
    return f"https://web.archive.org/web/{timestamp}id_/{original}"
