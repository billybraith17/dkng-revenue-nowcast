# ggr — nowcasting DraftKings revenue from state regulator filings

Every US state with legal online sports betting publishes official handle and
gross gaming revenue (GGR), and the large states publish it per operator,
monthly (New York: weekly). This project scrapes those primary sources across
seven state regulators, aggregates DraftKings' state-level figures bottom-up,
and nowcasts quarterly net revenue **before earnings**, using public data only.

**Status:** work in progress. The pipeline and walk-forward backtest are
complete; data-quality fixes are under way.

## Results

Walk-forward backtest over 17 quarters (2022Q1–2026Q1). Each prediction uses
only data that was public before DraftKings filed that quarter's results.

| Model | MAPE |
|---|---|
| **`log R = a + b·log C + c·t`** | **10.2%** |
| Same regression in levels | 12.4% |
| Covered revenue × fixed scalar | 13.0% |
| Seasonal-naive (no state data) | 16.3% |

Bias is +0.8%; 80% prediction intervals contained the actual in 10 of 13
quarters. State-reported gross revenue covers roughly 50–60% of DraftKings'
reported net revenue; the regression learns the mapping between the two.

**Known limitations:** errors are seasonal (Q3 over-predicted and Q4
under-predicted in every year so far, as the model has no seasonal term);
New Jersey reports by licence, and DraftKings' licence has also carried ESPN
Bet since August 2024; publication lags are estimates, only partly verified
against archived dates; 17 quarters is a small sample.

## How it works

1. **Ingest** — per-regulator adapters (`ggr/ingest/`) fetch reports through
   a throttled, immutable raw cache (`ggr/cache.py`); Michigan is read from
   Wayback Machine snapshots because its site blocks non-browser clients.
2. **Parse** — parsers (`ggr/parse/`) turn Excel, CSV and PDF reports into
   one tidy schema, and fail loudly on anything unexpected.
3. **Entity resolution** — regulators list legal entities, not brands
   ("Crown IA Gaming" is DraftKings in Iowa); `ggr/operators.py` maps them,
   including licences whose operator changed over time.
4. **Availability clock and nowcast** — each state-month counts as public a
   fixed number of days after it ends (`ggr/panel.py`); the regression is
   refitted each quarter on earlier quarters only (`ggr/nowcast.py`).

## Quickstart

```bash
uv sync                             # create env, install package + dev deps
uv run pytest                       # 202 tests against frozen fixtures, no network
uv run python -m ggr.ingest.edgar   # DraftKings ground truth from SEC EDGAR
uv run python -m ggr.ingest.ny      # ... and likewise mi, pa, il, nj, indiana, ia
uv run python -m ggr.coverage       # coverage of reported revenue, by quarter
uv run python -m ggr.nowcast        # walk-forward backtest
```

## Data etiquette

Public records only, fetched at one request per second with a User-Agent that
identifies the project, and cached so no file is fetched twice. New Jersey's
listing page rejects non-browser clients and is fetched with a browser
User-Agent; its reports use the identifying one.
