"""Wayback Machine access for sources whose sites block non-browser clients.

michigan.gov sits behind an Akamai WAF that 403s any non-browser User-Agent —
including for public records and robots.txt. Rather than impersonate a browser,
we read the Internet Archive's crawls: complete for finished years, and each
yearly MGCB file embeds the prior year as a comparison sheet, so revisions
propagate. Snapshot URLs are immutable, which suits the raw cache perfectly.

Known gap: the current year's file is only as fresh as the Archive's last crawl.
Fixing that (authenticated Save Page Now, or fetching from an unblocked runner)
is a Phase 2+ item tracked in docs/coverage-audit.md.
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
