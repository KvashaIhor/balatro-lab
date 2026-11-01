from collections import Counter

import pytest

from balatro.agent import Agent
from balatro.bots import GreedyBot
from balatro.cards import standard_deck
from balatro.content.decks import HANDLED
from balatro.items import CONSUMABLES, DECKS, entries
from balatro.run import Run
from balatro.shop import Shop


def deck_run(name, seed=0, **kw):
    run = Run(Agent(), seed=seed, deck=name, **kw)
    run.start_ante()
    return run


def basics(run):
    return (run.base_hands, run.base_discards, run.base_hand_size, run.money, run.joker_slots, run.consumable_slots)


def test_every_deck_has_code_and_every_modification_is_handled():
    assert set(DECKS) == {d["name"] for d in entries("deck")}
    for d in entries("deck"):
        assert set(d["modifications"]) <= HANDLED, d["name"]


@pytest.mark.parametrize("name, expected", [
    ("Red Deck", (4, 4, 8, 4, 5, 2)), ("Blue Deck", (5, 3, 8, 4, 5, 2)), ("Yellow Deck", (4, 3, 8, 14, 5, 2)),
    ("Black Deck", (3, 3, 8, 4, 6, 2)), ("Painted Deck", (4, 3, 10, 4, 4, 2)), ("Nebula Deck", (4, 3, 8, 4, 5, 1)),
    ("Magic Deck", (4, 3, 8, 4, 5, 3)), ("Plasma Deck", (4, 3, 8, 4, 5, 2)),
])
def test_deck_numbers(name, expected):
    assert basics(deck_run(name)) == expected


def test_decks_stack_with_stakes():
    assert deck_run("Red Deck", stake="Blue Stake").base_discards == 3


def test_green_deck_pays_for_hands_and_discards_but_no_interest():
    run = deck_run("Green Deck")
    run.blind = run.make_blind(0)
    run.money, run.hands_left, run.discards_left = 50, 2, 1
    run.cash_out()
    assert run.money == 50 + 3 + 2 * 2 + 1


def test_magic_deck_starts_with_crystal_ball_and_two_fools():
    run = deck_run("Magic Deck")
    assert run.vouchers == ["Crystal Ball"]
    if "The Fool" not in CONSUMABLES:
        pytest.skip("The Fool has no code yet")
    assert [c.name for c in run.consumables] == ["The Fool", "The Fool"]


def test_nebula_deck_starts_with_telescope():
    assert deck_run("Nebula Deck").vouchers == ["Telescope"]


def test_ghost_deck_sells_spectrals_and_starts_with_hex():
    run = deck_run("Ghost Deck")
    assert run.spectral_weight == 2 and run.shop_weights()["Spectral"] == 2
    if "Hex" not in CONSUMABLES:
        pytest.skip("Hex has no code yet")
    assert [c.name for c in run.consumables] == ["Hex"]
    kinds = Counter()
    for _ in range(100):
        kinds.update(o.kind for o in Shop(run).cards)
    assert kinds["Spectral"] > 0


def test_zodiac_deck_starts_with_three_vouchers():
    run = deck_run("Zodiac Deck")
    assert run.vouchers == ["Tarot Merchant", "Planet Merchant", "Overstock"]
    assert run.shop_card_slots == 3 and len(Shop(run).cards) == 3
    assert run.shop_weights()["Tarot"] == run.shop_weights()["Planet"] == 9.6


def test_abandoned_deck_has_no_face_cards():
    run = deck_run("Abandoned Deck")
    assert len(run.deck) == 40 == run.starting_deck_size
    assert not any(c.rank in (11, 12, 13) for c in run.deck)
    assert len({c.uid for c in run.deck}) == 40


def test_checkered_deck_is_spades_and_hearts():
    run = deck_run("Checkered Deck")
    assert Counter(c.suit for c in run.deck) == {"Spades": 26, "Hearts": 26}
    assert set(Counter((c.rank, c.suit) for c in run.deck).values()) == {2}
    assert len({c.uid for c in run.deck}) == 52


def test_erratic_deck_is_random_but_seeded():
    a, b, c = (sorted((x.rank, x.suit) for x in deck_run("Erratic Deck", seed=s).deck) for s in (1, 1, 2))
    assert len(a) == 52 and a == b and a != c
    assert a != sorted((x.rank, x.suit) for x in standard_deck())
    assert len({x.uid for x in deck_run("Erratic Deck").deck}) == 52


def test_anaglyph_deck_gives_a_double_tag_after_each_boss():
    run = deck_run("Anaglyph Deck")
    run.blind = run.make_blind(2)
    run.boss_defeated()
    assert [t.name for t in run.tags] == ["Double Tag"]


def test_plasma_deck_doubles_blinds_and_balances_scores():
    plasma, plain = deck_run("Plasma Deck"), Run(Agent(), seed=0)
    assert plasma.plasma and plasma.blind_scale == 2
    for kind in (0, 1):
        assert plasma.make_blind(kind).chips == 2 * plain.make_blind(kind).chips
    plain.start_ante()
    plasma.ante_boss = plain.ante_boss
    assert plasma.make_blind(2).chips == 2 * plain.make_blind(2).chips


@pytest.mark.parametrize("name", sorted(DECKS))
def test_every_deck_plays_full_runs(name):
    for seed in range(2):
        run = Run(GreedyBot(), seed=seed, deck=name, max_ante=4)
        result = run.play()
        assert result.blinds_beaten >= 0 and run.deck
        assert len({c.uid for c in run.deck}) == len(run.deck)
