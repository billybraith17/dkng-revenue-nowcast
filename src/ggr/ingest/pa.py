"""Pennsylvania — PGCB monthly sports wagering summaries, one XLSX per fiscal
year (July–June), discovered through the revenue page's fiscal-year filter
(a Drupal facet; file names are irregular enough — typos, "(1)" suffixes,
trailing spaces — that scraping beats pattern-guessing).

Online sports wagering only for now. The interactive gaming summaries are
certificate-holder level and a certificate can host multiple casino skins
(e.g. "PENN NATIONAL" blends Hollywood's and partners' iGaming), so they are
not operator-level for our purposes — revisit with a skin-attribution plan.

Run ``uv run python -m ggr.ingest.pa`` to write data/processed/pa_monthly.parquet.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup
import pandas as pd

from ggr import cache
from ggr.config import DATA_PROCESSED
from ggr.parse.pa import parse_workbook

BASE = "https://gamingcontrolboard.pa.gov"
REVENUE_PAGE = f"{BASE}/news-and-transparency/revenue"
FY_PARAM = "field_gaming_revenue_fiscal_year_target_id"

# Online sports wagering launched May 2019, i.e. fiscal year 2018/2019.
FIRST_FISCAL_YEAR = 2018


def fiscal_year_ids(html: str) -> dict[str, str]:
    """Fiscal-year label → Drupal taxonomy id, read from the page's own filter.

    PGCB mints a new taxonomy id every July; a hardcoded map would silently
    stop discovering the newest fiscal year (data would freeze at June with no
    error). Reading the dropdown keeps discovery evergreen — and if the form
    ever disappears, this raises instead of returning a stale subset.
    """
    soup = BeautifulSoup(html, "lxml")
    select = soup.find("select", attrs={"name": FY_PARAM})
    if select is None:
        raise ValueError(f"fiscal-year filter <select name={FY_PARAM}> not found on revenue page")
    ids = {}
    for option in select.find_all("option"):
        m = re.fullmatch(r"FY (\d{4})/(\d{4})", option.get_text(strip=True))
        if m and int(m.group(1)) >= FIRST_FISCAL_YEAR and option.get("value", "").isdigit():
            ids[f"FY{m.group(1)}-{m.group(2)[2:]}"] = option["value"]
    if len(ids) < 8:  # every year since FY2018-19 must be present
        raise ValueError(f"expected ≥8 fiscal years in filter, got {sorted(ids)}")
    return dict(sorted(ids.items()))


def discover() -> dict[str, str]:
    """Fiscal year → absolute URL of that year's sports wagering XLSX."""
    landing = cache.fetch(REVENUE_PAGE, subdir="pa", force=True)
    urls = {}
    for fy, target_id in fiscal_year_ids(landing.read_text(errors="ignore")).items():
        page = cache.fetch(f"{REVENUE_PAGE}?{FY_PARAM}={target_id}", subdir="pa", force=True)
        soup = BeautifulSoup(page.read_text(errors="ignore"), "lxml")
        candidates = [
            a["href"]
            for a in soup.find_all("a", href=True)
            if a["href"].lower().endswith(".xlsx")
            and "sport" in unquote(a["href"]).lower().replace("_", " ")
        ]
        if len(candidates) != 1:
            raise ValueError(f"{fy}: expected exactly one sports XLSX, got {candidates}")
        urls[fy] = urljoin(BASE, candidates[0])
    return urls


def build() -> pd.DataFrame:
    frames = []
    for fy, url in discover().items():
        frames.append(parse_workbook(cache.fetch(url, subdir="pa"), url))
    combined = pd.concat(frames, ignore_index=True)
    # Fiscal years are disjoint; any collision means PGCB republished a month.
    dupes = combined.duplicated(["period_end", "operator_raw"], keep=False)
    if dupes.any():
        raise ValueError(f"overlapping months across FY files:\n{combined[dupes]}")
    return combined.sort_values(["period_end", "operator_canonical"]).reset_index(drop=True)


def main() -> None:
    df = build()
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / "pa_monthly.parquet"
    df.to_parquet(out, index=False)
    summary = (
        df.groupby("operator_canonical")
        .agg(
            months=("period_end", "count"),
            gross=("gross_revenue", "sum"),
            promo=("promo_credits", "sum"),
        )
        .sort_values("gross", ascending=False)
        .head(12)
    )
    print(summary.assign(**{c: lambda d, c=c: (d[c] / 1e6).round(1) for c in ("gross", "promo")}).to_string())
    print(f"\nrange: {df.period_end.min():%Y-%m} → {df.period_end.max():%Y-%m}")
    print(f"wrote {len(df)} operator-months to {out}")


if __name__ == "__main__":
    main()
