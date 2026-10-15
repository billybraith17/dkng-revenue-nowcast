"""New Jersey — DGE monthly sports wagering tax return PDFs, June 2018+.

Discovery scrapes the njoag.gov listing page (their WordPress WAF 403s
non-browser clients, so the listing alone uses a browser UA; the PDFs
themselves live on the old nj.gov docs tree, which accepts our identifying
UA). Filenames follow ``SWRTaxReturns/{year}/{Month}{year}.pdf``.

Amendment files ("Amendments2019.pdf" etc.) are amended historical returns —
skipped for now and logged, tracked in docs/coverage-audit.md.

Run ``uv run python -m ggr.ingest.nj`` to write data/processed/nj_monthly.parquet.
"""

from __future__ import annotations

import re

import pandas as pd
from bs4 import BeautifulSoup

from ggr import cache
from ggr.config import DATA_PROCESSED
from ggr.parse.nj import parse_pdf

LISTING = (
    "https://www.njoag.gov/about/divisions-and-offices/"
    "division-of-gaming-enforcement-home/financial-and-statistical-information/"
    "monthly-sports-wagering-revenue-reports/"
)
PDF_NAME = re.compile(
    r"/SWRTaxReturns/\d{4}/"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(\d{4})\.pdf$"
)
MONTH_NUM = {m: i + 1 for i, m in enumerate(
    "January February March April May June July August September October November December".split()
)}


FIRST_MONTH = (2018, 6)


def monthly_pdf_urls(html: str) -> dict[tuple[int, int], str]:
    """(year, month) → PDF URL from the listing HTML, validated for gaps.

    A renamed file (e.g. "June2025_revised.pdf") would silently fall out of
    the name pattern and lose a month, so every month from launch through the
    newest listed month must be present — a hole is an error, not a note.
    """
    soup = BeautifulSoup(html, "lxml")
    found, skipped = {}, []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "SWRTaxReturns" not in href:
            continue
        m = PDF_NAME.search(href)
        if m:
            found[(int(m.group(2)), MONTH_NUM[m.group(1)])] = href
        elif href.lower().endswith(".pdf"):
            skipped.append(href.rsplit("/", 1)[-1])
    if skipped:
        print(f"note: skipping non-monthly files: {sorted(set(skipped))}")
    if FIRST_MONTH not in found:
        raise ValueError(f"NJ discovery looks broken: {len(found)} monthly PDFs, no launch month")

    year, month = FIRST_MONTH
    expected = set()
    while (year, month) <= max(found):
        expected.add((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    missing = expected - set(found)
    if missing:
        raise ValueError(f"NJ listing has holes (renamed files?): {sorted(missing)}")
    return dict(sorted(found.items()))


def discover() -> dict[tuple[int, int], str]:
    """(year, month) → PDF URL, from the njoag listing page."""
    page = cache.fetch(LISTING, subdir="nj", force=True, browser_ua=True)
    return monthly_pdf_urls(page.read_text(errors="ignore"))


def build() -> pd.DataFrame:
    frames = []
    for (year, month), url in discover().items():
        path = cache.fetch(url, subdir="nj")
        frames.append(parse_pdf(path, year, month, url))
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    df = build()
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "nj_monthly.parquet"
    df.to_parquet(out, index=False)
    summary = (
        df.groupby("operator_canonical")
        .agg(months=("period_end", "count"), gross=("gross_revenue", "sum"))
        .sort_values("gross", ascending=False)
    )
    print(summary.assign(gross=lambda d: (d["gross"] / 1e6).round(1)).to_string())
    print(f"\nrange: {df.period_end.min():%Y-%m} → {df.period_end.max():%Y-%m}")
    print(f"wrote {len(df)} operator-months to {out}")


if __name__ == "__main__":
    main()
