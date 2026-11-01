import random

import pytest

from balatro import pool
from balatro.agent import Agent
from balatro.bots import GreedyBot
from balatro.cards import SUITS, Card
from balatro.content.jokers_rare import AncientJoker
from balatro.hands import evaluate
from balatro.items import BOSSES, CONSUMABLES, Boss, Consumable, make
from balatro.jokers import CATALOG, JOKER_DATA, Joker
from balatro.run import Run
from balatro.scoring import HandContext, score_hand

RARE = ("DNA", "Vagabond", "Baron", "Obelisk", "Ancient Joker", "Campfire", "Wee Joker", "Hit the Road",
        "The Trio", "The Family", "The Order", "The Tribe", "Stuntman", "Invisible Joker", "Driver's License",
        "Burnt Joker")
LEGENDARY = ("Canio", "Triboulet", "Yorick", "Chicot", "Perkeo")


def card(text, **mods):
    rank = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10}.get(text[0]) or int(text[0])
    suit = {"S": "Spades", "H": "Hearts", "C": "Clubs", "D": "Diamonds"}[text[1]]
    return Card(rank, suit, **mods)


def cards(items):
    return [card(x) if isinstance(x, str) else x for x in items]


def make_run(*jokers, seed=0):
    run = Run(Agent(), seed=seed)
    run.start_ante()
    run.blind = run.make_blind(0)
    for j in jokers:
        run.add_joker(CATALOG[j]() if isinstance(j, str) else j)
    return run


def score(run, played, held=(), estimating=False):
    """Score a hand on the run, counting it first as the run does (bots' estimates don't count)."""
    played = cards(played)
    result = evaluate(played, run.rules)
    if not estimating:
        run.hand_plays[result.name] += 1
        run.round_hand_types[result.name] += 1
    return score_hand(HandContext(run, played, cards(held), result, random.Random(0), estimating=estimating))


def deal(run, hand, pile=()):
    run.hand, run.draw_pile = cards(hand), cards(pile)
    run.discards_left = 9


@pytest.fixture
def tarot(monkeypatch):
    """Vagabond creates a Tarot; the Tarot module may not be written yet."""
    if not any(c.kind == "Tarot" for c in CONSUMABLES.values()):
        class Fool(Consumable):
            name, kind, number = "The Fool", "Tarot", 0
        monkeypatch.setitem(CONSUMABLES, Fool.name, Fool)


class Always:
    """An rng whose every 1-in-n roll succeeds."""

    def random(self):
        return 0.0


# ---- registration and numbers ----------------------------------------------------------------------

def test_every_rare_and_legendary_joker_is_registered_from_the_data():
    for name in RARE + LEGENDARY:
        cls, d = CATALOG[name], JOKER_DATA[name]
        assert (cls.rarity, cls.copyable, cls.eternal_ok) == (d["rarity"], d["blueprint_compatible"], d["eternal_compatible"])
    assert sorted(n for n, c in CATALOG.items() if c.rarity == "Rare") == sorted(RARE + ("The Duo", "Baseball Card", "Blueprint", "Brainstorm"))
    assert not CATALOG["Chicot"].copyable and not CATALOG["Invisible Joker"].copyable
    assert not CATALOG["Invisible Joker"].eternal_ok


@pytest.mark.parametrize("name", LEGENDARY)
def test_legendaries_sell_for_ten_and_come_only_from_the_legendary_pool(name):
    run = make_run()
    assert run.sell_value(CATALOG[name]()) == JOKER_DATA[name]["values"]["sell_value"] == 10
    assert all(pool.random_joker(run, random.Random(s), "Legendary").rarity == "Legendary" for s in range(20))
    run.jokers = [CATALOG[n]() for n in LEGENDARY if n != name]
    assert pool.random_joker(run, random.Random(0), "Legendary").name == name  # no duplicates


def test_an_eternal_legendary_survives_destruction():
    run = make_run("Canio")
    run.jokers[0].eternal = True
    assert not run.remove_joker(run.jokers[0]) and not run.sell_joker(0) and len(run.jokers) == 1


# ---- hand types ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, played, hit", [
    ("The Trio", ["9S", "9H", "9C", "4D", "4S"], True),  # Full House contains Three of a Kind
    ("The Trio", ["9S", "9H", "9C", "9D"], True),
    ("The Trio", ["9S", "9H", "4C", "4D"], False),
    ("The Family", ["9S", "9H", "9C", "9D", "4S"], True),
    ("The Family", ["9S", "9H", "9C", "4D", "4S"], False),
    ("The Order", ["9S", "TH", "JC", "QD", "KS"], True),
    ("The Order", ["9S", "TS", "JS", "QS", "KS"], True),  # a Straight Flush contains a Straight
    ("The Order", ["9S", "TH", "JC", "QD", "AS"], False),
    ("The Tribe", ["2S", "5S", "9S", "JS", "KS"], True),
    ("The Tribe", ["9S", "TS", "JS", "QS", "KS"], True),
    ("The Tribe", ["2S", "5S", "9S", "JS", "KH"], False),
])
def test_hand_type_jokers_multiply_when_the_hand_is_contained(name, played, hit):
    plain, s = score(make_run(), played), score(make_run(name), played)
    factor = JOKER_DATA[name]["values"]["xmult"] if hit else 1
    assert s.chips == plain.chips and s.mult == plain.mult * factor


# ---- scoring-card and held-card jokers ------------------------------------------------------------

def test_baron_multiplies_per_held_king_with_retriggers_and_copies():
    held = [card("KS"), card("KH", seal="Red"), card("KC", debuffed=True), card("KD", enhancement="Stone"), card("QS")]
    assert score(make_run("Baron"), ["2S"], held).mult == pytest.approx(1.5 ** 3)  # Red Seal King counts twice
    assert score(make_run("Blueprint", "Baron"), ["2S"], held).mult == pytest.approx(1.5 ** 6)


def test_triboulet_doubles_each_scoring_king_and_queen_trigger():
    flush = ["KS", "QS", "JS", "9S", "2S"]
    plain = score(make_run(), flush).mult
    assert score(make_run("Triboulet"), flush).mult == plain * 4  # the Jack doesn't count
    two_pair = [card("KS"), card("KH"), card("QS", seal="Red"), card("QH")]
    assert score(make_run("Triboulet"), two_pair).mult == 2 * 2 ** 5
    assert score(make_run("Triboulet", "Brainstorm"), flush).mult == plain * 16


def test_ancient_joker_multiplies_its_suit_including_wild_cards():
    run = make_run("Ancient Joker")
    run.jokers[0].suit = "Hearts"
    assert score(run, ["KH", "KS"]).mult == 2 * 1.5
    assert score(run, [card("KH"), card("KS", enhancement="Wild")]).mult == 2 * 1.5 ** 2
    assert score(run, ["KC", "KS"]).mult == 2


def test_ancient_joker_suit_is_shared_and_changes_every_round():
    run = make_run("Ancient Joker")
    first = run.jokers[0]
    assert first.suit in SUITS
    second = AncientJoker()
    run.add_joker(second)
    seen = set()
    for _ in range(40):
        old = first.suit
        run.end_round()
        assert first.suit == second.suit != old
        seen.add(first.suit)
    assert seen == set(SUITS)


# ---- scaling jokers -----------------------------------------------------------------------------------

def test_obelisk_grows_until_the_most_played_hand_is_played():
    run = make_run("Obelisk")
    obelisk = run.jokers[0]
    pair, high, flush = ["KS", "KH"], ["2S"], ["2S", "5S", "9S", "JS", "KS"]
    score(run, pair)
    assert obelisk.xmult == 1  # Pair 1 play, every other hand 0: strictly the most played
    s = score(run, high)  # High Card ties Pair at 1 play: gains, and the gain counts for this hand
    assert obelisk.xmult == pytest.approx(1.2) and s.mult == pytest.approx(1.2)
    score(run, flush)
    assert obelisk.xmult == pytest.approx(1.4)
    score(run, high, estimating=True)
    assert obelisk.xmult == pytest.approx(1.4)
    score(run, flush)  # Flush 2 plays, the rest 1
    assert obelisk.xmult == 1


def test_an_obelisk_estimate_scores_what_the_live_hand_will():
    run = make_run("Obelisk")
    pair, high, flush = ["KS", "KH"], ["2S"], ["2S", "5S", "9S", "JS", "KS"]
    for hand in (pair, high, high, flush, flush, pair, flush):   # ties, a strict most played, and below it
        guess = score(run, hand, estimating=True).total
        assert score(run, hand).total == guess, hand


def test_blueprint_copies_obelisk_without_scaling_it_twice():
    run = make_run("Blueprint", "Obelisk")
    score(run, ["KS", "KH"])
    s = score(run, ["2S"])
    assert run.jokers[1].xmult == pytest.approx(1.2) and s.mult == pytest.approx(1.2 ** 2)


def test_each_effect_names_the_joker_that_acted_twins_and_copiers_their_own_place():
    # the viewer juices the joker at this place: twins each their own, Blueprint for what it copies (not the copied)
    s = score(make_run("Joker", "Joker", "Blueprint", "Greedy Joker", "Brainstorm"), ["2D"])
    acted = [(src, at) for (src, _, _), at in zip(s.log, s.who) if at is not None]
    assert acted == [("Greedy Joker", 2), ("Greedy Joker", 3), ("Joker", 0), ("Joker", 1), ("Joker", 4)]
    assert s.who[0] is None and s.who[1] is None                 # the hand's level and the card's chips: no joker


def test_campfire_gains_per_card_sold_and_resets_after_a_boss():
    run = make_run("Blueprint", "Campfire", "Joker")
    fire = run.jokers[1]
    run.consumables = [CONSUMABLES["Pluto"]()]
    assert run.sell_joker(2) and run.sell_consumable(0)
    assert fire.xmult == 1.5  # Blueprint copying it adds no gain
    assert score(run, ["2S"]).mult == 1.5 ** 2
    run.end_round()
    assert fire.xmult == 1.5
    run.boss_defeated()
    assert fire.xmult == 1


def test_wee_joker_grows_per_scoring_two_and_blueprint_copies_only_the_chips():
    run = make_run("Blueprint", "Wee Joker")
    wee = run.jokers[1]
    twos = [card("2S", seal="Red"), card("2H")]
    plain = score(make_run(), twos)
    s = score(run, twos)
    assert wee.chips == 3 * 8 and s.chips == plain.chips + 2 * 24  # 3 triggers, counted in this hand
    score(run, ["2S", "2H"], estimating=True)
    score(run, [card("2S", enhancement="Stone")])
    assert wee.chips == 24


def test_hit_the_road_counts_discarded_jacks_for_the_round():
    run = make_run("Blueprint", "Hit the Road")
    road = run.jokers[1]
    deal(run, ["JS", "JH", card("JC", debuffed=True), card("JD", enhancement="Stone"), "QS", "2S"])
    run.discard([0, 1, 2, 3, 4])
    assert road.xmult == 2  # two live Jacks; the copy adds no gain
    assert score(run, ["2S"]).mult == 2 * 2
    run.end_round()
    assert road.xmult == 1


def test_yorick_gains_every_23_cards_discarded_across_rounds():
    run = make_run("Blueprint", "Yorick")
    yorick = run.jokers[1]
    deal(run, [], run.deck * 2)
    run.draw("start")
    for _ in range(4):
        run.discard([0, 1, 2, 3, 4])
    assert yorick.xmult == 1
    run.discard([0, 1, 2])
    assert yorick.xmult == 2 and score(run, ["2S"]).mult == 2 * 2
    run.end_round()
    run.discards_left = 9
    for _ in range(4):
        run.discard([0, 1, 2, 3, 4])
    run.discard([0, 1])
    assert yorick.xmult == 2
    run.discard([0])
    assert yorick.xmult == 3


def test_canio_gains_for_each_destroyed_live_face_card():
    run = make_run("Blueprint", "Canio")
    canio = run.jokers[1]
    run.destroy_cards([card("KS"), card("JH"), card("QC", debuffed=True), card("5D")])
    assert canio.xmult == 3  # the copy adds no gain
    assert score(run, ["2S"]).mult == 3 * 3


def test_canio_counts_shattered_glass_faces_from_the_next_hand():
    run = make_run("Canio")
    glass = card("KS", enhancement="Glass")
    run.add_cards([glass])
    deal(run, [glass, "2H"])
    run.rng["luck"] = Always()
    total = run.play_hand([0])
    assert total == (5 + 10) * 1 * 2 and run.jokers[0].xmult == 2 and glass.uid not in {c.uid for c in run.deck}


def test_canio_with_pareidolia_counts_every_card_but_stone():
    class Pareidolia(Joker):
        name, rules = "Pareidolia", {"pareidolia": True}
    run = make_run("Canio", Pareidolia())
    run.destroy_cards([card("5D"), card("5H", enhancement="Stone")])
    assert run.jokers[0].xmult == 2


# ---- jokers that change the run -------------------------------------------------------------------

def test_dna_copies_a_lone_first_card_into_deck_and_hand_and_it_counts_as_held():
    run = make_run("DNA")
    king = card("KS", enhancement="Steel", seal="Gold", bonus_chips=5)
    run.add_cards([king])
    deal(run, [king, "2H"])
    size = len(run.deck)
    assert run.play_hand([0]) == (5 + 10 + 5) * 1.5  # the Steel copy is held while this hand scores
    twin = run.hand[-1]
    assert len(run.deck) == size + 1 and twin.uid == run.deck[-1].uid != king.uid
    assert (twin.rank, twin.suit, twin.enhancement, twin.seal, twin.bonus_chips) == (13, "Spades", "Steel", "Gold", 5)
    run.play_hand([0])  # second hand of the round
    assert len(run.deck) == size + 1


def test_dna_needs_one_card_and_a_real_play_and_blueprint_doubles_it():
    run = make_run("DNA")
    deal(run, ["KS", "KH", "2C"])
    run.play_hand([0, 1])
    assert len(run.deck) == 52
    run = make_run("DNA")
    score(run, ["KS"], estimating=True)
    assert len(run.deck) == 52
    run = make_run("Blueprint", "DNA")
    deal(run, ["KS", "2H"])
    run.play_hand([0])
    assert len(run.deck) == 54 and len(run.hand) == 3


def test_vagabond_makes_a_tarot_with_four_dollars_or_less(tarot):
    run = make_run("Vagabond")
    run.money = 4
    deal(run, [card("2S", seal="Gold"), "3S"])
    run.play_hand([0])  # the Gold Seal's $3 is paid after the hand
    assert [c.kind for c in run.consumables] == ["Tarot"] and run.money == 7
    score(run, ["3S"])
    assert len(run.consumables) == 1
    run.money = -3
    score(run, ["3S"], estimating=True)
    assert len(run.consumables) == 1
    score(run, ["3S"])
    assert len(run.consumables) == 2


def test_blueprint_copies_vagabond(tarot):
    run = make_run("Blueprint", "Vagabond")
    run.money = 0
    score(run, ["3S"])
    assert [c.kind for c in run.consumables] == ["Tarot", "Tarot"]


def test_stuntman_gives_chips_and_takes_hand_size_which_blueprint_does_not_copy():
    run = make_run("Blueprint", "Stuntman")
    assert run.hand_size == 6
    assert score(run, ["2S"]).chips == score(make_run(), ["2S"]).chips + 2 * 250


def test_drivers_license_needs_sixteen_enhanced_cards():
    run = make_run("Driver's License")
    for c in run.deck[:15]:
        c.enhancement = "Bonus"
    run.deck[15].edition, run.deck[15].seal = "Foil", "Gold"
    assert score(run, ["2S"]).mult == 1
    run.deck[15].enhancement = "Stone"
    assert score(run, ["2S"]).mult == 3


def test_burnt_joker_levels_up_the_first_discard_of_each_round():
    run = make_run("Blueprint", "Burnt Joker")
    deal(run, ["9S", "9H", "4C", "4D", "KS", "2H"])
    run.discard([0, 1, 2, 3])
    assert run.hand_levels["Two Pair"] == 3  # the original and the copy
    run.discard([0, 1])
    assert sum(run.hand_levels.values()) == len(run.hand_levels) + 2


# ---- Invisible Joker -------------------------------------------------------------------------------

def test_invisible_joker_does_nothing_before_two_rounds():
    run = make_run("Invisible Joker", "Joker")
    run.end_round()
    assert run.sell_joker(0) and [j.name for j in run.jokers] == ["Joker"]


def test_invisible_joker_shakes_once_it_is_ready():
    run = make_run("Invisible Joker")
    run.frames = []
    for ready in (False, False, True):
        run.frame("now")
        assert run.frames[-1]["jokers"][0].get("jiggle", False) is ready
        run.end_round()


def test_invisible_joker_copies_scaling_and_stickers_but_not_negative():
    run = make_run("Invisible Joker", "Obelisk")
    obelisk = run.jokers[1]
    obelisk.edition, obelisk.eternal, obelisk.xmult = "Negative", True, 3.0
    run.end_round()
    run.end_round()
    assert run.sell_joker(0)
    twin = run.jokers[1]
    assert twin is not obelisk and twin.name == "Obelisk" and twin.xmult == 3.0
    assert twin.eternal and twin.edition is None
    assert not run.remove_joker(twin) and len(run.jokers) == 2


def test_invisible_joker_needs_room_and_must_not_be_debuffed():
    run = make_run("Invisible Joker", "Joker", "Jolly Joker")
    run.jokers[0].rounds, run.joker_slots = 2, 2
    assert run.sell_joker(0) and len(run.jokers) == 2  # no slot left once it is gone
    run = make_run("Invisible Joker", "Joker")
    run.jokers[0].rounds, run.joker_slots = 2, 2
    assert run.sell_joker(0) and [j.name for j in run.jokers] == ["Joker", "Joker"]
    run = make_run("Invisible Joker", "Joker")
    run.jokers[0].rounds, run.jokers[0].perished = 2, True
    assert run.sell_joker(0) and len(run.jokers) == 1


def test_a_copied_invisible_joker_starts_over():
    run = make_run("Invisible Joker", "Invisible Joker")
    run.jokers[0].rounds = run.jokers[1].rounds = 5
    assert run.sell_joker(0)
    assert [j.rounds for j in run.jokers] == [5, 0]


# ---- Chicot, Perkeo -----------------------------------------------------------------------------------

def boss_run(*jokers):
    run = make_run(*jokers)
    run.ante = 2
    run.ante_boss = make(BOSSES, Boss, "The Wall")
    run.blind = run.make_blind(2)
    return run


def test_chicot_disables_the_boss_when_selected_and_the_wall_drops_to_2x():
    run = boss_run("Chicot")
    base = run.ante_table[2]
    assert run.blind.chips == 4 * base
    run.play_round()
    assert run.ante_boss.disabled and run.blind.chips == 2 * base


def test_chicot_ignores_small_blinds_and_cannot_be_copied():
    run = make_run("Blueprint", "Chicot")
    run.jokers[1].on_blind_select(run, run.blind)
    assert run.blind.chips == run.make_blind(0).chips and run.jokers[0].target(run) is None


def test_chicot_obtained_mid_boss_disables_it_at_once_but_not_after_the_round():
    run = boss_run()
    run.hands_left, run.round_score = 3, 0
    run.add_joker(CATALOG["Chicot"]())
    assert run.ante_boss.disabled
    run = boss_run()
    run.hands_left, run.round_score = 2, run.blind.chips  # boss beaten, now in the shop
    run.add_joker(CATALOG["Chicot"]())
    assert not run.ante_boss.disabled


def test_perkeo_makes_a_negative_copy_when_leaving_the_shop():
    run = make_run("Perkeo")
    mars = CONSUMABLES["Mars"]()
    mars.extra_sell = 2
    run.consumables = [mars, CONSUMABLES["Mars"]()]  # slots full: the Negative copy still fits
    run.shop()
    assert len(run.consumables) == 3 and [c.edition for c in run.consumables] == [None, None, "Negative"]
    twin = run.consumables[2]
    assert twin.name == "Mars" and all(twin is not c for c in run.consumables[:2])


def test_perkeo_keeps_extra_sell_value_and_blueprint_makes_another():
    run = make_run("Blueprint", "Perkeo")
    mars = CONSUMABLES["Mars"]()
    mars.extra_sell = 2
    run.consumables = [mars]
    run.shop()
    assert [c.edition for c in run.consumables] == [None, "Negative", "Negative"]
    assert all(c.extra_sell == 2 for c in run.consumables)
    assert run.sell_value(run.consumables[1]) == (3 + 5) // 2 + 2
    run = make_run("Perkeo")
    run.shop()
    assert run.consumables == []


# ---- whole runs ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("names", [
    ("Obelisk", "Campfire", "Yorick", "Perkeo", "Ancient Joker", "Hit the Road", "Invisible Joker", "Burnt Joker"),
    ("Baron", "Triboulet", "DNA", "Vagabond", "Wee Joker", "Stuntman", "Driver's License", "The Trio", "Canio",
     "Chicot", "Blueprint", "The Tribe"),
])
def test_runs_play_through_with_these_jokers(names):
    run = Run(GreedyBot(), seed=4, max_ante=3)
    for name in names:
        run.add_joker(CATALOG[name]())
    result = run.play()
    assert result.blinds_beaten >= 3
