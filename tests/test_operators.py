import pytest

from ggr.ingest.mi import FILES as MI_FILES  # noqa: F401  (import guards module health)
from ggr.ingest.ny import MOBILE_OPERATORS
from ggr.operators import ALIASES, canonicalize


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
    assert canonicalize("Mohegan Digital") is None
    assert canonicalize("Michigan Wagering Co") is None


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
    ],
)
def test_known_mappings(raw, slug):
    assert canonicalize(raw) == slug
