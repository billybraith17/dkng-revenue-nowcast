"""Iowa — IRGC sports wagering revenue PDFs (online since August 2019).

Two listing pages: the current fiscal year's monthly files, and an archive
with one concatenated file per closed fiscal year (Iowa FY = July–June).
Links are opaque Drupal media ids, so discovery matches on link *text*
("June 2026 Sports Wagering Revenue" / "Fiscal Year 2024 …"). Months present
in both a monthly file and a later FY archive resolve to the archive
(revisions propagate). Amendments files are skipped and tracked.

Run ``uv run python -m ggr.ingest.ia`` to write data/processed/ia_monthly.parquet.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

from ggr import cache
from ggr.config import DATA_PROCESSED
from ggr.parse.ia import parse_pdf
from ggr.schema import TIDY_COLUMNS

BASE = "https://irgc.iowa.gov"
CURRENT = f"{BASE}/publications-reports/sports-wagering-revenue"
ARCHIVE = f"{CURRENT}/archived-sports-revenue"

MONTHLY_TEXT = re.compile(r"^([A-Z][a-z]+) (\d{4}) Sports Wagering Revenue$")
FY_TEXT = re.compile(r"^Fiscal Year (\d{4}) Sports Wagering Revenue$")


def discover() -> list[tuple[str, str]]:
    """[(label, url)] for all monthly and fiscal-year revenue PDFs."""
    found = []
    for listing in (ARCHIVE, CURRENT):
        page = cache.fetch(listing, subdir="ia", force=True)
        soup = BeautifulSoup(page.read_text(errors="ignore"), "lxml")
        for a in soup.find_all("a", href=True):
            if "/media/" not in a["href"]:
                continue
            text = a.get_text(" ", strip=True)
            if MONTHLY_TEXT.match(text) or FY_TEXT.match(text):
                found.append((text, urljoin(BASE, a["href"])))
    fy_count = sum(bool(FY_TEXT.match(t)) for t, _ in found)
    if fy_count < 6:
        raise ValueError(f"IA discovery looks broken: only {fy_count} fiscal-year files")
    return found


def _prefer_and_aggregate(combined: pd.DataFrame) -> pd.DataFrame:
    """Resolve source overlap, then sum same-slug entities within a source.

    Two distinct concerns, in order:
    1. A month can appear in both a monthly file and a later FY archive
       (which carries revisions) — keep the earliest-listed source only
       (``_prio``; the archive page is listed first in discover()).
    2. Within one source, several licensees legitimately share a canonical
       slug (Wild Rose's three casinos are one company) — those rows are
       *summed*, never deduped: dropping them would silently lose revenue.
    """
    best = combined.groupby(["period_end", "operator_canonical"])["_prio"].transform("min")
    kept = combined[combined["_prio"] == best]
    aggregated = kept.groupby(
        ["state", "period_start", "period_end", "operator_canonical", "product"],
        as_index=False,
    ).agg(
        operator_raw=("operator_raw", lambda s: " + ".join(sorted(set(s)))),
        handle=("handle", lambda s: s.sum(min_count=1)),
        gross_revenue=("gross_revenue", lambda s: s.sum(min_count=1)),
        source_url=("source_url", "first"),
        fetched_at=("fetched_at", "first"),
    )
    for col in TIDY_COLUMNS:
        if col not in aggregated.columns:
            aggregated[col] = None
    return aggregated[TIDY_COLUMNS]


def build() -> pd.DataFrame:
    frames = []
    for prio, (label, url) in enumerate(discover()):
        try:
            frames.append(
                parse_pdf(cache.fetch(url, subdir="ia"), url).assign(_src=label, _prio=prio)
            )
        except ValueError as e:
            # The *current* fiscal year's "Fiscal Year N" file contains only
            # FYTD summary pages — its months come from the monthly files.
            if "no monthly report sections" in str(e) and FY_TEXT.match(label):
                print(f"note: {label} is FYTD-only, skipping")
                continue
            raise
    df = _prefer_and_aggregate(pd.concat(frames, ignore_index=True))
    return df.sort_values(["period_end", "operator_canonical"]).reset_index(drop=True)


def main() -> None:
    df = build()
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "ia_monthly.parquet"
    df.to_parquet(out, index=False)
    summary = (
        df.groupby("operator_canonical")
        .agg(months=("period_end", "count"), internet_gross=("gross_revenue", "sum"))
        .sort_values("internet_gross", ascending=False)
        .head(12)
    )
    print(summary.assign(internet_gross=lambda d: (d["internet_gross"] / 1e6).round(1)).to_string())
    print(f"\nrange: {df.period_end.min():%Y-%m} → {df.period_end.max():%Y-%m}")
    print(f"wrote {len(df)} casino-months to {out}")


if __name__ == "__main__":
    main()
