from collections import Counter

import pytest

from balatro.agent import Agent
from balatro.bots import GreedyBot
from balatro.items import BOSSES, CONSUMABLES, TAGS, entries
from balatro.jokers import CATALOG
from balatro.run import Run
from balatro.shop import Offer, Shop, cost_of


class Picker(Agent):
    """Takes the first card of every pack and records the hand size of each round."""

    def __init__(self):
        self.hand_sizes = []

    def pack_action(self, run, pack):
        return ("pick", 0, [])

    def round_action(self, run):
        self.hand_sizes.append(run.hand_size)
        return ("play", [0])


def make_run(agent=None, seed=0, **kw):
    run = Run(agent or Agent(), seed=seed, record=True, **kw)
    run.start_ante()
    return run


def new_tag(run, name):
    t = TAGS[name]()
    t.setup(run)
    return t


def gain(run, name):
    run.gain_tag(new_tag(run, name))


def held(run):
    return [t.name for t in run.tags]


def test_every_tag_has_code_and_its_minimum_ante():
    assert set(TAGS) == {t["name"] for t in entries("tag")}
    assert {n for n, cls in TAGS.items() if cls.min_ante == 2} == {
        "Negative Tag", "Standard Tag", "Meteor Tag", "Buffoon Tag", "Handy Tag", "Garbage Tag", "Ethereal Tag",
        "Top-up Tag", "Orbital Tag"}


# ---- money ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("money, after", [(10, 20), (50, 90), (-3, -3), (0, 0)])
def test_economy_tag_doubles_money_up_to_40(money, after):
    run = make_run()
    run.money = money
    gain(run, "Economy Tag")
    assert run.money == after and run.tags == []


def test_handy_garbage_and_speed_tags_pay_for_the_run_so_far():
    run = make_run()
    run.money, run.hands_played, run.unused_discards = 0, 7, 5
    gain(run, "Handy Tag")
    gain(run, "Garbage Tag")
    assert run.money == 12
    run.ante_tags[0] = new_tag(run, "Speed Tag")
    run.skips = 2
    run.blind = run.make_blind(0)
    run.skip(0)  # the third skip, this one included
    assert run.money == 12 + 15 and run.tags == []


def test_investment_tag_pays_after_the_next_boss():
    run = make_run()
    gain(run, "Investment Tag")
    gain(run, "Investment Tag")
    run.blind = run.make_blind(0)
    run.play_round()
    assert held(run) == ["Investment Tag", "Investment Tag"]
    run.money = 0
    run.boss_defeated()
    assert run.money == 50 and run.tags == []


# ---- immediate ------------------------------------------------------------------------------------

def test_top_up_tag_makes_common_jokers_for_free_slots():
    run = make_run()
    gain(run, "Top-up Tag")
    assert len(run.jokers) == 2 and all(j.rarity == "Common" for j in run.jokers)
    assert not any(j.eternal or j.perishable or j.rental for j in run.jokers)
    run.joker_slots = 3
    gain(run, "Top-up Tag")
    assert len(run.jokers) == 3


def test_orbital_tag_picks_a_visible_hand_when_rolled_and_levels_it_by_3():
    run = make_run()
    secret = {"Five of a Kind", "Flush House", "Flush Five"}
    picks = {new_tag(run, "Orbital Tag").hand for _ in range(300)}
    assert not picks & secret and len(picks) == 9
    run.hand_plays["Flush Five"] = 1
    assert "Flush Five" in {new_tag(run, "Orbital Tag").hand for _ in range(300)}
    orbital = new_tag(run, "Orbital Tag")
    gain(run, "Double Tag")
    run.gain_tag(orbital)  # the copy levels the same hand
    assert run.hand_levels[orbital.hand] == 7 and run.tags == []


def test_boss_tag_rerolls_the_ante_boss():
    run = make_run()
    old = run.ante_boss.name
    gain(run, "Boss Tag")
    assert run.ante_boss.name != old and run.boss_used[run.ante_boss.name] == 1
    assert isinstance(run.ante_boss, BOSSES[run.ante_boss.name])


@pytest.mark.parametrize("name, pack", [("Standard Tag", "Mega Standard Pack"), ("Charm Tag", "Mega Arcana Pack"),
                                        ("Meteor Tag", "Mega Celestial Pack"), ("Buffoon Tag", "Mega Buffoon Pack"),
                                        ("Ethereal Tag", "Spectral Pack")])
def test_pack_tags_open_a_free_pack(name, pack):
    run = make_run(Picker())
    run.money = 0
    gain(run, name)
    assert [e[3] for e in run.log if e[2] == "open"] == [pack]
    assert run.money == 0 and run.tags == []


def test_free_packs_give_what_they_hold():
    run = make_run(Picker())
    gain(run, "Standard Tag")
    assert len(run.deck) == 54 and len({c.uid for c in run.deck}) == 54  # Mega: 2 picks
    gain(run, "Buffoon Tag")
    assert len(run.jokers) == 2
    gain(run, "Meteor Tag")
    assert sum(run.hand_levels.values()) == len(run.hand_levels) + 2


def test_juggle_tag_adds_hand_size_for_the_next_round_only():
    agent = Picker()
    run = make_run(agent)
    gain(run, "Juggle Tag")
    gain(run, "Juggle Tag")
    run.blind = run.make_blind(0)
    run.play_round()
    run.play_round()
    assert agent.hand_sizes[0] == 14 and agent.hand_sizes[-1] == 8 and run.tags == []


# ---- the next shop --------------------------------------------------------------------------------

def test_coupon_tag_frees_the_initial_cards_and_packs_only():
    run = make_run()
    run.money = 100
    gain(run, "Coupon Tag")
    shop = Shop(run)
    assert all(cost_of(run, o) == 0 for o in shop.cards + shop.packs)
    assert all(cost_of(run, o) > 0 for o in shop.vouchers)
    shop.reroll()
    assert not any(o.free for o in shop.cards) and run.tags == []
    assert not any(o.free for o in Shop(run).cards)


def test_d6_tag_makes_rerolls_start_at_zero():
    run = make_run()
    run.money = 10
    gain(run, "D6 Tag")
    shop = Shop(run)
    costs = []
    for _ in range(3):
        costs.append(shop.reroll_cost)
        assert shop.reroll()
    assert costs == [0, 1, 2] and run.money == 7
    assert Shop(run).reroll_cost == 5


def test_voucher_tag_adds_a_second_voucher_for_one_shop():
    run = make_run()
    gain(run, "Voucher Tag")
    shop = Shop(run)
    names = [o.item for o in shop.vouchers]
    assert len(names) == 2 and len(set(names)) == 2 and names[0] == run.ante_voucher
    run.money = 10
    assert shop.buy("voucher", 1) and names[1] in run.vouchers
    assert [o.item for o in Shop(run).vouchers] == [run.ante_voucher]


@pytest.mark.parametrize("name, rarity", [("Uncommon Tag", "Uncommon"), ("Rare Tag", "Rare")])
def test_rarity_tags_put_a_free_joker_in_the_next_shop(name, rarity):
    for seed in range(5):
        run = make_run(seed=seed)
        gain(run, name)
        shop = Shop(run)
        free = [o for o in shop.cards if o.free]
        assert len(free) == 1 and free[0].kind == "Joker" and free[0].item.rarity == rarity
        assert len(shop.cards) == 2 and run.tags == []


def test_rare_tag_gives_nothing_when_no_rare_joker_can_appear():
    run = make_run()
    run.jokers = [cls() for cls in CATALOG.values() if cls.rarity == "Rare"]
    gain(run, "Rare Tag")
    shop = Shop(run)
    assert not any(o.free for o in shop.cards) and run.tags == []


def test_two_rarity_tags_fill_two_slots_and_a_third_waits():
    run = make_run()
    for name in ("Uncommon Tag", "Rare Tag", "Uncommon Tag"):
        gain(run, name)
    shop = Shop(run)
    assert sorted(o.item.rarity for o in shop.cards if o.free) == ["Rare", "Uncommon"]
    assert held(run) == ["Uncommon Tag"]


def test_rarity_tags_work_after_a_coupon_and_keep_an_edition_tag_s_edition():
    run = make_run()
    gain(run, "Coupon Tag")
    gain(run, "Uncommon Tag")
    shop = Shop(run)
    assert any(o.free and o.kind == "Joker" and o.item.rarity == "Uncommon" for o in shop.cards)
    assert run.tags == []
    shop.cards = [Offer("Joker", CATALOG["Joker"]("Foil"), free=True), Offer("Planet", CONSUMABLES["Pluto"]())]
    TAGS["Rare Tag"]().on_shop_open(run, shop)
    assert shop.cards[0].item.rarity == "Rare" and shop.cards[0].free
    assert shop.cards[0].item.edition in ("Foil", "Holographic", "Polychrome", "Negative")


@pytest.mark.parametrize("name, edition", [("Foil Tag", "Foil"), ("Holographic Tag", "Holographic"),
                                           ("Polychrome Tag", "Polychrome"), ("Negative Tag", "Negative")])
def test_edition_tags_change_the_next_plain_joker_on_sale(name, edition):
    run = make_run()
    run.money = 1000
    gain(run, name)
    shop = Shop(run)
    for _ in range(20):
        if not run.tags:
            break
        shop.reroll()
    tagged = [o for o in shop.cards if o.free]
    assert run.tags == [] and len(tagged) == 1
    assert tagged[0].kind == "Joker" and tagged[0].item.edition == edition and cost_of(run, tagged[0]) == 0


def test_edition_tags_skip_jokers_that_have_an_edition():
    run = make_run()
    shop = Shop(run)
    foil = TAGS["Foil Tag"]()
    shiny = Offer("Joker", CATALOG["Joker"]("Polychrome"))
    assert not foil.on_shop_offer(run, shop, shiny) and shiny.item.edition == "Polychrome" and not shiny.free
    plain = Offer("Joker", CATALOG["Joker"]())
    assert foil.on_shop_offer(run, shop, plain) and plain.item.edition == "Foil" and plain.free


def test_double_tag_doubles_real_tags():
    run = make_run()
    run.money = 10
    gain(run, "Double Tag")
    gain(run, "Economy Tag")
    assert run.money == 40 and run.tags == []
    gain(run, "Double Tag")
    gain(run, "Investment Tag")
    assert held(run) == ["Investment Tag", "Investment Tag"]


# ---- every tag through a real skip ----------------------------------------------------------------

class Skipper(GreedyBot):
    def skip_blind(self, run, blind, tag):
        return True


@pytest.mark.parametrize("name", sorted(TAGS))
def test_every_tag_through_a_skip_round_and_shop(name):
    run = Run(GreedyBot(), seed=1)
    run.ante = 2
    run.start_ante()
    run.money = 20
    run.ante_tags[0] = new_tag(run, name)
    run.blind = run.make_blind(0)
    run.skip(0)
    run.blind = run.make_blind(1)
    run.play_round()
    run.end_round()
    run.shop()
    assert run.skips == 1 and run.hand_size == 8


def test_skipping_every_blind_plays_through():
    gained = Counter()
    for seed in range(4):
        run = Run(Skipper(), seed=seed, max_ante=4, record=True)
        run.play()
        gained.update(e[3] for e in run.log if e[2] == "tag")
    assert sum(gained.values()) >= 8
