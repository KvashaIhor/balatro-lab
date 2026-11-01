import math
import random

import pytest

from balatro.cards import Card
from balatro.jokers import CATALOG
from balatro.run import Run
from balatro.shop import Offer, Shop
from balatro.strategy import AVERAGE_STRAIN, ValueBot, Weights, genome_of, weights_of


def test_value_bot_plays_a_whole_seeded_run():
    res = Run(ValueBot(), game_seed="DD8JI5Y5", deck="Red Deck", max_ante=3).play()
    assert res.progress >= 3                       # gets past ante 1


def test_a_times_mult_joker_is_worth_more_than_a_plus_mult_one_to_an_empty_build():
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    base = bot.power(run)
    plus_four = bot.joker_worth(run, CATALOG["Joker"](), base)
    times_three = bot.joker_worth(run, CATALOG["Cavendish"](), base)
    assert 0 < plus_four < times_three
    assert run.jokers == []                        # valuing a joker leaves the run as it was


def _round(bot, hand, pile, needed):
    """A small blind in play with `needed` chips still to score, this hand dealt and this pile to draw from (top last)."""
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.blind = run.make_blind(0)
    run.in_round, run.round_score = True, run.blind.chips - needed
    run.hands_left, run.discards_left = 4, 3
    run.hand, run.draw_pile = hand, pile
    return run


def test_it_discards_towards_a_much_better_hand_even_when_playing_would_get_there():
    hand = [Card(2, "Hearts"), Card(5, "Hearts"), Card(9, "Hearts"), Card(13, "Hearts"),
            Card(3, "Clubs"), Card(7, "Diamonds"), Card(8, "Spades"), Card(10, "Clubs")]
    pile = [Card(4, "Spades"), Card(4, "Clubs"), Card(6, "Diamonds"), Card(14, "Hearts")]  # the Ace of Hearts comes first
    bot = ValueBot()
    run = _round(bot, hand, pile, needed=50)          # the King high card alone (15) four times would get there
    action = bot.round_action(run)
    assert action[0] == "discard"
    assert {run.hand[i].suit for i in action[1]} == {"Clubs", "Diamonds", "Spades"}   # keeps the four Hearts
    # holding a flush, with nothing as good to come, it plays it
    made = hand[:4] + [Card(7, "Hearts")] + [Card(3, "Clubs"), Card(8, "Spades"), Card(10, "Clubs")]
    run = _round(bot, made, [Card(2, "Spades"), Card(3, "Diamonds"), Card(4, "Diamonds"), Card(6, "Clubs")], needed=300)
    action = bot.round_action(run)
    assert action[0] == "play" and {run.hand[i].suit for i in action[1]} == {"Hearts"}


def test_it_never_discards_a_card_that_pays_for_being_held_and_discards_purple_seals_first():
    gold_king = Card(13, "Spades", enhancement="Gold")
    hand = [Card(2, "Hearts"), Card(5, "Hearts"), Card(9, "Hearts"), Card(12, "Hearts"),
            gold_king, Card(3, "Clubs", seal="Purple"), Card(8, "Diamonds"), Card(10, "Clubs", seal="Blue")]
    pile = [Card(r, "Hearts") for r in (3, 4, 6, 7, 11, 13, 14)] + [Card(4, "Spades"), Card(6, "Diamonds"), Card(7, "Clubs")]
    bot = ValueBot()                                  # (hearts left to draw: the four hearts in hand chase a flush)
    run = _round(bot, hand, pile, needed=50)
    action = bot.round_action(run)
    assert action[0] == "discard"
    tossed = [run.hand[i] for i in action[1]]
    assert gold_king not in tossed and not any(c.seal == "Blue" for c in tossed)
    assert any(c.seal == "Purple" for c in tossed)


def test_among_winning_plays_it_keeps_gold_cards_in_hand_for_their_money_but_plays_them_to_win():
    junk = [Card(2, "Clubs"), Card(3, "Diamonds"), Card(7, "Spades"), Card(9, "Hearts")]
    hand = [Card(13, "Spades", enhancement="Gold"), Card(13, "Hearts", enhancement="Gold"),
            Card(5, "Spades"), Card(5, "Hearts")] + junk
    bot = ValueBot()
    run = _round(bot, list(hand), [Card(4, "Spades")], needed=20)       # the 5s alone win: the Kings pay $6 held
    action = bot.round_action(run)
    assert action[0] == "play" and all(run.hand[i].enhancement != "Gold" for i in action[1])
    run = _round(bot, list(hand), [Card(4, "Spades")], needed=90)       # only Two Pair (100) wins: it plays them
    run.hands_left = 1
    action = bot.round_action(run)
    assert action[0] == "play" and sum(run.hand[i].enhancement == "Gold" for i in action[1]) == 2


def test_with_luck_expected_a_lucky_card_counts_its_average_mult_but_a_win_has_to_be_sure():
    from balatro.bots import estimate
    from balatro.hands import evaluate
    # a Straight holding two Lucky cards (65 x 4 = 260 for sure, 65 x 12 = 780 on average) or a Flush (74 x 4 = 296)
    hand = [Card(5, "Clubs", enhancement="Lucky"), Card(6, "Clubs", enhancement="Lucky"), Card(7, "Diamonds"),
            Card(8, "Hearts"), Card(9, "Hearts"), Card(2, "Hearts"), Card(11, "Hearts"), Card(13, "Hearts")]
    played = lambda run, action: {c.rank for c in (run.hand[i] for i in action[1])}     # noqa: E731
    bot = ValueBot()
    for luck, needed, wanted in ((False, 1000, {2, 8, 9, 11, 13}), (True, 1000, {5, 6, 7, 8, 9}),
                                 (True, 280, {2, 8, 9, 11, 13})):     # 280: only the Flush wins for sure
        run = _round(bot, list(hand), [Card(3, "Spades")], needed=needed)
        run.hands_left, run.discards_left, run.expect_luck = 1, 0, luck
        action = bot.round_action(run)
        assert action[0] == "play" and played(run, action) == wanted, (luck, needed)
    run = _round(bot, list(hand), [], needed=1000)
    run.expect_luck = True
    straight = hand[:5]
    assert estimate(run, straight, hand[5:]) == 780 and estimate(run, straight, hand[5:], sure=True) == 260
    run.jokers.append(CATALOG["Bloodstone"]())        # X1.5 1 in 2 for each Heart: X1.25 on average
    hearts = [Card(8, "Hearts"), Card(8, "Diamonds")]
    assert estimate(run, hearts, [], evaluate(hearts, run.rules)) == int((10 + 16) * 2 * 1.25)


def test_on_the_last_hand_it_plays_for_the_chance_to_win_not_the_average():
    from balatro.bots import win_odds
    from balatro.hands import evaluate
    # a Flush of 296 for sure; a pair of Kings 60, or 660 when the Lucky King comes off (1 in 5): 180 on average
    hand = [Card(13, "Spades", enhancement="Lucky"), Card(13, "Diamonds"), Card(2, "Hearts"), Card(8, "Hearts"),
            Card(9, "Hearts"), Card(11, "Hearts"), Card(12, "Hearts"), Card(4, "Clubs")]
    bot = ValueBot()
    for odds, hands, wanted in ((False, 1, "Flush"), (True, 1, "Pair"), (True, 2, "Flush")):   # 2: not the last
        bot.LAST_HAND_ODDS = odds
        run = _round(bot, list(hand), [Card(3, "Spades")] * 4, needed=500)
        run.hands_left, run.discards_left = hands, 0
        action = bot.round_action(run)
        played = [run.hand[i] for i in action[1]]
        assert action[0] == "play" and evaluate(played, run.rules).name == wanted, (odds, hands)
    assert 0.1 < win_odds(run, [0, 1], 500) < 0.3 and win_odds(run, [2, 3, 4, 5, 6], 500) == 0.0
    assert win_odds(run, [2, 3, 4, 5, 6], 250) == 1.0


def test_tarots_that_destroy_or_overwrite_cards_spare_enhanced_ones_and_death_copies_the_best():
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    hand = [Card(2, "Hearts", enhancement="Gold"), Card(3, "Clubs"), Card(4, "Spades"), Card(13, "Diamonds", enhancement="Steel"),
            Card(7, "Hearts")]
    run = _round(bot, hand, [], needed=50)
    for targets, _ in bot._uses(run, CONSUMABLES["The Hanged Man"](), run.hand):
        assert all(run.hand[i].enhancement is None for i in targets)
    (targets, _), = bot._uses(run, CONSUMABLES["Death"](), run.hand)
    assert run.hand[targets[0]].enhancement is None and run.hand[targets[1]].enhancement == "Steel"


def test_with_a_winning_hand_it_first_discards_what_mail_in_rebate_pays_for():
    bot = ValueBot()
    hand = [Card(14, "Spades"), Card(14, "Hearts"), Card(14, "Clubs"), Card(5, "Diamonds"), Card(7, "Clubs"),
            Card(9, "Spades"), Card(3, "Hearts"), Card(12, "Diamonds")]
    run = _round(bot, hand, [Card(2, "Spades")] * 4, needed=20)          # three Aces win at once
    rebate = CATALOG["Mail-In Rebate"]()
    rebate.rank = 7
    run.jokers = [rebate]
    action = bot.round_action(run)
    assert action == ("discard", [4])                                    # the 7 first: $5, the Aces stay


def test_it_plays_the_hand_that_keeps_ride_the_bus_growing():
    bot = ValueBot()
    hand = [Card(13, "Spades"), Card(13, "Hearts"), Card(9, "Clubs"), Card(9, "Diamonds"), Card(2, "Clubs"),
            Card(4, "Spades"), Card(6, "Hearts"), Card(8, "Diamonds")]
    run = _round(bot, hand, [], needed=10)                               # either pair wins
    bus = CATALOG["Ride the Bus"]()
    bus.value = 20
    run.jokers = [bus]
    run.discards_left = 0
    action = bot.round_action(run)
    assert action[0] == "play" and not any(run.hand[i].rank == 13 for i in action[1])   # no scoring King


def test_with_satellite_a_planet_never_used_is_bought_for_what_it_will_pay():
    from balatro.items import CONSUMABLES
    for owned in ([], ["Satellite"]):
        bot = ValueBot()
        bot.w = Weights()
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
        run.money = 10
        run.jokers = [CATALOG[n]() for n in owned]
        shop = Shop(run)
        shop.cards, shop.packs, shop.vouchers = [Offer("Planet", CONSUMABLES["Eris"]())], [], []   # Flush Five
        bought = bot.shop_action(run, shop)[0] == "buy_use"
        assert bought == bool(owned)


def test_a_joker_that_pays_every_round_is_worth_that_money_at_its_strength_and_a_negative_rocket_is_bought():
    from balatro.modifiers import rounds_left
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="K74LGZC6", deck="Red Deck")
    run.ante = 2
    base = bot.power(run)
    golden = CATALOG["Golden Joker"]()
    assert bot.joker_worth(run, golden, base) == bot.bonus(golden)          # off by default (it made the bot worse)
    bot.w.mods["Golden Joker"] = 1.0
    assert abs(bot.joker_worth(run, golden, base) - bot.bonus(golden) - bot.dollars_worth(run, 4 * rounds_left(run))) < 1e-9
    assert bot.dollars_worth(run, 4 * rounds_left(run)) < 4 * rounds_left(run) * bot.w.money    # (past the reserve: spare)
    bot.w.grows = -0.5                             # (an evolved champion's: Rocket's payout grows, not its power)
    run.money = 40                                 # (enough that buying it costs no interest)
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [Offer("Joker", CATALOG["Rocket"]("Negative"))], [], []
    assert bot.shop_action(run, shop) == ("buy", "card", 0)


def test_it_sells_invisible_joker_once_ripe_for_the_copy_it_makes():
    for rounds, sold in ((1, False), (2, True)):
        bot = ValueBot()
        bot.w = Weights()
        run = Run(bot, game_seed="1VAXB1X6", deck="Red Deck")
        invisible = CATALOG["Invisible Joker"]()
        invisible.rounds = rounds
        run.jokers = [CATALOG["Cavendish"](), invisible]
        shop = Shop(run)
        shop.cards, shop.packs, shop.vouchers = [], [], []
        action = bot.shop_action(run, shop)
        while action[0] == "order_jokers":                                   # (as a run applies them)
            run.free_action(action)
            action = bot.shop_action(run, shop)
        k = run.jokers.index(invisible)
        assert (action == ("sell_joker", k)) == sold
    run.sell_joker(k)
    assert [j.name for j in run.jokers] == ["Cavendish", "Cavendish"]


def test_blueprint_is_valued_where_it_copies_the_best_joker():
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG[n]() for n in ("Joker", "Sly Joker", "Cavendish", "The Duo")]
    base = bot.power(run)
    cavendish = bot.joker_worth(run, CATALOG["Cavendish"](), base)
    blueprint = bot.joker_worth(run, CATALOG["Blueprint"](), base) - bot.bonus(CATALOG["Blueprint"]())
    assert blueprint > 0.9 * (cavendish - bot.bonus(CATALOG["Cavendish"]()))     # a second Cavendish, near enough


def test_before_a_blind_ceremonial_dagger_goes_where_it_has_no_joker_to_destroy():
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    cavendish = CATALOG["Cavendish"]()
    run.jokers = [CATALOG["Ceremonial Dagger"](), cavendish]       # the usual order: +Mult before xMult
    action = bot._reorder(run)
    assert action == ("order_jokers", [1, 0])
    run.jokers = [run.jokers[i] for i in action[1]]
    run.blind = run.make_blind(0)
    for j in list(run.jokers):
        j.on_blind_select(run, run.blind)
    assert cavendish in run.jokers
    run.in_round = True                                            # in a round, the order for scoring again
    assert bot._play_order(run) == [1, 0]


def test_it_places_brainstorm_to_copy_the_joker_that_scores_this_hand_best():
    bot = ValueBot()
    hand = [Card(r, s) for r, s in ((13, "Spades"), (13, "Hearts"), (2, "Clubs"), (5, "Diamonds"), (7, "Clubs"),
                                    (9, "Spades"), (11, "Hearts"), (4, "Diamonds"))]
    run = _round(bot, hand, [], needed=10_000)
    run.hand_levels["Pair"] = 5                    # Mult 6: copying x3 beats copying +4 ((6x3+4)x3 vs (6+8)x3)
    run.jokers = [CATALOG["Joker"](), CATALOG["Brainstorm"](), CATALOG["Cavendish"]()]
    order = bot._play_order(run)
    assert order is not None and run.jokers[order[0]].name == "Cavendish"    # Brainstorm copies x3, not +4


def test_a_free_joker_is_bought_for_at_least_its_resale_and_sold_if_that_is_all_it_is_worth():
    bot = ValueBot()
    bot.w = Weights()
    bot.w.rarity = (0.0, 0.0) + bot.w.rarity[2:]     # Dusk (Uncommon) worth nothing beyond what it does
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.money = 50
    shop = Shop(run)
    dusk = CATALOG["Dusk"]()                         # retriggers the final hand only: nothing as a round starts
    shop.cards, shop.packs, shop.vouchers = [Offer("Joker", dusk, free=True)], [], []
    assert bot.shop_action(run, shop) == ("buy", "card", 0)   # free: worth at least the $2 it sells for
    assert shop.buy("card", 0) and dusk in run.jokers
    bot.w.joker["Dusk"] = -0.5                       # once it clearly isn't worth keeping, it is sold
    run.shops_seen += 1                              # (the next shop: owned jokers are valued afresh)
    assert bot.shop_action(run, shop) == ("sell_joker", 0)


def test_with_money_to_spare_it_buys_blank_for_the_antimatter_it_opens_up():
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [], [], [Offer("Voucher", "Blank")]
    run.money = 205
    assert bot.shop_action(run, shop) == ("buy", "voucher", 0)
    # money beyond the interest reserve costs a quarter as much: $10 of $205 against $10 of $30
    assert bot.price(run, 10) < bot.price(Run(bot, game_seed="DD8JI5Y5", deck="Red Deck"), 10)
    run.money = 35                                   # at the reserve ($25 for interest, RESERVE_EXTRA $10 more)
    held = bot.price(run, 10)
    bot.RESERVE_EXTRA = 0                            # without the $10: the $10 above $25 is spare
    assert bot.price(run, 10) == pytest.approx(bot.w.money * bot.spare_money * 10) and bot.price(run, 10) < held


def test_to_make_room_it_never_sells_a_negative_joker():
    bot = ValueBot()
    bot.w = Weights()
    bot.w.negative = -0.5                           # the low end evolution may pick: Negative jokers valued least
    bot.w.sell_margin = 0.4                         # (so it isn't simply sold for its money; the swap is what's tested)
    bot.EXTRA = 0                                   # (plain sample hands: the swap is what's tested, not the estimate)
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.money = 50
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "Zany Joker", "Mad Joker", "Crazy Joker")]
    weak = CATALOG["Jolly Joker"]("Negative")       # a second Jolly adds little: the weakest, but it takes no slot
    run.jokers.append(weak)
    base = bot.power(run)
    assert min(range(6), key=lambda k: bot.owned_worth(run, k, base)) == 5
    assert not run.joker_room()
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [Offer("Joker", CATALOG["Cavendish"]())], [], []
    action = bot.shop_action(run, shop)
    assert action[0] == "sell_joker" and run.jokers[action[1]] is not weak


def test_the_estimate_sees_acrobat_dusk_card_sharp_and_loyalty_card_on_the_hand_it_scores():
    from balatro.bots import estimate
    bot = ValueBot()
    pair = [Card(13, "Spades"), Card(13, "Hearts")]
    run = _round(bot, pair + [Card(2, "Clubs")], [], needed=10_000)
    plain = estimate(run, pair, run.hand[2:])
    for name, factor in (("Acrobat", 3), ("Dusk", None), ("Card Sharp", 3), ("Loyalty Card", 4)):
        j = CATALOG[name]()
        run.jokers = [j]
        assert estimate(run, pair, run.hand[2:]) == plain             # not this hand yet
        if name in ("Acrobat", "Dusk"):
            run.hands_left = 1                                        # the final hand
        elif name == "Card Sharp":
            run.round_hand_types["Pair"] = 1                          # a Pair played before this round
        else:
            j.since = run.hands_played - 5                            # this is the 6th hand since it joined
        now = estimate(run, pair, run.hand[2:])
        assert now == plain * factor if factor else now > plain
        run.hands_left, run.round_hand_types = 4, type(run.round_hand_types)()


def test_power_counts_acrobat_on_one_hand_of_a_round_and_its_strength_scales_that():
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG["Joker"]()]
    acrobat = CATALOG["Acrobat"]()
    worth = lambda: bot.joker_worth(run, acrobat, bot.power(run)) - bot.bonus(acrobat)   # noqa: E731
    assert 0.15 < worth() < 0.4                                       # about log(3) / 4: X3 on one hand of four
    bot.w.mods["Acrobat"] = 0.0
    bot._powers.clear()
    assert abs(worth()) < 1e-9


def test_rules_value_what_a_play_pays_or_grows():
    from balatro.hands import evaluate
    from balatro.modifiers import Measure, play_bonus
    cases = [("Rough Gem", [Card(13, "Diamonds")], [Card(13, "Spades")]),
             ("Business Card", [Card(13, "Spades")], [Card(9, "Spades")]),
             ("Midas Mask", [Card(13, "Spades")], [Card(9, "Spades")]),
             ("Golden Ticket", [Card(9, "Spades", enhancement="Gold")], [Card(9, "Spades")]),
             ("Wee Joker", [Card(2, "Spades")], [Card(9, "Spades")]),
             ("Hiker", [Card(9, "Spades"), Card(9, "Hearts")], [Card(9, "Spades")]),
             ("Lucky Cat", [Card(9, "Spades", enhancement="Lucky")], [Card(9, "Spades")]),
             ("Vampire", [Card(9, "Spades", enhancement="Mult")], [Card(9, "Spades")]),
             ("8 Ball", [Card(8, "Spades")], [Card(9, "Spades")]),
             ("Supernova", [Card(9, "Spades"), Card(9, "Hearts")], None)]
    for name, more, less in cases:
        bot = ValueBot()
        bot.w = Weights()
        bot.EXTRA = 0                               # plain sample hands, where a Pair is often the best play
        run = _round(bot, more + (less or []) + [Card(3, "Clubs")], [], needed=10_000)
        run.jokers = [CATALOG["Joker"](), CATALOG[name]()]
        m = Measure(bot, run)
        bonus = lambda cards: play_bonus(bot, m, cards, evaluate(cards, run.rules))   # noqa: E731
        assert bonus(more) > (bonus(less) if less else 0.0), name


def test_among_winning_plays_it_plays_the_straight_superposition_pays_a_tarot_for():
    hand = [Card(10, "Hearts"), Card(11, "Hearts"), Card(12, "Hearts"), Card(13, "Spades"), Card(14, "Clubs"),
            Card(2, "Hearts"), Card(5, "Hearts"), Card(3, "Spades")]
    for owned in ([], ["Superposition"]):
        bot = ValueBot()
        bot.w = Weights()
        run = _round(bot, list(hand), [], needed=50)                 # both win: the Flush scores more
        run.hand_levels["Flush"] = 3
        run.jokers = [CATALOG[n]() for n in owned]
        action = bot.round_action(run)
        played = evaluate_played(run, action)
        assert played == ("Straight" if owned else "Flush")


def evaluate_played(run, action):
    from balatro.hands import evaluate
    assert action[0] == "play"
    return evaluate([run.hand[i] for i in action[1]], run.rules).name


def test_red_card_skips_a_pack_for_its_mult_and_flash_card_rerolls_for_its():
    from balatro.shop import PACKS, OpenPack
    standard = next(p for p in PACKS.values() if p.kind == "Standard" and p.size == "Normal")
    for owned in ([], ["Red Card"]):
        bot = ValueBot()
        bot.w = Weights()
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
        run.jokers = [CATALOG[n]() for n in owned]
        action = bot.pack_action(run, OpenPack(standard, [Card(7, "Clubs"), Card(4, "Hearts")], 1))
        assert action[0] == ("skip" if owned else "pick")
    for owned in ([], ["Flash Card"]):
        bot = ValueBot()
        bot.w = Weights()
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
        bot.w.reroll = 0.0                         # (no weight on a reroll itself: only Flash Card's Mult pays for it)
        run.money, run.jokers = 60, [CATALOG[n]() for n in owned]
        shop = Shop(run)
        shop.cards, shop.packs, shop.vouchers = [], [], []
        assert bot.shop_action(run, shop) == (("reroll",) if owned else ("leave",))


def test_a_planet_worth_buying_is_bought_before_a_reroll_throws_it_away():
    # the user's 6AWQ2FCT (30 Oct, ante 8, $77): "why not buy pluto while we are here? its like it rerolls for
    # rerolling"; the reroll read +0.057 and Pluto +0.040, and Pluto went with the reroll
    from balatro.items import CONSUMABLES
    for on in (True, False):
        bot = ValueBot()
        bot.w = Weights()
        bot.CARDS_BEFORE_REROLL = on
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
        run.money, run.jokers = 60, [CATALOG["Flash Card"]()]
        bot.w.reroll = 1.0                             # (the reroll best, whatever Pluto is worth)
        shop = Shop(run)
        shop.cards, shop.packs, shop.vouchers = [Offer("Planet", CONSUMABLES["Pluto"]())], [], []
        action = bot.shop_action(run, shop)
        assert bot.worths[("buy_use", 0, ())] > 0
        assert action == (("buy_use", 0, []) if on else ("reroll",))
        run.money = shop.reroll_cost + 1                  # Pluto bought, the reroll no longer affordable: the reroll
        assert bot.shop_action(run, shop) == ("reroll",)


def test_flash_card_grows_at_the_bots_own_reroll_rate_ahead_before_the_run_has_rerolled():
    # the user's 6AWQ2FCT (30 Oct, ante 3, no reroll yet): "flash card here beats sly given number of rerolls"; it
    # was projected to grow by the run's own rate so far, 0, and lost to every joker held
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.ante, run.rounds_played, run.hands_played, run.rerolls_done = 3, 5, 12, 0
    run.start_ante()
    run.jokers = [CATALOG["Joker"]()]
    flash = CATALOG["Flash Card"]()
    assert bot.growth_worth(run, flash) > 0.05


def test_with_bull_money_spent_costs_the_chips_it_gave():
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.money = 20
    plain = bot.price(run, 10)
    run.jokers = [CATALOG["Bull"]()]
    assert bot.price(run, 10) > plain + 0.05


def test_interest_lost_counts_until_the_purse_is_back_at_the_cap_and_bulls_chips_not_on_top_of_the_money():
    bot = ValueBot()
    bot.w = Weights()
    bot.INTEREST_REFILL = True
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    interest = lambda m: min(run.interest_cap, max(0, m) // 5)   # noqa: E731
    assert bot._interest_lost(32, 10, interest) == 1           # $5 -> $4 once: $22 + $6 + $4 is past the cap
    assert bot._interest_lost(12, 5, interest) == 4            # $2/$1, $4/$2, $5/$4, then both capped
    run.money = 32
    assert bot.price(run, 10) == pytest.approx(bot.w.money * (10 + 1))
    run.jokers = [CATALOG["Bull"]()]
    both = bot.price(run, 10)
    bot.MONEY_ONCE = True
    once = bot.price(run, 10)
    assert once < both and once >= bot.w.money * (10 + 1)


def test_mime_is_worth_the_gold_cards_it_pays_for_twice():
    from balatro.modifiers import income, rounds_left
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    for c in run.deck[:12]:
        c.enhancement = "Gold"
    mime = CATALOG["Mime"]()
    gold = run.deck[0]
    assert bot.MIME_HELD                                         # on by default since 28 Oct
    bot.MIME_HELD = False
    assert income(bot, run, mime) == 0.0                         # off: its scoring only, as before
    plain = bot._card_economy(run, gold)
    bot.MIME_HELD = True
    # 12 Gold cards, 8 held of 52: each pays $3 once more a round
    assert income(bot, run, mime) == pytest.approx(bot.w.money * 3 * 12 * 8 / 52 * rounds_left(run))
    assert bot._card_economy(run, gold) == pytest.approx(plain)   # no Mime held yet
    run.jokers.append(mime)
    assert bot._card_economy(run, gold) == pytest.approx(2 * plain)
    gold.seal = "Red"
    assert bot._card_economy(run, gold) == pytest.approx(3 * plain)


def test_shops_left_count_the_shops_before_the_runs_last_boss():
    from balatro.modifiers import shops_left
    run = Run(ValueBot(), game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.ante = 8
    run.start_ante()
    run.blind = run.make_blind(1)                      # the Big Blind beaten: the last boss next
    assert shops_left(run) == 0
    run.blind = run.make_blind(0)
    assert shops_left(run) == 1
    run.blind = run.make_blind(2)                      # ante 7's boss beaten (the ante has moved on to 8)
    assert shops_left(run) == 2
    run.max_ante = 16
    run.blind = run.make_blind(1)
    assert shops_left(run) == 24


def test_money_is_worth_less_where_the_next_boss_likely_ends_the_run_and_nothing_in_its_last_shop():
    from balatro.items import BOSSES
    bot = ValueBot()
    bot.w = Weights()
    bot.BEHIND_GAMBLE = False                                     # (on since 30 Oct: its own test below)
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.ante = 8
    run.start_ante()
    run.ante_boss = BOSSES["Violet Vessel"]()
    run.blind = run.make_blind(1)
    assert bot.money_scale(run) == (0.0, 0.0)                     # END_MONEY (on): the last shop, nothing to spend it on
    bot.END_MONEY = False
    assert bot.money_scale(run) == (1.25, 1.25)                   # and off: MONEY_SCALE (1.25), RISK_MONEY off (the default)
    bot.MONEY_SCALE = 1.0
    assert bot.money_scale(run) == (1.0, 1.0)
    bot.END_MONEY = True
    run.blind = run.make_blind(2)
    assert bot.money_scale(run) == (1.0, pytest.approx(2 / 5))   # two shops left for interest to be spent in
    bot.END_MONEY = False
    bot.RISK_MONEY = 0.5
    run.blind = run.make_blind(0)                                 # no jokers against Violet Vessel: hopeless
    assert bot.money_scale(run)[0] == pytest.approx(1 / (1 + 0.5 * 2 * 4), abs=0.01)
    run.ante = 1
    run.start_ante()
    run.blind = run.make_blind(0)
    run.jokers = [CATALOG[n]() for n in ("Cavendish", "The Duo", "Jolly Joker", "Joker", "Zany Joker")]
    assert bot.money_scale(run)[0] > 0.95                         # a strong build at ante 1: as before
    bot.RISK_MONEY, bot.MONEY_SCALE = 0.0, 1.5
    assert bot.money_scale(run) == (1.5, 1.5)                     # money worth more everywhere
    bot.MONEY_SCALE, bot.SURPLUS = 1.25, 0.4
    assert bot.money_scale(run)[0] == pytest.approx(1.25 * 1.4, abs=0.02)   # SURPLUS: the strong build, more
    run.ante = 8
    run.start_ante()
    run.ante_boss = BOSSES["Violet Vessel"]()
    run.blind = run.make_blind(0)
    run.jokers = []
    assert bot.money_scale(run) == (1.25, 1.25)                   # and nothing more where the boss likely wins
    bot.INTEREST_SCALE = 1.5
    assert bot.money_scale(run) == (1.25, 1.5)                    # interest scaled apart


def test_in_the_last_shop_it_rerolls_the_interest_reserve_it_would_otherwise_keep():
    for end, want in ((False, ("leave",)), (True, ("reroll",))):
        bot = ValueBot()
        bot.END_MONEY = end
        bot.BEHIND_GAMBLE = False                                 # (a jokerless deck before ante 8's boss: it rerolls too)
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
        run.ante = 8
        run.start_ante()
        run.blind = run.make_blind(1)
        run.money = 30                                            # within the reserve ($25 for interest, $10 more)
        shop = Shop(run)
        shop.cards, shop.packs, shop.vouchers = [], [], []
        assert bot.shop_action(run, shop) == want
        assert "w" not in bot.__dict__ and bot.w.money == ValueBot.w.money   # the class's weights, unscaled


def test_power_from_its_cache_is_power_afresh_when_the_pile_or_a_joker_has_changed():
    for exact in (False, True):
        bot = ValueBot()
        bot.POWER_EXACT = exact
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
        run.jokers = [CATALOG["Blue Joker"](), CATALOG["Green Joker"]()]
        run.draw_pile = list(run.deck[:5])                # the shop after a round: a few cards left in the pile
        before = bot.power(run)
        run.draw_pile = list(run.deck)                    # the next round's start: the pile full again
        run.jokers[1].value = 5                           # and Green Joker grown
        cached, fresh = bot.power(run), bot.power(run, fresh=True)
        assert fresh > before
        if exact:
            assert cached == fresh
        else:
            assert cached == before                       # what RZ364T64's boss round used (28 Oct)


def test_with_the_round_won_anyway_it_throws_mail_in_rebates_rank_whatever_banner_loses():
    hand = [Card(14, "Diamonds"), Card(10, "Diamonds"), Card(9, "Spades"), Card(7, "Clubs"), Card(6, "Clubs"),
            Card(4, "Clubs"), Card(3, "Clubs"), Card(2, "Spades"), Card(2, "Diamonds")]   # C5X6MXUN's Big Blind (28 Oct)
    pile = [Card(r, "Hearts") for r in (5, 8, 12, 13)]
    for won in (False, True):
        bot = ValueBot()
        bot.PAID_WON = won
        run = _round(bot, list(hand), list(pile), needed=100)          # a pair of 2s wins (Banner or not)
        rebate, banner = CATALOG["Mail-In Rebate"](), CATALOG["Banner"]()
        rebate.rank = 9
        run.jokers = [banner, rebate]
        action = bot.round_action(run)
        if won:
            assert action == ("discard", [2])                         # the 9: $5, and the round is won anyway
        else:
            assert action[0] == "play"                                # Banner's 30 chips outweighed the $5


def test_income_strength_counts_cloud_9_and_lasting_payments_run_to_the_runs_last_boss():
    from balatro.modifiers import income, rounds_left
    bot = ValueBot()
    bot.SURVIVAL_HORIZON = False                                   # the old rule's arithmetic (survival: its own test)
    run = Run(bot, game_seed="C5X6MXUN", deck="Abandoned Deck", max_ante=12)
    run.ante = 4
    cloud = CATALOG["Cloud 9"]()
    assert income(bot, run, cloud) == 0.0                          # off (modifiers.OFF), as before
    bot.INCOME_STRENGTH = 1.0
    nines = sum(c.rank == 9 for c in run.deck)
    assert nines == 4                                              # no face cards: four of each rank
    assert income(bot, run, cloud) == pytest.approx(nines * rounds_left(run) * bot.w.money)
    assert rounds_left(run) == 0.5 * 3 * 9                         # antes 4 to 12, not to 8
    run.max_ante = 8
    assert rounds_left(run) == 0.5 * 3 * 5


def test_with_pay_from_play_hand_payers_count_what_the_runs_hands_scored_and_held():
    from balatro.modifiers import OWN_HANDS, hand_pay, income, rounds_left
    bot = ValueBot()
    bot.SURVIVAL_HORIZON = False                                   # the old rule's arithmetic (survival: its own test)
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.blind = run.make_blind(0)
    run.in_round = True
    k, q, two = Card(13, "Spades"), Card(12, "Diamonds"), Card(2, "Clubs")
    for _ in range(OWN_HANDS):                         # a pair of face cards played, a face card held, each hand
        run.hand, run.hands_left = [Card(13, "Hearts"), Card(13, "Clubs"), k, two, q], 4
        run.play_hand([0, 1])
    assert run.pay_seen == {"faces": 12, "diamonds": 0, "gold": 0, "held faces": 12}
    run.rounds_played = 2                              # 3 hands a round
    assert hand_pay(run, "Business Card", own=True) == pytest.approx(0.5 * 2 * 2 * 3)      # 2 faces scored a hand
    assert hand_pay(run, "Reserved Parking", own=True) == pytest.approx(0.5 * 2 * 3)       # 2 faces held
    assert hand_pay(run, "Business Card") < hand_pay(run, "Business Card", own=True)       # the deck's share: 3/13
    sat = CATALOG["Satellite"]()
    run.planets_used = {"Pluto", "Mercury"}            # 2 types in 2 rounds: 1 a round to come
    run.max_ante = 8                                   # 12 rounds counted: 2 now, 14 at their end, 8 on average
    now = income(bot, run, sat)
    bot.PAY_FROM_PLAY = True
    assert rounds_left(run) == 12 and income(bot, run, sat) == pytest.approx(now * 8 / 2)
    run.max_ante = 16                                  # 24 rounds: 2 + 12 on average, but only 9 types to find
    assert income(bot, run, sat) == pytest.approx(now * 24 / 12 * 9 / 2)


def test_jokers_that_pay_for_discards_are_worth_their_typical_takings():
    from balatro.modifiers import discard_pay, income
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    rebate = CATALOG["Mail-In Rebate"]()
    assert income(bot, run, rebate) == 0.0                         # off: nothing, as before
    bot.DISCARD_INCOME = True
    seen = run.hand_size + 3 * run.base_discards                   # the hand and each discard's refill (Red Deck: 4)
    assert discard_pay(run, "Mail-In Rebate") == pytest.approx(0.5 * 5 * seen / 13)
    assert income(bot, run, rebate) > 0.3                          # about $3 a round over half the rounds to ante 8
    assert 0 < discard_pay(run, "Faceless Joker") < discard_pay(run, "Mail-In Rebate")
    run.base_discards = 0
    assert discard_pay(run, "Trading Card") == 0.0                 # no discards: nothing


def test_with_the_consumable_slots_full_a_much_better_tarot_is_bought_in_place_of_the_least():
    from balatro.items import CONSUMABLES
    from balatro.models import make
    from balatro.shop import Offer
    for swap in (False, True):
        bot = make("value")
        bot.CONSUMABLE_SWAP = swap
        run = Run(bot, game_seed="ALEEB", deck="Red Deck", max_ante=8)
        run.money = 20
        run.consumables = [CONSUMABLES["The Moon"](), CONSUMABLES["The Empress"]()]   # a suit Tarot: next to nothing
        shop = Shop(run)
        shop.cards, shop.packs, shop.vouchers = [Offer("Tarot", CONSUMABLES["The Empress"]())], [], []
        least = bot.keep_worth(run, run.consumables[0])
        assert bot.keep_worth(run, shop.cards[0].item) - least > bot.w.sell_margin
        move = bot.shop_action(run, shop)
        assert move == (("sell_consumable", 0) if swap else ("leave",))


def test_out_of_a_round_power_sees_the_pile_a_round_starts_with_not_what_the_last_one_left():
    for pile_too in (False, True):
        bot = ValueBot()
        bot.POWER_PILE = pile_too
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
        run.jokers = [CATALOG["Blue Joker"]()]
        powers = []
        for left in (5, 40):                              # what the last round left in the pile
            run.draw_pile = list(run.deck[:left])
            powers.append(bot.power(run, fresh=True))
        assert len(run.draw_pile) == 40                   # put back as it was
        if pile_too:
            assert powers[0] == powers[1]
        else:
            assert powers[0] < powers[1]


def test_an_arcana_pack_is_worth_the_best_of_the_tarots_it_likely_shows():
    from balatro.shop import PACKS

    class Stop(Exception):
        pass

    def first_shop(bot):
        """ALEEB's shop after ante 1's Big Blind ($5: The Empress $3, Ceremonial Dagger $6, a Standard and an Arcana
        Pack), as the value bot of the Lab plays it."""
        seen = {}

        def shop_action(run, shop):
            move = type(bot).shop_action(bot, run, shop)
            if any(getattr(o.item, "name", "") == "The Empress" for o in shop.cards):
                seen["move"] = move
                raise Stop
            return move
        def pack_action(run, pack):                   # the path these numbers were measured on: the Buffoon Pack
            if any(getattr(x, "name", "") == "Riff-Raff" for x in pack.cards):   # skipped, as before the resale
                return ("skip",)                      # floor (29 Oct: now Riff-Raff is taken, and the shop differs)
            return type(bot).pack_action(bot, run, pack)
        bot.shop_action, bot.pack_action = shop_action, pack_action
        try:
            Run(bot, game_seed="ALEEB", deck="Red Deck", max_ante=16).play()
        except Stop:
            pass
        return seen["move"]

    from balatro.models import make
    old, cheap = make("value"), make("value")
    cheap.PACK_TRUST = True
    old.BEHIND_GAMBLE = cheap.BEHIND_GAMBLE = False   # (on since 30 Oct: Canio alone likely loses ante 1's boss, so money
                                                      # counts at the odds of surviving it and the pack's gross wins)
    assert first_shop(old) == ("buy", "card", 0)      # The Empress (+0.250; the pack +0.070, flat)
    assert first_shop(cheap) == ("buy", "pack", 1)    # the pack at twice its weight (+0.32); it held The Soul. Measured
                                                      # (PACK_MEASURED) the pack is 0.233 to The Empress's 0.41: the Empress

    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    worths = {}
    bot._pack_card_worth = lambda run, c: worths.setdefault(c.name, len(worths) * 0.01)
    bot.PACK_DRAWS = 99                                # every Tarot weighed
    pack = PACKS["Arcana Pack"]
    v = bot.pack_worth(run, pack)
    from balatro.strategy import _top_sum
    assert v == pytest.approx(_top_sum(sorted(worths.values(), reverse=True), 3, 1))
    assert len(worths) >= 20                           # the Tarots it can deal (The Soul left out)
    bot.PACK_TRUST = True
    assert bot.pack_weight(run, pack) == pytest.approx(bot.w.packs["Arcana"] * bot.KEEP_TRUST)


def test_jokers_that_pay_as_hands_are_played_are_worth_their_typical_takings():
    from balatro.modifiers import hand_pay, income
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    parking = CATALOG["Reserved Parking"]()
    assert bot.HAND_INCOME                                      # on by default since 28 Oct
    bot.HAND_INCOME = False
    assert income(bot, run, parking) == 0.0                     # off: counted nothing, as before
    bot.HAND_INCOME = True
    # 8 cards, 4 held, 12 faces in 52, 1 in 2, two hands a round: $1.38 a round
    assert hand_pay(run, "Reserved Parking") == pytest.approx(0.5 * 4 * 12 / 52 * 2)
    assert income(bot, run, parking) > 0.1
    assert hand_pay(run, "Golden Ticket") == 0.0                # no Gold card in the deck


def test_tarots_that_change_a_card_or_two_are_worth_what_they_do():
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    bot.w = Weights()
    bot.EXTRA = 0                                   # (plain sample hands: the measure, not the estimate's size)
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    picks = [(2, "Clubs"), (3, "Diamonds"), (14, "Spades"), (14, "Hearts"), (9, "Clubs"), (7, "Hearts"), (5, "Spades"), (12, "Diamonds")]
    run.hand = [next(c for c in run.deck if (c.rank, c.suit) == rs) for rs in picks]

    def worth(name, targets):
        return bot.effect_worth(run, lambda t: t.apply_consumable(CONSUMABLES[name](), t.cards_at(targets)))
    # one or two cards changed: among power's 12 sample hands these used to count for nothing
    for name, targets in (("The Hierophant", [2, 3]), ("The Empress", [2, 3]), ("The Magician", [2, 3]),
                          ("The Devil", [2]), ("The High Priestess", [])):
        assert worth(name, targets) > 0, name
    assert worth("Death", [0, 2]) > 0.02                                       # the 2 becomes a copy of the Ace
    assert abs(worth("The Hanged Man", [0, 1])) < 0.1                          # thinning: small either way (noisy)
    assert worth("The Empress", [2, 3]) == worth("The Empress", [2, 3])        # the same hands every time
    assert run.hand[2].enhancement is None and len(run.deck) == 52             # tried on copies only


def test_a_hand_that_cannot_win_is_never_played_while_a_discard_is_left():
    bot = ValueBot()
    hand = [Card(2, "Hearts"), Card(5, "Clubs"), Card(9, "Spades"), Card(13, "Diamonds"),
            Card(3, "Clubs"), Card(7, "Diamonds"), Card(8, "Spades"), Card(10, "Clubs")]
    pile = [Card(4, "Spades"), Card(4, "Clubs"), Card(6, "Diamonds"), Card(11, "Hearts"), Card(12, "Hearts")]
    # The Needle: one hand, far short of the blind, and the next draw is no better: still a discard
    run = _round(bot, list(hand), list(pile), needed=5_000)
    run.hands_left = 1
    assert bot.round_action(run)[0] == "discard"
    # nothing would score (The Mouth after another hand type): never waste a hand on it
    assert bot._worth_discarding(run, 0, 0, 1_000)
    # losing the round otherwise outweighs what Delayed Gratification pays for discards kept
    run.hands_left = 4
    assert bot._worth_discarding(run, 100, 120, 1_000, extra=-0.5)
    assert not bot._worth_discarding(run, 300, 320, 1_000, extra=-0.5)   # here playing on gets there


def _boss_round(bot, boss, hand, pile, needed):
    from balatro.items import BOSSES
    run = _round(bot, hand, pile, needed)
    run.ante_boss = BOSSES[boss]()
    run.blind = run.make_blind(2)
    run.round_score = run.blind.chips - needed
    run.blind.boss.on_select(run)
    return run


def test_under_the_mouth_it_opens_with_a_hand_it_can_repeat():
    from balatro.bots import best_play
    from balatro.hands import evaluate
    hand = [Card(3, "Hearts"), Card(4, "Clubs"), Card(5, "Diamonds"), Card(6, "Spades"), Card(7, "Hearts"),
            Card(2, "Clubs"), Card(2, "Diamonds"), Card(9, "Spades")]
    # no 10s and no low cards left: never another Straight, while a Pair comes every hand
    pile = [Card(r, s) for r in (8, 9, 11, 12, 13) for s in ("Clubs", "Diamonds")]
    bot = ValueBot()
    run = _boss_round(bot, "The Mouth", list(hand), list(pile), needed=700)
    run.hand_levels["Pair"] = 3
    run.discards_left = 0
    straight = best_play(run)
    assert evaluate([run.hand[i] for i in straight[1]], run.rules).name == "Straight"   # 220 against the 2s' 176
    action = bot.round_action(run)
    assert action[0] == "play" and evaluate([run.hand[i] for i in action[1]], run.rules).name == "Pair"


def test_under_the_ox_it_keeps_its_money_unless_the_hand_is_worth_more():
    from balatro.hands import evaluate
    hand = [Card(13, "Hearts"), Card(13, "Clubs"), Card(12, "Diamonds"), Card(12, "Spades"), Card(2, "Hearts"),
            Card(4, "Clubs"), Card(6, "Diamonds"), Card(9, "Spades")]
    bot = ValueBot()
    run = _boss_round(bot, "The Ox", list(hand), [], needed=5_000)
    run.blind.boss.hand = "Two Pair"
    run.discards_left = 0
    played = lambda: evaluate([run.hand[i] for i in bot.round_action(run)[1]], run.rules).name
    run.money = 30
    assert played() == "Pair"            # Two Pair (120) over a Pair (60) isn't worth $30 and its interest
    run.money = 0
    assert played() == "Two Pair"


def test_a_few_dollars_short_it_sells_its_weakest_joker_to_buy_a_much_better_one():
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG["Chaos the Clown"](), CATALOG["Cavendish"]()]      # Chaos the Clown adds nothing to a hand
    run.money = 8
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [Offer("Joker", CATALOG["Blueprint"]())], [], []   # $10: a second Cavendish
    assert bot.shop_action(run, shop) == ("sell_joker", 0)
    run.money += run.sell_value(run.jokers[0])
    run.jokers = run.jokers[1:]
    run.shops_seen += 1                                                       # (owned jokers valued afresh)
    assert bot.shop_action(run, shop) == ("buy", "card", 0)


def test_it_skips_a_blind_for_a_strong_tag_only_when_its_build_is_safe_without_the_shop():
    from balatro.items import TAGS
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    small = run.make_blind(0)
    investment, boss = TAGS["Investment Tag"](), TAGS["Boss Tag"]()
    assert not bot.skip_blind(run, small, investment)          # no jokers: a round couldn't beat the Big Blind safely
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "The Duo", "Cavendish")]
    bot._powers.clear()
    assert bot.skip_blind(run, small, investment)              # $25 later beats the Small Blind's reward and shop
    assert not bot.skip_blind(run, small, boss)                # a boss reroll doesn't


def test_a_blind_played_is_worth_what_its_round_pays_golden_joker_and_the_lucky_cards_rolls_at_the_runs_rate():
    from balatro.items import TAGS
    from balatro.modifiers import lucky_each
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "The Duo", "Cavendish")]
    assert bot.round_income(run) == 0.0
    run.jokers.append(CATALOG["Golden Joker"]())
    assert bot.round_income(run) == pytest.approx(bot.w.money * 4)               # $4 as each round ends
    run.rounds_played, run.pay_seen["lucky"] = 4, 8                              # two Lucky rolls a round so far
    assert bot.round_income(run) == pytest.approx(bot.w.money * (4 + 2 * lucky_each(run)))
    run.unused_discards = 20                                     # the Garbage Tag: $20, against the Small Blind's $3,
    small, garbage = run.make_blind(0), TAGS["Garbage Tag"]()   # $1 a hand left and the shop, and the round's $6.67
    assert not bot.skip_blind(run, small, garbage)
    bot.SKIP_ROUND_INCOME = False
    assert bot.skip_blind(run, small, garbage)                   # (it was skipped for, the round's pay left out)


def test_the_shop_a_skip_gives_up_is_worth_a_share_of_what_the_runs_recent_shops_offered_when_measured():
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    assert bot.skip_shop_worth(run) == bot.w.skip_shop
    bot.SKIP_SHOP_MEASURED = True
    bot._rerolls = (id(run), set(), [0.4, 0.6])
    assert bot.skip_shop_worth(run) == bot.w.skip_shop             # two sets of offers seen: not enough yet
    bot._rerolls[2].append(0.8)
    assert bot.skip_shop_worth(run) == pytest.approx(bot.GLYPH_SHOP_SHARE * 0.6)


def test_a_tag_that_brings_a_joker_is_worth_only_its_gain_over_the_weakest_when_the_slots_are_full():
    from balatro.items import TAGS
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "The Duo", "Cavendish")]
    rare = TAGS["Rare Tag"]()
    with_room = bot.tag_worth(run, rare)
    run.jokers.append(CATALOG["Abstract Joker"]())                # 5 of 5
    assert not run.joker_room() and bot.tag_worth(run, rare) <= with_room
    run.jokers = [CATALOG["Cavendish"]() for _ in range(5)]       # nothing weak to replace
    assert bot.tag_worth(run, rare) == 0.0
    assert bot.tag_worth(run, TAGS["Negative Tag"]()) > 0         # a Negative joker needs no slot


def test_madness_costs_the_jokers_it_will_destroy_and_a_dagger_kept_rightmost_never_grows():
    from balatro.strategy import GROWS
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    madness = CATALOG["Madness"]()
    alone = bot.joker_worth(run, madness, bot.power(run))
    assert bot.havoc(run, madness) == 0.0                         # nothing to destroy
    run.jokers = [CATALOG[n]() for n in ("Cavendish", "The Duo", "Jolly Joker")]
    assert bot.joker_worth(run, madness, bot.power(run)) < alone   # two of these gone each ante
    run.jokers.append(madness)
    k = len(run.jokers) - 1
    assert bot.owned_worth(run, k, bot.power(run)) < bot.owned_worth(run, k, bot.power(run), havoc=False)
    assert "Ceremonial Dagger" not in GROWS and "Ride the Bus" in GROWS


def test_a_joker_fed_by_cards_grows_only_as_far_as_the_deck_feeds_it():
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    cat = CATALOG["Lucky Cat"]()
    worth = lambda: bot.joker_worth(run, cat, bot.power(run))       # noqa: E731
    starved = worth()
    assert starved == bot.bonus(cat, run) < bot.bonus(cat)           # no Lucky card: none of the grows weight
    for c in run.deck[:2]:
        c.enhancement = "Lucky"
    bot._powers.clear()
    two = worth()
    for c in run.deck[2:12]:
        c.enhancement = "Lucky"
    bot._powers.clear()
    assert starved < two < worth()
    assert bot.bonus(cat, run) == bot.bonus(cat)                     # enough Lucky cards: all of it


def test_before_the_first_discard_it_puts_both_copiers_on_burnt_joker_then_orders_for_scoring_again():
    from balatro.bots import copy_fires
    hand = [Card(2, "Hearts"), Card(2, "Diamonds"), Card(5, "Clubs"), Card(9, "Spades"), Card(13, "Diamonds"),
            Card(7, "Hearts"), Card(3, "Clubs"), Card(11, "Spades")]
    pile = [Card(r, s) for r in (4, 6, 8, 10, 12) for s in ("Clubs", "Hearts")]
    bot = ValueBot()
    run = _round(bot, list(hand), list(pile), needed=50_000)          # far off: it discards
    run.jokers = [CATALOG[n]() for n in ("Cavendish", "Burnt Joker", "Card Sharp", "Blueprint", "Brainstorm")]
    fires = lambda: dict(zip((j.name for j in run.jokers), copy_fires(run.jokers)))   # noqa: E731
    moves = []
    for _ in range(4):                                                   # orders and the discard, no flip-flop
        a = bot.round_action(run)
        moves.append(a[0])
        if a[0] != "order_jokers":
            break
        run.jokers = [run.jokers[i] for i in a[1]]
    assert moves[-1] == "discard" and moves.count("order_jokers") == 1
    assert fires()["Burnt Joker"] == 3                                 # itself, Brainstorm's copy, Blueprint's
    run.discard(a[1])
    for _ in range(8):                                                   # on to the next play (a later discard pays
        a = bot.round_action(run)                                        # Burnt Joker nothing, so any order does)
        if a[0] == "order_jokers":
            run.jokers = [run.jokers[i] for i in a[1]]
        elif a[0] == "discard":
            run.discard(a[1])
        else:
            break
    assert a[0] == "play" and fires()["Cavendish"] == 3                  # scored with Cavendish's X3 three times


def test_a_safe_first_hand_with_dna_plays_one_card_with_both_copiers_on_dna():
    from balatro.bots import copy_fires
    hand = [Card(13, "Spades", enhancement="Steel"), Card(2, "Diamonds"), Card(5, "Clubs"), Card(9, "Spades"),
            Card(13, "Diamonds"), Card(7, "Hearts"), Card(3, "Clubs"), Card(11, "Spades")]
    pile = [Card(r, s) for r in (4, 6, 8, 10, 12) for s in ("Clubs", "Hearts")]
    bot = ValueBot()
    run = _round(bot, list(hand), list(pile), needed=300)
    run.jokers = [CATALOG[n]() for n in ("Cavendish", "DNA", "Blueprint", "Brainstorm", "Steel Joker")]
    next(c for c in run.deck if c.rank == 13 and c.suit == "Spades").enhancement = "Steel"   # the full deck's too
    moves = []                                       # (Steel Joker counts it; at X1, below its resale, it was sold first)
    for _ in range(4):
        a = bot.round_action(run)
        moves.append(a[0])
        if a[0] != "order_jokers":
            break
        run.jokers = [run.jokers[i] for i in a[1]]
    assert moves[-1] == "play" and len(a[1]) == 1
    assert dict(zip((j.name for j in run.jokers), copy_fires(run.jokers)))["DNA"] == 3
    played = run.hand[a[1][0]]
    size = len(run.deck)
    run.play_hand(a[1])
    assert len(run.deck) == size + 3 and played.enhancement == "Steel"   # the Steel King, three times over


def test_the_boss_ahead_counts_in_boss_tags_skips_and_suit_tarots():
    from balatro.items import BOSSES, CONSUMABLES, TAGS
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.ante = 2                                                    # where this build is borderline against 6x
    run.start_ante()
    run.jokers = [CATALOG[n]() for n in ("Cavendish", "The Duo", "Jolly Joker", "Joker", "Zany Joker")]
    tag = TAGS["Boss Tag"]()
    run.ante_boss = BOSSES["Violet Vessel"]()                       # 6x the base
    against_vessel = bot.tag_worth(run, tag)
    run.ante_boss = BOSSES["Cerulean Bell"]()                       # 2x
    assert against_vessel > 0.5 > bot.tag_worth(run, tag)
    # before The Needle (one hand, at 1x the base) the build is less safe than before The Hook (four hands at 2x)
    run.ante_boss = BOSSES["The Needle"]()
    big = run.make_blind(1)
    margin = bot.boss_margin(run, run.ante_boss)
    run.ante_boss = BOSSES["The Hook"]()
    assert bot.boss_margin(run, run.ante_boss) > 1.5 * margin
    # The Sun waits while The Head (Hearts debuffed) is still ahead this ante
    run.ante_boss = BOSSES["The Head"]()
    run.blind = big
    assert bot._boss_ahead_debuffs(run, "Hearts") and not bot._boss_ahead_debuffs(run, "Spades")
    run.hand = [Card(9, "Hearts"), Card(8, "Hearts"), Card(4, "Hearts"), Card(9, "Spades"), Card(3, "Spades")]
    run.consumables = [CONSUMABLES["The Sun"]()]
    uses = bot._uses(run, run.consumables[0], run.hand)
    assert uses and bot.consumable_choice(run, run.consumables[0], uses) == len(uses)


def test_with_full_slots_it_sells_its_weakest_joker_to_take_a_much_better_one_from_a_pack():
    from balatro.run import OpenPack
    from balatro.shop import PACKS
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "Zany Joker", "Mad Joker", "Credit Card")]
    state = run.open_pack_state = OpenPack(PACKS["Buffoon Pack"], [CATALOG["Cavendish"]()], 1)
    action = bot.pack_action(run, state)
    assert action[0] == "sell_joker" and run.jokers[action[1]].name == "Credit Card"   # it adds nothing to a hand
    run.sell_joker(action[1])
    assert bot.pack_action(run, state) == ("pick", 0, [])


def test_it_feeds_campfire_by_selling_what_it_doesnt_need():
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.money = 30
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "Campfire")]
    run.consumables = [CONSUMABLES["The Tower"]()]
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [], [], []
    assert bot.shop_action(run, shop) == ("sell_consumable", 0)
    run.consumables = []                                    # nothing left to sell: none bought to sell on an empty shop
    assert bot.shop_action(run, shop) == ("leave",)


def test_with_no_discards_it_plays_dead_cards_along_and_keeps_steel_held():
    from balatro.bots import best_play
    from balatro.hands import evaluate
    hand = [Card(14, "Spades"), Card(2, "Hearts"), Card(3, "Clubs"), Card(4, "Diamonds"), Card(6, "Hearts"),
            Card(9, "Clubs"), Card(11, "Diamonds"), Card(13, "Hearts", enhancement="Steel")]
    bot = ValueBot()
    run = _round(bot, list(hand), [Card(r, "Spades") for r in range(5, 10)], needed=5_000)
    run.discards_left = 0
    action = bot.round_action(run)
    played = [run.hand[i] for i in action[1]]
    assert action[0] == "play" and len(played) > 1 and evaluate(played, run.rules).name == "High Card"
    assert all(c.enhancement != "Steel" for c in played)          # the Steel King stays held for its X1.5
    # a padded play scoring the same: never with a Steel card along when another kicker does as well
    run.hand = [Card(9, "Spades"), Card(9, "Hearts"), Card(5, "Clubs", enhancement="Steel"), Card(4, "Clubs"),
                Card(3, "Hearts"), Card(2, "Diamonds"), Card(7, "Spades"), Card(8, "Diamonds")]
    from balatro.bots import ranked_plays
    fives = [[run.hand[i] for i in idx] for _, idx, _ in ranked_plays(run) if len(idx) == 5]
    assert fives and all(c.enhancement != "Steel" for c in fives[0])


def test_jokers_that_wear_away_and_late_vouchers_are_worth_less():
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.rounds_played, run.hands_played = 6, 18
    fresh, worn = CATALOG["Ice Cream"](), CATALOG["Ice Cream"]()
    worn.chips = 10
    assert bot.growth_worth(run, fresh) < 0 and bot.growth_worth(run, worn) < 0      # it will be lower than now
    seltzer = CATALOG["Seltzer"]()
    seltzer.hands = 2                                   # all but gone
    run.jokers = [CATALOG["Joker"](), seltzer]
    assert bot.growth_worth(run, seltzer) < 0
    run.jokers = []
    early = bot.voucher_worth(run, "Money Tree", bot.power(run))
    run.ante = 8
    assert 0 < bot.voucher_worth(run, "Money Tree", bot.power(run)) < early


def test_chicot_and_perkeo_are_worth_what_they_do_not_only_a_legendary_bonus():
    worths = {"Chicot": [], "Perkeo": []}
    for salt in ("", "a", "b", "c"):                               # one draw of sample hands swings Chicot 0.7-1.4
        bot = ValueBot()                                           # (29 Oct): the mean over four
        bot.w, bot.SAMPLE_SALT = Weights(), salt
        bot.LASTING_HORIZON = False                                # (on since 30 Oct: fewer antes counted in a run to 8)
        run = Run(bot, game_seed="ALEEB", deck="Red Deck")
        run.ante = 3
        run.start_ante()
        run.jokers = [CATALOG[n]() for n in ("Canio", "Triboulet", "Joker", "Jolly Joker")]
        run.hand_plays["Pair"] = 8
        base = bot.power(run)
        for name in worths:
            worths[name].append(bot.joker_worth(run, CATALOG[name](), base))
    flat = Weights().rarity[3]                                     # the legendary bonus alone
    for name, ws in worths.items():
        assert sum(ws) / len(ws) > flat + 0.2, name


def test_under_the_eye_with_nothing_left_that_scores_the_play_keeps_the_draw_to_a_new_hand():
    from balatro.cards import Card as C
    hand = [C(4, "Diamonds"), C(8, "Hearts"), C(6, "Clubs"), C(7, "Diamonds"), C(8, "Spades"), C(14, "Spades"),
            C(6, "Hearts"), C(4, "Clubs")]
    pile = [C(r, s) for r in (5, 9, 10, 2, 3, 11, 12, 13) for s in ("Clubs", "Hearts")]
    bot = ValueBot()
    run = _boss_round(bot, "The Eye", list(hand), list(pile), needed=416)
    for used in ("Pair", "Two Pair", "High Card"):            # every hand these cards make is spent
        run.round_hand_types[used] = 1
    run.discards_left, run.hands_left = 0, 4
    action = bot.round_action(run)
    kept = {run.hand[i].rank for i in range(len(run.hand)) if i not in action[1]}
    assert action[0] == "play" and {6, 7, 8} <= kept              # a straight draw stays in hand (4-6-7-8 or 6-7-8:
                                                                    # 25.0 and 24.5 on 1000 draws, a coin toss on 24)


def test_under_the_house_what_the_face_down_cards_are_changes_nothing():
    from dataclasses import replace
    from balatro.cards import Card as C
    # The House deals the first hand face down. With every card down it used to weigh them as they were: three Kings
    # played at once, junk thrown away. Two deals of the same deck: the move must be the same.
    deck = [C(r, s, uid=k) for k, (r, s) in enumerate((r, s) for s in ("Hearts", "Clubs", "Spades", "Diamonds")
                                                      for r in range(2, 15))]
    junk = [0, 16, 33, 48, 2, 44, 23, 29]                             # 2H 5C 9S JD 4H 8D QC 5S... nothing made
    kings = [11, 24, 37] + junk[3:]                                     # KH KC KS and the same five
    actions = []
    for discards in (3, 0):
        for picked in (junk, kings):
            hand = [replace(deck[k], face_down=True) for k in picked]
            pile = [c for k, c in enumerate(deck) if k not in picked]
            bot = ValueBot()
            run = _boss_round(bot, "The House", hand, pile, needed=1600)
            run.discards_left = discards
            actions.append(bot.round_action(run))
    assert actions[0] == actions[1] and actions[2] == actions[3]
    assert actions[0][0] == "discard" and len(actions[0][1]) == 5      # five unknown cards traded for five seen
    assert actions[2][0] == "play" and len(actions[2][1]) == 5         # no discards: five blind, the most drawn


def test_a_random_effect_is_worth_what_it_may_do_not_what_the_runs_streams_say_it_will():
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    run = Run(bot, seed=5, deck="Red Deck")                             # no game seed: every roll from the streams
    run.jokers = [CATALOG["Joker"](), CATALOG["Cavendish"](), CATALOG["Bull"]()]
    run.money = 20

    def worths():
        out = set()
        for state in range(6):
            run.rng["misc"].seed(state)
            out.add(round(bot.effect_worth(run, lambda t: t.apply_consumable(CONSUMABLES["The Wheel of Fortune"](), [])), 9))
        return out
    honest = worths()
    assert len(honest) == 1 and 0 < honest.pop() < 0.3                  # a 1 in 4 chance of an edition, on average
    bot.HONEST_TRIALS = False                                           # the copy's own streams: it knew the roll
    assert min(worths()) <= 0 < 0.3 < max(worths())


def test_the_fool_is_worth_the_card_it_would_copy():
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    bot.MADE_MEASURED, bot.KEEP_MEASURED = True, False   # (a kept Tarot at the flat w.keep, to see it below)
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.money = 12

    def fool(last):
        run.last_tarot_planet = last
        return bot.effect_worth(run, lambda t: t.apply_consumable(CONSUMABLES["The Fool"](), []))
    # it used to be w.keep whatever it copied
    assert fool("Pluto") > fool("Neptune") + 0.05                     # High Card's level, against a Straight Flush's
    assert abs(fool("The Hermit") - bot.w.money * 12) < 0.02             # $12 doubled
    assert fool("The Empress") == bot.w.keep                            # used on cards: waits on a hand


def test_a_tarot_kept_for_a_later_hand_is_worth_what_it_typically_does_there():
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG["Steel Joker"](), CATALOG["Arrowhead"]()]
    sun, chariot = CONSUMABLES["The Sun"](), CONSUMABLES["The Chariot"]()
    bot.KEEP_MEASURED = False
    assert bot.keep_worth(run, sun) == bot.keep_worth(run, chariot) == bot.w.keep     # off: the flat weight
    bot.KEEP_MEASURED = True
    floor = bot.w.money * run.sell_value(sun)
    assert bot.keep_worth(run, sun) == floor            # nothing pays for Hearts (and Arrowhead pays for Spades)
    assert bot.keep_worth(run, chariot) > floor + 0.01  # Steel cards for Steel Joker
    assert bot.keep_worth(run, chariot) == bot.keep_worth(run, chariot)                 # the same hands each time


def test_with_perkeo_it_holds_only_what_is_worth_copying():
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG["Perkeo"](), CATALOG["Brainstorm"]()]          # (a copier: planet_worth gives up)
    pluto, sun = CONSUMABLES["Pluto"](), CONSUMABLES["The Sun"]()
    run.consumables = [sun, pluto]
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [], [], []
    bot.PERKEO_FOCUS = False
    assert bot.shop_action(run, shop) == ("leave",)        # off: both held, each shop's copy a draw between them
    bot.PERKEO_FOCUS = True
    assert bot._perkeo_pick(run) is pluto                  # High Card's level, which hands make; no Heart pays here
    assert bot.shop_action(run, shop) == ("sell_consumable", 0)


def test_with_no_joker_slot_free_judgement_is_worth_only_its_sale_and_perkeo_copies_something_else():
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    bot.w = Weights()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG["Perkeo"]()] + [CATALOG["Joker"]() for _ in range(4)]   # every slot full
    pluto, judgement = CONSUMABLES["Pluto"](), CONSUMABLES["Judgement"]()
    run.consumables = [judgement, pluto]
    assert bot.keep_worth(run, judgement) == bot.w.money * run.sell_value(judgement)   # it can't be used: it sells
    assert bot._perkeo_pick(run) is pluto                    # (it was copied at w.keep and piled up: ALEEB)
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [], [], []
    assert bot.shop_action(run, shop) == ("sell_consumable", 0)


def test_a_tag_skipped_for_counts_once_for_each_copy_the_double_tags_held_make():
    from balatro.items import TAGS, Tag, make
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Anaglyph Deck")
    rare, boss = make(TAGS, Tag, "Rare Tag"), make(TAGS, Tag, "Boss Tag")
    assert bot.tag_copies(run, rare) == 1
    run.tags = [make(TAGS, Tag, "Double Tag") for _ in range(3)]          # three bosses beaten on the Anaglyph Deck
    assert bot.tag_copies(run, rare) == 4
    assert bot.tag_copies(run, boss) == 1                                 # a second reroll of the boss adds nothing


def test_weights_survive_the_genome_round_trip():
    w = Weights()
    w.grows, w.packs["Spectral"] = 0.9, 0.7
    assert weights_of(genome_of(w)) == w


def test_a_grown_ride_the_bus_is_projected_from_what_it_has_built():
    from types import SimpleNamespace as NS
    run = NS(pareidolia=False)
    bus = NS(name="Ride the Bus", value=24)
    plain, face = ([Card(5, "Hearts")], NS(scoring=[0])), ([Card(12, "Hearts")], NS(scoring=[0]))
    plays = [plain] * 9 + [face]                                   # 1 in 10 best plays scores a face card: p = 0.9
    old = ValueBot._grown_value(run, bus, "value", 24, 1, plays, 2.0, 5, 3)
    new = ValueBot._grown_value(run, bus, "value", 24, 1, plays, 2.0, 5, 3, from_now=True)
    assert old == 6                                                # the steady state from 0: its +24 thrown away
    assert new == pytest.approx(0.9 ** 6 * 24 + 0.9 * (1 - 0.9 ** 6) / 0.1)   # ~16: what it keeps, and grows
    assert ValueBot._grown_value(run, bus, "value", 24, 1, [plain] * 10, 2.0, 5, 3, from_now=True) == 30   # never reset


def test_a_discount_voucher_worth_buying_goes_before_the_pack_it_makes_cheaper():
    from balatro.models import make
    from balatro.shop import PACKS
    for first in (False, True):
        bot = make("value")
        bot.DISCOUNT_FIRST = first
        run = Run(bot, game_seed="ALEEB", deck="Red Deck", max_ante=8)
        run.money = 30
        shop = Shop(run)
        shop.cards, shop.packs, shop.vouchers = [], [Offer("Pack", PACKS["Celestial Pack"])], [Offer("Voucher", "Liquidation")]
        bot.pack_weight = lambda run, p: 1.0                   # the pack: the best single buy here
        bot.voucher_worth = lambda run, name, base: 0.5         # the voucher: worth buying too
        move = bot.shop_action(run, shop)
        assert move == (("buy", "voucher", 0) if first else ("buy", "pack", 0))


def test_in_a_round_a_tarot_that_would_spoil_the_hand_held_waits():
    from balatro.items import CONSUMABLES
    hand = [Card(10, "Spades"), Card(9, "Diamonds"), Card(8, "Spades"), Card(7, "Clubs"), Card(6, "Hearts"),
            Card(2, "Clubs"), Card(2, "Diamonds"), Card(4, "Hearts")]                  # a 10-high straight
    for guard in (False, True):
        bot = ValueBot()
        bot.USE_GUARD, bot.GUARD_AT_RISK = guard, False     # the first, broader guard
        run = _round(bot, list(hand), [Card(3, "Spades")] * 4, needed=5000)
        run.consumables = [CONSUMABLES["Strength"]()]
        strength = run.consumables[0]
        targets = [0, 1]                                    # the 10 and the 9 up a rank: no straight left
        assert not bot._keeps_best_play(run, strength, targets)
        bot._use_or_keep = lambda run, c, uses: targets     # (the long-run measure says use it)
        assert bot._use(run) == (None if guard else ("use", 0, targets))
    bot = ValueBot()
    bot.USE_GUARD = bot.GUARD_AT_RISK = True                # only when it costs the round: the straight scores 280, the
    for needed, keeps in ((20, True), (200, False), (1000, False), (5000, True)):     # pair of 2s left 28; 4 hands
        run = _round(bot, list(hand), [Card(3, "Spades")] * 4, needed=needed)
        assert bot._keeps_best_play(run, CONSUMABLES["Strength"](), [0, 1]) == keeps, needed


def test_with_power_paired_a_hand_a_card_smaller_is_the_first_cards_of_the_larger_one():
    bot = ValueBot()
    bot.POWER_PAIRED = True
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    bot.power(run)
    small = [list(i) for i in bot._idx]
    run.base_hand_size += 1                         # Paint Brush: one card more in hand
    bot.power(run)
    big = [list(i) for i in bot._idx]
    assert len(big) == len(small) == bot.HANDS
    assert all(len(b) == len(s) + 1 and b[:len(s)] == s for s, b in zip(small, big))


def test_without_power_paired_power_samples_as_before():
    bot = ValueBot()
    bot.POWER_PAIRED = False
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    bot.power(run)
    rng = random.Random(str(bot._key) + bot.SAMPLE_SALT)
    n = len(bot._idx[0])
    assert bot._idx == [rng.sample(range(len(run.deck)), n) for _ in range(bot.HANDS)]


def test_with_the_horizon_cap_a_run_to_16_counts_lasting_things_as_a_run_to_8_does_until_ante_5():
    from balatro.modifiers import rounds_left, shops_left
    bot = ValueBot()
    bot.SURVIVAL_HORIZON = False                                   # the cap shapes the old rule (survival replaces it)
    short = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    long = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=16)
    assert rounds_left(long) > rounds_left(short)                      # without the cap: the whole run
    bot.HORIZON_CAP = True
    for ante in (1, 4):
        short.ante = long.ante = ante
        assert rounds_left(long) == rounds_left(short) and shops_left(long) == shops_left(short)
    long.ante = 10
    assert rounds_left(long) == 0.5 * 3 * (14 + 1 - 10)                # 4 antes ahead past ante 4
    short.ante = 8
    assert rounds_left(short) == 0.5 * 3                               # a run to 8: as before


def test_with_the_survival_horizon_a_strong_build_counts_further_ahead_and_a_long_run_doesnt_double_it():
    from balatro.modifiers import rounds_left
    bot = ValueBot()
    bot.SURVIVAL_HORIZON = True
    short = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    long = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=16)
    assert rounds_left(short) <= rounds_left(long) < rounds_left(short) + 2   # at ante 1: not twice as many in a run to 16
    long.ante = 5
    counts = {}
    for margin in (1.0, 3.0):
        bot.boss_margin = lambda run, boss, m=margin: m
        bot.__dict__.pop("_survival", None)
        counts[margin] = rounds_left(long)
    del bot.boss_margin
    assert 3 <= counts[1.0] < counts[3.0]                              # a build far ahead prepares further
    bot.SURVIVAL_HORIZON = False
    assert rounds_left(long) == 0.5 * 3 * (16 + 1 - 5)                 # off: as before


def _full_row(names):
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG[n]() for n in names]
    run.money = 50
    return bot, run



def test_a_swap_is_scored_as_the_lineup_it_leaves():
    """The replay review's M1 (7S5X1EZS): beside Baseball Card (Uncommon jokers X1.5), Rough Gem (Uncommon) looks worth
    far more than it is once Baseball Card is sold for it. The old score took its worth beside every joker held less
    Baseball Card's own; swap_worth measures the lineup the sale leaves. The same lineup (a joker for its twin): 0."""
    bot, run = _full_row(["Baseball Card", "Mime", "Raised Fist", "Banner", "Blueprint"])
    base = bot.power(run)
    adj = bot.adjust(run, base)
    gem = CATALOG["Rough Gem"]()
    additive = bot.joker_worth(run, gem, base) + adj(("joker", "Rough Gem")) - bot.owned_worth(run, 0, base) \
        - adj(("joker", "Baseball Card"))
    exact = bot.swap_worth(run, 0, gem, adj)
    assert exact < additive - 0.5                                   # (1.74 by the old score, 0.52 as the lineup)
    assert bot._best_swap(run, gem, adj, range(5))[1] != 0    # and selling it isn't the best swap
    assert abs(bot.swap_worth(run, 2, CATALOG["Raised Fist"](), adj)) < 1e-9


def test_a_purple_seal_goes_on_a_card_thrown_not_on_a_gold_card_held():
    """6X7SCM12 (Zodiac Deck, the user's catch, 29 Oct): Medium was offered only the highest unsealed card, a Gold
    Queen, and its Purple Seal (a Tarot when the card is discarded) was worth as much there as on a plain 4, though a
    Gold card is held for its $3, never thrown."""
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    queen = next(c for c in run.deck if c.rank == 12)
    queen.enhancement = "Gold"
    plain = [c for c in run.deck if c.rank in (4, 6, 9, 10, 11) and c.enhancement is None][:7]
    run.hand = [queen] + plain
    gold, four = bot._card_economy(run, queen), bot._card_economy(run, plain[0])
    queen.seal = plain[0].seal = "Purple"
    assert bot._card_economy(run, queen) == gold                    # nothing more on a card held
    assert bot._card_economy(run, plain[0]) > four
    queen.seal = plain[0].seal = None
    medium = CONSUMABLES["Medium"]()
    uses = bot._uses(run, medium, run.hand)
    first = uses[0][0]                                              # a lowest plain card offered, and first
    assert len(first) == 1 and run.hand[first[0]].rank == min(c.rank for c in plain)
    assert [0] in [u[0] for u in uses]                              # (the Gold Queen still weighed: it is worth less)


def test_a_standard_pack_gives_its_best_card_not_its_first():
    """The replay review's m1: every playing card weighed the flat w.card, so the first was taken (79 of 79 picks), a
    plain 7 over a Glass 10 and a Blue Seal 8."""
    import types
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    pack = types.SimpleNamespace(cards=[Card(7, "Clubs"), Card(10, "Diamonds", enhancement="Glass"),
                                        Card(8, "Hearts", seal="Blue")])
    assert bot.pack_action(run, pack)[:2] != ("pick", 0)


def test_under_the_mouth_a_dead_play_keeps_the_pair_toward_two_pair():
    """6X7SCM12 (Zodiac Deck, the user's catch, 29 Oct): Two Pair played first, no discards left, three Jacks and a
    Glass Ace in hand. Every play scores 0, so the play is a discard; it threw two Jacks (keeping J 7 10, 119 on 1000
    draws) over keeping J J A (1,036), screened out on 6 draws, so every dead play is now weighed on more draws
    (_ranked_discards' `everything`). The miss needs that game's own pile and draws (replayed: the fixed bot keeps
    J J A, draws Kings, and ends at 67,666 of 70,000 against 50,215); this deck, richer in pairs, checks the behaviour."""
    from balatro.cards import Card as C
    hand = [C(6, "Clubs"), C(11, "Diamonds"), C(14, "Spades", enhancement="Glass"), C(7, "Clubs", enhancement="Mult"),
            C(4, "Hearts"), C(11, "Clubs"), C(10, "Spades"), C(11, "Diamonds", seal="Gold")]
    pile = [C(r, s) for r in (2, 3, 5, 8, 9, 12, 13) for s in ("Clubs", "Hearts", "Spades", "Diamonds")]
    bot = ValueBot()
    run = _boss_round(bot, "The Mouth", list(hand), list(pile), needed=19785)
    run.round_hand_types["Two Pair"] = 2
    run.discards_left, run.hands_left = 0, 3
    action = bot.round_action(run)
    kept = [run.hand[i] for i in range(len(run.hand)) if i not in action[1]]
    assert action[0] == "play" and sum(c.rank == 11 for c in kept) >= 2


def test_measured_overstock_pays_its_price_early_and_less_late():
    """The user's NNVPEGNB (29 Oct): Overstock at ante 1 for $10 with $10, scored 0.4 flat against a price of 0.5, so
    a $4 Buffoon Pack was bought. VOUCHERS_MEASURED: a card more in each shop left."""
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.money = 10
    base = bot.power(run)
    bot.VOUCHERS_MEASURED = False                                    # (on since 30 Oct)
    flat = bot.voucher_worth(run, "Overstock", base)
    bot.VOUCHERS_MEASURED = True
    early = bot.voucher_worth(run, "Overstock", base)
    assert early > flat and early > bot.price(run, 10)
    run.ante = 8
    assert bot.voucher_worth(run, "Overstock", base) < early        # fewer shops ahead


def test_under_observatory_a_planet_held_is_worth_its_x1_5_mult():
    """The voucher audit (29 Oct): a Planet kept was the flat w.keep, Observatory or not, so the stack of held Planets
    Observatory pays for (x1.5 Mult each when its hand is played) was never built."""
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    from dataclasses import replace
    bot.w = replace(bot.w, keep=0.0)                                 # (w.keep is the floor: off, the measure shows)
    mercury, neptune = CONSUMABLES["Mercury"](), CONSUMABLES["Neptune"]()   # Pair, often played; Straight Flush, never
    assert bot.keep_worth(run, mercury) == bot.keep_worth(run, neptune)
    run.vouchers.append("Observatory")
    assert bot.keep_worth(run, mercury) > bot.keep_worth(run, neptune) + 0.05


def _mark_round(bot, swap=False):
    """The Mark: four face cards face down in hand among junk, more face cards in the pile."""
    from balatro.cards import Card as C
    down = [C(13, "Spades"), C(13, "Hearts"), C(12, "Diamonds"), C(11, "Clubs")]
    pile = [C(12, "Spades"), C(11, "Hearts"), C(13, "Diamonds"), C(12, "Clubs")] + [C(r, "Hearts") for r in (3, 5, 6, 8)]
    for c in down + pile:                             # each card its own uid, as in a run (the pool is sorted by it)
        c.uid = c.rank * 10 + "SHDC".index(c.suit[0])
    if swap:                                          # which face cards are down and which in the pile: not known
        down, pile = pile[:4], down + pile[4:]
    for c in down:
        c.face_down = True
    hand = [C(2, "Clubs"), C(4, "Diamonds"), C(7, "Spades"), C(9, "Hearts")] + down
    return _boss_round(bot, "The Mark", hand, pile, needed=10_000)


def test_under_the_mark_face_down_face_cards_are_played_on_what_they_could_be():
    """The user's catch (29 Oct; the review's m5): face-down cards were never played, so under The Mark (it draws the
    face cards face down) the hand filled with them. Now plays with them are weighed over what they could be: the face
    cards not seen."""
    from balatro.bots import best_play
    bot = ValueBot()
    run = _mark_round(bot)
    _, idx = best_play(run, need=10_000)
    assert any(run.hand[i].face_down for i in idx)


def test_a_face_down_play_reads_nothing_of_what_the_cards_are():
    from balatro.bots import best_play
    a = _mark_round(ValueBot())
    b = _mark_round(ValueBot(), swap=True)
    assert best_play(a, need=10_000) == best_play(b, need=10_000)


def test_measured_hieroglyph_counts_an_ante_replayed_and_a_hand_at_the_margin():
    """The user's NNVPEGNB (ante 5, 29 Oct): Hieroglyph scored -0.76, a flat 0.1 for an ante back against -0.48 for a
    6th hand by the log rule tuned on Grabber at 4 hands, though the run used 2.3 a round. GLYPH_MEASURED: the ante's
    shops and cash-out less the replayed boss's risk, a hand at the share of them the run uses."""
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.ante, run.base_hands, run.money = 5, 6, 34
    run.rounds_played, run.hands_played = 12, 28                     # 2.3 hands a round
    base = bot.power(run)
    flat = bot.voucher_worth(run, "Hieroglyph", base)
    bot.GLYPH_MEASURED = True
    spare = bot.voucher_worth(run, "Hieroglyph", base)
    assert flat < 0 < spare
    run.hands_played = 70                                            # every hand used: the hand lost costs more
    assert bot.voucher_worth(run, "Hieroglyph", base) < spare


def _leaf_round(bot, ante=8, max_ante=8):
    from balatro.cards import Card as C
    hand = [C(13, "Spades"), C(13, "Hearts"), C(9, "Clubs"), C(9, "Diamonds"), C(5, "Spades"), C(4, "Hearts"),
            C(3, "Clubs"), C(2, "Diamonds")]
    pile = [C(r, s) for r in (6, 7, 8, 10, 11, 12) for s in ("Clubs", "Hearts", "Spades")]
    run = _boss_round(bot, "Verdant Leaf", hand, pile, needed=50_000)
    run.ante, run.max_ante = ante, max_ante
    run.jokers = [CATALOG["Joker"](), CATALOG["Credit Card"](), CATALOG["Jolly Joker"]()]
    for c in run.deck + run.hand + run.draw_pile:
        c.debuffed = True
    return run


def test_under_verdant_leaf_the_joker_worth_least_is_sold_to_lift_it():
    """The second replay review's M1 (29 Oct): Verdant Leaf debuffs every card until a joker is sold in the round, and
    the bot never sold one there (0.80 of ante-8 Verdant Leafs beaten; a weighed sale turned 9 of 14 losses into wins)."""
    bot = ValueBot()
    run = _leaf_round(bot)
    action = bot.round_action(run)
    assert action[0] == "sell_joker" and run.jokers[action[1]].name == "Credit Card"


def test_amber_acorn_s_shuffled_jokers_are_neither_read_nor_reordered():
    """The second replay review's B1: the jokers are face down and shuffled for the round; the bot put them back in
    order at once (it saw them). Now it weighs plays in the order it last saw, whatever the shuffle."""
    from balatro.cards import Card as C
    actions = []
    for order in ([0, 1, 2], [2, 0, 1]):
        bot = ValueBot()
        hand = [C(13, "Spades"), C(13, "Hearts"), C(9, "Clubs"), C(5, "Diamonds"), C(4, "Spades"), C(3, "Hearts"),
                C(2, "Clubs"), C(7, "Diamonds")]
        run = _boss_round(bot, "Amber Acorn", hand, [C(r, "Clubs") for r in (6, 8, 10, 11, 12)], needed=2_000)
        jokers = [CATALOG["Joker"](), CATALOG["Blueprint"](), CATALOG["Jolly Joker"]()]
        boss = run.active_boss
        boss.shuffled, boss.before = True, list(jokers)
        run.jokers = [jokers[i] for i in order]
        actions.append(bot.round_action(run))
    assert actions[0] == actions[1] and actions[0][0] != "order_jokers"


def test_obelisk_resets_on_a_tie_for_the_most_played_hand():
    """The second replay review's m2 (4U1Q98ID, ante 10): Two Pair, Pair and High Card tied at 13 plays; the bot played
    Pair as if Obelisk (X6) would grow, but any of them becomes the most played outright and resets it."""
    from balatro.bots import best_play
    from balatro.cards import Card as C
    from balatro.hands import evaluate
    from balatro.modifiers import play_bonus
    bot = ValueBot()
    run = _round(bot, [C(13, "Spades"), C(13, "Hearts"), C(9, "Clubs"), C(5, "Diamonds"), C(3, "Hearts")], [], 10_000)
    ob = CATALOG["Obelisk"]()
    ob.xmult = 6.0
    run.jokers = [ob]
    for h in ("Two Pair", "Pair", "High Card"):
        run.hand_plays[h] = 13
    played = run.hand[:2]
    assert play_bonus(bot, bot._measure(run), played, evaluate(played, run.rules)) < 0


def test_amber_acorn_s_jokers_are_known_only_from_what_their_hands_showed():
    """The user (29 Oct): after a hand a player can tell which joker is where from what each did when it scored, but
    not those that did nothing, nor two that looked alike. AmberAcorn.known: a joker whose effects seen are its own;
    the last one left by elimination."""
    from balatro.items import BOSSES
    boss = BOSSES["Amber Acorn"]()
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    a, b, c = CATALOG["Joker"](), CATALOG["Jolly Joker"](), CATALOG["Credit Card"]()
    run.jokers = [b, c, a]
    boss.shuffled, boss.before = True, [a, b, c]
    assert boss.known(run) == set()                                  # nothing seen yet
    boss.seen = {id(a): [("+mult", 4.0)]}
    assert boss.known(run) == {id(a)}                                # Jolly Joker and Credit Card: either may be where
    boss.seen[id(b)] = [("+mult", 8.0)]
    assert boss.known(run) == {id(a), id(b), id(c)}                  # Credit Card by elimination
    boss.seen[id(b)] = [("+mult", 4.0)]                              # the two looked alike: neither told apart
    assert boss.known(run) == set()


def test_with_milk_won_a_sure_win_waits_while_face_cards_pay_through_business_card():
    """The user's NNVPEGNB at The Club (29 Oct): a sure win in hand, Business Card owned, spare face cards and hands to
    spare: play the face cards first for money (1 in 2 for $2 each that scores), then win. MILK_WON (off until measured).
    A pair of Jacks pays $2 against the $1 of cash-out the hand gives up; a lone face card would be even."""
    from balatro.cards import Card as C
    hand = [C(2, "Hearts"), C(5, "Hearts"), C(7, "Hearts"), C(8, "Hearts"), C(9, "Hearts"), C(11, "Spades"),
            C(11, "Diamonds"), C(3, "Clubs")]                         # a Flush to win, the Jacks no part of it
    pile = [C(r, "Clubs") for r in (4, 6, 10, 12, 13, 14)]
    actions = []
    for milk in (False, True):
        bot = ValueBot()
        bot.MILK_WON = milk
        run = _round(bot, list(hand), list(pile), needed=300)          # the Flush (528) wins, the Jacks (180) don't
        run.jokers = [CATALOG["Business Card"](), CATALOG["Joker"]()]
        a = bot.round_action(run)
        actions.append(sorted(run.hand[i].rank for i in a[1]) if a[0] == "play" else a)
    assert actions[0] == [2, 5, 7, 8, 9]                             # the Flush at once
    assert actions[1] == [11, 11]                                    # the Jacks first


def test_a_round_won_anyway_is_won_with_a_lone_lucky_card_hanging_chad_rolls_three_times():
    """The user's 6AWQ2FCT at The Goad (30 Oct): "if anything clears the win, it makes sense to use lucky just to get
    some money". A Lucky card's $20 (1 in 15) was never counted, and a lone 2 never ranked among the plays weighed."""
    from balatro.cards import Card as C
    hand = [C(14, "Hearts", enhancement="Mult"), C(12, "Hearts"), C(9, "Clubs"), C(7, "Clubs"), C(5, "Diamonds"),
            C(4, "Spades"), C(3, "Spades"), C(2, "Clubs", enhancement="Lucky")]
    pile = [C(r, "Diamonds") for r in (6, 8, 10, 11, 13)]
    picks = []
    for lucky in (False, True):
        bot = ValueBot()
        bot.LUCKY_MONEY = lucky
        run = _round(bot, list(hand), list(pile), needed=20)              # any card wins it
        run.jokers = [CATALOG["Hanging Chad"](), CATALOG["Joker"]()]
        a = bot.round_action(run)
        picks.append([str(run.hand[i]) for i in a[1]] if a[0] == "play" else a)
    assert picks[1] == ["2C[Lucky]"] and picks[0] != picks[1]


def test_a_glass_card_alone_is_weighed_as_a_play_though_its_rank_is_low(monkeypatch):
    """The user's 6AWQ2FCT at ante 9 (30 Oct): "why does it advise me go create a glass and discard it?" The cheap
    ranking before full scoring left enhancements out, so a Glass 3 alone was never scored and never played."""
    from balatro import bots
    from balatro.cards import Card as C
    hand = [C(13, "Spades"), C(12, "Hearts"), C(11, "Clubs"), C(9, "Diamonds"), C(7, "Spades"), C(5, "Hearts"),
            C(4, "Clubs"), C(3, "Hearts", enhancement="Glass")]        # no pair, no straight, no flush: K high 15
    run = Run(ValueBot(), game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    picks = {}
    for on in (False, True):
        monkeypatch.setattr(bots, "BASE_CARD_EFFECTS", on)
        _, idx = bots.best_play(run, hand=hand)
        picks[on] = [str(hand[i]) for i in idx]
    assert picks[True] == ["3H[Glass]"]                                   # (5 + 3) x 1 x 2 = 16 over the King's 15
    assert picks[False] != ["3H[Glass]"]


def test_behind_a_discard_needs_the_usual_gain_with_behind_strict():
    """The review agent's round lab (31 Oct): behind (this hand every hand short), any gain at all was worth a discard."""
    bot = ValueBot()
    run = _round(bot, [Card(13, "Spades"), Card(9, "Hearts")], [Card(2, "Clubs")], needed=1000)   # 4 hands, no jokers
    assert bot._worth_discarding(run, now=100, after=105, needed=1000)          # 400 short of 1000: any gain
    bot.BEHIND_STRICT = True
    assert not bot._worth_discarding(run, now=100, after=105, needed=1000)
    assert bot._worth_discarding(run, now=100, after=130, needed=1000)          # 1.3x: the usual rule


def test_on_the_last_hand_a_discard_that_can_reach_the_target_beats_a_play_that_cannot():
    """LAST_DISCARD_ODDS (the review agent, 31 Oct): with one discard left on the last hand, the bot played a hand that
    couldn't win unless the typical draw beat it."""
    hand = [Card(13, "Spades"), Card(9, "Hearts"), Card(7, "Diamonds"), Card(5, "Clubs"), Card(3, "Spades"),
            Card(2, "Hearts"), Card(4, "Diamonds"), Card(8, "Clubs")]          # King high: 15; a 6 makes a straight
    pile = [Card(6, "Hearts"), Card(6, "Clubs"), Card(10, "Spades"), Card(11, "Diamonds"), Card(12, "Clubs")]
    bot = ValueBot()
    run = _round(bot, hand, pile, needed=100)
    run.hands_left, run.discards_left = 1, 1
    assert bot._last_discard(run, [0]) is not None                           # the King alone can't win; a 6 can


def test_a_chance_that_missed_in_every_copy_is_tried_on_more_copies():
    """The user's XRTTE7VX (31 Oct): The Wheel of Fortune's 1 in 4 missed in all 8 copies and measured 0; on 200, +0.19."""
    import copy as copy_
    from balatro.items import CONSUMABLES
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.jokers = [CATALOG["Joker"]()]
    wheel = CONSUMABLES["The Wheel of Fortune"]()
    bot.TRIALS = 1                                                          # one copy: a hit or a miss, then 32
    assert bot.effect_worth(run, lambda t: t.apply_consumable(copy_.deepcopy(wheel), [])) > 0


def test_a_free_pack_pick_worth_what_skipping_is_is_taken():
    """The user's XRTTE7VX (31 Oct): Jupiter, Earth and Saturn all measured 0 and the Celestial pack was skipped."""
    from balatro.items import CONSUMABLES
    from balatro.shop import OpenPack, Pack
    picks = {}
    for ties in (False, True):
        bot = ValueBot()
        bot.PICK_TIES = ties
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
        pack = OpenPack(Pack("Celestial Pack", "Celestial", "Normal", 4, 3, 1),
                        [CONSUMABLES["Eris"](), CONSUMABLES["Planet X"]()], 1)   # hands a plain deck never makes: 0
        run.open_pack_state = pack
        picks[ties] = bot.pack_action(run, pack)[0]
    assert picks == {False: "skip", True: "pick"}


def test_hanging_chad_and_lucky_cards_count_what_the_lucky_cards_pay():
    from balatro.cards import Card as C
    from balatro.modifiers import hand_pay
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    assert hand_pay(run, "Hanging Chad") == 0.0                           # no Lucky card: nothing to roll again
    plain, lucky = C(2, "Clubs"), C(2, "Clubs", enhancement="Lucky")
    assert bot._card_economy(run, lucky) > bot._card_economy(run, plain) == 0.0
    for c in run.deck[:6]:
        c.enhancement = "Lucky"
    assert hand_pay(run, "Hanging Chad") == pytest.approx(2 * 20 / 15 * 6 / 52 * 2.0)   # 2 hands a round before any


def test_with_lasting_horizon_vouchers_past_ante_8_count_the_antes_the_run_may_last():
    """The second review's m4 and the voucher audit's G1: from ante 9 every voucher counted a quarter (9 - ante), in
    runs to 16 too. LASTING_HORIZON (off until measured): the antes the run is likely to last (rounds_left)."""
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=16)
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "Cavendish", "Baron", "Blueprint")]
    run.ante = 9
    base = bot.power(run)
    old = bot.voucher_worth(run, "Overstock", base)
    bot.LASTING_HORIZON = True
    assert bot.voucher_worth(run, "Overstock", base) >= old


def test_behind_gamble_counts_money_at_the_odds_of_surviving_the_boss_ahead():
    """The user (29 Oct): losing the next boss, money held is worth little. BEHIND_GAMBLE (on since 30 Oct): in the
    shop before a boss the build likely loses to, money's weight times those odds."""
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    from balatro.items import BOSSES
    run.ante, run.ante_boss = 6, BOSSES["The Wall"]()
    run.blind = run.make_blind(1)                                    # the Big Blind just beaten: the boss next
    bot.BEHIND_GAMBLE = False
    plain = bot.money_scale(run)
    bot.BEHIND_GAMBLE = True
    odds = bot.boss_odds(run, run.ante_boss)
    assert odds < bot.BEHIND_ODDS                                    # a jokerless deck at ante 6
    assert abs(bot.money_scale(run)[0] - plain[0] * odds) < 1e-9
    run.blind = run.make_blind(0)                                    # not the shop before the boss: unchanged
    assert bot.money_scale(run) == plain


def test_mouth_odds_is_the_chance_enough_later_hands_make_the_opening_type():
    """MOUTH_ODDS (off until measured): The Mouth's opening type by the chance the round reaches its target with it."""
    odds = ValueBot._mouth_odds
    assert odds([0, 5000, 0, 6000], 9000, 3) == 0.5                 # 2 of 3 made at 1 in 2
    assert odds([20000] * 4, 9000, 1) == 1.0
    assert odds([0] * 4, 100, 3) == 0.0 and odds([0] * 4, 0, 3) == 1.0
    assert odds([1000] * 4, 9000, 3) == 0.0                          # 9 hands' worth needed, 3 left


def test_under_the_mouth_with_mouth_odds_the_plan_still_opens_with_a_play():
    from balatro.cards import Card as C
    hand = [C(2, "Clubs"), C(7, "Clubs"), C(9, "Hearts"), C(3, "Clubs"), C(9, "Clubs"), C(6, "Clubs"), C(7, "Spades"),
            C(3, "Hearts")]
    pile = [C(r, s) for r in (4, 5, 8, 10, 11, 12, 13, 14) for s in ("Hearts", "Spades")]
    bot = ValueBot()
    bot.MOUTH_ODDS = True
    run = _boss_round(bot, "The Mouth", hand, pile, needed=5_000)
    plan = bot._hand_type_plan(run, 5_000, bot._measure(run))
    assert plan is None or (plan[0] > 0 and plan[1])


def test_a_free_joker_from_a_pack_is_taken_for_its_resale_and_sold_before_it_scores():
    # EURSXV11 (the user, 29 Oct): with Joker Stencil every joker in a Mega Buffoon Pack measured below 0 (each costs
    # the Stencil X1), so the bot skipped them all, where taking one and selling it is free money
    from balatro.shop import PACKS, OpenPack
    buffoon = next(p for p in PACKS.values() if p.kind == "Buffoon" and p.size == "Normal")
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG["Joker Stencil"]()]
    clown = CATALOG["Chaos the Clown"]()                 # (a free reroll a shop: no X1 Mult's worth)
    assert bot.joker_worth(run, clown, bot.scoring_power(run)) < 0
    assert bot.pack_action(run, OpenPack(buffoon, [clown], 1)) == ("pick", 0, [])
    run.jokers.append(clown)                             # then, before the next round's first hand, sold
    hand = [Card(r, s) for r, s in ((2, "Hearts"), (5, "Clubs"), (9, "Hearts"), (13, "Spades"), (3, "Clubs"),
                                    (7, "Diamonds"), (8, "Spades"), (10, "Clubs"))]
    rnd = _round(bot, hand, [Card(4, "Spades")], needed=300)
    rnd.jokers, rnd.round_score = run.jokers, 0
    assert bot.round_action(rnd) == ("sell_joker", 1)
    rnd.round_hand_types["Pair"] += 1                    # not once a hand is played
    assert bot._dead_sale(rnd) is None


def test_constellation_counts_the_planets_the_shops_offer_before_any_is_used():
    # EURSXV11: no Planet used in four rounds, so Constellation was projected never to grow, and sold; owned, it makes
    # every Planet worth buying
    from balatro.strategy import planets_offered
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.rounds_played = 4
    assert 0.8 < planets_offered(run) < 1.0              # 2 x 1/7 in the shop's cards, 2 x 0.31 in its Celestial packs
    assert bot.growth_worth(run, CATALOG["Constellation"]()) > 0
    assert bot.growth_worth(run, CATALOG["Hologram"]()) > 0          # (Standard packs' cards, none added yet)


def test_a_shop_sale_records_its_worth_and_parts_for_the_play_tab():
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG["Chaos the Clown"](), CATALOG["Joker Stencil"]()]   # (in its order: no reorder first)
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [], [], []
    assert bot.shop_action(run, shop) == ("sell_joker", 0)
    p = bot.worth_parts[("sell_joker", 0)]
    assert p["kept"] < 0 and abs(p["gross"] - (p["sale"] - p["kept"])) < 1e-9
    assert bot.worths[("sell_joker", 0)] == p["gross"]


def test_riff_raff_is_worth_the_commons_it_makes_while_there_is_room():
    # ALEEB (29 Oct): Riff-Raff was worth only its rarity's weight (0.08); a free one was skipped with 4 slots empty
    bot = ValueBot()
    bot.RIFF_MEASURED = True
    run = Run(bot, game_seed="ALEEB", deck="Red Deck")
    run.jokers = [CATALOG["Canio"]()]
    base = bot.scoring_power(run)
    assert bot.joker_worth(run, CATALOG["Riff-Raff"](), base) > bot.joker_worth(run, CATALOG["Joker"](), base)
    run.jokers = [CATALOG[n]() for n in ("Canio", "Joker", "Greedy Joker", "Riff-Raff", "Banner")]   # no room: nothing
    assert bot.riff_worth(run, run.jokers[3]) == 0.0


def test_a_celestial_pack_counts_what_its_planets_grow_constellation_by():
    from balatro.shop import PACKS
    celestial = next(p for p in PACKS.values() if p.kind == "Celestial" and p.size == "Normal")
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    plain = bot.celestial_worth(run, celestial)
    run.jokers = [CATALOG["Constellation"]()]
    assert bot.planet_growth_worth(run) > 0
    assert bot.celestial_worth(run, celestial) > plain        # (Constellation alone scores nothing: the levels are the same)


def test_a_joker_that_takes_a_hand_pays_for_it_one_that_adds_capacity_gets_nothing_for_it():
    # the third review's M1 (2QL7UDYN, ante 1): Troubadour's -1 hand counted 0, so it was bought over Card Sharp
    bot = ValueBot()
    run = Run(bot, game_seed="2QL7UDYN", deck="Red Deck")
    base = bot.scoring_power(run)
    assert bot.capacity_change(run, CATALOG["Troubadour"]()) < -0.6        # 4+2 hands' worth to 3+2 (Hieroglyph's rule)
    assert bot.joker_worth(run, CATALOG["Card Sharp"](), base) > bot.joker_worth(run, CATALOG["Troubadour"](), base)
    drunkard = CATALOG["Drunkard"]()
    assert bot.capacity_change(run, drunkard) > 0                          # +1 discard: not counted
    counted = bot.bonus(drunkard, run)
    bot.capacity_change = lambda run, j: 0.0
    assert bot.bonus(drunkard, run) == counted


def test_money_a_joker_earns_counts_as_spare_money_far_past_the_reserve():
    # the third review's M2 (X9XXRX4K, $129: Satellite) and EURSXV11's Rocket (the user, 30 Oct): pay counted in full
    # where a spent dollar costs a tenth
    from balatro.modifiers import income
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    bot.INCOME_STRENGTH = 1.0                                   # (pure payers count 0 by default: modifiers.OFF)
    gold = CATALOG["Golden Joker"]()                            # $4 a round
    reserve = 5 * run.interest_cap + bot.RESERVE_EXTRA
    dollars = income(bot, run, gold) / bot.w.money
    assert dollars > reserve
    run.money = reserve - 5                                     # the first $5 fill the reserve, the rest are spare
    assert abs(bot.earned(run, gold) - bot.w.money * (5 + bot.spare_money * (dollars - 5))) < 1e-9
    run.money = 129                                             # all of it past the reserve
    assert abs(bot.earned(run, gold) - bot.spare_money * income(bot, run, gold)) < 1e-12


def test_reroll_surplus_counts_the_rerolls_the_bot_makes_later_not_only_those_made_so_far():
    # EURSXV11 (the user, 30 Oct): at ante 4 with no reroll yet, Reroll Surplus measured exactly 0
    from balatro.strategy import REROLLS_A_SHOP
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.ante, run.shops_seen, run.rerolls_done = 4, 9, 0
    base = bot.power(run)
    assert REROLLS_A_SHOP and max(REROLLS_A_SHOP.values()) > 1               # many rerolls late
    assert bot.voucher_worth(run, "Reroll Surplus", base) > 0


def test_with_slots_full_it_sells_a_spent_stencil_for_a_good_offer_not_a_joker_the_stencil_would_feed():
    # EURSXV11 (the user, 30 Oct): five jokers, so Joker Stencil gave X1. Ice Cream measured below its resale (gone,
    # its slot would feed the Stencil), so it was sold at once and Obelisk filled its slot; selling the Stencil for
    # Obelisk left more build and more money. The sale now competes with the swaps.
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.money = 30
    run.jokers = [CATALOG[n]() for n in ("Ice Cream", "Jolly Joker", "Zany Joker", "Mad Joker", "Joker Stencil")]
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [Offer("Joker", CATALOG["Cavendish"]())], [], []
    assert bot.shop_action(run, shop) == ("sell_joker", 4)
    assert any(k[0] == "sell_joker" and k[1] != 4 for k in bot.worths)        # (the plain sales were weighed too)


def test_burnt_joker_is_worth_the_levels_its_first_discards_bring():
    # CCU44VLE (the user, 30 Oct): Burnt Joker counted only its rarity in the shop (−0.30 at $8)
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.hand_plays["Two Pair"] = 4
    burnt = CATALOG["Burnt Joker"]()
    assert bot.burnt_worth(run, burnt) > 0
    assert bot.bonus(burnt, run) > bot.bonus(burnt)                 # (with the run: its levels; without: weights only)


def test_calibrated_odds_read_a_margin_as_what_the_bots_play_beats_and_a_skip_pays_for_its_risk():
    # the user's CCU44VLE (30 Oct): a bare deck's skip check read 0.68 against ante 1's Big Blind (beaten 98% of the time)
    # and its boss odds 2% (margin 0.38); a Foil Tag counted a flat 0.15 for +50 chips
    bot = ValueBot()
    assert bot.margin_odds(1.0) == 0.5                              # the old curve: even at 1
    bot.ODDS_CALIBRATED = True
    assert 0.4 < bot.margin_odds(0.416) < 0.6 and bot.margin_odds(1.0) > 0.9   # the fit: even near 0.42
    assert bot.margin_odds(0.7, boss=False) > bot.margin_odds(0.7)  # a Big Blind is easier than a boss at the same margin
    bot.EDITION_TAGS_MEASURED = True
    run = Run(bot, game_seed="CCU44VLE", deck="Anaglyph Deck", max_ante=8)
    run.start_ante()
    run.blind = run.make_blind(0)
    from balatro.items import TAGS
    foil = TAGS["Foil Tag"]()
    assert bot.edition_worth(run, "Foil") > 0.5                     # +50 chips on a bare deck
    parts = bot.skip_parts(run, run.blind, foil)
    assert any("risk" in t and v < 0 for t, v in parts["skip_parts"])
    assert bot.skip_blind(run, run.blind, foil) == (parts["skip"] > parts["play"])


def test_a_level_never_lowers_a_hands_best_score():
    # CCU44VLE (the user, 30 Oct): a free Pluto measured -0.025. Ranked at their levels, High Card's level pushed the
    # Pair that played its low kicker (so Raised Fist read a higher card held) out of the sets scored in full.
    import random
    bot = ValueBot()
    run = Run(bot, game_seed="CCU44VLE", deck="Anaglyph Deck")
    run.jokers = [CATALOG[n]() for n in ("Misprint", "Raised Fist", "Blue Joker")]
    rng = random.Random(5)
    with bot._as_round_starts(run):                      # (measured as level_worth does: the sets ranked at the
        for _ in range(40):                              # levels the change is measured from)
            hand = rng.sample(run.deck, 7)
            for h in ("High Card", "Pair", "Two Pair", "Flush"):
                with bot._ranked_at(run.hand_levels):
                    before = bot._best_log(run, hand)
                    run.hand_levels[h] += 1
                    after = bot._best_log(run, hand)
                    run.hand_levels[h] -= 1
                assert after >= before - 1e-12, (h, [c.label() for c in hand])
    for h in run.hand_levels:                            # no Planet measures below 0
        assert bot.level_worth(run, h) >= 0, h
    run.hand_levels["Pair"] = 5                          # a levelled hand keeps its kicker variants: three of them
    hand = [Card(5, "Hearts"), Card(5, "Diamonds"), Card(3, "Clubs"), Card(12, "Clubs"), Card(13, "Diamonds"),
            Card(10, "Clubs"), Card(8, "Hearts")]
    pairs = [sub for sub, r in bot._candidates(run, hand) if r.name == "Pair"]
    assert len(pairs) >= 3


def test_the_high_priestess_waits_for_room_for_both_planets():
    # CCU44VLE (the user, 30 Oct): with The World held, used in the shop it makes one Planet of its two
    from balatro.items import CONSUMABLES
    for held, used in ((["The World", "The High Priestess"], False), (["The High Priestess"], True)):
        bot = ValueBot()
        run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
        run.consumables = [CONSUMABLES[n]() for n in held]
        shop = Shop(run)
        shop.cards, shop.packs, shop.vouchers = [], [], []
        action = bot.shop_action(run, shop)
        assert (action[0] == "use") == used, (held, action)


def test_a_purple_seal_card_played_loses_the_tarot_its_discard_would_make():
    # CCU44VLE (the user, 30 Oct): a Purple Seal 4 played as a Pair's kicker, a discard and a slot to spare
    from balatro.modifiers import purple_forfeit
    hand = [Card(10, "Spades"), Card(10, "Clubs"), Card(4, "Clubs", seal="Purple"), Card(6, "Hearts"),
            Card(5, "Diamonds"), Card(12, "Clubs"), Card(13, "Hearts")]
    bot = ValueBot()
    run = _round(bot, list(hand), [Card(2, "Hearts")], needed=300)
    assert purple_forfeit(bot, run, [hand[0], hand[1], hand[2]]) > 0
    assert purple_forfeit(bot, run, [hand[0], hand[1]]) == 0
    run.discards_left = 0                                        # no discard left: nothing to lose
    assert purple_forfeit(bot, run, [hand[0], hand[1], hand[2]]) == 0


def test_double_tags_are_kept_for_the_big_blinds_better_tag():
    # CCU44VLE (the user, 30 Oct): two Double Tags held, a Foil Tag on the Small Blind with the slots full and a
    # Negative Tag on the Big Blind: skipping now spent the copies on the Foil Tag
    from balatro.items import TAGS
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.start_ante()
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "Zany Joker", "Mad Joker", "Crazy Joker")]
    run.tags = [TAGS["Double Tag"](), TAGS["Double Tag"]()]
    run.ante_tags = [TAGS["Juggle Tag"](), TAGS["Negative Tag"]()]    # (the Big Blind's tag clearly the better one)
    run.blind = run.make_blind(0)
    assert bot.tag_worth(run, run.ante_tags[1]) > bot.tag_worth(run, run.ante_tags[0])
    assert not bot.skip_blind(run, run.blind, run.ante_tags[0])
    run.tags = []                                                    # no copies to keep: each skip on its own
    assert bot._double_lookahead(run, run.blind, run.ante_tags[0], 1.0, 0.5)


def test_milk_likely_spends_a_spare_hand_on_pay_when_the_round_is_all_but_won():
    # CCU44VLE (the user, 30 Oct): a round cleared in about 1.5 hands, Business Card, hands to spare. A pair of Jacks
    # pays $2 on average ($2 each, 1 in 2), more than the $1 a hand left over brings; a lone face card pays $1, no gain.
    hand = [Card(10, "Spades"), Card(10, "Hearts"), Card(10, "Clubs"), Card(10, "Diamonds"), Card(11, "Clubs"),
            Card(11, "Diamonds"), Card(2, "Hearts")]
    pile = [Card(r, s) for r in (9, 8, 7, 4, 13, 12) for s in ("Spades", "Hearts")]
    moves = {}
    for flag in (False, True):
        bot = ValueBot()
        bot.MILK_LIKELY = flag
        run = _round(bot, list(hand), list(pile), needed=300)
        run.jokers = [CATALOG[n]() for n in ("Business Card", "Joker", "Jolly Joker")]
        run.blind.chips, run.round_score, run.hands_left, run.discards_left = 2100, 0, 5, 2
        moves[flag] = bot.round_action(run)
    assert sorted(moves[False][1]) == [0, 1, 2, 3]                  # the four 10s, short of the target
    assert moves[True][0] == "play" and sorted(moves[True][1]) == [4, 5]   # the pair of Jacks first


def test_copies_of_a_joker_tag_with_the_slots_full_each_replace_the_next_weakest_joker():
    # CCU44VLE (the user, 30 Oct): three Rare Tags (two Double Tags held), slots full, each counted over the weakest
    from balatro.items import TAGS
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "Zany Joker", "Cavendish", "Gros Michel")]
    run.tags = [TAGS["Double Tag"](), TAGS["Double Tag"]()]
    each = bot.tag_copies_worth(run, TAGS["Rare Tag"]())
    assert len(each) == 3 and each[0] >= each[1] >= each[2]
    assert each[0] == bot.tag_worth(run, TAGS["Rare Tag"]())          # the first: over the weakest, as before
    run.jokers = run.jokers[:2]                                          # room: every copy the same
    each = bot.tag_copies_worth(run, TAGS["Rare Tag"]())
    assert each == [each[0]] * 3


def test_behind_dig_discards_toward_what_each_hand_must_make():
    # CCU44VLE (the user, 30 Oct): 52,500 in 5 hands, a Pair played where a discard reached the average needed one
    # time in five, and the round ended with its discards unused
    hand = [Card(13, "Spades"), Card(10, "Spades"), Card(10, "Hearts"), Card(8, "Hearts"), Card(7, "Clubs"),
            Card(7, "Diamonds"), Card(5, "Diamonds")]
    pile = [Card(10, s) for s in ("Clubs", "Diamonds", "Spades", "Hearts")] * 3 + [Card(r, "Clubs") for r in (2, 3, 4, 6)]
    moves = {}
    for flag in (False, True):
        bot = ValueBot()
        bot.BEHIND_DIG = flag
        run = _round(bot, list(hand), list(pile), needed=300)
        run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker")]
        run.blind.chips, run.round_score, run.hands_left, run.discards_left = 4000, 0, 4, 3
        moves[flag] = bot.round_action(run)
    assert moves[True][0] == "discard"
    kept = [c for i, c in enumerate(hand) if i not in moves[True][1]]
    assert sum(c.rank == 10 for c in kept) == 2                     # the 10s kept, to draw more


def test_odds_by_ante_read_a_late_round_as_harder_at_the_same_margin():
    # the calibration by ante (30 Oct): a Big Blind at antes 6-8 beaten 86% of the time at margin 0.75-1.0, at antes
    # 1-3 96%; the user's CCU44VLE skip into ante 7's Big Blind read at 95% by the pooled curve
    bot = ValueBot()
    bot.ODDS_CALIBRATED = bot.ODDS_BY_ANTE = True
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.ante = 2
    early = bot.margin_odds(0.79, boss=False, run=run)
    run.ante = 7
    late = bot.margin_odds(0.79, boss=False, run=run)
    assert 0.95 < early and 0.85 < late < 0.92
    assert bot.margin_odds(0.79, boss=False) > late                  # without a run: the pooled curve


def test_rollout_odds_play_the_blind_out_on_copies_and_leave_the_game_alone():
    # the user's CCU44VLE (30 Oct): the margin curve read ante 7's Big Blind at 88%, played out it was 0 of 201
    bot = ValueBot()
    bot.ROLLOUT_ODDS = True
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.start_ante()
    streams = {k: r.getstate() for k, r in run.rng.items()}
    deck, seeds = [c.uid for c in run.deck], run.seedrng
    easy = bot.outlook_odds(run, 0)
    assert {k: r.getstate() for k, r in run.rng.items()} == streams          # the game's chances aren't drawn
    assert [c.uid for c in run.deck] == deck and run.seedrng is seeds and run.blind is None
    run.ante = 8                                                              # a bare deck against 50,000
    hard = bot.outlook_odds(run, 0)
    assert easy > 0.8 and hard < 0.01
    assert bot.outlook_odds(run, 0, gain=8.0) > 0.99 > hard                   # a stronger build moves every rollout
    bot._outlooks.clear()
    assert bot.outlook_odds(run, 0) == hard                                   # the same position reads the same


def test_survival_counts_what_an_option_adds_to_the_odds_of_the_next_blind(monkeypatch):
    # the user's priority (30 Oct): a purchase counted only the power it adds, the same in a must-win round as in a
    # safe one, and a sale that weakens the next round cost nothing more
    monkeypatch.setattr("balatro.strategy.ROLLOUT_FIT", (0.0, 1.0))          # (the odds' calibration isn't what's tested)
    monkeypatch.setattr("balatro.strategy.ROLLOUT_BLEND", (0.0, 1.7, 0.0, 0.0))
    bot = ValueBot()
    bot.SURVIVAL = True
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.ante = 2
    run.start_ante()
    run.blind, run.money = run.make_blind(0), 20                             # the Small Blind beaten: the Big is next
    run.jokers = [CATALOG["Joker"]()]
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [Offer("Joker", CATALOG["Cavendish"]())], [], []
    run.current_shop = shop
    assert 0.1 < bot.outlook_odds(run, 1) < bot.SURVIVAL_SURE
    buy, sell = bot.survival_gain(run, ("buy", "card", 0)), bot.survival_gain(run, ("sell_joker", 0))
    assert buy > 0 > sell and bot.survival_gain(run, ("leave",)) == 0.0
    assert [j.name for j in run.jokers] == ["Joker"] and len(shop.cards) == 1 and run.money == 20   # tried on copies
    assert bot.shop_action(run, shop) == ("buy", "card", 0)
    assert bot.worth_parts[("buy", "card", 0)]["survival"] == pytest.approx(buy)


def _ante2_shop_run(bot, jokers):
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.ante = 2
    run.start_ante()
    run.blind, run.money = run.make_blind(0), 20                             # the Small Blind beaten: the Big is next
    run.rounds_played, run.hands_played, run.discards_made = 4, 12, 4
    run.jokers = jokers
    return run


def test_goal_margin_projects_growing_jokers_and_hand_levels_to_ante_8_on_a_copy():
    # the user's priority (30 Oct): scaling toward ante 8's boss, where 60% of the losses are
    bot = ValueBot()
    run = _ante2_shop_run(bot, [CATALOG["Green Joker"]()])
    run.hand_levels["Pair"] = 3
    assert bot.rounds_to_goal(run) == 3 * 6 + 1 + 0.5
    base = run.ante_table[8] * run.blind_scale
    now = math.log(math.expm1(bot.power(run, plain=True)) * bot._capacity(run)[0] * AVERAGE_STRAIN / (2 * base))
    assert bot.goal_margin(run) > now + 0.1                                  # Green Joker grown, Pair levelled further
    assert run.jokers[0].value == 0 and run.hand_levels["Pair"] == 3       # the run left alone
    gone = _ante2_shop_run(bot, [CATALOG["Joker"](), CATALOG["Seltzer"]()])
    gone.jokers[1].hands = 3                                                # runs out long before ante 8
    plain = _ante2_shop_run(bot, [CATALOG["Joker"]()])
    assert bot.goal_margin(gone) == pytest.approx(bot.goal_margin(plain))
    gone.ante = 9
    assert bot.rounds_to_goal(gone) == 0 and bot.scaling_odds(gone) == 1.0


def test_scaling_counts_what_an_option_adds_to_the_odds_of_beating_ante_8(monkeypatch):
    monkeypatch.setattr("balatro.strategy.SCALING_FIT", ((-1.0,) * 8, ((1.0, 0.0, 0.0),) * 3))   # (the fit isn't tested)
    bot = ValueBot()
    bot.SCALING = True
    run = _ante2_shop_run(bot, [CATALOG["Joker"]()])
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [Offer("Joker", CATALOG["Cavendish"]())], [], []
    run.current_shop = shop
    buy, sell = bot.scaling_gain(run, ("buy", "card", 0)), bot.scaling_gain(run, ("sell_joker", 0))
    assert buy > 0 > sell and bot.scaling_gain(run, ("leave",)) == 0.0
    assert [j.name for j in run.jokers] == ["Joker"] and len(shop.cards) == 1 and run.money == 20   # tried on copies
    assert bot.shop_action(run, shop) == ("buy", "card", 0)
    assert bot.worth_parts[("buy", "card", 0)]["ante 8"] == pytest.approx(buy)
    monkeypatch.setattr("balatro.strategy.SCALING_FIT", ((-1.0,) * 8, ((0.0, 3.0, 0.0),) * 3))   # money alone counts
    bot._scaling_now.clear()                                                # (the odds now were read by the old fit)
    assert bot.scaling_gain(run, ("buy", "card", 0)) < 0 < bot.scaling_gain(run, ("sell_joker", 0))


def test_a_negative_joker_counts_the_rounds_it_stays_beyond_a_joker_that_takes_a_slot():
    # the user (30 Oct): a Negative joker is never sold to make room, so it stays where another is kept ~6 rounds
    from balatro.modifiers import rounds_left
    bot = ValueBot()
    bot.NEGATIVE_LASTS = True
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck", max_ante=8)
    run.ante = 2
    run.start_ante()
    base = bot.scoring_power(run)
    plain, neg = (bot.joker_worth(run, CATALOG["Cavendish"](e), base) for e in (None, "Negative"))
    assert rounds_left(run) > bot.HOLD_ROUNDS and neg > plain * 1.3
    bot.HOLD_ROUNDS = 1000                                           # no more rounds than any joker gets: no premium
    assert abs(bot.joker_worth(run, CATALOG["Cavendish"]("Negative"), base) - plain) < 1e-9
