import random
from collections import Counter

import pytest

from balatro import pool
from balatro.agent import Agent
from balatro.bots import GreedyBot
from balatro.cards import Card
from balatro.items import CONSUMABLES, Tag
from balatro.jokers import CATALOG
from balatro.run import Run
from balatro.shop import PACKS, Offer, Shop, cost_of, price


def make_run(**kw):
    run = Run(Agent(), seed=kw.pop("seed", 0), **kw)
    run.start_ante()
    return run


@pytest.mark.parametrize("base, edition, discount, expected", [
    (3, None, 0, 3), (3, None, 25, 2), (3, None, 50, 1),  # Tarot
    (10, None, 25, 7), (10, None, 50, 5),  # Voucher
    (6, "Foil", 0, 8),  # Joker $6 + Foil
])
def test_prices_match_the_examples_in_the_data(base, edition, discount, expected):
    run = make_run()
    run.discount_percent = discount
    assert price(run, base, edition) == expected


def test_sell_value_is_half_the_buy_price_plus_extra():
    run = make_run()
    j = CATALOG["Greedy Joker"]("Foil")  # $5 + $2 Foil
    assert run.sell_value(j) == 3
    j.extra_sell = 3
    assert run.sell_value(j) == 6
    j.rental = True
    assert run.sell_value(j) == 4  # rentals cost $1, so sell for $1 + extra
    assert run.sell_value(CONSUMABLES["Pluto"]()) == 1


def test_rerolls_cost_more_each_time_and_reset_each_shop():
    run = make_run()
    run.money = 100
    shop = Shop(run)
    costs = []
    for _ in range(3):
        costs.append(shop.reroll_cost)
        assert shop.reroll()
    assert costs == [5, 6, 7] and run.money == 100 - 18
    assert Shop(run).reroll_cost == 5
    run.redeem_voucher("Reroll Surplus")
    assert Shop(run).reroll_cost == 3


def test_reroll_needs_the_money():
    run = make_run()
    run.money = 4
    assert not Shop(run).reroll() and run.money == 4


def test_first_shop_offers_a_buffoon_pack_and_the_ante_voucher():
    run = make_run()
    shop = Shop(run)
    assert shop.packs[0].item == PACKS["Buffoon Pack"]
    assert [o.item for o in shop.vouchers] == [run.ante_voucher]
    assert len(shop.cards) == 2


def test_overstock_adds_a_slot_that_fills_at_once():
    run = make_run()
    run.current_shop = shop = Shop(run)
    run.redeem_voucher("Overstock")
    assert len(shop.cards) == 3 and run.shop_card_slots == 3


def test_vouchers_change_the_run():
    run = make_run()
    run.ante = 3
    for v in ("Grabber", "Wasteful", "Paint Brush", "Seed Money", "Crystal Ball", "Antimatter", "Clearance Sale", "Hone"):
        run.redeem_voucher(v)
    assert (run.base_hands, run.base_discards, run.base_hand_size) == (5, 4, 9)
    assert (run.interest_cap, run.consumable_slots, run.joker_slots) == (10, 3, 6)
    assert (run.discount_percent, run.edition_rate) == (25, 2)
    run.redeem_voucher("Hieroglyph")
    assert run.ante == 2 and run.base_hands == 4


def test_vouchers_follow_their_prerequisites():
    run = make_run()
    rng = random.Random(1)
    seen = {pool.random_voucher(run, rng) for _ in range(500)}
    assert "Liquidation" not in seen and "Clearance Sale" in seen
    run.vouchers.append("Clearance Sale")
    seen = {pool.random_voucher(run, rng) for _ in range(500)}
    assert "Liquidation" in seen and "Clearance Sale" not in seen


def test_buying_a_joker_needs_money_and_room():
    run = make_run()
    shop = Shop(run)
    shop.cards = [Offer("Joker", CATALOG["Joker"]()), Offer("Joker", CATALOG["Greedy Joker"]())]
    run.money = 3
    assert shop.buy("card", 0) and run.money == 1 and [j.name for j in run.jokers] == ["Joker"]
    assert not shop.buy("card", 0)  # Greedy Joker costs $5
    run.money, run.joker_slots = 10, 1
    assert not shop.buy("card", 0)
    shop.cards[0].item.edition = "Negative"  # Negative jokers need no slot
    assert shop.buy("card", 0) and len(run.jokers) == 2


def test_buy_and_use_a_planet_without_a_slot():
    run = make_run()
    run.consumable_slots = 0
    shop = Shop(run)
    shop.cards = [Offer("Planet", CONSUMABLES["Mercury"]())]
    assert not shop.buy("card", 0)
    assert shop.buy("card", 0, use=True) and run.hand_levels["Pair"] == 2


def test_coupon_style_free_offers_cost_nothing():
    run = make_run()
    offer = Offer("Joker", CATALOG["Blueprint"](), free=True)
    assert cost_of(run, offer) == 0


def test_edition_odds():
    rng = random.Random(0)
    n = 200_000
    base = Counter(pool.roll_edition(rng) for _ in range(n))
    assert abs(base["Negative"] / n - 0.003) < 0.0006
    assert abs(base["Polychrome"] / n - 0.003) < 0.0006
    assert abs(base["Holographic"] / n - 0.014) < 0.0015
    assert abs(base["Foil"] / n - 0.02) < 0.002
    glow = Counter(pool.roll_edition(rng, rate=4) for _ in range(n))
    assert abs(glow["Foil"] / n - 0.08) < 0.004 and abs(glow["Negative"] / n - 0.003) < 0.0006
    standard = Counter(pool.roll_edition(rng, scale=2, negative=False) for _ in range(n))
    assert standard["Negative"] == 0 and abs(standard["Foil"] / n - 0.04) < 0.003


def test_rarity_odds():
    rng = random.Random(0)
    n = 100_000
    c = Counter(pool.roll_rarity(rng) for _ in range(n))
    assert abs(c["Common"] / n - 0.7) < 0.01 and abs(c["Rare"] / n - 0.05) < 0.005


def test_no_duplicate_jokers_without_showman():
    run = make_run()
    owned = {"Blueprint", "Brainstorm", "Baseball Card"}
    run.jokers = [CATALOG[n]() for n in owned]
    rng = random.Random(0)
    names = {pool.random_joker(run, rng, "Rare").name for _ in range(300)}
    assert not names & owned and len(names) > 5


def test_boss_selection_rules():
    run = make_run()
    rng = random.Random(0)
    run.ante = 1
    first = [pool.random_boss(run, rng).name for _ in range(8)]
    assert len(set(first)) == 8  # all 8 ante-1 bosses before any repeats
    run.ante = 8
    assert all(pool.random_boss(run, rng).showdown for _ in range(10))
    run.ante = 9
    assert not any(pool.random_boss(run, rng).showdown for _ in range(30))


def test_stakes():
    red = make_run(stake="Red Stake")
    assert red.make_blind(0).reward == 0
    green = make_run(stake="Green Stake")
    green.ante = 2
    assert green.make_blind(0).chips == 900 and make_run().make_blind(0).chips == 300
    assert make_run(stake="Blue Stake").base_discards == 2


def test_gold_stake_stickers():
    run = make_run(stake="Gold Stake")
    rng = random.Random(0)
    jokers = [pool.random_joker(run, rng, stickers=True) for _ in range(2000)]
    eternal = sum(j.eternal for j in jokers) / 2000
    perishable = sum(j.perishable for j in jokers) / 2000
    rental = sum(j.rental for j in jokers) / 2000
    assert 0.25 < eternal < 0.35 and 0.25 < perishable < 0.35 and 0.25 < rental < 0.35
    assert not any(j.eternal and j.perishable for j in jokers)


class Picker(Agent):
    def pack_action(self, run, pack):
        return ("pick", 0, [])


def test_celestial_pack_uses_the_planet_and_buffoon_pack_gives_a_joker():
    run = Run(Picker(), seed=0)
    run.start_ante()
    run.open_pack(PACKS["Celestial Pack"])
    assert sum(run.hand_levels.values()) == len(run.hand_levels) + 1
    run.open_pack(PACKS["Mega Buffoon Pack"])
    assert len(run.jokers) == 2  # Mega packs pick 2
    run.open_pack(PACKS["Standard Pack"])
    assert len(run.deck) == 53 and len({c.uid for c in run.deck}) == 53


def test_telescope_puts_the_most_played_planet_in_celestial_packs():
    from balatro.shop import pack_cards
    run = make_run()
    run.vouchers.append("Telescope")
    run.hand_plays["Flush"] = 3
    for seed in range(10):
        assert pack_cards(run, PACKS["Celestial Pack"], random.Random(seed))[0].name == "Jupiter"
    for game_seed in ("1VAXB1X6", "K74LGZC6", "TPA4SJAV"):              # seeded packs come from the game model
        seeded = Run(Agent(), game_seed=game_seed)
        seeded.vouchers.append("Telescope")
        seeded.hand_plays["Flush"] = 3
        cards = pack_cards(seeded, PACKS["Celestial Pack"], random.Random(0))
        assert cards[0].name == "Jupiter" and len({c.name for c in cards}) == len(cards)


def test_secret_planets_need_their_hand_played():
    run = make_run()
    rng = random.Random(0)
    names = {pool.random_consumable(run, "Planet", rng).name for _ in range(500)}
    assert "Planet X" not in names and len(names) == 9
    run.hand_plays["Five of a Kind"] = 1
    assert "Planet X" in {pool.random_consumable(run, "Planet", rng).name for _ in range(500)}


class Double(Tag):
    name = "Double Tag"


class Money(Tag):
    name = "Money"

    def on_gain(self, run):
        run.money += 10
        return True


def test_double_tag_copies_the_next_tag():
    run = make_run()
    run.money = 0
    run.gain_tag(Double())
    run.gain_tag(Double())  # a Double Tag doesn't copy another
    assert [t.name for t in run.tags] == ["Double Tag", "Double Tag"]
    run.gain_tag(Money())
    assert run.money == 30 and run.tags == []


class Skipper(GreedyBot):
    def skip_blind(self, run, blind, tag):
        return True


def test_skipped_blinds_count_toward_progress():
    for seed in range(4):
        result = Run(Skipper(), seed=seed, max_ante=3).play()
        # only bosses get played, so each ante passed counts 3 blinds for 1 beaten
        if result.blinds_beaten == 3:
            assert result.progress == 9
        else:
            assert result.blinds_beaten == result.ante - 1
            assert 3 * result.blinds_beaten + 2 <= result.progress < 3 * result.blinds_beaten + 3


def test_selling_and_eternal():
    run = make_run()
    run.jokers = [CATALOG["Joker"](), CATALOG["Greedy Joker"]()]
    run.jokers[1].eternal = True
    assert run.sell_joker(0) and run.money == 4 + 1
    assert not run.sell_joker(0) and len(run.jokers) == 1


def test_end_of_round_gold_cards_blue_seals_stickers():
    run = make_run()
    run.blind = run.make_blind(0)
    run.hand = [Card(5, "Hearts", enhancement="Gold"), Card(6, "Hearts", seal="Blue"), Card(7, "Hearts", enhancement="Gold", seal="Red")]
    run.last_hand = "Flush"
    perishable, rental = CATALOG["Joker"](), CATALOG["Jolly Joker"]()
    perishable.perishable, perishable.perish_rounds = True, 1
    rental.rental = True
    run.jokers = [perishable, rental]
    run.money, run.hands_left, run.discards_left = 0, 0, 0
    run.end_round()
    # Gold $3 + Gold with Red Seal $6 - rent $3, then $3 Small Blind reward; interest on $6 is $1
    assert run.money == 3 + 6 - 3 + 3 + 1
    assert [c.name for c in run.consumables] == ["Jupiter"]
    assert perishable.perished and run.active_jokers() == [rental]


def test_observatory_and_plasma():
    from balatro.hands import evaluate
    from balatro.scoring import HandContext, score_hand
    run = make_run()
    played = [Card(9, "Spades"), Card(9, "Hearts")]
    ctx = lambda: HandContext(run, played, [], evaluate(played, run.rules), random.Random(0))  # noqa: E731
    plain = score_hand(ctx()).total  # Pair: (10 + 18) x 2
    run.consumables = [CONSUMABLES["Mercury"]()]
    run.vouchers.append("Observatory")
    assert plain == 56 and score_hand(ctx()).total == 84
    run.vouchers, run.plasma = [], True
    assert score_hand(ctx()).total == 15 * 15  # (28 + 2) / 2 each


def test_credit_card_style_debt():
    run = make_run()

    class Credit(CATALOG["Joker"]):
        debt = 20
    run.jokers = [Credit()]
    run.money = 0
    assert run.debt_limit == -20
    assert Shop(run).reroll() and run.money == -5


def test_blueprint_copies_run_hooks_without_double_scaling():
    from balatro.jokers import Joker

    class Grower(Joker):
        name = "Grower"
        copyable = True
        grown = 0

        def on_blind_select(self, run, blind):
            run.money += 2  # an effect on the run: a copy does it too
            if not run.copying:
                self.grown += 1  # own state: only the original

    run = make_run()
    grower = Grower()
    run.jokers = [CATALOG["Blueprint"](), grower]
    run.money = 0
    for j in run.active_jokers():
        j.on_blind_select(run, None)
    assert run.money == 4 and grower.grown == 1 and not run.copying
    run.jokers = [CATALOG["Blueprint"](), CATALOG["Brainstorm"]()]  # they point at each other: no loop
    for j in run.active_jokers():
        j.on_blind_select(run, None)


class Reorderer(Agent):
    """Puts the last joker first, then plays a pair."""

    def __init__(self, order):
        self.order, self.done = order, False

    def round_action(self, run):
        if not self.done:
            self.done = True
            return ("order_jokers", self.order)
        pair = next((i, k) for i in range(len(run.hand)) for k in range(i + 1, len(run.hand)) if run.hand[i].rank == run.hand[k].rank)
        return ("play", list(pair))


def test_joker_order_changes_the_score():
    def first_hand(order):
        run = Run(Reorderer(order), seed=2, max_ante=1, record=True)
        run.jokers = [CATALOG["The Duo"](), CATALOG["Joker"]()]
        run.start_ante()
        run.blind = run.make_blind(0)
        run.play_round()
        return run, next(f for f in run.frames if f["kind"] == "play")
    kept, played = first_hand([0, 1])
    swapped, played_swapped = first_hand([1, 0])
    assert played["mult"] == 2 * 2 + 4 and played_swapped["mult"] == (2 + 4) * 2  # Pair base mult 2
    assert [j.name for j in swapped.jokers] == ["Joker", "The Duo"]
    assert any(f["kind"] == "order" for f in swapped.frames) and not any(f["kind"] == "order" for f in kept.frames)


def test_greedy_bot_orders_xmult_last_and_blueprint_before_it():
    from balatro.bots import joker_order
    jokers = [CATALOG[n]() for n in ("The Duo", "Blueprint", "Joker", "Greedy Joker")]
    assert [jokers[i].name for i in joker_order(jokers)] == ["Joker", "Greedy Joker", "Blueprint", "The Duo"]
    holo = CATALOG["Cavendish"]("Holographic")                   # its +10 Mult goes before the other xMult jokers
    jokers = [CATALOG["The Duo"](), holo, CATALOG["Joker"]()]
    assert [jokers[i] for i in joker_order(jokers)] == [jokers[2], holo, jokers[0]]


def test_the_orders_tried_include_blueprint_on_brainstorm_with_the_big_xmult_leftmost():
    # Cavendish leftmost for Brainstorm, Blueprint just left of Brainstorm: Cavendish's X3 three times, and the
    # + joker after Cavendish, before the other xMult jokers
    from balatro.bots import copier_orders
    names = ("Cavendish", "Joker", "Card Sharp", "Blueprint", "Brainstorm", "Steel Joker")
    jokers = [CATALOG[n]() for n in names]
    orders = [[jokers[i].name for i in o] for o in copier_orders(jokers)]
    assert any(o[0] == "Cavendish" and o[1] == "Joker" and o.index("Blueprint") + 1 == o.index("Brainstorm")
               for o in orders)
    assert len(orders) == len({tuple(o) for o in orders}) < 40
