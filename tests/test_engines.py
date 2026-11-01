import random
import types

from balatro.cards import Card
from balatro.engines import DNA, ENGINES, FLUSH, HELD, consumable_expected, expected_changes, joker_chance, shops_ahead
from balatro.items import CONSUMABLES
from balatro.jokers import CATALOG
from balatro.run import Run
from balatro.strategy import ValueBot


def _run(bot=None, jokers=(), steel_kings=0, red=False):
    """A seeded Red Deck run out of a round, with these jokers and this many Kings made Steel (with Red Seals)."""
    run = Run(bot or ValueBot(), game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG[n]() for n in jokers]
    for c in [c for c in run.deck if c.rank == 13][:steel_kings]:
        c.enhancement = "Steel"
        if red:
            c.seal = "Red"
    return run


def test_joker_chance_grows_with_the_cards_seen_and_counts_only_jokers_that_can_come():
    run = _run()
    one = joker_chance(run, ["Baron"], 10)
    assert 0 < one < joker_chance(run, ["Baron"], 40) < 1
    assert joker_chance(run, ["Baron", "Mime"], 10) > one
    assert joker_chance(run, ["Baron"], 10, buffoon=4) > one     # Buffoon pack cards are all jokers
    assert joker_chance(run, ["Steel Joker"], 10) == 0          # no Steel card in the deck: it can't come
    run.deck[0].enhancement = "Steel"
    assert joker_chance(run, ["Steel Joker"], 10) > 0
    run.jokers = [CATALOG["Baron"]()]
    assert joker_chance(run, ["Baron"], 10) == 0                 # owned


def test_consumables_expected_grow_with_the_shops_and_with_a_merchant():
    run = _run()
    few, more = consumable_expected(run, "The Chariot", 3), consumable_expected(run, "The Chariot", 6)
    assert 0 < few < more
    run.vouchers.append("Tarot Merchant")
    assert consumable_expected(run, "The Chariot", 3) > few
    assert shops_ahead(run, 2) == 6


def test_expected_changes_make_the_whole_ones_and_return_the_fraction():
    trial = types.SimpleNamespace(n=0)

    def one(t):
        t.n += 1
        return True
    rest = expected_changes(trial, 2.4, one)
    assert trial.n == 2 and len(rest) == 1 and abs(rest[0][0] - 0.4) < 1e-9
    assert expected_changes(trial, 0.004, one) == [] and trial.n == 2


def test_held_progress_counts_its_group_and_the_engine_cards_made_not_the_starting_kings():
    assert HELD.progress(_run()) == 0                             # every deck's 4 Kings: nothing made yet
    run = _run(jokers=("Baron",), steel_kings=1)
    assert abs(HELD.progress(run) - (0.5 + 0.5 * 2 / 4)) < 1e-9  # Baron; a Steel King counts twice
    run = _run(jokers=("Baron",), steel_kings=2, red=True)
    assert abs(HELD.progress(run) - 1.0) < 1e-9                  # 2 Steel Red Seal Kings: 6 of 4
    assert HELD.owned(run) and not HELD.owned(_run())


def test_held_projection_puts_the_chariots_on_kings_and_leaves_the_run_unchanged():
    import copy
    run = _run(jokers=("Baron",))
    trial = copy.deepcopy(run)
    rest = HELD.project(run, trial, 30)                          # many shops: several Chariots expected
    steel = [c for c in trial.deck if c.enhancement == "Steel"]
    assert steel and all(c.rank == 13 for c in steel[:4])
    assert not any(c.enhancement == "Steel" for c in run.deck)
    assert all(0 < f < 1 for f, _ in rest)


def test_dna_projection_copies_the_main_strategys_key_card_once_a_round_for_each_time_dna_fires():
    import copy
    run = _run(steel_kings=1, red=True)
    run.jokers = [CATALOG["Blueprint"](), CATALOG["DNA"]()]          # Blueprint copies the joker to its right: DNA
    trial = copy.deepcopy(run)
    DNA.project(run, trial, 3, HELD.key)
    new = [c for c in trial.deck if c.uid not in {x.uid for x in run.deck}]
    assert len(new) == 2 * 3                                         # DNA and its copy, 3 rounds
    assert all(c.rank == 13 and c.enhancement == "Steel" and c.seal == "Red" for c in new)
    trial = copy.deepcopy(run)                                       # under Flush (Hearts): the best Heart
    run.jokers.append(CATALOG["Lusty Joker"]())
    trial.jokers.append(CATALOG["Lusty Joker"]())
    DNA.project(run, trial, 1, FLUSH.key)
    new = [c for c in trial.deck if c.uid not in {x.uid for x in run.deck}]
    assert new and all(c.suit == "Hearts" for c in new)
    trial = copy.deepcopy(run)
    assert DNA.project(run, trial, 3, None) == [] and len(trial.deck) == len(run.deck)   # no strategy: no copies


def test_dna_is_a_tool_it_is_never_scored_nor_the_main_engine_and_starts_no_plan():
    assert DNA.kind == "tool" and HELD.kind == FLUSH.kind == "strategy"
    bot = _plan_bot()
    run = _run(bot, jokers=("DNA",))
    plan = bot._plan(run)
    assert "dna" not in plan[:1]
    assert "dna" not in bot.plan_log[-1]["scores"]
    bot = _plan_bot(PLAN_MIN=99.0)                                   # no plan: buying DNA starts none
    empty = _run(bot)
    assert bot._plan_after(empty, _with(empty, "DNA"), ()) == ()


def _with(run, *names):
    import copy
    t = copy.deepcopy(run)
    t.jokers += [CATALOG[n]() for n in names]
    return t


def _suited_run(bot=None, jokers=(), hearts=0):
    """A Red Deck run with these jokers and this many more cards (off-suit, low first) turned to Hearts."""
    run = _run(bot, jokers)
    for c in sorted((c for c in run.deck if c.suit != "Hearts"), key=lambda c: (c.rank, c.uid))[:hearts]:
        c.suit = "Hearts"
    return run


def test_flush_suit_progress_and_key_card():
    from balatro.engines import flush_suit
    assert flush_suit(_run(jokers=("Lusty Joker",))) == "Hearts"
    assert flush_suit(_run(jokers=("Arrowhead",))) == "Spades"
    assert flush_suit(_suited_run(hearts=5)) == "Hearts"             # no suit joker: the deck's most common suit
    assert FLUSH.progress(_run()) == 0                               # a plain deck: 25% a suit
    assert FLUSH.progress(_run(jokers=("Droll Joker",))) == 0.5
    full = _suited_run(jokers=("Lusty Joker",), hearts=19)           # 32 of 52 Hearts: above 60%
    assert abs(FLUSH.progress(full) - 1.0) < 1e-9
    full.deck[0].enhancement = "Glass"
    full.deck[0].suit = "Hearts"
    assert FLUSH.key(full) is full.deck[0]


def test_flush_projection_turns_off_suit_cards_to_its_suit_and_leaves_the_run_unchanged():
    import copy
    run = _run(jokers=("Lusty Joker",))
    trial = copy.deepcopy(run)
    FLUSH.project(run, trial, 60)                                    # many shops: several Suns and Hanged Men
    hearts = lambda r: sum(c.suit == "Hearts" for c in r.deck)      # noqa: E731
    assert hearts(trial) > hearts(run) == 13
    assert len(trial.deck) < len(run.deck) == 52                     # The Hanged Man's off-suit cards gone
    assert sum(c.suit == "Hearts" for c in run.deck) == 13


def test_flush_wants_its_suits_tarot_on_off_suit_cards_and_offers_it_under_a_flush_plan():
    run = _run(jokers=("Lusty Joker",))
    assert FLUSH.prefers(run, "The Sun", Card(5, "Spades")) and not FLUSH.prefers(run, "The Sun", Card(5, "Hearts"))
    assert not FLUSH.prefers(run, "The Moon", Card(5, "Spades"))      # another suit's Tarot
    assert FLUSH.prefers(run, "The Hanged Man", Card(5, "Spades"))
    assert not FLUSH.prefers(run, "The Hanged Man", Card(5, "Spades", enhancement="Glass"))
    bot = _plan_bot(PLAN_HELD=False)
    run = _run(bot, jokers=("Lusty Joker", "Droll Joker"))
    assert bot._plan(run)[:1] == ("flush",)
    sun = CONSUMABLES["The Sun"]()
    run.consumables = [sun]
    run.hand = [c for c in run.deck if c.suit != "Hearts"][:6] + [c for c in run.deck if c.suit == "Hearts"][:2]
    assert bot._targets(run, sun, run.hand) is None                  # 2 Hearts in hand: today it would wait
    uses = bot._uses(run, sun, run.hand)
    assert uses and all(all(run.hand[i].suit != "Hearts" for i in u[0]) for u in uses)


def test_a_strategy_that_doesnt_fit_the_main_one_counts_only_as_a_switch():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron", "Mime"), steel_kings=3, red=True)
    plan = bot._plan(run)
    assert plan[0] == "held"
    assert bot._plan_after(run, _with(run, "Greedy Joker"), plan) == plan   # one suit joker doesn't outweigh it
    assert "dna" in bot._plan_after(run, _with(run, "DNA"), plan)           # a tool joins


def test_a_missing_joker_counts_only_for_what_the_projection_adds_to_it(monkeypatch):
    import balatro.strategy as s
    monkeypatch.setattr(s, "joker_chance", lambda run, names, cards, buffoon=0.0: 1.0)
    bot = _plan_bot()
    run = _run(bot)
    run.max_ante = run.ante - 1                                     # no shops ahead: the projection changes nothing
    none = bot._plan_value(run, run, ())
    assert abs(bot._plan_value(run, run, ("flush",)) - none) < 1e-9    # Onyx Agate's own worth isn't the plan's
    plain = _plan_bot(PLAN_SYNERGY=False)
    assert plain._plan_value(run, run, ("flush",)) > plain._plan_value(run, run, ())


def test_the_held_engine_holds_steel_cards_and_kings_with_baron_and_wants_the_chariot_on_a_king():
    run = _run(jokers=("Baron",))
    king, ace = Card(13, "Spades"), Card(14, "Hearts")
    assert HELD.holds(run, king) and not HELD.holds(run, ace)
    assert HELD.holds(run, Card(14, "Hearts", enhancement="Steel"))
    assert HELD.prefers(run, "The Chariot", king) and not HELD.prefers(run, "The Chariot", ace)
    assert not HELD.prefers(run, "The Chariot", Card(13, "Spades", enhancement="Steel"))
    assert set(ENGINES) == {"held", "flush", "dna"}


def _plan_bot(**switches):
    bot = ValueBot()
    bot.PLAN = True
    for k, v in switches.items():
        setattr(bot, k, v)
    return bot


def _held_bot(**switches):
    """A plan bot with only the held strategy (and the DNA tool): for tests of how held plays, not of the choice."""
    return _plan_bot(PLAN_FLUSH=False, **switches)


def test_a_missing_group_counts_once_at_its_chance(monkeypatch):
    import balatro.strategy as s
    bot = _plan_bot(PLAN_SYNERGY=False)                           # the chance term as such
    run = _run(bot, steel_kings=3, red=True)                      # the held group missing
    values = {}
    for p in (0.0, 0.5, 1.0):
        monkeypatch.setattr(s, "joker_chance", lambda run, names, cards, buffoon=0.0, p=p: p)
        values[p] = bot._plan_value(run, run, ("held",))
    assert values[1.0] > values[0.0]
    assert abs(values[0.5] - (values[0.0] + values[1.0]) / 2) < 1e-9


def test_the_plan_never_reads_the_game_seed_nor_the_draw_piles_order():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron",), steel_kings=2)
    calls = []

    class Spy:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError(f"the plan read the game seed: {name}")

    add_mime = lambda t: t.jokers.append(CATALOG["Mime"]())                    # noqa: E731
    real, run.seedrng = run.seedrng, Spy()
    try:
        worth = bot.plan_worth(run, add_mime, names=("Mime",))
    finally:
        run.seedrng = real
    assert calls == [] and worth != 0
    run.blind = run.make_blind(0)                                 # in a round, with a draw pile to shuffle
    run.in_round, run.hand, run.draw_pile = True, run.deck[:8], run.deck[8:]
    worth = _plan_bot().plan_worth(run, add_mime, names=("Mime",))
    random.Random(1).shuffle(run.draw_pile)
    assert _plan_bot().plan_worth(run, add_mime, names=("Mime",)) == worth


def test_with_baron_and_steel_kings_the_plan_is_held_and_dna_fits_it():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron",), steel_kings=3, red=True)
    plan = bot._plan(run)
    assert set(plan) == {"held", "dna"}                           # dna: its Steel cards to copy (progress above 0)
    assert bot.plan_log and set(bot.plan_log[-1]["plan"]) == {"held", "dna"}
    assert _plan_bot(PLAN_MIN=99.0)._plan(run) == ()              # nothing scores that much: no plan


def test_with_steel_red_seal_kings_held_by_baron_and_mime_dna_is_worth_more_than_wee_joker():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron", "Mime"), steel_kings=3, red=True)
    base = bot.power(run)
    adj = bot.adjust(run, base)
    dna = bot.joker_worth(run, CATALOG["DNA"](), base) + adj(("joker", "DNA"))
    wee = bot.joker_worth(run, CATALOG["Wee Joker"](), base) + adj(("joker", "Wee Joker"))
    assert adj(("joker", "DNA")) > 0
    assert dna > wee


def test_an_item_can_start_an_engine_and_a_joker_outside_the_plan_gets_nothing_with_a_free_slot():
    bot = _plan_bot()
    run = _run(bot)                                                 # a plain deck
    adj = bot.adjust(run, bot.power(run))
    assert adj(("joker", "Baron")) > 0                              # starts held (or adds to it)
    assert adj(("joker", "Jolly Joker")) == 0


def test_with_dna_copying_kings_selling_baron_counts_what_the_plan_loses():
    bot = _held_bot()
    run = _run(bot, jokers=("Baron", "DNA", "Jolly Joker"), steel_kings=2)
    adj = bot.adjust(run, bot.power(run))
    assert adj(("joker", "Baron")) > abs(adj(("joker", "Jolly Joker")))
    bot.PLAN = False
    assert bot.adjust(run, bot.power(run))(("joker", "Baron")) == 0


def _hand_of(run, ranks):
    """Plain hand cards taken from the run's own deck (so deck changes on them are seen), by rank, in order."""
    out, used = [], set()
    for r in ranks:
        c = next(c for c in run.deck if c.rank == r and c.enhancement is None and id(c) not in used)
        used.add(id(c))
        out.append(c)
    return out


def test_under_a_held_plan_the_chariot_is_offered_and_used_on_a_king():
    bot = _held_bot()
    run = _run(bot, jokers=("Baron", "DNA"))
    chariot = CONSUMABLES["The Chariot"]()
    run.consumables = [chariot]
    run.hand = _hand_of(run, (14, 13, 7, 5, 3, 9, 2, 4))          # an Ace first, a plain King second
    uses = bot._uses(run, chariot, run.hand)
    assert [1] in [u[0] for u in uses]                             # the King is offered (today: highest and lowest only)
    k = bot.consumable_choice(run, chariot, uses)
    assert k < len(uses) and uses[k][0] == [1]


def test_keeping_the_chariot_for_a_king_is_worth_something_only_when_no_king_is_in_hand():
    bot = _held_bot()
    run = _run(bot, jokers=("Baron", "DNA"))
    chariot = CONSUMABLES["The Chariot"]()
    run.consumables = [chariot]
    run.hand = _hand_of(run, (14, 7, 5, 3, 9, 2, 4, 6))
    assert bot._plan_keep(run, chariot, full=True) > 0
    run.hand = _hand_of(run, (13, 7, 5, 3, 9, 2, 4, 6))
    assert bot._plan_keep(run, chariot, full=True) == 0


def test_under_a_held_plan_a_standard_pack_gives_its_steel_king():
    bot = _held_bot()
    run = _run(bot, jokers=("Baron", "DNA"), steel_kings=1)
    pack = types.SimpleNamespace(cards=[Card(5, "Clubs"), Card(13, "Hearts", enhancement="Steel")])
    assert bot.pack_action(run, pack) == ("pick", 1, [])
    bot.PLAN = False
    assert bot.pack_action(run, pack) == ("pick", 1, [])            # and without it: its own worth (card_add_worth)


def test_under_a_held_plan_an_arcana_pack_is_worth_its_chance_of_the_chariot():
    bot = _held_bot()
    run = _run(bot, jokers=("Baron", "DNA"))
    assert bot._plan_pack(run, "Arcana Pack") > 0
    assert bot._plan_pack(run, "Celestial Pack") == 0
    assert bot._plan_reroll(run) == 0                              # its groups are owned: nothing for a reroll to find


def _held_round(bot, hand, pile):
    """A Small Blind in play under a held plan: Baron and DNA, the hand's Kings plain (a Steel card is protected
    already: held_value), so only the plan keeps them."""
    run = _run(bot, jokers=("Baron", "DNA"))
    bot._plan(run)                                                  # chosen in the shop before the round
    run.blind = run.make_blind(0)
    run.in_round, run.round_score = True, 0
    run.hands_left, run.discards_left = 4, 3
    run.hand, run.draw_pile = hand(run), pile
    return run


def test_under_a_held_plan_a_discard_never_throws_a_held_card():
    bot = _held_bot()
    run = _held_round(bot, lambda r: _hand_of(r, (13, 13, 2, 3, 5, 7, 9, 10)), [Card(4, "Spades"), Card(6, "Clubs")])
    assert bot._holds(run)(run.hand[0])
    for _, opt, _ in bot._ranked_discards(run, []):
        assert not any(run.hand[i].rank == 13 for i in opt)


def test_playing_a_held_card_costs_for_the_hands_left_after_this_one():
    from balatro.modifiers import plan_hold_cost
    bot = _held_bot()
    run = _held_round(bot, lambda r: _hand_of(r, (13, 13, 2, 3, 5, 7, 9, 10)), [])
    kings = [run.hand[0], run.hand[1]]
    assert plan_hold_cost(bot, run, kings) == 2 * 3 * bot.PLAN_HOLD
    assert plan_hold_cost(bot, run, [run.hand[2]]) == 0
    assert bot._measure(run) is not None                            # so play_bonus runs


def test_the_main_strategy_changes_only_for_a_clear_lead(monkeypatch):
    bot = _plan_bot()
    run = _run(bot)
    values = {(): 0.0, ("held",): 0.03, ("flush",): 0.01}
    monkeypatch.setattr(bot, "_plan_value", lambda run0, state, plan, skip=frozenset(): values[plan])
    assert bot._plan(run)[0] == "held"
    values[("flush",)] = 0.045                                      # half as much again, but under PLAN_MARGIN more
    run.rounds_played += 1
    assert bot._plan(run)[0] == "held"
    values[("flush",)] = 0.06
    run.rounds_played += 1
    assert bot._plan(run)[0] == "flush"
    values[("flush",)], values[("held",)] = -0.01, 0.0              # just under PLAN_MIN, held no clear lead: kept
    run.rounds_played += 1
    assert bot._plan(run)[0] == "flush"
    values[("flush",)] = -0.03                                      # well under: chosen afresh
    run.rounds_played += 1
    assert bot._plan(run) == ()                                     # (held at 0 isn't above PLAN_MIN)
