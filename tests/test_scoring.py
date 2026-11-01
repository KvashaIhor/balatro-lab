import random

import pytest

from balatro.cards import Card
from balatro.hands import Rules, evaluate
from balatro.jokers import CATALOG
from balatro.scoring import HandContext, hand_base, score_hand


class RunStub:
    """Just enough run state for scoring tests."""

    def __init__(self, jokers=(), smeared=False):
        self.jokers = [CATALOG[name]() if isinstance(name, str) else name for name in jokers]
        self.smeared = smeared
        self.probability_scale = 1
        self.lucky_triggers = 0

    def active_jokers(self):
        return [j for j in self.jokers if not j.disabled]

    def on_lucky_trigger(self):
        self.lucky_triggers += 1


def card(text, **mods):
    rank = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10}.get(text[0]) or int(text[0])
    suit = {"S": "Spades", "H": "Hearts", "C": "Clubs", "D": "Diamonds"}[text[1]]
    return Card(rank, suit, **mods)


def score(played, jokers=(), held=(), level=1, seed=0):
    played = [card(c) if isinstance(c, str) else c for c in played]
    run = RunStub(jokers)
    ctx = HandContext(run, played, list(held), evaluate(played, Rules()), random.Random(seed))
    return score_hand(ctx, level)


def test_hand_levels_add_chips_and_mult():
    assert hand_base("Pair", 1) == (10, 2)
    assert hand_base("Pair", 3) == (40, 4)
    assert hand_base("Flush Five", 2) == (210, 19)


def test_a_pair_of_kings_scores_only_the_pair():
    s = score(["KS", "KH", "2C"])  # (10 + 10 + 10) chips x 2 mult; the 2 doesn't score
    assert (s.chips, s.mult, s.total) == (30, 2, 60)


def test_jokers_add_mult_then_multiply_left_to_right():
    assert score(["KS", "KH"], ["Joker", "The Duo"]).total == 30 * (2 + 4) * 2
    assert score(["KS", "KH"], ["The Duo", "Joker"]).total == 30 * (2 * 2 + 4)  # order matters


def test_suit_jokers_fire_per_scoring_card():
    s = score(["2D", "5D", "9D", "JD", "KD"], ["Greedy Joker"])  # flush of diamonds: 5 x +3 mult
    assert s.mult == 4 + 15 and s.chips == 35 + 2 + 5 + 9 + 10 + 10


def test_hanging_chad_retriggers_the_first_scoring_card_twice():
    plain, chad = score(["KS", "KH"]), score(["KS", "KH"], ["Hanging Chad"])
    assert chad.chips - plain.chips == 2 * 10


def test_red_seal_retriggers_and_glass_doubles_mult():
    s = score([card("KS", seal="Red", enhancement="Glass"), card("KH")])
    assert s.chips == 10 + 10 * 2 + 10 and s.mult == 2 * 2 * 2


def test_steel_cards_held_in_hand_multiply():
    s = score(["KS", "KH"], held=[card("3C", enhancement="Steel")])
    assert s.mult == 2 * 1.5


def test_joker_editions_wrap_its_effect():
    poly = CATALOG["Joker"](edition="Polychrome")
    s = score(["KS", "KH"], [poly])
    assert s.mult == (2 + 4) * 1.5


def test_baseball_card_multiplies_each_uncommon_joker():
    class Uncommon(CATALOG["Joker"]):
        name, rarity = "Some Uncommon", "Uncommon"
    s = score(["KS", "KH"], [Uncommon(), "Baseball Card"])
    assert s.mult == (2 + 4) * 1.5


def test_blueprint_copies_the_joker_to_its_right_and_brainstorm_the_leftmost():
    assert score(["KS", "KH"], ["Blueprint", "The Duo"]).mult == 2 * 2 * 2
    assert score(["KS", "KH"], ["The Duo", "Brainstorm"]).mult == 2 * 2 * 2
    assert score(["KS", "KH"], ["Blueprint", "Blueprint"]).mult == 2  # copying a copy of nothing


@pytest.mark.parametrize("seed", range(3))
def test_score_log_reconstructs_the_total(seed):
    s = score(["KS", "KH", card("7S", enhancement="Lucky")], ["Joker", "Hanging Chad"], seed=seed)
    chips, mult = hand_base("Pair", 1)
    for _, kind, amount in s.log[1:]:
        if kind == "+chips":
            chips += amount
        elif kind == "+mult":
            mult += amount
        elif kind == "xmult":
            mult *= amount
    assert (chips, mult) == (s.chips, s.mult)
