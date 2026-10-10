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

import datetime as dt
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
    # Pennsylvania (PGCB prints the land-based licensee, not the online skin).
    # Brand mappings only where the licensee↔skin pair is well documented:
    # DKNG 10-K (Meadows), FanDuel/Boyd (Valley Forge), RSI-owned casinos
    # (Rivers), Penn's own skin (Hollywood), BetMGM launch via Morgantown,
    # Caesars via its Harrah's property. Everything else keeps a licensee slug
    # rather than a guessed brand.
    "hollywood casino at the meadows": "draftkings",
    "meadows": "draftkings",  # pre-2023 name of the same licensee (DKNG's PA home since Nov 2019)
    "valley forge casino": "fanduel",
    "rivers - pittsburgh": "rsi",
    "rivers - philadelphia": "rsi",
    "hollywood casino morgantown": "betmgm",
    "harrah's": "caesars",
    "parx casino": "parx",
    "parx shippensburg": "parx",
    "parx at malvern": "parx",  # renamed Oaks satellite, FY21-22 era
    "hollywood casino york": "hollywood_york",  # TODO verify skin before brand-mapping
    "presque isle": "presque_isle",
    "mount airy": "mount_airy",  # FOX Bet era, then rotated — licensee slug on purpose
    # Parent-level slug: Mohegan Tribal Gaming runs skins in PA and CT; the
    # state column disambiguates, so one slug serves both.
    "mohegan": "mohegan",
    "mohegan - lehigh valley": "mohegan_lehigh_valley",
    "live! casino pittsburgh": "live_pittsburgh",
    "live! casino philadelphia": "live_philadelphia",
    "wind creek": "wind_creek",
    # Pennsylvania FY18-19 era names
    "rivers": "rsi",  # Rivers Pittsburgh, before the Pittsburgh/Philadelphia split naming
    "sugarhouse casino": "rsi",  # Rush Street's Philadelphia casino, renamed Rivers Phila. 2019
    "oaks race and sportsbook": "parx",  # Greenwood/Parx satellite (Valley Forge Turf Club)
    "south philadelphia race and sportsbook": "parx",  # Greenwood/Parx turf club
    # Illinois (IGB prints the master licensee entity; skin pairs per the IGB
    # "Authorized Operating Sportsbooks" page, stable since each launch except
    # where noted).
    "casino queen, inc.": "draftkings",  # DKNG owns Casino Queen; IL online home since Aug 2021
    "fairmount park, inc.": "fanduel",
    "midwest gaming & entertainment, llc": "rsi",  # Rivers Des Plaines / BetRivers
    "elgin riverboat resort": "caesars",  # Grand Victoria / Caesars Sportsbook
    # Par-A-Dice is deliberately absent here: its online skin changed company
    # (FanDuel 2020-21 → BetMGM 2022+), so it lives in ERA_OVERRIDES below and
    # only resolves through canonicalize_dated().
    "hawthorne race course, inc.": "fanatics",  # PointsBet → Fanatics conversion, ended Jan 2026
    # Online skin only ever Fanatics (from Jan 2026, moved over from
    # Hawthorne); all earlier online rows are zero-valued placeholders.
    "alton casino, llc": "fanatics",
    "hc aurora, llc": "penn",  # Penn-owned; hosts Penn brands (theScore Bet online 2025+)
    "hc joliet, llc": "penn",  # Penn-owned, retail only
    "fhr-illinois llc": "circa",  # Full House Resorts' American Place; Circa online
    "walker's bluff casino resort, llc": "bet365",
    "the rock island boatworks, llc": "bally",  # Bally's Quad Cities
    "southern illinois riverboat/casino cruises llc": "caesars",  # Harrah's Metropolis, retail
    "815 entertainment": "hard_rock",  # Hard Rock Rockford
    "casino queen marquette, inc.": "draftkings",  # DKNG-owned sister property
    "northside crown gaming llc": "draftkings",  # Crown Gaming = DKNG subsidiary (Wrigley license)
}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


# Licensees whose online skin changed *company* over time. Static aliases
# can't express these; parsers with a period in hand use canonicalize_dated().
# Boundaries are verified against the volume series itself (e.g. Par-A-Dice
# online: FanDuel-scale until Feb 2021, ~zero, then BetMGM's Mar 2022 launch).
# Dates are inclusive; None = open-ended.
ERA_OVERRIDES: list[tuple[str, str, str | None, str | None, str]] = [
    ("IL", "par-a-dice gaming corporation", None, "2022-02-28", "fanduel"),
    ("IL", "par-a-dice gaming corporation", "2022-03-01", None, "betmgm"),
]


# Aliases too generic to use for whole-word containment: "rivers" must match
# the PA licensee printed exactly as "RIVERS", but not every future "X Rivers
# Casino". These resolve via exact match only.
EXACT_ONLY = {"rivers"}

# Longest alias first so "fanatics sportsbook" wins over "fanatics" etc.
_FALLBACK_PATTERNS = [
    (re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)"), slug)
    for alias, slug in sorted(ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True)
    if alias not in EXACT_ONLY
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


def canonicalize_dated(operator_raw: str, state: str, period_end: dt.date) -> str | None:
    """canonicalize(), but era-aware for licensees whose skin changed company."""
    name = _norm(operator_raw)
    for st, alias, start, end, slug in ERA_OVERRIDES:
        if st != state or alias != name:
            continue
        after = start is None or period_end >= dt.date.fromisoformat(start)
        before = end is None or period_end <= dt.date.fromisoformat(end)
        if after and before:
            return slug
    return canonicalize(operator_raw)
