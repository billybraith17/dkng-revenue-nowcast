import datetime as dt

import pytest

from ggr.ingest.mi import FILES as MI_FILES  # noqa: F401  (import guards module health)
from ggr.ingest.ny import MOBILE_OPERATORS
from ggr.operators import ALIASES, canonicalize, canonicalize_dated


def test_all_ny_mobile_operators_are_known():
    for operator_raw in MOBILE_OPERATORS.values():
        assert canonicalize(operator_raw) is not None, operator_raw


def test_nj_licensee_quirk():
    assert canonicalize("DraftKings (Resorts Digital)") == "draftkings"


def test_unknown_returns_none():
    assert canonicalize("Totally New Sportsbook LLC") is None


def test_case_and_whitespace_insensitive():
    assert canonicalize("  DRAFTKINGS   Sportsbook ") == "draftkings"
    assert canonicalize("FanDuel ") == "fanduel" or canonicalize("FanDuel ") == "fanduel"


def test_word_boundaries_prevent_false_matches():
    # "gan" (the 2021 MI platform) must not swallow names that merely contain it
    assert canonicalize("GAN") == "gan"
    assert canonicalize("Michigan Wagering Co") is None
    # ...while "Mohegan Digital" correctly reaches the Mohegan parent slug,
    # not "gan" (longest-alias-first + word boundaries)
    assert canonicalize("Mohegan Digital") == "mohegan"


def test_longest_alias_wins():
    assert canonicalize("Batavia Downs Gaming/Hybrid (Caesars Sportsbook)") == "caesars"


def test_sequential_rebrands_share_a_slug():
    assert canonicalize("PointsBet") == canonicalize("Fanatics") == "fanatics"
    assert canonicalize("Barstool Sportsbook") == canonicalize("ESPN Bet") == "penn"


def test_simultaneous_entities_stay_separate():
    # William Hill and Caesars both operated in MI in 2021 — merging the slugs
    # would let the MI dedupe silently drop one of the two rows.
    assert canonicalize("William Hill") != canonicalize("Caesars")


def test_alias_table_is_normalized():
    for alias in ALIASES:
        assert alias == alias.strip().lower(), f"alias {alias!r} not normalized"


@pytest.mark.parametrize(
    ("raw", "slug"),
    [
        ("Rush Street Interactive NY", "rsi"),
        ("BetRivers", "rsi"),
        ("Wynn Interactive", "wynnbet"),
        ("Golden Nugget", "golden_nugget"),
        ("TwinSpires", "twinspires"),
        ("FoxBet", "foxbet"),
        # PA licensees
        ("HOLLYWOOD CASINO AT THE MEADOWS", "draftkings"),
        ("MEADOWS", "draftkings"),
        ("VALLEY FORGE CASINO", "fanduel"),
        ("SUGARHOUSE CASINO", "rsi"),
        # IL licensees
        ("Casino Queen, Inc.", "draftkings"),
        ("Northside Crown Gaming LLC", "draftkings"),
        ("FHR-Illinois  LLC", "circa"),  # double space as printed by IGB
    ],
)
def test_known_mappings(raw, slug):
    assert canonicalize(raw) == slug


def test_exact_only_aliases_do_not_leak_into_containment():
    # "RIVERS" (PA FY18-19) must map exactly, but the word inside a longer
    # unknown name must not silently claim it for Rush Street.
    assert canonicalize("RIVERS") == "rsi"
    assert canonicalize("Two Rivers Casino Resort") is None


class TestEraOverrides:
    def test_par_a_dice_boundaries(self):
        d = dt.date
        raw = "Par-A-Dice Gaming Corporation"
        assert canonicalize_dated(raw, "IL", d(2020, 8, 31)) == "fanduel"
        assert canonicalize_dated(raw, "IL", d(2022, 2, 28)) == "fanduel"  # inclusive end
        assert canonicalize_dated(raw, "IL", d(2022, 3, 1)) == "betmgm"  # inclusive start
        assert canonicalize_dated(raw, "IL", d(2026, 5, 31)) == "betmgm"

    def test_undated_lookup_refuses_era_licensees(self):
        # Without a date the mapping is ambiguous — must be None (loud), never a guess.
        assert canonicalize("Par-A-Dice Gaming Corporation") is None
        assert canonicalize("RESORTS CASINO HOTEL (DGMB CASINO, LLC.)") is None

    def test_nj_dgmb_handoff(self):
        d = dt.date
        # DGMB's online line is $0 until DraftKings' revenue moves onto it
        # (Sep 2024, from Resorts Digital's discontinued return) — and the
        # containment matching covers all four spelling variants.
        for raw in (
            "RESORTS CASINO HOTEL (DGMB CASINO, LLC.)",
            "RESORTS CASINO HOTEL (DGMB CASINO LLC)",
            "RESORTS CASNIO HOTEL (DGMB CASINO LLC)",  # regulator typo era
            "Resorts Casino - DGMB",
        ):
            assert canonicalize_dated(raw, "NJ", d(2024, 8, 31)) == "resorts_ac"
            assert canonicalize_dated(raw, "NJ", d(2024, 9, 30)) == "draftkings"

    def test_other_states_unaffected(self):
        assert canonicalize_dated("DraftKings", "NY", dt.date(2022, 1, 9)) == "draftkings"
        assert canonicalize_dated("Par-A-Dice Gaming Corporation", "PA", dt.date(2021, 1, 31)) is None
