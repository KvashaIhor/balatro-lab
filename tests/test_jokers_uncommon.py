import random

import pytest

from balatro import pool
from balatro.agent import Agent
from balatro.bots import GreedyBot
from balatro.cards import SEALS, Card
from balatro.hands import evaluate
from balatro.items import CONSUMABLES, Boss, Consumable
from balatro.jokers import CATALOG, JOKER_DATA
from balatro.run import Blind, Run
from balatro.scoring import HandContext, score_hand
from balatro.shop import PACKS, Offer, Shop, cost_of

UNCOMMON = sorted(n for n, d in JOKER_DATA.items() if d["rarity"] == "Uncommon")


def card(text, **mods):
    rank = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10}.get(text[0]) or int(text[0])
    suit = {"S": "Spades", "H": "Hearts", "C": "Clubs", "D": "Diamonds"}[text[1]]
    return Card(rank, suit, **mods)


def cards(*items):
    return [card(c) if isinstance(c, str) else c for c in items]


def make_run(*jokers, agent=None, seed=0):
    run = Run(agent or Agent(), seed=seed)
    run.start_ante()
    run.blind = run.make_blind(0)
    run.hands_left, run.discards_left = 3, 3
    for j in jokers:
        run.add_joker(CATALOG[j]() if isinstance(j, str) else j)
    return run


def score(run, played, held=(), rng=None, estimating=False):
    played, held = cards(*played), cards(*held)
    ctx = HandContext(run, played, held, evaluate(played, run.rules), rng or random.Random(0), estimating=estimating)
    return score_hand(ctx)


def fired(s, name):
    return [amount for source, _, amount in s.log if source == name]


def select_blind(run, kind=0):
    run.blind = run.make_blind(kind)
    run.hands_left, run.discards_left = 4, 3
    for j in list(run.active_jokers()):
        j.on_blind_select(run, run.blind)


class Always:
    """An rng whose every 1-in-n roll hits."""

    def random(self):
        return 0.0


class Never:
    def random(self):
        return 0.999999


class FakeSpectral(Consumable):
    name, kind, number = "Fake Spectral", "Spectral", 999


class FakeTarot(Consumable):
    name, kind, number = "Fake Tarot", "Tarot", 999


def steel(n):
    def setup(run):
        for c in run.deck[:n]:
            c.enhancement = "Steel"
    return setup


def stone(n):
    def setup(run):
        for c in run.deck[:n]:
            c.enhancement = "Stone"
    return setup


def attrs(**values):
    def setup(run):
        for k, v in values.items():
            setattr(run, k, v)
    return setup


def test_all_64_uncommon_jokers_are_registered():
    assert len(UNCOMMON) == 64
    assert all(n in CATALOG and CATALOG[n].rarity == "Uncommon" for n in UNCOMMON)


# ---- numbers in the joker pass and per scored card ------------------------------------------------

@pytest.mark.parametrize("joker, played, held, setup, chips, mult", [
    ("Fibonacci", ["AS", "AH", "KC"], [], None, 32, 18),
    ("Fibonacci", ["KS", "KH"], [], None, 30, 2),
    ("Arrowhead", ["KS", "KH"], [], None, 80, 2),
    ("Onyx Agate", ["KC", "KH"], [], None, 30, 9),
    ("Hack", ["2S", "2H"], [], None, 18, 2),
    ("Hack", ["6S", "6H"], [], None, 22, 2),
    ("Sock and Buskin", ["KS", "KH"], [], None, 50, 2),
    ("Sock and Buskin", ["9S", "9H"], [], None, 28, 2),
    ("Dusk", ["KS", "KH"], [], attrs(hands_left=0), 50, 2),
    ("Dusk", ["KS", "KH"], [], attrs(hands_left=1), 30, 2),
    ("Acrobat", ["KS", "KH"], [], attrs(hands_left=0), 30, 6),
    ("Acrobat", ["KS", "KH"], [], attrs(hands_left=1), 30, 2),
    ("Steel Joker", ["KS", "KH"], [], steel(2), 30, 2.8),
    ("Steel Joker", ["KS", "KH"], [], None, 30, 2),
    ("Stone Joker", ["KS", "KH"], [], stone(2), 80, 2),
    ("Erosion", ["KS", "KH"], [], lambda run: setattr(run, "deck", run.deck[:-3]), 30, 14),
    ("Erosion", ["KS", "KH"], [], None, 30, 2),
    ("Bull", ["KS", "KH"], [], attrs(money=10), 50, 2),
    ("Bull", ["KS", "KH"], [], attrs(money=-5), 30, 2),
    ("Bootstraps", ["KS", "KH"], [], attrs(money=14), 30, 6),
    ("Throwback", ["KS", "KH"], [], attrs(skips=2), 30, 3),
    ("Throwback", ["KS", "KH"], [], None, 30, 2),
    ("Mime", ["KS", "KH"], [card("3C", enhancement="Steel")], None, 30, 4.5),
    ("Loyalty Card", ["KS", "KH"], [], attrs(hands_played=6), 30, 8),
    ("Loyalty Card", ["KS", "KH"], [], attrs(hands_played=5), 30, 2),
    ("Card Sharp", ["KS", "KH"], [], lambda run: run.round_hand_types.update({"Pair": 2}), 30, 6),
    ("Card Sharp", ["KS", "KH"], [], lambda run: run.round_hand_types.update({"Pair": 1}), 30, 2),
    ("Flower Pot", ["2H", "3D", "4S", "5C", "6H"], [], None, 50, 12),
    ("Joker Stencil", ["KS", "KH"], [], None, 30, 10),
])
def test_joker_numbers(joker, played, held, setup, chips, mult):
    run = make_run(joker)
    if setup:
        setup(run)
    s = score(run, played, held)
    assert (s.chips, s.mult) == pytest.approx((chips, mult))


@pytest.mark.parametrize("played, money", [(["KD", "KH"], 1), ([card("KD", seal="Red"), "KH"], 2), (["KS", "KH"], 0)])
def test_rough_gem_pays_per_diamond_trigger(played, money):
    assert score(make_run("Rough Gem"), played).money == money


def test_bull_and_bootstraps_count_money_earned_earlier_in_the_hand():
    run = make_run("Rough Gem", "Bull", "Bootstraps")
    run.money = 4
    s = score(run, ["KD", "KH"])  # Rough Gem's $1 makes $5
    assert fired(s, "Bull") == [10] and fired(s, "Bootstraps") == [2]


def test_bloodstone_is_a_coin_flip_per_heart_and_oops_makes_it_certain():
    run = make_run("Bloodstone")
    rng = random.Random(1)
    hits = sum(bool(fired(score(run, ["KH"], rng=rng), "Bloodstone")) for _ in range(2000))
    assert 900 < hits < 1100
    assert score(run, ["KS", "KH"], rng=Always()).mult == 2 * 1.5
    assert score(run, ["KS", "KH"], rng=Never()).mult == 2
    run.add_joker(CATALOG["Oops! All 6s"]())
    assert run.probability_scale == 2
    for seed in range(20):
        assert score(run, ["KH", "KD"], rng=random.Random(seed)).mult == 2 * 1.5  # 2 in 2: every Heart


def test_oops_all_6s_stack():
    run = make_run("Oops! All 6s", "Oops! All 6s")
    assert run.probability_scale == 4


def test_hiker_adds_permanent_chips_per_trigger_and_blueprint_adds_more():
    run = make_run("Blueprint", "Hiker")
    ks, kh = card("KS", seal="Red"), card("KH")
    s = score(run, [ks, kh])
    assert ks.bonus_chips == 20 and kh.bonus_chips == 10
    assert s.chips == 10 + 10 + (10 + 10) + 10  # the Red Seal trigger sees the first trigger's bonus
    score(run, [ks, kh], estimating=True)
    assert ks.bonus_chips == 20


def test_the_idol_matches_rank_and_suit_and_rerolls_from_the_deck():
    idol = CATALOG["The Idol"]()
    run = make_run(idol)
    idol.rank, idol.suit = 13, "Spades"
    assert fired(score(run, ["KS", "KH"]), "The Idol") == [2]
    assert fired(score(run, ["KC", "KH"]), "The Idol") == []
    run.add_joker(CATALOG["Smeared Joker"]())
    assert fired(score(run, ["KS", "KC"]), "The Idol") == [2, 2]
    idol.end_of_round(run, run.blind)
    assert (idol.rank, idol.suit) in {(c.rank, c.suit) for c in run.deck}
    for c in run.deck:
        c.enhancement = "Stone"
    idol.end_of_round(run, run.blind)
    assert (idol.rank, idol.suit) == (14, "Spades")


@pytest.mark.parametrize("held, fires", [
    ([], True), (["2S", "3C"], True), (["2S", "3H"], False),
    ([card("3H", enhancement="Wild")], True), ([card("3H", enhancement="Wild", debuffed=True)], False),
    ([card("3S", debuffed=True)], True), ([card("3S", enhancement="Stone")], False),
])
def test_blackboard(held, fires):
    s = score(make_run("Blackboard"), ["KH", "KD"], held)
    assert bool(fired(s, "Blackboard")) == fires


@pytest.mark.parametrize("played, smeared, fires", [
    (["2H", "3D", "4S", "5C", "6H"], False, True),
    (["2H", "3D", "4S", "5H", "6H"], False, False),
    (["2H", "3D", "4S", card("5H", enhancement="Wild"), "6H"], False, True),
    (["2H", "3D", "4S", card("5H", enhancement="Wild", debuffed=True), "6H"], False, False),
    (["2H", "3D", "4S", card("5C", debuffed=True), "6H"], False, True),
    (["2H", "2H", "3S", "3S"], True, True),
    (["2H", "2H", "3S", "3S"], False, False),
])
def test_flower_pot(played, smeared, fires):
    run = make_run("Flower Pot", *(["Smeared Joker"] if smeared else []))
    assert bool(fired(score(run, played), "Flower Pot")) == fires


@pytest.mark.parametrize("played, smeared, fires", [
    (["KC", "KH"], False, True), (["KC", "KC"], False, False), (["KS", "KH"], False, False),
    ([card("KH", enhancement="Wild"), "KS"], False, True),
    ([card("KH", enhancement="Wild"), card("KD", enhancement="Wild")], False, True),
    ([card("KC", debuffed=True), "KH"], False, False),
    (["KS"], True, True), (["KH"], True, False),
])
def test_seeing_double(played, smeared, fires):
    run = make_run("Seeing Double", *(["Smeared Joker"] if smeared else []))
    assert bool(fired(score(run, played), "Seeing Double")) == fires


@pytest.mark.parametrize("jokers, expected", [
    (["Joker Stencil"], [5]),
    (["Joker Stencil", "Joker"], [4]),
    (["Joker Stencil", "Joker Stencil"], [5, 5]),
    (["Joker Stencil", CATALOG["Joker"]("Negative")], [5]),
    ([CATALOG["Joker Stencil"]("Negative")], [6]),
    (["Joker Stencil", "Joker", "Joker", "Joker", "Joker"], []),  # X1 does nothing
    (["Blueprint", "Joker Stencil"], [4, 4]),
])
def test_joker_stencil_counts_empty_slots(jokers, expected):
    run = make_run(*jokers)
    assert fired(score(run, ["KS", "KH"]), "Joker Stencil") == expected  # a copy logs under the Stencil's name


def test_card_sharp_through_real_plays():
    run = make_run("Card Sharp")
    totals = []
    for _ in range(2):
        run.hand = cards("KS", "KH")
        totals.append(run.play_hand([0, 1]))
    assert totals == [60, 180]


def test_loyalty_card_fires_on_every_sixth_hand_since_it_joined():
    run = make_run()
    run.hands_played = 4
    run.add_joker(CATALOG["Loyalty Card"]())
    totals = []
    for _ in range(12):
        run.hand, run.hands_left = cards("KS", "KH"), 5
        totals.append(run.play_hand([0, 1]))
    assert totals == [60] * 5 + [240] + [60] * 5 + [240]


def test_matador_pays_when_the_boss_triggers():
    run = make_run("Matador")
    assert score(run, ["KS", "KH"]).money == 0  # no boss
    boss = Boss()
    run.blind = Blind("Boss Blind", 2, 600, 5, boss)
    assert score(run, ["KS", "KH"]).money == 0
    assert score(run, [card("KS", debuffed=True), "KH"]).money == 8
    assert score(run, ["KS", "KH", card("2C", debuffed=True)]).money == 0  # not a scoring card
    boss.triggered = True
    assert score(run, ["KS", "KH"]).money == 8
    boss.disabled = True
    assert score(run, ["KS", "KH"]).money == 0


# ---- rules and passives ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, rule", [("Four Fingers", "four_fingers"), ("Shortcut", "shortcut"),
                                        ("Smeared Joker", "smeared"), ("Pareidolia", "pareidolia"),
                                        ("Showman", "showman")])
def test_rule_jokers_set_their_rule(name, rule):
    run = make_run()
    assert not run._rule(rule)
    run.add_joker(CATALOG[name]())
    assert run._rule(rule) and not CATALOG[name].copyable


def test_rule_jokers_change_hands_and_faces():
    run = make_run("Four Fingers", "Shortcut")
    assert evaluate(cards("2H", "5H", "9H", "KH"), run.rules).name == "Flush"
    assert evaluate(cards("2S", "4H", "6C", "8D", "TS"), run.rules).name == "Straight"
    assert evaluate(cards("2S", "4H", "6C", "8D"), run.rules).name == "Straight"
    run = make_run("Smeared Joker")
    assert evaluate(cards("2H", "5D", "9H", "KD", "3H"), run.rules).name == "Flush"
    run = make_run("Pareidolia", "Sock and Buskin")
    assert score(run, ["3S", "3H"]).chips == 10 + 2 * 3 * 2
    run = make_run("Showman")
    assert pool.taken(run, ["Joker"]) == set()


def test_passive_hand_size_hands_and_discards():
    class Recorder(Agent):
        seen = None

        def round_action(self, run):
            self.seen = self.seen or (run.hands_left, run.discards_left, len(run.hand))
            return ("play", [0])

    def first_look(*jokers):
        agent = Recorder()
        run = make_run(*jokers, agent=agent)
        run.play_round()
        return agent.seen

    assert first_look() == (4, 3, 8)
    assert first_look("Troubadour", "Merry Andy") == (3, 6, 9)
    assert first_look("Blueprint", "Burglar") == (10, 0, 8)
    assert first_look("Certificate") == (4, 3, 9)


def test_turtle_bean_shrinks_each_round_then_goes():
    bean = CATALOG["Turtle Bean"]()
    run = make_run(bean)
    sizes = [run.hand_size]
    for _ in range(5):
        run.end_round()
        sizes.append(run.hand_size)
    assert sizes == [13, 12, 11, 10, 9, 8] and bean not in run.jokers


def test_astronomer_makes_planets_and_celestial_packs_free():
    run = make_run()
    planet, pack = Offer("Planet", CONSUMABLES["Pluto"]()), Offer("Pack", PACKS["Celestial Pack"])
    assert cost_of(run, planet) == 3 and cost_of(run, pack) == 4
    run.add_joker(CATALOG["Astronomer"]())
    assert cost_of(run, planet) == 0 and cost_of(run, pack) == 0


@pytest.mark.parametrize("name, enhancement", [("Steel Joker", "Steel"), ("Stone Joker", "Stone"),
                                               ("Lucky Cat", "Lucky"), ("Glass Joker", "Glass")])
def test_enhancement_gated_jokers(name, enhancement):
    run = make_run()
    assert not CATALOG[name].can_spawn(run)
    run.deck[10].enhancement = enhancement
    assert CATALOG[name].can_spawn(run)


# ---- before scoring -------------------------------------------------------------------------------

def test_space_joker_levels_the_hand_before_it_scores():
    run = make_run("Space Joker")
    s = score(run, ["KS", "KH"], rng=Always())
    assert run.hand_levels["Pair"] == 2 and (s.chips, s.mult) == (25 + 20, 3)
    score(run, ["KS", "KH"], rng=Always(), estimating=True)
    score(run, ["KS", "KH"], rng=Never())
    assert run.hand_levels["Pair"] == 2
    rng = random.Random(0)
    for _ in range(400):
        score(run, ["2S"], rng=rng)
    assert 70 < run.hand_levels["High Card"] - 1 < 130  # 1 in 4


def test_blueprint_space_joker_rolls_again():
    run = make_run("Blueprint", "Space Joker")
    score(run, ["KS", "KH"], rng=Always())
    assert run.hand_levels["Pair"] == 3


def test_midas_mask_turns_scoring_faces_gold_first():
    run = make_run("Midas Mask")
    ks, kh, kicker = card("KS", enhancement="Glass"), card("KH", debuffed=True), card("QC")
    s = score(run, [ks, kh, kicker, "2C"])  # Pair of Kings: the Queen doesn't score
    assert ks.enhancement == "Gold" and kh.enhancement is None and kicker.enhancement is None
    assert s.mult == 2  # no Glass x2
    jack = card("JS", enhancement="Glass")
    score(run, [jack, "JH"], estimating=True)
    assert jack.enhancement == "Glass"
    run.add_joker(CATALOG["Pareidolia"]())
    three = card("3S")
    score(run, [three, "3H"])
    assert three.enhancement == "Gold"


def test_vampire_eats_enhancements_and_copies_only_give_the_xmult():
    vampire = CATALOG["Vampire"]()
    run = make_run("Blueprint", vampire)
    glass, bonus, kicker = card("KS", enhancement="Glass"), card("KH", enhancement="Bonus"), card("2C", enhancement="Mult")
    s = score(run, [glass, bonus, kicker])
    assert glass.enhancement is None and bonus.enhancement is None and kicker.enhancement == "Mult"
    assert vampire.xmult == 1.2
    assert s.chips == 30 and s.mult == pytest.approx(2 * 1.2 * 1.2)
    lucky = card("QS", enhancement="Lucky")
    score(run, [lucky, "QH"], estimating=True)
    assert lucky.enhancement == "Lucky" and vampire.xmult == 1.2
    score(run, [card("QS", enhancement="Steel", debuffed=True), "QH"])
    assert vampire.xmult == 1.2


def test_spare_trousers_scale_before_scoring_without_double_counting_copies():
    trousers = CATALOG["Spare Trousers"]()
    run = make_run("Blueprint", trousers)
    s = score(run, ["KS", "KH", "2C", "2D"])
    assert trousers.mult == 2 and s.mult == 2 + 2 + 2
    score(run, ["KS", "KH", "2C", "2D"], estimating=True)
    assert trousers.mult == 2
    score(run, ["KS", "KH", "KC", "2D", "2S"])  # a Full House contains a Two Pair
    assert trousers.mult == 4
    score(run, ["KS", "KH", "KC", "KD"])  # a Four of a Kind doesn't
    assert trousers.mult == 4


def test_lucky_cat_counts_each_lucky_trigger_once():
    cat = CATALOG["Lucky Cat"]()
    run = make_run("Blueprint", cat)
    lucky = card("KS", enhancement="Lucky", seal="Red")
    s = score(run, [lucky, "KH"], rng=Always())
    assert run.lucky_triggers == 4  # two triggers, each hitting both rolls
    assert cat.xmult == 1.5
    assert s.mult == pytest.approx((2 + 20 + 20) * 1.5 * 1.5) and s.money == 40
    score(run, [card("QS", enhancement="Lucky"), "QH"], rng=Always(), estimating=True)
    score(run, [card("QS", enhancement="Lucky"), "QH"], rng=Never())
    assert cat.xmult == 1.5


# ---- retriggers and after scoring -----------------------------------------------------------------

def test_seltzer_retriggers_for_ten_hands_and_copies_dont_use_charges():
    seltzer = CATALOG["Seltzer"]()
    run = make_run("Blueprint", seltzer)
    totals = []
    for _ in range(11):
        run.hand, run.hands_left = cards("KS", "KH"), 5
        totals.append(run.play_hand([0, 1]))
    assert totals == [(10 + 30 + 30) * 2] * 10 + [60]  # 3 triggers per card: itself, Seltzer, its copy
    assert seltzer not in run.jokers


def test_mime_retriggers_gold_cards_at_end_of_round():
    run = make_run("Mime")
    run.hand = [card("5H", enhancement="Gold")]
    run.money, run.hands_left, run.discards_left = 0, 0, 0
    run.end_round()
    assert run.money == 6 + 3 + 1  # Gold twice, Small Blind $3, $1 interest on $6


def test_sixth_sense_destroys_a_lone_six_on_the_first_hand(monkeypatch):
    monkeypatch.setitem(CONSUMABLES, FakeSpectral.name, FakeSpectral)
    run = make_run("Sixth Sense")
    six, other = [c for c in run.deck if c.rank == 6][:2]
    run.hand = [six, other]
    run.play_hand([0])
    assert all(c is not six for c in run.deck) and len(run.deck) == 51
    assert [c.kind for c in run.consumables] == ["Spectral"]
    run.hand = [other]
    run.play_hand([0])  # second hand of the round
    assert len(run.deck) == 51 and len(run.consumables) == 1


def test_seance_makes_a_spectral_for_a_straight_flush(monkeypatch):
    monkeypatch.setitem(CONSUMABLES, FakeSpectral.name, FakeSpectral)
    run = make_run("Blueprint", "Séance")
    score(run, ["2H", "3H", "4H", "5H", "6H"], estimating=True)
    score(run, ["2H", "3H", "4H", "5H", "7H"])
    assert run.consumables == []
    score(run, ["2H", "3H", "4H", "5H", "6H"])
    assert len(run.consumables) == 2  # the copy makes one too


# ---- run hooks ------------------------------------------------------------------------------------

def test_ceremonial_dagger_eats_its_right_neighbour():
    dagger = CATALOG["Ceremonial Dagger"]()
    victim = CATALOG["Joker"]("Foil")
    run = make_run("Blueprint", dagger, victim, "Burglar")
    value = run.sell_value(victim)
    select_blind(run)
    assert value == 2 and dagger.mult == 4
    assert [j.name for j in run.jokers] == ["Blueprint", "Ceremonial Dagger", "Burglar"]  # the copy ate nothing
    assert score(run, ["KS", "KH"]).mult == 2 + 4 + 4
    run.jokers[2].eternal = True
    select_blind(run)
    assert dagger.mult == 4 and len(run.jokers) == 3


def test_madness_grows_on_small_and_big_blinds_and_destroys_a_random_joker():
    madness = CATALOG["Madness"]()
    eternal = CATALOG["Jolly Joker"]()
    eternal.eternal = True
    run = make_run("Blueprint", madness, "Joker", eternal)
    select_blind(run, 2)
    assert madness.xmult == 1 and len(run.jokers) == 4
    select_blind(run, 0)
    assert madness.xmult == 1.5 and len(run.jokers) == 3 and eternal in run.jokers
    select_blind(run, 1)
    select_blind(run, 1)
    assert madness.xmult == 2.5 and [j.name for j in run.jokers] == ["Madness", "Jolly Joker"]


def test_marble_joker_adds_stone_cards_that_hologram_counts():
    hologram = CATALOG["Hologram"]()
    run = make_run("Marble Joker", hologram)
    select_blind(run)
    assert len(run.deck) == 53 and sum(c.is_stone for c in run.deck) == 1
    assert hologram.xmult == 1.25
    run.add_cards([card("2S"), card("3S")])
    assert hologram.xmult == 1.75
    run.add_joker(CATALOG["Blueprint"]())  # copies Hologram: no extra growth
    run.add_cards([card("4S")])
    assert hologram.xmult == 2.0


def test_blueprint_marble_joker_adds_another_stone_card():
    run = make_run("Blueprint", "Marble Joker")
    select_blind(run)
    assert len(run.deck) == 54 and sum(c.is_stone for c in run.deck) == 2


def test_hologram_counts_cards_added_by_a_copied_joker():
    hologram = CATALOG["Hologram"]()
    run = make_run("Blueprint", "Marble Joker", hologram)
    select_blind(run)
    assert hologram.xmult == 1.5


def test_certificate_adds_a_sealed_card_to_hand_and_deck():
    run = make_run("Blueprint", "Certificate")
    run.hand = []
    for j in run.active_jokers():
        j.on_round_start(run)
    assert len(run.hand) == 2 and len(run.deck) == 54
    assert all(c.seal in SEALS and any(d is c for d in run.deck) for c in run.hand)


def test_cartomancer_makes_a_tarot_per_copy(monkeypatch):
    monkeypatch.setitem(CONSUMABLES, FakeTarot.name, FakeTarot)
    run = make_run("Blueprint", "Cartomancer")
    select_blind(run)
    assert [c.kind for c in run.consumables] == ["Tarot", "Tarot"]
    select_blind(run)
    assert len(run.consumables) == 2  # no room


def test_trading_card_and_glass_joker():
    glass_joker = CATALOG["Glass Joker"]()
    run = make_run("Blueprint", glass_joker, "Trading Card")
    run.money = 0
    glass = run.deck[0]
    glass.enhancement = "Glass"
    run.hand = run.deck[:3]
    run.discard([0])
    assert run.money == 3 and len(run.deck) == 51 and glass_joker.xmult == 1.75
    run.discard([0])
    assert run.money == 3 and len(run.deck) == 51
    run.discards_used = 0
    run.hand = run.deck[:2]
    run.discard([0, 1])
    assert run.money == 3 and len(run.deck) == 51


def test_glass_joker_grows_after_the_hand_that_shatters():
    glass_joker = CATALOG["Glass Joker"]()
    run = make_run(glass_joker, "Oops! All 6s", "Oops! All 6s")  # 4 in 4: glass always breaks
    run.hand = [card("KS", enhancement="Glass"), card("KH", enhancement="Glass")]
    run.add_cards(run.hand)
    total = run.play_hand([0, 1])
    assert total == 30 * 2 * 2 * 2 and glass_joker.xmult == 2.5 and len(run.deck) == 52


def test_castle_counts_discarded_cards_of_its_suit():
    castle = CATALOG["Castle"]()
    run = make_run("Blueprint", castle)
    assert castle.suit in ("Spades", "Hearts", "Clubs", "Diamonds")
    castle.suit = "Hearts"
    run.hand = cards("2H", "3H", card("4H", debuffed=True), "5S", card("6S", enhancement="Wild"))
    run.discard(range(5))
    assert castle.chips == 9
    assert score(run, ["KS", "KH"]).chips == 30 + 9 + 9
    run.add_joker(CATALOG["Smeared Joker"]())
    run.hand = cards("2D")
    run.discard([0])
    assert castle.chips == 12


def test_ramen_loses_a_hundredth_per_card_and_goes_on_the_hundredth():
    ramen = CATALOG["Ramen"]()
    run = make_run("Blueprint", ramen)
    run.discards_left = 100

    def discard(n):
        run.hand = [card("2S") for _ in range(n)]
        run.discard(range(n))

    discard(5)
    assert ramen.xmult == 1.95
    assert score(run, ["KS", "KH"]).mult == pytest.approx(2 * 1.95 * 1.95)
    for _ in range(18):
        discard(5)
    discard(4)
    assert ramen.xmult == 1.01 and ramen in run.jokers
    discard(1)
    assert ramen not in run.jokers


def test_flash_card_grows_per_reroll_once():
    flash = CATALOG["Flash Card"]()
    run = make_run("Blueprint", flash)
    run.money = 100
    shop = Shop(run)
    shop.reroll()
    shop.reroll()
    assert flash.mult == 4
    assert score(run, ["KS", "KH"]).mult == 2 + 4 + 4


def test_constellation_grows_per_planet_used():
    constellation = CATALOG["Constellation"]()
    run = make_run("Blueprint", constellation)
    run.consumables = [CONSUMABLES["Pluto"](), CONSUMABLES["Mercury"]()]
    run.use_consumable(0, [])
    run.use_consumable(0, [])
    constellation.on_consumable_used(run, FakeTarot())
    assert constellation.xmult == 1.2


def test_burglar_and_copies():
    run = make_run("Blueprint", "Burglar")
    select_blind(run)
    assert (run.hands_left, run.discards_left) == (10, 0)


def test_luchador_disables_the_boss_only_during_its_round():
    run = make_run("Luchador")
    run.blind = run.make_blind(2)
    assert run.sell_joker(0) and run.active_boss is None
    run = make_run("Luchador")
    run.blind = run.make_blind(2)
    run.current_shop = Shop(run)
    run.sell_joker(0)
    assert run.active_boss is not None
    run = make_run("Luchador")
    assert run.sell_joker(0) and not run.blind.boss


def test_diet_cola_gives_a_double_tag_when_sold():
    run = make_run("Diet Cola")
    run.sell_joker(0)
    assert [t.name for t in run.tags] == ["Double Tag"]


def test_mr_bones_saves_a_quarter_of_the_blind_and_forfeits_the_reward():
    bones = CATALOG["Mr. Bones"]()
    run = make_run(bones)
    run.hands_left = 0
    run.round_score = run.blind.chips // 4 - 1
    assert not bones.on_fail(run)
    run.round_score = run.blind.chips // 4
    run.hands_left = 1
    assert not bones.on_fail(run)  # lost with hands left: out of cards
    run.hands_left = 0
    assert bones.on_fail(run) and bones not in run.jokers and run.blind.reward == 0


# ---- end of round ---------------------------------------------------------------------------------

def test_rocket_grows_when_a_boss_is_beaten():
    rocket = CATALOG["Rocket"]()
    run = make_run(rocket)
    assert [rocket.end_of_round(run, run.make_blind(k)) for k in (0, 1, 2, 0)] == [1, 1, 3, 3]


def test_end_of_round_money():
    run = make_run()
    assert CATALOG["Cloud 9"]().end_of_round(run, run.blind) == 4
    next(c for c in run.deck if c.rank == 9).enhancement = "Stone"
    assert CATALOG["Cloud 9"]().end_of_round(run, run.blind) == 3
    run.planets_used = {"Pluto", "Mars"}
    assert CATALOG["Satellite"]().end_of_round(run, run.blind) == 2
    moon = CATALOG["To the Moon"]()
    run.money = 23
    assert moon.end_of_round(run, run.blind) == 4
    run.money = 100
    assert moon.end_of_round(run, run.blind) == 5
    run.interest_enabled = False
    assert moon.end_of_round(run, run.blind) == 0


def test_to_the_moon_doubles_interest_at_cash_out():
    run = make_run("To the Moon")
    run.money, run.hands_left, run.discards_left = 23, 0, 0
    run.end_round()
    assert run.money == 23 + 3 + 4 + 4


def test_gift_card_adds_sell_value_to_everything():
    gift = CATALOG["Gift Card"]()
    run = make_run(gift, "Joker")
    run.consumables = [CONSUMABLES["Pluto"]()]
    before = [run.sell_value(x) for x in run.jokers + run.consumables]
    run.end_round()
    assert [run.sell_value(x) for x in run.jokers + run.consumables] == [v + 1 for v in before]


# ---- whole runs -----------------------------------------------------------------------------------

@pytest.mark.parametrize("group", [UNCOMMON[i:i + 5] for i in range(0, len(UNCOMMON), 5)])
def test_every_uncommon_joker_survives_real_runs(group):
    for seed in range(2):
        run = Run(GreedyBot(), seed=seed, max_ante=2)
        for name in group:
            run.add_joker(CATALOG[name]())
        result = run.play()
        assert result.ante >= 1 and not run.copying


def test_jokers_whose_effect_reads_the_run_show_what_it_comes_to():
    from balatro.jokers import NOW, joker_now
    run = Run(Agent(), game_seed="C5X6MXUN", deck="Abandoned Deck", max_ante=8)
    cloud, sat, bull, abstract, rocket = (CATALOG[n]() for n in ("Cloud 9", "Satellite", "Bull", "Abstract Joker", "Rocket"))
    run.jokers = [cloud, sat, bull, abstract, rocket]
    run.planets_used = {"Mercury", "Venus"}
    run.money = 12
    assert joker_now(cloud, run) == "$4 a round"                   # four 9s (no face cards in the deck)
    assert joker_now(cloud, run) == f"${cloud.end_of_round(run, None)} a round"
    assert joker_now(sat, run) == "$2 a round"
    assert joker_now(bull, run) == "+24 Chips"
    assert joker_now(abstract, run) == "+15 Mult"                  # five jokers
    assert joker_now(rocket, run) == "$1 a round"
    assert joker_now(cloud) == ""                                  # without the run: its own values only, as before
    assert set(NOW) <= set(CATALOG)
