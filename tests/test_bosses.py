import dataclasses

import pytest

from balatro.agent import Agent
from balatro.bots import GreedyBot, estimate
from balatro.cards import Card
from balatro.items import BOSSES, CONSUMABLES, entries
from balatro.jokers import CATALOG, Joker
from balatro.run import Run


class Script(Agent):
    """Takes the given round actions in order, then plays the first card; records what it saw each time."""

    def __init__(self, *actions):
        self.actions = list(actions)
        self.seen = []

    def round_action(self, run):
        self.seen.append({"hand": [dataclasses.replace(c) for c in run.hand],
                          "pile": [dataclasses.replace(c) for c in run.draw_pile],
                          "hand_size": run.hand_size, "hands": run.hands_left, "discards": run.discards_left,
                          "money": run.money, "jokers": [(j.name, j.disabled) for j in run.jokers],
                          "forced": run.active_boss.forced_selection(run) if run.active_boss else None})
        if self.actions:
            action = self.actions.pop(0)
            return action(run) if callable(action) else action
        return ("play", [0])


class Seller(Joker):
    """Disables the boss when sold, like Luchador."""
    name = "Seller"

    def on_sold(self, run):
        run.disable_boss()


class Plain(Joker):
    def __init__(self, name):
        super().__init__()
        self.name = name


class Rules(Joker):
    def __init__(self, **rules):
        super().__init__()
        self.rules = rules


class DiscardCounter(Joker):
    name = "Discard Counter"

    def __init__(self):
        super().__init__()
        self.seen = []

    def on_discard(self, run, cards, first):
        self.seen.append((len(cards), first))


def boss_run(name, agent=None, seed=0, jokers=()):
    """A run at the boss's minimum ante with `name` as the ante's boss and its blind up."""
    run = Run(agent or Agent(), seed=seed, record=True)
    run.ante = max(1, BOSSES[name].min_ante)
    run.start_ante()
    run.ante_boss = BOSSES[name]()
    run.blind = run.make_blind(2)
    run.jokers = list(jokers)
    return run


def cards(run, text):
    """Cards from the run's deck by label, e.g. "KC KH 5S"."""
    out = []
    for label in text.split():
        rank = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10}.get(label[0]) or int(label[0])
        suit = {"S": "Spades", "H": "Hearts", "C": "Clubs", "D": "Diamonds"}[label[1]]
        out.append(next(c for c in run.deck if c.rank == rank and c.suit == suit and c not in out))
    return out


def deal(run, hand, pile=()):
    """Mid-round state with a known hand, as if the boss's round had started."""
    run.hand, run.draw_pile = list(hand), list(pile)
    run.hands_left, run.discards_left, run.round_score = 4, 3, 0
    run.refresh_debuffs()


def new_cards(before, after):
    old = {c.uid for c in before}
    return [c for c in after if c.uid not in old]


# ---- data -----------------------------------------------------------------------------------------

def test_every_boss_has_code_and_the_data_numbers():
    assert set(BOSSES) == {b["name"] for b in entries("boss")}
    assert [BOSSES[n].chip_mult for n in ("The Wall", "The Needle", "Violet Vessel", "The Hook")] == [4, 1, 6, 2]
    assert BOSSES["Cerulean Bell"].showdown and BOSSES["Cerulean Bell"].reward == 8
    assert BOSSES["The Ox"].min_ante == 6 and BOSSES["The Hook"].reward == 5


@pytest.mark.parametrize("name, mult, disabled", [("The Wall", 4, 2), ("Violet Vessel", 6, 2), ("The Needle", 1, 1),
                                                  ("The Club", 2, 2)])
def test_requirement_and_disabled_requirement(name, mult, disabled):
    run = boss_run(name)
    base = run.ante_table[run.ante]
    assert run.blind.chips == int(base * mult)
    run.disable_boss()
    assert run.blind.chips == int(base * disabled) and run.active_boss is None


# ---- debuffs --------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, suit", [("The Club", "Clubs"), ("The Goad", "Spades"), ("The Window", "Diamonds"),
                                        ("The Head", "Hearts")])
def test_suit_bosses_debuff_their_suit_in_hand_and_deck(name, suit):
    agent = Script()
    boss_run(name, agent).play_round()
    seen = agent.seen[0]
    assert all(c.debuffed == (c.suit == suit) for c in seen["hand"] + seen["pile"])


def test_suit_debuffs_follow_wild_stone_and_smeared():
    run = boss_run("The Club")
    club = run.active_boss
    assert club.debuffs(run, Card(5, "Hearts", enhancement="Wild"))
    assert not club.debuffs(run, Card(5, "Clubs", enhancement="Stone"))
    assert not club.debuffs(run, Card(5, "Spades"))
    run.jokers = [Rules(smeared=True)]
    assert club.debuffs(run, Card(5, "Spades")) and not club.debuffs(run, Card(5, "Hearts"))


def test_debuffed_cards_score_nothing_and_trigger_the_boss_for_that_hand_only():
    run = boss_run("The Club")
    deal(run, cards(run, "KC KH 5S 5H"))
    assert run.play_hand([0, 1]) == (10 + 10) * 2  # the King of Clubs adds nothing
    assert run.blind.boss.triggered
    assert run.play_hand([0, 1]) == (10 + 5 + 5) * 2
    assert not run.blind.boss.triggered


def test_the_plant_debuffs_face_cards_and_pareidolia_makes_everything_a_face():
    agent = Script()
    boss_run("The Plant", agent).play_round()
    assert all(c.debuffed == (c.rank in (11, 12, 13)) for c in agent.seen[0]["hand"] + agent.seen[0]["pile"])
    run = boss_run("The Plant", jokers=[Rules(pareidolia=True)])
    assert run.active_boss.debuffs(run, Card(2, "Spades"))
    assert not run.active_boss.debuffs(run, Card(2, "Spades", enhancement="Stone"))


def test_the_pillar_debuffs_cards_played_earlier_in_the_ante():
    agent = Script(("play", [0, 1, 2]))
    run = Run(agent, seed=3)
    run.start_ante()
    run.blind = run.make_blind(0)
    run.play_round()
    played = set(run.played_this_ante)
    assert len(played) >= 3
    run.ante_boss = BOSSES["The Pillar"]()
    run.blind = run.make_blind(2)
    agent.seen = []
    run.play_round()
    seen = agent.seen[0]["hand"] + agent.seen[0]["pile"]
    assert len(seen) == 52 and all(c.debuffed == (c.uid in played) for c in seen)
    assert any(c.debuffed for c in seen)


def test_verdant_leaf_debuffs_everything_until_a_joker_is_sold():
    agent = Script(("sell_consumable", 0), ("sell_joker", 0))
    run = boss_run("Verdant Leaf", agent, jokers=[Plain("A")])
    run.consumables = [CONSUMABLES["Pluto"]()]
    run.play_round()
    first, after_consumable, after_joker = agent.seen[:3]
    assert all(c.debuffed for c in first["hand"] + first["pile"])
    assert all(c.debuffed for c in after_consumable["hand"])
    assert not any(c.debuffed for c in after_joker["hand"] + after_joker["pile"])
    assert run.blind.boss.disabled


# ---- hands that are not allowed -------------------------------------------------------------------

def test_the_psychic_needs_five_cards():
    run = boss_run("The Psychic")
    deal(run, cards(run, "KC KH KS KD 2S 3S 4S 6H 7D"))
    assert run.play_hand([0, 1, 2, 3]) == 0 and run.blind.boss.triggered
    assert run.play_hand([0, 1, 2, 3, 4]) > 0 and not run.blind.boss.triggered


def test_the_mouth_allows_only_the_first_hand_type():
    run = boss_run("The Mouth")
    deal(run, cards(run, "KC KH 2S 5S 5H"))
    pair, high = cards(run, "QC QH"), cards(run, "2C")
    assert estimate(run, high, []) > 0
    assert run.play_hand([0, 1]) > 0
    assert estimate(run, high, []) == 0 and estimate(run, pair, []) > 0
    assert run.play_hand([0]) == 0 and run.blind.boss.triggered  # High Card after a Pair
    assert run.play_hand([0, 1]) > 0 and not run.blind.boss.triggered


def test_the_eye_allows_each_hand_type_once():
    run = boss_run("The Eye")
    deal(run, cards(run, "KC KH 2S 5S 5H"))
    assert run.play_hand([0, 1]) > 0
    assert run.play_hand([0]) > 0
    assert run.play_hand([0, 1]) == 0 and run.blind.boss.triggered  # a second Pair


# ---- on play --------------------------------------------------------------------------------------

def test_the_hook_discards_two_held_cards_when_play_is_pressed():
    counter = DiscardCounter()
    run = boss_run("The Hook", jokers=[counter])
    hand = cards(run, "KC KH 2S 3S 4S 6H 7D 9C")
    deal(run, hand, [c for c in run.deck if c not in hand])
    held = hand[1:]
    run.play_hand([0])
    kept = [c for c in held if any(c is x for x in run.hand)]
    assert len(kept) == 5 and len(run.hand) == 8  # 7 held - 2 hooked + 3 drawn
    assert counter.seen == [(2, False)] and run.blind.boss.triggered
    assert [e for e in run.log if e[2] == "hook"]


def test_the_tooth_charges_a_dollar_per_card_played():
    run = boss_run("The Tooth")
    deal(run, cards(run, "KC KH 2S 5S 5H"))
    run.money = 10
    run.play_hand([0, 1, 2])
    assert run.money == 7 and run.blind.boss.triggered


def test_the_arm_lowers_the_level_before_scoring_and_estimates_know_it():
    run = boss_run("The Arm")
    deal(run, cards(run, "KC KH KS KD"))
    run.hand_levels["Pair"] = 2
    assert estimate(run, run.hand[:2], []) == (10 + 10 + 10) * 2  # scored at level 1
    assert run.play_hand([0, 1]) == 60 and run.hand_levels["Pair"] == 1 and run.blind.boss.triggered
    assert run.play_hand([0, 1]) == 60 and run.hand_levels["Pair"] == 1 and not run.blind.boss.triggered


def test_the_ox_takes_your_money_for_the_most_played_hand():
    run = boss_run("The Ox")
    run.hand_plays.update({"Straight": 3, "Pair": 3, "Flush": 1})  # a tie goes to the higher hand
    run.blind.boss.on_select(run)
    assert run.blind.boss.hand == "Straight"
    deal(run, cards(run, "KC KH 2S 3H 4D 5C 6S") + cards(run, "2C 3C 4C 5H 6C"))
    run.money = 20
    run.play_hand([0, 1])  # Pair
    assert run.money == 20 and not run.blind.boss.triggered
    run.play_hand([0, 1, 2, 3, 4])  # Straight
    assert run.money == 0 and run.blind.boss.triggered


def test_estimates_score_bull_with_the_money_the_ox_and_the_tooth_leave():
    for name, money in (("The Ox", 0), ("The Tooth", 18)):
        run = boss_run(name, jokers=[CATALOG["Bull"]()])
        run.blind.boss.hand = "Pair"
        deal(run, cards(run, "KC KH 2S 5S 9H"))
        run.money = 20
        pair = run.hand[:2]
        assert estimate(run, pair, run.hand[2:]) == (10 + 10 + 10 + 2 * money) * 2, name
        assert run.money == 20
        assert run.play_hand([0, 1]) == (10 + 10 + 10 + 2 * money) * 2, name


def test_the_ox_ignores_a_straight_flush_when_straight_is_most_played():
    run = boss_run("The Ox")
    run.hand_plays["Straight"] = 2
    run.blind.boss.on_select(run)
    deal(run, cards(run, "2C 3C 4C 5C 6C"))
    run.money = 20
    run.play_hand([0, 1, 2, 3, 4])
    assert run.money == 20


def test_the_flint_halves_base_chips_and_mult_rounding_up():
    run = boss_run("The Flint")
    deal(run, cards(run, "2S KC KH"))
    assert estimate(run, run.hand[:1], []) == (3 + 2) * 1  # High Card 5x1 -> 3x1
    assert run.play_hand([0]) == 5 and run.blind.boss.triggered
    assert run.play_hand([0, 1]) == (5 + 20) * 1  # Pair 10x2 -> 5x1


# ---- hands, discards, hand size and disabling mid-round -------------------------------------------

def test_the_needle_leaves_one_hand_until_disabled():
    agent = Script(("sell_joker", 0))
    run = boss_run("The Needle", agent, jokers=[Seller()])
    run.play_round()
    assert agent.seen[0]["hands"] == 1 and agent.seen[1]["hands"] == 4


def test_the_water_takes_the_discards_until_disabled():
    agent = Script(("sell_joker", 0))
    boss_run("The Water", agent, jokers=[Seller()]).play_round()
    assert agent.seen[0]["discards"] == 0 and agent.seen[1]["discards"] == 3


def test_the_manacle_takes_a_card_of_hand_size_and_gives_it_back_when_disabled():
    agent = Script(("sell_joker", 0))
    run = boss_run("The Manacle", agent, jokers=[Seller()])
    run.play_round()
    first, after = agent.seen[:2]
    assert (first["hand_size"], len(first["hand"])) == (7, 7)
    assert (after["hand_size"], len(after["hand"])) == (8, 8)
    assert run.hand_size == 8


def test_disabled_at_blind_select_the_boss_changes_nothing():
    class Chicotish(Joker):
        def on_blind_select(self, run, blind):
            run.disable_boss()

    for name in ("The Needle", "The Water", "The Manacle", "The House"):
        agent = Script()
        boss_run(name, agent, jokers=[Chicotish()]).play_round()
        seen = agent.seen[0]
        assert (seen["hands"], seen["discards"], seen["hand_size"]) == (4, 3, 8)
        assert len(seen["hand"]) == 8 and not any(c.face_down for c in seen["hand"])


# ---- face-down cards and draws --------------------------------------------------------------------

def test_the_house_deals_the_first_hand_face_down():
    agent = Script(("play", [0]), ("sell_joker", 0))
    boss_run("The House", agent, jokers=[Seller()]).play_round()
    first, second, disabled = agent.seen[:3]
    assert all(c.face_down for c in first["hand"])
    drawn = new_cards(first["hand"], second["hand"])
    assert len(drawn) == 1 and not drawn[0].face_down
    assert sum(c.face_down for c in second["hand"]) == 7
    assert not any(c.face_down for c in disabled["hand"])


def test_the_fish_draws_face_down_after_a_play_only():
    agent = Script(("discard", [0, 1]), ("play", [0, 1]))
    boss_run("The Fish", agent).play_round()
    start, after_discard, after_play = agent.seen[:3]
    assert not any(c.face_down for c in start["hand"])
    assert not any(c.face_down for c in new_cards(start["hand"], after_discard["hand"]))
    drawn = new_cards(after_discard["hand"], after_play["hand"])
    assert len(drawn) == 2 and all(c.face_down for c in drawn)


def test_the_mark_draws_face_cards_face_down():
    agent = Script(("discard", [0, 1, 2, 3, 4]))
    boss_run("The Mark", agent, seed=1).play_round()
    for seen in agent.seen[:3]:
        assert all(c.face_down == (c.rank in (11, 12, 13)) for c in seen["hand"])
    assert any(c.face_down for s in agent.seen for c in s["hand"])


def test_the_wheel_turns_one_card_in_seven_face_down():
    run = boss_run("The Wheel")
    wheel = run.active_boss
    n = 14000
    down = sum(wheel.face_down(run, Card(5, "Spades"), "play") for _ in range(n))
    assert abs(down / n - 1 / 7) < 0.015
    agent = Script(("discard", [0, 1, 2, 3, 4]), ("discard", [0, 1, 2, 3, 4]))
    boss_run("The Wheel", agent).play_round()
    assert any(c.face_down for s in agent.seen for c in s["hand"])


def test_the_serpent_always_draws_three():
    agent = Script(("play", [0]), ("discard", [0, 1, 2, 3, 4]))
    boss_run("The Serpent", agent).play_round()
    assert [len(s["hand"]) for s in agent.seen[:3]] == [8, 10, 8]


def test_cerulean_bell_forces_a_card_into_every_play():
    def other_card(run):
        return ("play", [next(i for i in range(len(run.hand)) if i != run.active_boss.forced_selection(run))])
    agent = Script(other_card)
    run = boss_run("Cerulean Bell", agent)
    run.play_round()
    first, second = agent.seen[:2]
    forced = first["hand"][first["forced"]]
    plays = [e for e in run.log if e[2] == "play"]
    assert len(plays[0][3]) == 2 and forced.label() in plays[0][3]
    assert second["forced"] is not None and second["hand"][second["forced"]].uid != forced.uid


# ---- jokers ---------------------------------------------------------------------------------------

def test_amber_acorn_shuffles_the_jokers_even_when_chicot_disables_it():
    jokers = [Plain(n) for n in "ABCDE"]
    agent = Script()
    boss_run("Amber Acorn", agent, jokers=jokers).play_round()
    order = [n for n, _ in agent.seen[0]["jokers"]]
    assert sorted(order) == list("ABCDE") and order != list("ABCDE")

    class Chicotish(Joker):
        name = "Z"

        def on_blind_select(self, run, blind):
            run.disable_boss()
    run = boss_run("Amber Acorn", jokers=[Plain(n) for n in "ABCD"] + [Chicotish()])
    run.play_round()
    assert run.blind.boss.disabled and [j.name for j in run.jokers] != list("ABCDZ")


def test_crimson_heart_disables_a_different_joker_each_hand():
    agent = Script()
    run = boss_run("Crimson Heart", agent, jokers=[Plain(n) for n in "ABC"])
    run.play_round()
    picks = []
    for seen in agent.seen:
        off = [n for n, disabled in seen["jokers"] if disabled]
        assert len(off) == 1
        picks.append(off[0])
    assert len(picks) == 4 and all(a != b for a, b in zip(picks, picks[1:]))
    assert not any(j.disabled for j in run.jokers)  # the run clears it after the round


def test_crimson_heart_with_one_joker_and_with_perished_jokers():
    agent = Script()
    boss_run("Crimson Heart", agent, jokers=[Plain("A")]).play_round()
    assert all(s["jokers"] == [("A", True)] for s in agent.seen)
    perished = Plain("P")
    perished.perished = True
    agent = Script()
    boss_run("Crimson Heart", agent, jokers=[perished, Plain("A"), Plain("B")]).play_round()
    assert all(not dict(s["jokers"])["P"] for s in agent.seen)


def test_crimson_heart_keeps_the_joker_of_the_winning_hand_and_clears_when_disabled():
    agent = Script(("sell_joker", 2))
    run = boss_run("Crimson Heart", agent, jokers=[Plain("A"), Plain("B"), Seller()])
    run.play_round()
    assert sum(d for _, d in agent.seen[1]["jokers"]) == 0
    run = boss_run("Crimson Heart", jokers=[Plain("A"), Plain("B")])
    heart = run.active_boss
    deal(run, cards(run, "KC KH"))
    heart.after_draw(run)
    off = [j.name for j in run.jokers if j.disabled]
    run.round_score = run.blind.chips
    heart.after_hand(run)
    assert [j.name for j in run.jokers if j.disabled] == off


def test_a_disabled_joker_does_not_score():
    run = boss_run("Crimson Heart", jokers=[CATALOG["Joker"]()])
    deal(run, cards(run, "KC KH"))
    run.active_boss.after_draw(run)
    assert run.jokers[0].disabled and run.play_hand([0, 1]) == 60 and run.blind.boss.triggered


# ---- every boss in real rounds --------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(BOSSES))
def test_every_boss_survives_a_greedy_round_and_cleans_up(name):
    for seed in range(2):
        jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "The Duo")]
        run = boss_run(name, GreedyBot(), seed=seed, jokers=jokers)
        run.money = 30
        run.hand_plays["Pair"] = 1
        assert run.play_round() in (True, False)
        assert run.hand_size == 8 and not any(j.disabled for j in run.jokers)
        assert not any(c.debuffed or c.face_down for c in run.deck)
        assert sorted(j.name for j in run.jokers) == ["Joker", "Jolly Joker", "The Duo"]


def test_bosses_come_up_in_full_runs_up_to_a_showdown():
    seen = set()
    for seed in range(3):
        run = Run(GreedyBot(), seed=seed, max_ante=9)
        run.hand_levels = {h: 3000 for h in run.hand_levels}  # strong enough to see every ante
        assert run.play().blinds_beaten == 27
        seen |= {b for b, n in run.boss_used.items() if n}
    assert len(seen) >= 15 and any(BOSSES[b].showdown for b in seen)
