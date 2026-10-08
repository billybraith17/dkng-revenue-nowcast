# ggr — nowcasting DraftKings revenue from state regulator filings

Every US state with legal online sports betting publishes official handle and gross gaming
revenue (GGR), and the large states publish it per operator, monthly (New York: weekly).
This project scrapes those primary sources across ~12 regulators, aggregates DraftKings'
state-level figures bottom-up, and nowcasts quarterly net revenue **before earnings** —
the same tracker gaming-sector analysts maintain at buy-side funds, built entirely from
public data.

## Status

Phase 1 (in progress): repo scaffold, DKNG ground truth from SEC EDGAR, New York and
Michigan adapters end-to-end, state coverage audit.

## Layout

```
src/ggr/          the package: ingest/ (fetch + discover per source), parse/ (raw file →
                  tidy schema), features/, models/, eval/
data/raw/         immutable cache of every downloaded artifact (gitignored)
data/processed/   tidy parquet/csv tables (gitignored)
tests/            golden-file parser tests against frozen fixtures
docs/             coverage audit and write-up material
```

## Setup

```bash
uv sync          # creates .venv, installs ggr editable + dev deps
uv run pytest    # run tests
```

## Data etiquette

Public data only; throttled requests (1/sec) with an identifying User-Agent; every raw
response cached immutably so source sites are hit once per artifact.
