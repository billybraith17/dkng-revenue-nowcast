# ggr — nowcasting DraftKings revenue from state regulator filings

Every US state with legal online sports betting publishes official handle and gross gaming
revenue (GGR), and the large states publish it per operator, monthly (New York: weekly).
This project scrapes those primary sources across seven state regulators, aggregates DraftKings'
state-level figures bottom-up, and nowcasts quarterly net revenue **before earnings** —
the same tracker gaming-sector analysts maintain at buy-side funds, built entirely from
public data.

## Status

In progress. Built so far: DraftKings ground truth from SEC EDGAR, and regulator
adapters for seven states (New York, Michigan, Pennsylvania, Illinois, New Jersey,
Indiana, Iowa), each with golden-file tests against frozen source files. Next:
coverage analysis and the walk-forward revenue nowcast.

## Layout

```
src/ggr/            cache.py (throttled immutable fetch layer), operators.py
                    (entity resolution), schema.py (tidy schema), wayback.py,
                    ingest/ (discover + fetch per state), parse/ (raw file →
                    tidy schema)
data/raw/           immutable cache of every downloaded artifact (gitignored)
data/processed/     tidy parquet tables (gitignored)
tests/              golden-file + synthetic tests, frozen fixtures
```

## Setup

```bash
uv sync          # creates .venv, installs ggr editable + dev deps
uv run pytest    # run tests
```

## Data etiquette

Public data only; throttled requests (1/sec) with an identifying User-Agent; every raw
response cached immutably so source sites are hit once per artifact.
