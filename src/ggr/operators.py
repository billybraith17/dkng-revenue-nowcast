"""Operator alias dictionary.

Regulators print operator names inconsistently — NJ files DraftKings under its
land-based partner ("Resorts Digital"), NY prints licensee legal entities, MI pairs
each platform with a tribal/commercial casino. ``ALIASES`` maps every raw string we
have seen to one canonical brand slug; parsers must not invent their own mappings.

Unknown names canonicalize to ``None`` rather than guessing — the tests assert that
every operator in a frozen fixture is known, so new entrants surface as test
failures instead of silently polluting the panel.
"""

from __future__ import annotations

import re

ALIASES: dict[str, str] = {
    # New York (licensee names as printed in weekly reports)
    "batavia downs gaming/hybrid (caesars sportsbook)": "caesars",
    "caesars sportsbook": "caesars",
    "draftkings": "draftkings",
    "draftkings sportsbook": "draftkings",
    "fanduel": "fanduel",
    "fanduel sportsbook": "fanduel",
    "betmgm": "betmgm",
    "ballybet": "bally",
    "bally bet": "bally",
    "esbet": "esbet",
    "pointsbet": "fanatics",  # acquired by Fanatics mid-2023; treated as one lineage
    "fanatics sportsbook": "fanatics",
    "fanatics": "fanatics",
    "wynn interactive": "wynnbet",
    "resorts world bet": "resorts_world",
    "rush street interactive ny": "rsi",
    "betrivers": "rsi",
    "wynnbet": "wynnbet",
    # Michigan (platform provider names in MGCB detail files)
    "bet365": "bet365",
    "betfred": "betfred",
    "eagle casino & sports": "eagle",
    "espn bet": "penn",
    "barstool sportsbook": "penn",  # rebranded to ESPN Bet Nov 2023; one lineage
    "firekeepers": "firekeepers",
    "four winds sportsbook": "four_winds",
    "golden nugget": "golden_nugget",  # DraftKings brand, kept separate
    "gun lake casino (playgunlake)": "gun_lake",
    "hollywood casino": "penn",
    "soaring eagle casino": "soaring_eagle",
    "caesars": "caesars",
    "wynn": "wynnbet",
    # Michigan early era (2021-2023 exits and rebrands)
    "foxbet": "foxbet",  # Flutter brand, shut down Aug 2023
    "gan": "gan",
    "nyx digital": "nyx",
    "pala interactive": "pala",
    "parx interactive": "parx",
    "rush street": "rsi",
    "twinspires": "twinspires",  # Churchill Downs, exited early 2022
    # Kept separate from caesars: both operated in MI simultaneously in 2021,
    # merging the slugs would collide rows before the Aug 2022 consolidation.
    "william hill": "william_hill",
}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


# Longest alias first so "fanatics sportsbook" wins over "fanatics" etc.
_FALLBACK_PATTERNS = [
    (re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)"), slug)
    for alias, slug in sorted(ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True)
]


def canonicalize(operator_raw: str) -> str | None:
    """Map a raw operator string to its canonical slug, or None if unknown.

    Exact match first, then whole-word containment ("DraftKings (Resorts
    Digital)" → draftkings). Word boundaries matter: plain substring matching
    would map e.g. "Mohegan Digital" to the unrelated platform "GAN".
    """
    name = _norm(operator_raw)
    if name in ALIASES:
        return ALIASES[name]
    for pattern, slug in _FALLBACK_PATTERNS:
        if pattern.search(name):
            return slug
    return None
