import random

import pytest

from balatro.agent import Agent
from balatro.bots import GreedyBot, estimate
from balatro.cards import Card
from balatro.content import jokers_common
from balatro.content.jokers_common import SECRET_HANDS
from balatro.hands import HAND_ORDER, evaluate
from balatro.jokers import CATALOG, JOKER_DATA, Joker
from balatro.run import Run
from balatro.scoring import HandContext, score_hand
from balatro.shop import PACKS, Offer, Shop

RANK = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10}


def card(text, **mods):
    rank = RANK.get(text[0]) or int(text[0])
    suit = {"S": "Spades", "H": "Hearts", "C": "Clubs", "D": "Diamonds"}[text[1]]
    return Card(rank, suit, **mods)


def cards(text):
    return [card(t) for t in text.split()]


def make_run(*jokers, seed=0, agent=None):
    run = Run(agent or Agent(), seed=seed)
    run.start_ante()
    run.blind = run.make_blind(0)
    run.jokers = [CATALOG[j]() if isinstance(j, str) else j for j in jokers]
    return run


def score(run, played, held=(), rng=None, estimating=False):
    played = cards(played) if isinstance(played, str) else played
    held = cards(held) if isinstance(held, str) else list(held)
    ctx = HandContext(run, played, held, evaluate(played, run.rules), rng or random.Random(0), estimating=estimating)
    return score_hand(ctx)


def effects(s, name):
    """What `name` (or a copy of it) added to a score: (kind, amount) per log entry."""
    return [(kind, amount) for source, kind, amount in s.log if source == name]


class Fixed:
    """An rng whose every roll is `value`: 0 hits any 1-in-N chance, 0.99 misses them all."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


class Oops(Joker):
    name = "Oops! All 6s"


class Pareidolia(Joker):
    name = "Pareidolia"
    rules = {"pareidolia": True}


def recorder(monkeypatch, run):
    made = []
    monkeypatch.setattr(run, "create_consumable", lambda kind=None, name=None, edition=None, source=None: made.append(kind))
    return made


# ---- the catalog and its numbers --------------------------------------------------------------------

COMMON = {n for n, d in JOKER_DATA.items() if d["rarity"] == "Common"}
MINE = {n for n, c in CATALOG.items() if c.__module__ == jokers_common.__name__}


def test_every_common_joker_has_a_class():
    assert len(MINE) == 57 and MINE | {"Joker", "Greedy Joker", "Jolly Joker", "Hanging Chad"} == COMMON


@pytest.mark.parametrize("name", sorted(n for n in MINE if issubclass(CATALOG[n], jokers_common.HandTypeJoker)))
def test_hand_type_numbers_match_the_data(name):
    cls, v = CATALOG[name], JOKER_DATA[name]["values"]
    assert (cls.hand_type, cls.chips, cls.mult) == (v["hand_type"], v.get("chips", 0), v.get("mult", 0))


@pytest.mark.parametrize("name", sorted(n for n in MINE if issubclass(CATALOG[n], jokers_common.RankJoker)))
def test_rank_numbers_match_the_data(name):
    cls, v = CATALOG[name], JOKER_DATA[name]["values"]
    ranks = {RANK.get(r) or int(r) for r in v.get("ranks", [v.get("rank")])}
    assert (cls.ranks, cls.chips, cls.mult) == (ranks, v.get("chips_per_card", 0), v.get("mult_per_card", 0))


# ---- hand types -------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, hits, misses", [
    ("Zany Joker", "5S 5H 5C 9D 9S", "5S 5H 9D 9S"),
    ("Mad Joker", "3S 3H 3C 4D 4S", "4S 4H 4C 4D"),  # Four of a Kind doesn't contain Two Pair
    ("Crazy Joker", "2S 3H 4C 5D 6S", "2H 4H 6H 8H TH"),
    ("Droll Joker", "2H 4H 6H 8H TH", "2S 3H 4C 5D 6S"),
    ("Sly Joker", "KS KH KC", "KS QH"),
    ("Wily Joker", "5S 5H 5C 5D", "5S 5H 6C 6D"),
    ("Clever Joker", "3S 3H 4C 4D", "4S 4H 4C 4D"),
    ("Devious Joker", "AS 2H 3C 4D 5S", "2S 3H 4C 5D 7S"),
    ("Crafty Joker", "2H 2H 2H 8H 8H", "2H 4H 6H 8H TS"),  # a Flush House contains a Flush
])
def test_hand_type_jokers_check_what_the_hand_contains(name, hits, misses):
    v = JOKER_DATA[name]["values"]
    expected = [("+chips", v["chips"])] if "chips" in v else [("+mult", v["mult"])]
    run = make_run(name)
    assert effects(score(run, hits), name) == expected
    assert effects(score(run, misses), name) == []


# ---- per scoring card -------------------------------------------------------------------------------

@pytest.mark.parametrize("name, played, expected", [
    ("Lusty Joker", "KH KS", [("+mult", 3)]),
    ("Wrathful Joker", "KH KS", [("+mult", 3)]),
    ("Gluttonous Joker", "KH KC 2C", [("+mult", 3)]),  # the 2 doesn't score
    ("Even Steven", "TS TH QS", [("+mult", 4)] * 2),
    ("Even Steven", "QS QH", []),
    ("Odd Todd", "AS AH", [("+chips", 31)] * 2),
    ("Odd Todd", "8S 8H", []),
    ("Scholar", "AS AH", [("+chips", 20), ("+mult", 4)] * 2),
    ("Walkie Talkie", "4S 4H TC", [("+chips", 10), ("+mult", 4)] * 2),
    ("Scary Face", "KS KH", [("+chips", 30)] * 2),
    ("Smiley Face", "JS JH 2C", [("+mult", 5)] * 2),
    ("Smiley Face", "AS AH", []),
])
def test_per_card_jokers(name, played, expected):
    assert effects(score(make_run(name), played), name) == expected


def test_per_card_jokers_count_wild_cards_and_skip_stone_and_debuffed_ones():
    run = make_run("Lusty Joker", "Odd Todd", "Smiley Face")
    played = [card("AS", enhancement="Wild"), card("AD"), card("KH", debuffed=True), card("KS"),
              card("3C", enhancement="Stone")]
    s = score(run, played)
    assert effects(s, "Lusty Joker") == [("+mult", 3)]  # only the Wild Ace
    assert effects(s, "Odd Todd") == [("+chips", 31)] * 2  # the Stone card has no rank
    assert effects(s, "Smiley Face") == [("+mult", 5)]  # the debuffed King doesn't score


def test_retriggers_fire_per_card_jokers_again():
    s = score(make_run("Hanging Chad", "Scholar"), "AS AH")
    assert effects(s, "Scholar").count(("+mult", 4)) == 4


def test_pareidolia_makes_every_card_a_face():
    run = make_run(Pareidolia(), "Scary Face", "Smiley Face")
    s = score(run, "2S 2H")
    assert len(effects(s, "Scary Face")) == len(effects(s, "Smiley Face")) == 2


def test_photograph_doubles_the_first_scoring_face_card_each_time_it_scores():
    run = make_run("Photograph")
    s = score(run, "2S KS KH")
    assert effects(s, "Photograph") == [("xmult", 2)] and s.mult == 2 * 2
    assert effects(score(run, [card("KS", debuffed=True), card("KH")]), "Photograph") == [("xmult", 2)]
    run.jokers.insert(0, CATALOG["Hanging Chad"]())
    assert effects(score(run, "KS KH"), "Photograph") == [("xmult", 2)] * 3
    run.jokers = [Pareidolia(), CATALOG["Photograph"]()]
    assert effects(score(run, "2S 2H"), "Photograph") == [("xmult", 2)]


def test_golden_ticket_pays_per_scoring_gold_card_and_needs_one_in_the_deck():
    run = make_run("Golden Ticket")
    assert not CATALOG["Golden Ticket"].can_spawn(run)
    run.deck[0].enhancement = "Gold"
    assert CATALOG["Golden Ticket"].can_spawn(run)
    played = [card("KS", enhancement="Gold"), card("KH", enhancement="Gold", seal="Red"), card("2C", enhancement="Gold")]
    assert score(run, played).money == 4 * 3  # KS once, KH twice; the 2 doesn't score


@pytest.mark.parametrize("seed", range(6))
def test_business_card_rolls_1_in_2_per_scoring_face_card(seed):
    s = score(make_run("Business Card"), "KS KH 2C", rng=random.Random(seed))
    mirror = random.Random(seed)
    assert s.money == 2 * sum(mirror.random() * 2 < 1 for _ in range(2))


def test_eight_ball_makes_tarots_for_real_hands_only(monkeypatch):
    run = make_run("8 Ball")
    made = recorder(monkeypatch, run)
    score(run, "8S 8H", rng=Fixed(0.0))
    assert made == ["Tarot", "Tarot"]
    score(run, "8S 8H", rng=Fixed(0.0), estimating=True)
    score(run, "8S 8H", rng=Fixed(0.3))  # 0.3 x 4 >= 1: a miss
    score(run, [card("8S", enhancement="Stone")], rng=Fixed(0.0))
    assert len(made) == 2
    run.jokers.append(Oops())  # 2 in 4
    score(run, "8S 8H", rng=Fixed(0.3))
    assert len(made) == 4
    run.jokers = [CATALOG["Blueprint"](), CATALOG["8 Ball"]()]  # a copy makes them too
    score(run, "8S 8H", rng=Fixed(0.0))
    assert len(made) == 8


# ---- held in hand -----------------------------------------------------------------------------------

@pytest.mark.parametrize("held, mult", [("5S 3H 3C KD", 6), ("KS", 20), ("AS", 22), ("TS JS", 20)])
def test_raised_fist_doubles_the_lowest_held_card(held, mult):
    assert effects(score(make_run("Raised Fist"), "9S", held), "Raised Fist") == [("+mult", mult)]


def test_raised_fist_picks_the_rightmost_lowest_card_skips_stones_and_never_falls_back():
    run = make_run("Raised Fist")
    left, right = card("3H"), card("3C", seal="Red")
    assert effects(score(run, "9S", [card("5S"), left, right]), "Raised Fist") == [("+mult", 6)] * 2
    right.debuffed = True
    assert effects(score(run, "9S", [card("5S"), left, right]), "Raised Fist") == []
    assert effects(score(run, "9S", [card("2S", enhancement="Stone"), card("9H")]), "Raised Fist") == [("+mult", 18)]


def test_shoot_the_moon_counts_each_held_queen_trigger():
    run = make_run("Shoot the Moon")
    held = [card("QS"), card("QH", seal="Red"), card("QD", debuffed=True), card("QC", enhancement="Stone"), card("KS")]
    assert effects(score(run, "2S", held), "Shoot the Moon") == [("+mult", 13)] * 3


@pytest.mark.parametrize("seed", range(6))
def test_reserved_parking_rolls_1_in_2_per_held_face_card(seed):
    s = score(make_run("Reserved Parking"), "2S", "KS QH 5C JD", rng=random.Random(seed))
    mirror = random.Random(seed)
    assert s.money == sum(mirror.random() * 2 < 1 for _ in range(3))


def test_oops_all_6s_doubles_reserved_parking():
    run = make_run("Reserved Parking")
    assert score(run, "2S", "KS QH", rng=Fixed(0.7)).money == 0
    run.jokers.append(Oops())
    assert score(run, "2S", "KS QH", rng=Fixed(0.7)).money == 2


# ---- independent ------------------------------------------------------------------------------------

def test_half_joker_counts_played_cards_not_scoring_ones():
    run = make_run("Half Joker")
    assert effects(score(run, "KS KH 2C"), "Half Joker") == [("+mult", 20)]
    assert effects(score(run, "KS KH 2C 3D"), "Half Joker") == []


def test_banner_and_mystic_summit_read_the_discards_left():
    run = make_run("Banner", "Mystic Summit")
    run.discards_left = 2
    s = score(run, "KS")
    assert effects(s, "Banner") == [("+chips", 60)] and effects(s, "Mystic Summit") == []
    run.discards_left = 0
    s = score(run, "KS")
    assert effects(s, "Banner") == [] and effects(s, "Mystic Summit") == [("+mult", 15)]


def test_misprint_adds_0_to_23_mult():
    run = make_run("Misprint")
    values = []
    for seed in range(300):
        values.append(score(run, "KS", rng=random.Random(seed)).mult - 1)
        assert values[-1] == random.Random(seed).randint(0, 23)
    assert set(values) == set(range(24))


def test_abstract_joker_counts_every_joker_including_debuffed_ones():
    run = make_run("Abstract Joker", "Joker", "Egg")
    run.jokers[2].perished = True
    assert effects(score(run, "KS"), "Abstract Joker") == [("+mult", 9)]


def test_blue_joker_counts_the_draw_pile():
    run = make_run("Blue Joker")
    run.draw_pile = run.deck[:44]
    assert effects(score(run, "KS"), "Blue Joker") == [("+chips", 88)]


def test_fortune_teller_counts_tarots_used_this_run():
    run = make_run("Fortune Teller")
    assert effects(score(run, "KS"), "Fortune Teller") == []
    run.consumables_used["Tarot"] += 5
    run.consumables_used["Planet"] += 3
    assert effects(score(run, "KS"), "Fortune Teller") == [("+mult", 5)]


def test_swashbuckler_adds_the_other_jokers_sell_values():
    egg = CATALOG["Egg"]()
    egg.extra_sell = 3
    run = make_run("Swashbuckler", "Joker", "Greedy Joker", egg)
    assert effects(score(run, "KS"), "Swashbuckler") == [("+mult", 1 + 2 + 5)]
    run.jokers.insert(0, CATALOG["Blueprint"]())  # sells for $5; the copy also leaves Swashbuckler out
    assert effects(score(run, "KS"), "Swashbuckler") == [("+mult", 5 + 8)] * 2


def test_supernova_counts_the_hand_being_played_and_estimated():
    run = make_run("Supernova")
    run.hand = cards("KS KH QC QD 5S 7H")
    assert run.play_hand([0, 1]) == 30 * (2 + 1)  # first Pair of the run
    assert run.play_hand([0, 1]) == 30 * (2 + 2)
    assert estimate(run, cards("JS JH"), []) == 30 * (2 + 3)
    assert run.hand_plays["Pair"] == 2


def test_superposition_needs_a_straight_and_a_scoring_ace(monkeypatch):
    run = make_run("Superposition")
    made = recorder(monkeypatch, run)
    score(run, "AS 2H 3C 4D 5S")
    score(run, "AS 2H 3C 4D 5S", estimating=True)
    score(run, "2S 3H 4C 5D 6S")
    score(run, "AS AH 3C 4D 5S")
    assert made == ["Tarot"]


# ---- Gros Michel, Cavendish, Ice Cream, Popcorn -------------------------------------------------------

def test_gros_michel_goes_extinct_and_lets_cavendish_appear():
    run = make_run("Gros Michel", "Joker")
    gros = run.jokers[0]
    assert effects(score(run, "KS"), "Gros Michel") == [("+mult", 15)]
    assert CATALOG["Gros Michel"].can_spawn(run) and not CATALOG["Cavendish"].can_spawn(run)
    run.rng["misc"] = Fixed(0.2)  # 0.2 x 6 >= 1: survives
    gros.end_of_round(run, run.blind)
    assert gros in run.jokers
    run.rng["misc"] = Fixed(0.1)
    gros.end_of_round(run, run.blind)
    assert gros not in run.jokers and run.extinct == {"Gros Michel"}
    assert not CATALOG["Gros Michel"].can_spawn(run) and CATALOG["Cavendish"].can_spawn(run)


def test_selling_gros_michel_is_not_extinction():
    run = make_run("Gros Michel")
    assert run.sell_joker(0) and not run.extinct


@pytest.mark.parametrize("oops, odds", [(False, 1 / 6), (True, 2 / 6)])
def test_gros_michel_dies_1_in_6_rounds(oops, odds):
    run = make_run(*([Oops()] if oops else []))
    run.rng["misc"] = random.Random(5)
    died = 0
    for _ in range(3000):
        gros = CATALOG["Gros Michel"]()
        run.jokers.append(gros)
        gros.end_of_round(run, run.blind)
        if gros not in run.jokers:
            died += 1
        else:
            run.jokers.remove(gros)
    assert abs(died / 3000 - odds) < 0.025


def test_cavendish_triples_mult_and_rarely_dies_without_ending_its_line():
    run = make_run("Cavendish")
    cav = run.jokers[0]
    assert effects(score(run, "KS"), "Cavendish") == [("xmult", 3)]
    run.rng["misc"] = Fixed(0.002)
    cav.end_of_round(run, run.blind)
    assert cav in run.jokers
    run.rng["misc"] = Fixed(0.0009)
    cav.end_of_round(run, run.blind)
    assert run.jokers == [] and not run.extinct


def test_ice_cream_melts_5_chips_a_hand_and_is_gone_after_the_20th():
    run = make_run("Ice Cream")
    ice = run.jokers[0]
    for i in range(20):
        chips = 100 - 5 * i
        assert ice.chips == chips and ice in run.jokers
        run.hand = cards("KS 2H")
        assert run.play_hand([0]) == 5 + 10 + chips
    assert ice not in run.jokers


def test_ice_cream_copied_by_blueprint_melts_once():
    run = make_run("Blueprint", "Ice Cream")
    run.hand = cards("KS")
    assert run.play_hand([0]) == 5 + 10 + 100 + 100
    assert run.jokers[1].chips == 95
    score(run, "KS", estimating=True)
    assert run.jokers[1].chips == 95


def test_popcorn_loses_4_mult_a_round_and_is_gone_after_the_5th():
    run = make_run("Popcorn")
    pop = run.jokers[0]
    for mult in (20, 16, 12, 8, 4):
        assert effects(score(run, "KS"), "Popcorn") == [("+mult", mult)]
        run.end_round()
    assert pop not in run.jokers


# ---- scaling ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, played, start, grown", [
    ("Ride the Bus", "2S 2H", 3, 4), ("Ride the Bus", "KS KH", 3, 0),
    ("Runner", "2S 3H 4C 5D 6S", 15, 30), ("Runner", "2S 2H", 15, 15),
    ("Square Joker", "2S 2H 3C 4D", 8, 12), ("Square Joker", "2S 2H", 8, 8),
    ("Green Joker", "2S", 2, 3),
])
def test_scaling_jokers_grow_before_scoring_once_and_estimates_see_it_without_keeping_it(name, played, start, grown):
    run = make_run("Blueprint", name)
    j = run.jokers[1]
    j.value = start
    s = score(run, played, estimating=True)
    assert j.value == start and sum(a for _, a in effects(s, name)) == 2 * grown
    s = score(run, played)
    assert j.value == grown and sum(a for _, a in effects(s, name)) == 2 * grown


def test_ride_the_bus_resets_only_on_a_scoring_face_card():
    run = make_run("Ride the Bus")
    bus = run.jokers[0]
    assert effects(score(run, "2S 2H"), "Ride the Bus") == [("+mult", 1)]
    score(run, "2S 2H KS")  # the King doesn't score
    assert bus.value == 2
    score(run, [card("KS", debuffed=True), card("KH", debuffed=True)])  # debuffed faces aren't faces
    assert bus.value == 3
    score(run, "KS KH")
    assert bus.value == 0
    run.jokers.insert(0, Pareidolia())
    score(run, "2S")
    score(run, "2S")
    assert bus.value == 0


def test_green_joker_loses_one_per_discard_never_below_zero():
    run = make_run("Blueprint", "Green Joker")
    green = run.jokers[1]
    score(run, "KS")
    score(run, "KS")
    run.hand = cards("2S 3S 4S 5S")
    run.discard([0, 1])  # once per discard, not per card; the copy takes nothing
    assert green.value == 1
    run.discard([0])
    run.discard([0])
    assert green.value == 0


def test_red_card_grows_3_per_skipped_pack_but_not_per_copy():
    run = make_run("Blueprint", "Red Card")
    red = run.jokers[1]
    run.open_pack(PACKS["Buffoon Pack"])  # the default agent skips
    run.open_pack(PACKS["Buffoon Pack"])
    assert red.mult == 6
    assert effects(score(run, "KS"), "Red Card") == [("+mult", 6)] * 2


def test_red_card_ignores_packs_that_were_picked_from():
    class Picker(Agent):
        def pack_action(self, run, pack):
            return ("pick", 0, [])
    run = make_run("Red Card", agent=Picker())
    run.open_pack(PACKS["Buffoon Pack"])
    assert run.jokers[0].mult == 0


# ---- discards, money, targets ------------------------------------------------------------------------

def test_faceless_joker_pays_5_for_3_face_cards_in_one_discard():
    run = make_run("Blueprint", "Faceless Joker")
    run.money = 0
    run.hand = cards("KS QH JD 2C 3C")
    run.discard([0, 1, 2])
    assert run.money == 10  # the copy pays too
    run.hand = [card("KS"), card("QH"), card("JD", debuffed=True), card("2C")]
    run.discard([0, 1, 2, 3])
    assert run.money == 10


def test_mail_in_rebate_pays_5_per_discarded_card_of_its_rank():
    run = make_run("Blueprint", "Mail-In Rebate")
    run.jokers[1].rank = 5
    run.money = 0
    run.hand = [card("5S"), card("5H"), card("5C", debuffed=True), card("5D", enhancement="Stone"), card("KS")]
    run.discard([0, 1, 2, 3, 4])
    assert run.money == 2 * 10


def test_mail_in_rebate_rolls_its_rank_from_the_deck():
    run = make_run()
    run.deck = [card("7S"), card("7H"), card("2C", enhancement="Stone")]
    mail = CATALOG["Mail-In Rebate"]()
    run.add_joker(mail)
    assert mail.rank == 7
    run.deck = [card("2C", enhancement="Stone")]
    mail.end_of_round(run, run.blind)
    assert mail.rank == 14


def test_to_do_list_pays_on_its_exact_hand_including_copies():
    run = make_run("Blueprint", "To Do List")
    run.jokers[1].target = "Pair"
    run.money = 0
    score(run, "KS KH", estimating=True)
    assert run.money == 0
    score(run, "KS KH")
    assert run.money == 8
    score(run, "KS KH KC")  # contains a Pair, but is a Three of a Kind
    assert run.money == 8


def test_to_do_list_rolls_a_new_visible_hand_each_round():
    run = make_run()
    todo = CATALOG["To Do List"]()
    run.add_joker(todo)
    assert todo.target in HAND_ORDER and todo.target not in SECRET_HANDS
    seen = set()
    for _ in range(200):
        old = todo.target
        todo.end_of_round(run, run.blind)
        assert todo.target != old
        seen.add(todo.target)
    assert seen == set(HAND_ORDER) - SECRET_HANDS
    run.hand_plays["Flush Five"] = 1
    for _ in range(200):
        todo.end_of_round(run, run.blind)
        seen.add(todo.target)
    assert "Flush Five" in seen


def test_end_of_round_money_and_sell_value():
    run = make_run("Delayed Gratification", "Golden Joker", "Egg")
    egg = run.jokers[2]
    run.money, run.hands_left, run.discards_left, run.discards_used = 0, 0, 3, 0
    run.end_round()
    assert run.money == 3 + 4 + 2 * 3  # Small Blind, Golden Joker, $2 per unused discard
    assert egg.extra_sell == 3 and run.sell_value(egg) == 2 + 3
    run.money, run.discards_left, run.discards_used = 0, 2, 1
    run.end_round()
    assert run.money == 3 + 4
    assert run.sell_value(egg) == 2 + 6


def test_credit_card_allows_20_dollars_of_debt():
    run = make_run("Credit Card")
    run.money = 0
    assert run.debt_limit == -20 and Shop(run).reroll() and run.money == -5


# ---- creating things --------------------------------------------------------------------------------

def test_riff_raff_makes_up_to_two_commons_in_free_slots():
    run = make_run("Riff-Raff")
    riff = run.jokers[0]
    riff.on_blind_select(run, run.blind)
    assert len(run.jokers) == 3
    assert all(j.rarity == "Common" and not (j.eternal or j.perishable or j.rental) for j in run.jokers)
    run.jokers = [riff] + [CATALOG["Joker"]() for _ in range(3)]
    riff.on_blind_select(run, run.blind)
    assert len(run.jokers) == 5
    riff.on_blind_select(run, run.blind)
    assert len(run.jokers) == 5


def test_riff_raff_copies_make_jokers_too():
    run = make_run("Blueprint", "Riff-Raff")
    for j in list(run.active_jokers()):
        j.on_blind_select(run, run.blind)
    assert len(run.jokers) == 5  # the copy fills 2 slots, Riff-Raff the last one


@pytest.mark.parametrize("copies", [1, 2])
def test_hallucination_rolls_1_in_2_per_pack_opened(monkeypatch, copies):
    run = make_run(*(["Blueprint"] * (copies - 1)), "Hallucination")
    made = recorder(monkeypatch, run)
    mirror = random.Random()
    mirror.setstate(run.rng["misc"].getstate())
    for _ in range(20):
        run.open_pack(PACKS["Buffoon Pack"])
    hits = sum(mirror.random() * 2 < 1 for _ in range(20 * copies))
    assert made == ["Tarot"] * hits and 0 < hits < 20 * copies


# ---- passives ---------------------------------------------------------------------------------------

def test_chaos_the_clown_gives_one_free_reroll_per_shop():
    run = make_run("Chaos the Clown")
    run.money = 10
    shop = Shop(run)
    assert shop.reroll_cost == 0 and shop.reroll() and run.money == 10
    assert shop.reroll_cost == 5


def test_chaos_bought_mid_shop_frees_a_reroll_at_once_and_selling_it_takes_that_back():
    run = make_run()
    run.money = 20
    shop = run.current_shop = Shop(run)
    shop.cards = [Offer("Joker", CATALOG["Chaos the Clown"]())]
    assert shop.buy("card", 0) and shop.reroll_cost == 0
    assert run.sell_joker(0) and shop.reroll_cost == 5


def test_splash_scores_every_played_card():
    run = make_run("Splash")
    assert run.rules.splash and score(run, "KS KH 2C").chips == 10 + 10 + 10 + 2


def test_juggler_and_drunkard():
    run = make_run("Juggler", "Drunkard")
    assert run.hand_size == 9
    run.play_round()  # the default agent never discards
    assert run.discards_left == 4


def test_drunkard_changes_the_current_discards_when_added_or_sold():
    run = make_run()
    run.discards_left = 2
    run.add_joker(CATALOG["Drunkard"]())
    assert run.discards_left == 3
    assert run.sell_joker(0) and run.discards_left == 2


# ---- in a real run ----------------------------------------------------------------------------------

@pytest.mark.parametrize("batch", range(12))
def test_runs_with_common_jokers_play_through(batch):
    names = sorted(MINE)[batch * 5:batch * 5 + 5]
    run = Run(GreedyBot(), seed=batch, max_ante=2)
    for n in names:
        run.add_joker(CATALOG[n]())
    run.play()
    assert run.hands_played > 0 and not run.copying
