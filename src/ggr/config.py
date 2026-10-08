from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"

# SEC (and good scraping etiquette generally) requires an identifying User-Agent
# with a contact address.
USER_AGENT = "ggr-research/0.1 (billybraith17@googlemail.com)"

# Minimum seconds between outbound requests, applied globally in ggr.cache.
REQUEST_INTERVAL = 1.0
