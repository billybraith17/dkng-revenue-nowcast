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
    # New Jersey (DGE prints licensees; online skins BLEND under a licence —
    # the plan's known NJ caveat. Brand slugs only where one skin dominates
    # and the pairing is stable: Resorts Digital ≈ DraftKings, Meadowlands ≈
    # FanDuel (+ small partners), Borgata = MGM's own. Entity slugs otherwise.)
    "resorts digital gaming, llc": "draftkings",
    "new meadowlands racetrack": "fanduel",  # printed with and without ", LLC"
    "borgata hotel casino & spa": "betmgm",
    # Bally's AC licence lineage (Park Place era included; ownership moved
    # Caesars→Bally's Corp Nov 2020). From 2024 its online line is mostly the
    # Fanatics NJ skin — the licensee-blend caveat, documented in parse/nj.py.
    "bally's ac": "bally",  # covers "PREMIER ENT[ERTAINMENT] AC, LLC DBA BALLY'S AC" variants
    "bally's atlantic city": "bally",
    "bally's park place": "bally",  # printed with and without "LLC"
    "hard rock": "hard_rock",  # matches "HARD ROCK HOTEL AND CASINO ATLANTIC CITY"
    # Ocean's name is printed four different ways across 2018 alone
    "ocean casino resort": "ocean",
    "ocean resort casino": "ocean",
    "ocean resorts casino": "ocean",
    "ocean resorts": "ocean",
    # Resorts' own return ("DGMB" in every spelling variant, including the
    # "RESORTS CASNIO HOTEL" typo era) lives in ERA_OVERRIDES: its online
    # line is zero until Sep 2024, then carries DraftKings' revenue.
    "tropicana": "caesars",  # Caesars-owned; hosts Caesars' NJ online book
    "boardwalk regency": "caesars",  # Caesars AC's legal entity name
    "fr park racing, lp (freehold raceway)": "freehold",
    "monmouth park": "monmouth",  # covers all Darby Development spellings incl. typos
    # Indiana (IGC prints per-skin domains: "AS - Sportsbook.DraftKings.com").
    # Word-boundary matching on the domain token does the work; these aliases
    # cover tokens not already in the table.
    "betamerica": "twinspires",  # Churchill Downs brand, renamed TwinSpires (sequential)
    "caesarsonline": "caesars",
    "unibet": "unibet",  # Kindred; exited US 2023
    "thescore": "penn",  # theScore Bet, Penn's brand (also the 2025 relaunch)
    "williamhill": "william_hill",  # ran simultaneously with Caesars skins in IN — kept separate
    "betway": "betway",
    "barstool": "penn",
    "barstoolsportbook": "penn",  # official filing typo, missing the 's'
    "espnbet": "penn",
    "smarkets": "smarkets",
    "getsbk": "smarkets",  # SBK = Smarkets' consumer app
    "maximbet": "maximbet",
    "hardrocksportsbook": "hard_rock",
    # Iowa casino licensees (pre-2023 era reports blend skins per casino,
    # like NJ — entity slugs). Distinctive-token aliases because wrapped
    # column headers reconstruct with drifted words and footnote digits.
    "ameristar": "ameristar",
    "catfish bend": "catfish_bend",
    "marquette": "casino_queen_marquette",  # incl. the Bally's Marquette rename
    "dubuque": "diamond_jo_dubuque",
    "worth": "diamond_jo_worth",
    "grand falls": "grand_falls",
    "horseshoe": "caesars",  # Horseshoe Council Bluffs, Caesars-owned
    "waterloo": "isle_waterloo",
    "bettendorf": "isle_bettendorf",
    "lakeside": "lakeside",
    "prairie meadows": "prairie_meadows",
    "q casino": "q_casino",
    "dubuque racing": "q_casino",  # DRA operates Q Casino; outranks "dubuque" (longer)
    "rhythm city": "rhythm_city",
    "riverside casino": "riverside_ia",
    "rose": "wild_rose",  # Wild Rose Clinton/Emmetsburg/Jefferson, one company
    # Iowa "BY OPERATOR" entities (2023+ reports — true operator-level)
    "betfair": "fanduel",  # Betfair Interactive US = FanDuel's legal entity
    "crown": "draftkings",  # Crown IA Gaming — DKNG subsidiary naming again
    "american wagering": "caesars",  # Caesars' William Hill US entity
    "digital gaming corporation": "betway",  # DGC USA operates Betway in the US
    "hillside": "bet365",  # Hillside = bet365's corporate name
    "fbg": "fanatics",  # Fanatics Betting & Gaming
    "penn sports": "penn",
    "twin river": "bally",  # Bally's Corp's former name
    "circa": "circa",
    "bluebet": "bluebet",
    "tipico": "tipico",
    "sporttrade": "sporttrade",
    "sbopco": "superbook",  # SuperBook Sports opco
    "sce partners": "sce_partners",
    "elite": "elite",  # Elite Sportsbook (Q Casino / Elite Hospitality group)
    "sports information": "drf",  # Sports Information Group = DRF Bets
    "score digital": "penn",  # Score Digital Sports Ventures = theScore, Penn's brand
    "fubo": "fubo",  # fubo Gaming, exited 2022
    # Exact garble repairs: "Sports Information Group, LLC" wraps and its
    # first words drift into the SCE column; only these exact full strings.
    "sce partners, llc sports information": "sce_partners",
    "group, llc": "drf",
}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


# Licensees whose online skin changed *company* over time. Static aliases
# can't express these; parsers with a period in hand use canonicalize_dated().
# Boundaries are verified against the volume series itself (e.g. Par-A-Dice
# online: FanDuel-scale until Feb 2021, ~zero, then BetMGM's Mar 2022 launch;
# NJ's DGMB return carries $0 online until DraftKings' revenue moves onto it
# from Resorts Digital's discontinued return in Sep 2024). Dates are
# inclusive; None = open-ended. Matching is whole-word containment, so one
# entry covers all of a licensee's spelling variants (DGMB appears four ways).
ERA_OVERRIDES: list[tuple[str, str, str | None, str | None, str]] = [
    ("IL", "par-a-dice gaming corporation", None, "2022-02-28", "fanduel"),
    ("IL", "par-a-dice gaming corporation", "2022-03-01", None, "betmgm"),
    ("NJ", "dgmb", None, "2024-08-31", "resorts_ac"),
    ("NJ", "dgmb", "2024-09-01", None, "draftkings"),
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


_ERA_PATTERNS = [
    (state, re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)"), start, end, slug)
    for state, alias, start, end, slug in ERA_OVERRIDES
]


def canonicalize_dated(operator_raw: str, state: str, period_end: dt.date) -> str | None:
    """canonicalize(), but era-aware for licensees whose skin changed company."""
    name = _norm(operator_raw)
    for st, pattern, start, end, slug in _ERA_PATTERNS:
        if st != state or not pattern.search(name):
            continue
        after = start is None or period_end >= dt.date.fromisoformat(start)
        before = end is None or period_end <= dt.date.fromisoformat(end)
        if after and before:
            return slug
    return canonicalize(operator_raw)
