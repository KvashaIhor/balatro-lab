from collections import Counter

import pytest

from balatro.agent import Agent
from balatro.cards import Card
from balatro.items import CONSUMABLES, Boss
from balatro.jokers import CATALOG
from balatro.run import Blind, Run
from balatro.shop import PACKS, OpenPack, Shop


def make_run(seed=0):
    run = Run(Agent(), seed=seed)
    run.start_ante()
    run.hand = run.deck[:8]
    return run


def use(run, name, targets=(), **kw):
    """Put the card in the consumable area and use it on hand positions `targets`."""
    run.consumables.append(CONSUMABLES[name](**kw))
    return run.use_consumable(len(run.consumables) - 1, list(targets))


def test_all_tarots_are_registered():
    assert sum(c.kind == "Tarot" for c in CONSUMABLES.values()) == 22


@pytest.mark.parametrize("name, enhancement, most", [
    ("The Magician", "Lucky", 2), ("The Empress", "Mult", 2), ("The Hierophant", "Bonus", 2),
    ("The Lovers", "Wild", 1), ("The Chariot", "Steel", 1), ("Justice", "Glass", 1),
    ("The Devil", "Gold", 1), ("The Tower", "Stone", 1),
])
def test_enhancing_tarots_take_one_to_their_limit(name, enhancement, most):
    run = make_run()
    assert not use(run, name, [])
    assert not use(run, name, range(most + 1))
    run.consumables.clear()
    assert use(run, name, range(most))
    assert [c.enhancement for c in run.hand[:most + 1]] == [enhancement] * most + [None]
    assert run.consumables == [] and run.last_tarot_planet == name


@pytest.mark.parametrize("name, suit", [("The Star", "Diamonds"), ("The Moon", "Clubs"),
                                        ("The Sun", "Hearts"), ("The World", "Spades")])
def test_suit_tarots_change_up_to_three_cards(name, suit):
    run = make_run()
    run.hand = [Card(r, "Spades" if suit != "Spades" else "Hearts", uid=100 + r) for r in range(2, 7)]
    assert not use(run, name, range(4))
    run.consumables.clear()
    assert use(run, name, [0, 2, 4])
    assert [c.suit == suit for c in run.hand] == [True, False, True, False, True]


def test_strength_raises_rank_and_wraps_aces():
    run = make_run()
    run.hand = [Card(13, "Hearts", uid=1), Card(14, "Hearts", uid=2), Card(5, "Hearts", uid=3)]
    assert use(run, "Strength", [0, 1])
    assert [c.rank for c in run.hand] == [14, 2, 5]


def test_hanged_man_destroys_up_to_two_cards_from_deck_and_hand():
    run = make_run()
    gone = run.hand[:2]
    assert not use(run, "The Hanged Man", range(3))
    run.consumables.clear()
    assert use(run, "The Hanged Man", [0, 1])
    assert len(run.deck) == 50 and len(run.hand) == 6
    assert not any(c in run.deck for c in gone)


def test_death_turns_the_left_card_into_the_right_one():
    run = make_run()
    left, right = Card(2, "Clubs", uid=1), Card(13, "Hearts", "Glass", "Foil", "Red", bonus_chips=15, debuffed=True, uid=2)
    run.hand = [left, Card(7, "Spades", uid=3), right]
    assert not use(run, "Death", [0])
    assert not use(run, "Death", [0, 1, 2])
    run.consumables.clear()
    assert use(run, "Death", [2, 0])  # order of selection doesn't matter: left becomes right
    assert (left.rank, left.suit, left.enhancement, left.edition, left.seal, left.bonus_chips) == (13, "Hearts", "Glass", "Foil", "Red", 15)
    assert left.debuffed and left.uid == 1 and right.rank == 13


def test_the_fool_copies_the_last_tarot_or_planet_but_not_itself():
    run = make_run()
    assert not use(run, "The Fool")  # nothing used yet
    run.consumables.clear()
    assert use(run, "Mercury")
    assert use(run, "The Fool")
    assert [c.name for c in run.consumables] == ["Mercury"] and run.consumables[0].edition is None
    assert not use(run, "The Fool")  # the last card used was The Fool
    run.consumables = []
    assert use(run, "Strength", [0]) and use(run, "The Fool")
    assert [c.name for c in run.consumables] == ["Strength"]


def test_the_fool_with_full_slots_works_only_from_the_consumable_area():
    run = make_run()
    run.last_tarot_planet = "Jupiter"
    run.consumables = [CONSUMABLES["The Fool"](), CONSUMABLES["Pluto"]()]
    assert run.use_consumable(0, [])
    assert sorted(c.name for c in run.consumables) == ["Jupiter", "Pluto"]
    run.consumables.append(CONSUMABLES["Saturn"]("Negative"))
    run.last_tarot_planet = "Jupiter"
    assert not CONSUMABLES["The Fool"]().can_use(run, [])  # from a pack or the shop: no room


def test_priestess_and_emperor_create_up_to_two_limited_by_room():
    run = make_run()
    run.consumable_slots = 3
    assert use(run, "The High Priestess")
    assert len(run.consumables) == 2 and all(c.kind == "Planet" for c in run.consumables)
    assert len({c.name for c in run.consumables}) == 2
    run.consumables = [CONSUMABLES["Pluto"](), CONSUMABLES["Mars"]()]
    assert use(run, "The Emperor")  # used from the area, its own slot frees up: one Tarot
    assert [c.kind for c in run.consumables] == ["Planet", "Planet", "Tarot"]
    run.consumables.append(CONSUMABLES["Pluto"]("Negative"))
    assert not CONSUMABLES["The Emperor"]().can_use(run, [])  # full slots, not in the area


@pytest.mark.parametrize("money, after", [(5, 10), (0, 0), (20, 40), (35, 55), (-3, -3)])
def test_hermit_doubles_money_up_to_twenty(money, after):
    run = make_run()
    run.money = money
    assert use(run, "The Hermit") and run.money == after


def test_temperance_pays_joker_sell_values_up_to_fifty():
    run = make_run()
    run.money = 0
    assert use(run, "Temperance") and run.money == 0  # no jokers: usable for $0
    jokers = [CATALOG["Greedy Joker"]("Foil"), CATALOG["Joker"]()]
    jokers[1].perished = True  # debuffed jokers still count
    run.jokers = jokers
    assert use(run, "Temperance") and run.money == 3 + 1
    jokers[0].extra_sell = 60
    assert use(run, "Temperance") and run.money == 4 + 50


def test_wheel_of_fortune_hits_one_in_four_on_editionless_jokers():
    run = make_run()
    assert not use(run, "The Wheel of Fortune")  # no jokers
    run.consumables.clear()
    run.jokers = [CATALOG["Joker"]("Foil")]
    assert not use(run, "The Wheel of Fortune")  # nothing edition-less
    run.consumables.clear()
    hits = Counter()
    for _ in range(2000):
        run.jokers = [CATALOG["Joker"]("Holographic"), CATALOG["Joker"]()]
        assert use(run, "The Wheel of Fortune")
        assert run.jokers[0].edition == "Holographic"
        hits[run.jokers[1].edition] += 1
    assert abs(sum(n for e, n in hits.items() if e) / 2000 - 0.25) < 0.03
    assert set(hits) == {None, "Foil", "Holographic", "Polychrome"}
    assert hits["Foil"] > hits["Holographic"] > hits["Polychrome"]


def test_wheel_of_fortune_odds_double_with_oops():
    run = make_run()
    oops = type("Oops", (CATALOG["Joker"],), {"name": "Oops! All 6s"})
    hits = 0
    for _ in range(2000):
        run.jokers = [CATALOG["Joker"](), oops("Foil")]
        use(run, "The Wheel of Fortune")
        hits += run.jokers[0].edition is not None
    assert abs(hits / 2000 - 0.5) < 0.04


def test_judgement_creates_a_joker_when_there_is_room():
    run = make_run()
    assert use(run, "Judgement")
    j = run.jokers[0]
    assert j.rarity in ("Common", "Uncommon", "Rare") and not (j.eternal or j.perishable or j.rental)
    run.joker_slots = 1
    assert not use(run, "Judgement")
    run.consumables.clear()
    run.jokers[0].edition = "Negative"  # a Negative joker leaves the slot free
    assert use(run, "Judgement") and len(run.jokers) == 2


def test_cards_need_a_hand_from_the_round_or_an_arcana_pack():
    run = make_run()
    run.current_shop = Shop(run)  # in the shop, run.hand still holds last round's cards
    assert not CONSUMABLES["The Empress"]().can_use(run, run.hand[:1])
    assert CONSUMABLES["The Hermit"]().can_use(run, [])
    run.open_pack_state = OpenPack(PACKS["Buffoon Pack"], [], 1)
    assert not CONSUMABLES["The Empress"]().can_use(run, run.hand[:1])
    run.open_pack_state = OpenPack(PACKS["Arcana Pack"], [], 1)
    assert CONSUMABLES["The Empress"]().can_use(run, run.hand[:1])


class PickFirstUsable(Agent):
    def pack_action(self, run, pack):
        for i, item in enumerate(pack.cards):
            for targets in ([0], [0, 1], []):
                if item.can_use(run, run.cards_at(targets)):
                    return ("pick", i, targets)
        return ("skip",)


def test_an_arcana_pack_deals_a_hand_to_use_tarots_on():
    for seed in range(5):
        run = Run(PickFirstUsable(), seed=seed)
        run.start_ante()
        run.jokers = [CATALOG["Joker"]()]
        run.open_pack(PACKS["Arcana Pack"])
        assert run.consumables_used["Tarot"] + run.consumables_used["Spectral"] == 1
        assert run.hand == [] and len({c.uid for c in run.deck}) == len(run.deck)


class TheClub(Boss):
    name = "The Club"

    def debuffs(self, run, card):
        return card.has_suit("Clubs", run.smeared)


def test_changed_cards_get_boss_debuffs_checked_again():
    run = make_run()
    run.blind = Blind("Boss Blind", 2, 600, 5, TheClub())
    run.hand = [Card(5, "Clubs", uid=1), Card(6, "Hearts", uid=2), Card(7, "Hearts", uid=3)]
    run.refresh_debuffs()
    assert [c.debuffed for c in run.hand] == [True, False, False]
    assert use(run, "The Star", [0])
    assert use(run, "The Lovers", [1])  # Wild cards count as Clubs
    assert [c.debuffed for c in run.hand] == [False, True, False]
