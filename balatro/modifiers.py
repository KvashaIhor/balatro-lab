"""Behaviour modifiers: what each joker rewards or punishes beyond the score of the hand in front of the bot, so
the bot plays to the jokers it has (and to Purple Seals).

The value bot judges a play, a discard or a purchase by the score it gives now. Many jokers pay off later: Runner
keeps the +15 Chips a Straight gives it, a scoring face card throws away everything Ride the Bus has built up,
Mail-In Rebate pays $5 for every discarded card of its rank, Satellite pays every round for each new Planet used.
Each RULE says what one joker (or seal) rewards, and its worth is measured, not guessed: the joker's lasting
change is applied to a copy of it and the build's power (ValueBot.power) measured with it, or the money counted
at the bot's money weight. Each rule has a strength in the bot's Weights (`mods`, 1 by default), which evolution
can tune: the neurons of how much the bot cares.

Hooks (strategy.py): play_bonus ranks the plays of a hand, discard_bonus the discards (and discard_options adds the
ones only a rule wants), planet_bonus and card_bonus the Planets and playing cards it buys or takes, income what
a joker it buys or keeps pays every round, skip_bonus
and reroll_bonus skipping a pack and rerolling, spend_cost what money spent takes from the build, and timed the
jokers that act on some hands only, for ValueBot.power.
"""
from __future__ import annotations

import copy
import math
from collections import Counter

from .hands import evaluate

# rule -> what it rewards (labels for the Evolution tab and the README)
RULES = {
    "Space Joker": "a 1 in 4 chance to level up the hand played: play the hand worth levelling",
    "Ride the Bus": "+1 Mult a hand without a scoring face card; a scoring face card resets it",
    "Runner": "+15 Chips for good each time a Straight is played",
    "Square Joker": "+4 Chips for good each time exactly 4 cards are played",
    "Spare Trousers": "+2 Mult for good each time a Two Pair is played",
    "Obelisk": "X0.2 Mult a hand that isn't the most played hand; the most played hand resets it",
    "Supernova": "+1 Mult for good to the poker hand played (its Mult is the times it was played)",
    "Wee Joker": "+8 Chips for good for each scoring 2",
    "Hiker": "+5 Chips for good on each scoring card",
    "Lucky Cat": "X0.25 Mult for good each time a scoring Lucky card hits",
    "Vampire": "X0.1 Mult for good per scoring enhanced card, whose enhancement it takes",
    "Midas Mask": "scoring face cards become Gold ($3 each round one is held as it ends)",
    "To Do List": "$4 when its poker hand is played",
    "Business Card": "$2 for each scoring face card, 1 in 2",
    "Reserved Parking": "$1 for each face card held in hand as a hand is played, 1 in 2",
    "Rough Gem": "$1 for each scoring Diamond",
    "Golden Ticket": "$4 for each scoring Gold card",
    "8 Ball": "a Tarot for each scoring 8, 1 in 4",
    "Superposition": "a Tarot for a Straight with a scoring Ace",
    "Séance": "a Spectral card for a Straight Flush",
    "Green Joker": "-1 Mult for good each discard",
    "Ramen": "X0.01 Mult less for good per card discarded",
    "Castle": "+3 Chips for good per discarded card of its suit",
    "Mail-In Rebate": "$5 per discarded card of its rank",
    "Hit the Road": "X0.5 Mult for the round per Jack discarded",
    "Yorick": "X1 Mult for good every 23 cards discarded",
    "Trading Card": "$3 for a first discard of a single card (which is destroyed)",
    "Faceless Joker": "$5 for discarding 3 or more face cards at once",
    "Burnt Joker": "the first discard of a round levels up its poker hand",
    "DNA": "a first hand of one card adds a copy of it to the deck (once more for each copy of DNA)",
    "Delayed Gratification": "$2 per discard left at the end of a round, if none was used",
    "Purple Seal": "a Tarot for each Purple Seal card discarded",
    "Banner": "+30 Chips per discard left: each discard costs every hand after it",
    "Hologram": "X0.25 Mult for good per playing card added to the deck",
    "Satellite": "$1 every round for each different Planet used this run",
    "Golden Joker": "$4 at the end of each round",
    "Rocket": "$1 at the end of each round, $2 more for each boss beaten",
    "Cloud 9": "$1 at the end of each round per 9 in the deck",
    "To the Moon": "$1 more interest per $5 held",
    "Egg": "+$3 sell value at the end of each round",
    "Red Card": "+3 Mult for good for each booster pack skipped",
    "Campfire": "X0.25 Mult for each card sold, until a boss is beaten",
    "Flash Card": "+2 Mult for good for each reroll",
    "Bull": "+2 Chips per $1 held: money spent takes Chips",
    "Bootstraps": "+2 Mult per $5 held: money spent takes Mult",
    "Acrobat": "X3 Mult on a round's final hand: counted on one of its hands",
    "Dusk": "retriggers the cards of a round's final hand: counted on one of its hands",
    "Loyalty Card": "X4 Mult every 6th hand: counted on one hand in six",
    "Card Sharp": "X3 Mult for a poker hand already played this round: counted on half the hands after the first",
    "Mystic Summit": "+15 Mult with no discards left: counted on half the hands",
}
# Acrobat, Dusk, Loyalty Card, Card Sharp and Mystic Summit are in the build's power (a round's start would see
# them on every hand or none) on the share of hands their rule says, times its strength.
TIMED = ("Acrobat", "Dusk", "Loyalty Card", "Card Sharp", "Mystic Summit")
# Jokers that pay at the end of every round: what they pay is in their worth when the bot buys or keeps one (income).
INCOME = ("Golden Joker", "Rocket", "Cloud 9", "To the Moon", "Satellite", "Egg")
# Rules whose strength starts at 0, not 1. Counting what these jokers pay made the bot worse on 480 seeds (beat ante 8
# 24.2% at strength 0, 23.8% at 0.25, 22.5% at 1): it already overvalues money it then dies holding.
OFF = dict.fromkeys(("Golden Joker", "Rocket", "Cloud 9", "To the Moon", "Egg"), 0.0)


def strength(bot, rule: str) -> float:
    if rule in OFF and getattr(bot, "INCOME_STRENGTH", None) is not None:
        return bot.INCOME_STRENGTH
    return bot.w.mods.get(rule, OFF.get(rule, 1.0))


def last_ante(run) -> int:
    """The ante lasting things are counted to: the run's last boss; with the bot's HORIZON_CAP, ante 8, or 4 antes
    ahead once past ante 4, whichever is later, never past the run's last (a run to 8 plays as before; a longer one the
    same through ante 4). Without the cap a run to 16 counted 16 antes from ante 1, played the long game from the
    start and beat ante 8 in 37.5% of 96 seeds against 51% when the same seeds' runs ended at 8 (29 Oct)."""
    if getattr(getattr(run, "agent", None), "HORIZON_CAP", False):
        return min(run.max_ante, max(8, run.ante + 4))
    return run.max_ante


def rounds_left(run) -> float:
    """The rounds a lasting payment is counted for: half of those left to the last ante counted (last_ante; most runs
    end sooner); with the bot's SURVIVAL_HORIZON, those the run is likely to last (its survival_rounds)."""
    agent = getattr(run, "agent", None)
    if getattr(agent, "SURVIVAL_HORIZON", False):
        return agent.survival_rounds(run)
    return 0.5 * 3 * max(1, last_ante(run) + 1 - run.ante)


def final_round(run) -> bool:
    """Is this the run's last blind, its last ante's boss?"""
    return run.blind is not None and run.blind.kind == 2 and run.ante >= run.max_ante


def shops_left(run) -> int:
    """In a shop: the shops after this one where money can still be spent, one before each blind after the next, up
    to the last ante counted's boss (last_ante: no shop after it counts). After a boss the ante has already moved on."""
    kind = run.blind.kind if run.blind is not None else -1
    following = 3 * (run.ante - 1) + (0 if kind == 2 else kind + 1)
    return max(0, 3 * last_ante(run) - 1 - following)


def gold_money(run) -> float:
    """What one more Gold card pays over the run: $3 at the end of each round it is held (about the share of the
    deck a hand holds)."""
    return 3 * run.hand_size / max(1, len(run.deck)) * rounds_left(run)


def held_triggers(run, c) -> int:
    """How many times a card held as a round ends pays (a Gold card's $3, a Blue Seal's Planet): once, again with a
    Red Seal, and again for each Mime."""
    return 1 + (c.seal == "Red") + sum(j.name == "Mime" for j in run.active_jokers())


def mime_pay(bot, run) -> float:
    """What one more Mime brings outside the hands it scores: each Gold card and Blue Seal held as a round ends pays
    once more (about the share of the deck a hand holds), over the rounds left."""
    golds = sum(c.enhancement == "Gold" for c in run.deck)
    blues = sum(c.seal == "Blue" for c in run.deck)
    return (bot.w.money * 3 * golds + bot.w.keep * blues) * run.hand_size / max(1, len(run.deck)) * rounds_left(run)


class Measure:
    """What a lasting change is worth to the build, measured once per decision: a joker's state set on a copy
    of it, or a hand levelled, and the build's power taken with it."""

    def __init__(self, bot, run):
        self.bot, self.run, self.cache = bot, run, {}
        self.base = bot.power(run)

    def joker(self, joker, attr: str, value) -> float:
        key = (id(joker), attr, value)
        if key not in self.cache:
            run = self.run
            k = next(i for i, j in enumerate(run.jokers) if j is joker)
            twin = copy.copy(joker)            # a new object, so power's cache can't answer for the old state
            setattr(twin, attr, value)
            saved = run.jokers
            run.jokers = saved[:k] + [twin] + saved[k + 1:]
            try:
                self.cache[key] = self.bot.power(run) - self.base
            finally:
                run.jokers = saved
        return self.cache[key]

    def level(self, hand: str) -> float:
        key = ("level", hand)
        if key not in self.cache:
            self.run.hand_levels[hand] += 1
            try:
                self.cache[key] = self.bot.power(self.run) - self.base
            finally:
                self.run.hand_levels[hand] -= 1
        return self.cache[key]

    def played(self, hand: str) -> float:
        """A poker hand played once more this run (Supernova's Mult)."""
        key = ("played", hand)
        if key not in self.cache:
            self.run.hand_plays[hand] += 1
            try:
                self.cache[key] = self.bot.power(self.run, fresh=True) - self.base
            finally:
                self.run.hand_plays[hand] -= 1
        return self.cache[key]

    def card_chips(self, chips: int) -> float:
        """`chips` more for good on one card of the deck: as much on every card, shared out over the deck."""
        key = ("card_chips", chips)
        if key not in self.cache:
            deck = self.run.deck
            for c in deck:
                c.bonus_chips += chips
            try:
                self.cache[key] = (self.bot.power(self.run, fresh=True) - self.base) / max(1, len(deck))
            finally:
                for c in deck:
                    c.bonus_chips -= chips
        return self.cache[key]

    def card_added(self, card) -> float:
        """A copy of this card added to the deck for good (DNA), as the bot weighs a card added (deck_change_worth)."""
        key = ("added", card.uid)
        if key not in self.cache:
            twin = copy.copy(card)
            twin.uid = -1 - len(self.cache)                    # a uid no card in the deck has
            trial = copy.copy(self.run)
            trial.deck = self.run.deck + [twin]
            self.cache[key] = self.bot.deck_change_worth(self.run, trial)
        return self.cache[key]

    def discards(self, delta: int) -> float:
        """`delta` discards more left (Banner's chips, Mystic Summit's Mult): the build's typical hand (the plain
        estimate, the same sample hands either way), as it changes."""
        key = ("discards", delta)
        if key not in self.cache:
            run, base = self.run, self.bot.power(self.run, plain=True)
            run.discards_left += delta
            try:
                self.cache[key] = self.bot.power(run, fresh=True, plain=True) - base
            finally:
                run.discards_left -= delta
        return self.cache[key]

    def money(self, dollars: float) -> float:
        """Dollars paid in a round; nothing in the run's last (the run ends with it: a Gold King's $3 chose Pair over
        Three of a Kind at 3I7DG4FM's last boss, the replay review's m4)."""
        return 0.0 if final_round(self.run) else dollars * self.bot.w.money

    def consumable(self, chance: float = 1.0) -> float:
        """A Tarot or Spectral card made (with this chance), if there is room for it: worth one bought to keep; nothing
        in the run's last round."""
        return chance * self.bot.w.keep if self.run.consumable_room() and not final_round(self.run) else 0.0


def _jokers(run):
    return [j for j in run.active_jokers() if j.name in RULES]


def play_bonus(bot, measure: Measure, played, result) -> float:
    """What playing these cards (a poker hand `result`) is worth beyond its score: the lasting changes it makes."""
    run, total = measure.run, 0.0
    scoring = [played[i] for i in result.scoring]
    live = [c for c in scoring if not c.debuffed]
    faces = sum(c.is_face(run.pareidolia) for c in live)
    for j in _jokers(run):
        n = j.name
        if n == "Space Joker":
            v = 0.25 * measure.level(result.name)
        elif n == "Ride the Bus":
            face = any(not c.debuffed and c.is_face(run.pareidolia) for c in scoring)
            v = measure.joker(j, "value", 0) if face else measure.joker(j, "value", j.value + 1)
        elif n == "Runner":
            v = measure.joker(j, "value", j.value + 15) if "Straight" in result.contains else 0.0
        elif n == "Square Joker":
            v = measure.joker(j, "value", j.value + 4) if len(played) == 4 else 0.0
        elif n == "Spare Trousers":
            v = measure.joker(j, "mult", j.mult + 2) if "Two Pair" in result.contains else 0.0
        elif n == "Obelisk":                     # it grows unless this hand becomes the most played outright (a tie for
            plays, after = run.hand_plays, run.hand_plays[result.name] + 1   # most then resets it too: the second review's
            grows = any(v >= after for h, v in plays.items() if h != result.name)   # m2, an X6 lost at ante 10)
            v = measure.joker(j, "xmult", round(j.xmult + 0.2, 2)) if grows else measure.joker(j, "xmult", 1)
        elif n == "Supernova":
            v = measure.played(result.name)
        elif n == "Wee Joker":
            k = sum(c.rank == 2 and not c.is_stone for c in live)
            v = measure.joker(j, "chips", j.chips + 8 * k) if k else 0.0
        elif n == "Hiker":
            v = len(live) * measure.card_chips(5)
        elif n == "Lucky Cat":
            k = sum(c.enhancement == "Lucky" for c in live)          # hits: Mult 1 in 5 or money 1 in 15
            v = measure.joker(j, "xmult", round(j.xmult + 0.25 * 0.25 * k, 4)) if k else 0.0
        elif n == "Vampire":
            taken = [c for c in live if c.enhancement]
            v = (measure.joker(j, "xmult", round(j.xmult + 0.1 * len(taken), 2))
                 - sum(measure.money(gold_money(run)) if c.enhancement == "Gold" else bot.w.card for c in taken)) if taken else 0.0
        elif n == "Midas Mask":
            turned = [c for c in live if c.is_face(run.pareidolia) and c.enhancement != "Gold"]
            v = sum(measure.money(gold_money(run)) - (bot.w.card if c.enhancement else 0.0) for c in turned)
        elif n == "To Do List":
            v = measure.money(4) if result.name == j.target else 0.0
        elif n == "Business Card":
            v = measure.money(0.5 * 2 * faces)
        elif n == "Reserved Parking":
            held = [c for c in run.hand if not any(c is p for p in played)]
            v = measure.money(0.5 * sum(not c.debuffed and c.is_face(run.pareidolia) for c in held))
        elif n == "Rough Gem":
            v = measure.money(sum(c.has_suit("Diamonds", run.smeared) for c in live))
        elif n == "Golden Ticket":
            v = measure.money(4 * sum(c.enhancement == "Gold" for c in live))
        elif n == "8 Ball":
            k = sum(c.rank == 8 and not c.is_stone for c in scoring)
            v = measure.consumable(1 - 0.75 ** k) if k else 0.0
        elif n == "Superposition":
            ace = any(c.rank == 14 and not c.is_stone for c in scoring)
            v = measure.consumable() if ace and "Straight" in result.contains else 0.0
        elif n == "Séance":
            v = measure.consumable() if "Straight Flush" in result.contains else 0.0
        elif n == "DNA":                                           # (copies counted as the order for it stands)
            v = (measure.card_added(played[0]) * bot._copy_plan(run, [j])[1].get(id(j), 1)
                 if run.round_hands_played == 0 and len(played) == 1 else 0.0)
        else:
            continue
        total += strength(bot, n) * v
    if getattr(bot, "LUCKY_MONEY", False):          # a Lucky card's $20 at 1 in 15 each time it scores (retriggers too):
        k = lucky_triggers(run, played, result)      # among plays that win anyway, the one that rolls it most
        if k:
            total += measure.money(k * lucky_each(run))
    return (total - held_forfeit(measure, played) - boss_toll(bot, run, result, played)
            - plan_hold_cost(bot, run, played) - purple_forfeit(bot, run, played))


def purple_forfeit(bot, run, played) -> float:
    """A Purple Seal card played loses the Tarot a discard of it would make, while the round has a discard and a free
    consumable slot (CCU44VLE, the user, 30 Oct: a Purple Seal 4 played as a Pair's kicker)."""
    if not (getattr(bot, "PURPLE_ROOM", True) and run.in_round and run.discards_left > 0 and run.consumable_room()):
        return 0.0
    n = sum(c.seal == "Purple" and not c.debuffed for c in played)
    return strength(bot, "Purple Seal") * n * bot.w.keep if n else 0.0


def plan_hold_cost(bot, run, played) -> float:
    """Playing a card the build plan holds (a Steel card, a King with Baron): PLAN_HOLD for each hand left after this
    one, its held effect gone from them (spec 4.5)."""
    holds = bot._holds(run) if getattr(bot, "PLAN", False) else None
    if holds is None:
        return 0.0
    return bot.PLAN_HOLD * max(0, run.hands_left - 1) * sum(1 for c in played if not c.face_down and holds(c))


TOLL_BOSSES = ("The Ox", "The Tooth")


def boss_toll(bot, run, result, played) -> float:
    """What the boss takes for this play, priced as spending it (the bot's price: interest, Bull and Bootstraps):
    The Ox all the money on its hand, The Tooth $1 a card."""
    boss = run.active_boss
    if boss is None or boss.name not in TOLL_BOSSES:
        return 0.0
    lost = run.money - boss.money_when_scored(run, result, played)
    return bot.price(run, lost) if lost > 0 else 0.0


def held_forfeit(measure: Measure, played) -> float:
    """What the played cards would have paid for staying in hand to the round's end: a Gold card's $3, a Blue Seal's
    Planet (twice with a Red Seal; with the bot's MIME_HELD, again for each Mime). The bot never discards them, so
    playing one is the only way to lose that."""
    total = 0.0
    mime = getattr(measure.bot, "MIME_HELD", False)
    for c in played:
        if c.debuffed:
            continue
        times = held_triggers(measure.run, c) if mime else 1 + (c.seal == "Red")
        if c.enhancement == "Gold":
            total += measure.money(3 * times)
        if c.seal == "Blue":
            total += times * measure.consumable()
    return total


COPIED_ON_DISCARD = ("Burnt Joker", "Mail-In Rebate", "Faceless Joker")   # a copy repeats their discard effect
# (tested in the engine: a Blueprint on Trading Card, or on a joker that grows on discards, adds nothing)


def discard_fires(run, order=None) -> dict:
    """id(joker) -> how many times its effects go off with the jokers in `order` (indices; the present order by
    default): itself and each copy (bots.copy_fires)."""
    from .bots import copy_fires
    jokers = run.jokers if order is None else [run.jokers[i] for i in order]
    return {id(j): n for j, n in zip(jokers, copy_fires(jokers))}


def discard_bonus(bot, measure: Measure, cards, fires: dict | None = None, won: bool = False) -> float:
    """What discarding these cards is worth beyond the hand it leads to: what the jokers (and seals) make of it.
    `fires`: how many times each joker's effects go off (discard_fires; the present order's by default), for the
    effects a copy repeats (COPIED_ON_DISCARD). `won`: the round is won with or without the discard, so what only
    this round's score loses (Banner's 30 chips a discard left) costs nothing."""
    run, total = measure.run, 0.0
    fires = discard_fires(run) if fires is None else fires
    first = run.discards_used == 0
    live = [c for c in cards if not c.debuffed and not c.is_stone]
    for j in _jokers(run):
        n = j.name
        if n == "Green Joker":
            v = measure.joker(j, "value", max(0, j.value - 1))
        elif n == "Ramen":
            v = measure.joker(j, "xmult", round(j.xmult - 0.01 * len(cards), 2))
        elif n == "Castle":
            k = sum(c.suit == j.suit for c in live)
            v = measure.joker(j, "chips", j.chips + 3 * k) if k else 0.0
        elif n == "Mail-In Rebate":
            v = measure.money(5 * sum(c.rank == j.rank for c in live))
        elif n == "Hit the Road":
            k = sum(c.rank == 11 for c in live)
            v = 0.5 * measure.joker(j, "xmult", j.xmult + 0.5 * k) if k else 0.0      # for this round only
        elif n == "Yorick":
            gain = (j.discarded + len(cards)) // 23 - j.discarded // 23
            v = measure.joker(j, "xmult", j.xmult + gain) if gain else 0.0
        elif n == "Trading Card":
            v = measure.money(3) if first and len(cards) == 1 else 0.0
        elif n == "Faceless Joker":
            v = measure.money(5) if sum(c.is_face(run.pareidolia) for c in live) >= 3 else 0.0
        elif n == "Burnt Joker":
            v = measure.level(evaluate(cards, run.rules).name) if first else 0.0
        elif n == "Delayed Gratification":
            v = -measure.money(2 * run.discards_left) if first else 0.0
        elif n == "Banner":                                     # 30 chips a discard left, on every hand to come
            v = measure.discards(-1) if run.in_round and getattr(bot, "ROUND_DISCARDS", True) and not won else 0.0
        else:
            continue
        total += strength(bot, n) * v * (fires.get(id(j), 1) if n in COPIED_ON_DISCARD else 1)
    purple = sum(c.seal == "Purple" and not c.debuffed for c in cards)
    if purple and run.consumable_room():
        total += strength(bot, "Purple Seal") * purple * bot.w.keep
    return total


def discard_options(run) -> list[set[int]]:
    """Cards worth throwing away only for what a joker pays for them: Mail-In Rebate's rank, Jacks for Hit the
    Road, Castle's suit, face cards for Faceless Joker, one low card first for Trading Card."""
    hand, out = run.hand, []
    for j in _jokers(run):
        if j.name == "Mail-In Rebate":
            out.append({i for i, c in enumerate(hand) if c.rank == j.rank and not c.is_stone})
        elif j.name == "Hit the Road":
            out.append({i for i, c in enumerate(hand) if c.rank == 11 and not c.is_stone})
        elif j.name == "Castle":
            out.append({i for i, c in enumerate(hand) if c.suit == j.suit and not c.is_stone})
        elif j.name == "Faceless Joker":
            faces = {i for i, c in enumerate(hand) if c.is_face(run.pareidolia)}
            if len(faces) >= 3:
                out.append(faces)
        elif j.name == "Trading Card" and run.discards_used == 0 and hand:
            out.append({min(range(len(hand)), key=lambda i: hand[i].rank)})
        elif j.name == "Burnt Joker" and run.discards_used == 0 and hand:
            out.extend(_hand_type_sets(run))       # the cards of a poker hand, thrown to level it up
    return [s for s in out if s]


def _hand_type_sets(run) -> list[set[int]]:
    """For each poker hand the cards in hand make, the lowest cards that make it exactly (a discard of them levels it
    with Burnt Joker): the lowest-scoring play of each poker hand, as best_play's ranking finds them."""
    from .bots import ranked_plays
    lowest: dict[str, list[int]] = {}
    for _, idx, r in ranked_plays(run, top=40):
        lowest[r.name] = idx                          # ranked best first: the last of each is its lowest
    return [set(idx) for idx in lowest.values()]


def planet_bonus(bot, run, planet) -> float:
    """Satellite: a Planet not used yet this run pays $1 at the end of every round left (per Satellite); that
    money over half the rounds left to ante 8's boss (most runs end sooner)."""
    n = sum(j.name == "Satellite" for j in run.active_jokers())
    if not n or getattr(planet, "kind", None) != "Planet" or planet.name in run.planets_used:
        return 0.0
    return strength(bot, "Satellite") * n * rounds_left(run) * bot.w.money


PLANET_TYPES = 9                 # Planets a shop or pack offers (Planet X, Ceres and Eris only once their hand is played)
HAND_PAYS = ("Reserved Parking", "Business Card", "Rough Gem", "Golden Ticket", "Hanging Chad")
PLAYED_CARDS = 4                 # cards a typical hand plays (the rest are held)
SCORED_CARDS = 3                 # and scores


def lucky_each(run) -> float:
    """What a Lucky card is expected to pay each time it scores: $20 at 1 in 15 (each Oops! All 6s doubling it)."""
    return 20 * min(1.0, getattr(run, "probability_scale", 1) / 15)


def lucky_triggers(run, played, result) -> int:
    """How many times a play's Lucky cards score: once each and once more for each retrigger (a Red Seal, Hanging
    Chad on the first scoring card, Sock and Buskin, Hack, Seltzer, Dusk...). A debuffed one scores nothing."""
    from .bots import NO_LUCK
    from .scoring import HandContext
    ctx = HandContext(run, played, [], result, NO_LUCK, estimating=True)
    jokers = run.active_jokers()
    return sum(1 + (c.seal == "Red") + sum(j.retriggers(ctx, c, position) for j in jokers)
               for position, c in enumerate(played[i] for i in result.scoring)
               if c.enhancement == "Lucky" and not c.debuffed)


OWN_HANDS = 6                    # hands played before the run's own record replaces the deck's share (PAY_FROM_PLAY)


def hand_pay(run, name: str, own: bool = False) -> float:
    """What a joker that pays as hands are played brings in a typical round: from the deck's share of the cards it pays
    on, held (Reserved Parking: $1 a face card, 1 in 2) or scored (Business Card $2 a face card, 1 in 2; Rough Gem $1 a
    Diamond; Golden Ticket $4 a Gold card), times the hands this run's rounds have taken (2 before any). With `own`,
    after OWN_HANDS hands, from what this run's hands have scored and held instead (`run.pay_seen`): its play favours
    some cards (face cards score more chips), and the deck's share counted Business Card at about half what it paid
    (calibration, 28 Oct: Business Card 1.93x, Reserved Parking 1.65x, Golden Ticket 1.61x, Rough Gem 1.50x)."""
    deck = [c for c in run.deck if not c.is_stone]
    if not deck:
        return 0.0
    lucky = 2 * lucky_each(run)          # Hanging Chad: the first scoring card twice more, a Lucky one's $20 rolled again
    if own and run.hands_played >= OWN_HANDS:
        seen = run.pay_seen
        per_hand = {"Reserved Parking": 0.5 * seen["held faces"], "Business Card": 0.5 * 2 * seen["faces"],
                    "Rough Gem": seen["diamonds"], "Golden Ticket": 4 * seen["gold"],
                    "Hanging Chad": lucky * seen["lucky first"]}[name] / run.hands_played
    else:
        share = lambda f: sum(map(f, deck)) / len(deck)                         # noqa: E731
        faces = share(lambda c: c.is_face(run.pareidolia))
        per_hand = {"Reserved Parking": 0.5 * max(0, run.hand_size - PLAYED_CARDS) * faces,
                    "Business Card": 0.5 * 2 * SCORED_CARDS * faces,
                    "Rough Gem": SCORED_CARDS * share(lambda c: c.has_suit("Diamonds", run.smeared)),
                    "Golden Ticket": 4 * SCORED_CARDS * share(lambda c: c.enhancement == "Gold"),
                    "Hanging Chad": lucky * share(lambda c: c.enhancement == "Lucky")}[name]
    hands = run.hands_played / run.rounds_played if run.rounds_played else 2.0
    return per_hand * max(1.0, hands)


DISCARD_PAYS = ("Mail-In Rebate", "Trading Card", "Faceless Joker")
DISCARD_CARDS = 3                # cards a typical discard throws (and draws again)


def discard_pay(run, name: str) -> float:
    """What a joker that pays for discards brings in a typical round, half of what the round's discards could take
    (the rest build the hand played): Mail-In Rebate $5 a card of its rank (one of the ranks the deck has), from the
    cards a round shows (the hand and DISCARD_CARDS more a discard); Trading Card $3 for a first discard of one card;
    Faceless Joker $5 for three face cards thrown at once (the chance a hand holds three). Nothing without discards."""
    deck = [c for c in run.deck if not c.is_stone]
    discards = max(0, run.base_discards + sum(j.discards_bonus for j in run.active_jokers()))
    if not deck or not discards:
        return 0.0
    if name == "Mail-In Rebate":
        seen = run.hand_size + DISCARD_CARDS * discards
        return 0.5 * 5 * min(seen / len({c.rank for c in deck}), 5 * discards)
    if name == "Trading Card":
        return 0.5 * 3
    p, n = sum(c.is_face(run.pareidolia) for c in deck) / len(deck), run.hand_size
    three = 1 - sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(3))
    return 0.5 * 5 * three


def income(bot, run, joker) -> float:
    """What a joker pays at the end of every round, over the rounds a lasting payment is counted for, at the bot's
    money weight: Golden Joker's $4, Rocket's payout (+$2 a boss: one round in three), Cloud 9's $1 per 9 in the deck,
    To the Moon's interest, Satellite's $1 per Planet used, Egg's $3 of sell value. With the bot's HAND_INCOME, also
    what one paying as hands are played brings a round (hand_pay); with its DISCARD_INCOME, one paying for discards
    (discard_pay); with its MIME_HELD, Mime's second payment from held Gold cards and Blue Seals (mime_pay)."""
    n = joker.name
    if n == "Mime" and getattr(bot, "MIME_HELD", False):
        return strength(bot, n) * mime_pay(bot, run)
    rounds = rounds_left(run)
    return strength(bot, n) * round_dollars(bot, run, joker, rounds) * rounds * bot.w.money


def round_dollars(bot, run, joker, rounds: float = 0.0) -> float:
    """The dollars a joker pays a round, as it ends or as its hands are played (income's, before its rule's strength):
    over `rounds` to come, Rocket's mean payout and Satellite's Planet types to come (PAY_FROM_PLAY); 0 for the rest."""
    n = joker.name
    own = getattr(bot, "PAY_FROM_PLAY", False)
    if n in HAND_PAYS and getattr(bot, "HAND_INCOME", False):
        return hand_pay(run, n, own)
    if n in DISCARD_PAYS and getattr(bot, "DISCARD_INCOME", False):
        return discard_pay(run, n)
    if n not in INCOME:
        return 0.0
    if n == "Golden Joker":
        return 4
    if n == "Rocket":
        return joker.dollars + rounds / 3              # its mean payout over those rounds
    if n == "Cloud 9":
        return sum(c.rank == 9 and not c.is_stone for c in run.deck)
    if n == "To the Moon":
        return min(run.interest_cap, max(0, run.money) // 5) if run.interest_enabled else 0
    if n == "Satellite":
        each = len(run.planets_used)
        if own and run.rounds_played:                  # and the new Planet types to come, at this run's rate so far
            each = min(PLANET_TYPES, each + len(run.planets_used) / run.rounds_played * rounds / 2)
        return each
    return 3                                           # Egg


def card_bonus(bot, run, n: int = 1) -> float:
    """Hologram: each playing card added to the deck gives it X0.25 Mult for good."""
    holos = [j for j in run.active_jokers() if j.name == "Hologram"]
    if not holos:
        return 0.0
    measure = Measure(bot, run)
    return strength(bot, "Hologram") * sum(measure.joker(j, "xmult", j.xmult + 0.25 * n) for j in holos)


def _growth(bot, run, name: str, attr: str, step) -> float:
    """What each joker called `name` gains for good from `step` more `attr`, times its rule's strength."""
    owned = [j for j in run.active_jokers() if j.name == name]
    if not owned:
        return 0.0
    measure = Measure(bot, run)
    return strength(bot, name) * sum(measure.joker(j, attr, getattr(j, attr) + step) for j in owned)


def skip_bonus(bot, run) -> float:
    """Red Card: skipping a booster pack gives it +3 Mult for good."""
    return _growth(bot, run, "Red Card", "mult", 3)


def sell_bonus(bot, run) -> float:
    """Campfire: each card sold gives it X0.25 Mult (until a boss is beaten)."""
    return _growth(bot, run, "Campfire", "xmult", 0.25)


def reroll_bonus(bot, run) -> float:
    """Flash Card: each reroll gives it +2 Mult for good."""
    return _growth(bot, run, "Flash Card", "mult", 2)


def spend_cost(bot, run, cost: int) -> float:
    """Bull (+2 Chips per $1 held) and Bootstraps (+2 Mult per $5): what spending `cost` takes from the build."""
    names = {j.name for j in run.active_jokers()} & {"Bull", "Bootstraps"}
    if not names or cost <= 0:
        return 0.0
    base = bot.power(run)
    run.money -= cost
    try:
        after = bot.power(run)
    finally:
        run.money += cost
    return sum(strength(bot, n) for n in names) / len(names) * (base - after)


def repeat_chance(seen) -> float:
    """How often a hand can make the build's main poker hand again (the one most of power's sample hands play
    best): the share of sample hands with a play of it. `seen`: (best poker hand, those it can make, ...) per hand."""
    if not seen:
        return 0.5
    main = Counter(s[0] for s in seen).most_common(1)[0][0]
    return sum(main in s[1] for s in seen) / len(seen)


def timed(bot, run, hands: int, seen=()) -> list:
    """The jokers that act on some hands only, for a build's power: (the share of hands counted, times the rule's
    strength; whether the run is set for such a hand now: True, False or None for some hands; a function that sets
    the run for one, or for another hand, and returns how to undo it). `hands`: a round's hands; `seen`: the sample
    hands' poker hands (repeat_chance)."""
    names = {j.name for j in run.active_jokers()}
    out = []

    def setting(attr, on, off):
        def force(is_on):
            saved = getattr(run, attr)
            setattr(run, attr, on if is_on else off)
            return lambda: setattr(run, attr, saved)
        return force

    final = [strength(bot, n) for n in ("Acrobat", "Dusk") if n in names]
    if final:                                       # (a bot's estimate sees the final hand as the one with a hand left)
        out.append((sum(final) / len(final) / max(1, hands), run.hands_left == 1, setting("hands_left", 1, 2)))
    loyal = next((j for j in run.active_jokers() if j.name == "Loyalty Card"), None)
    if loyal is not None:
        since = loyal.since or 0
        n = run.hands_played + 1 - since
        out.append((strength(bot, "Loyalty Card") / 6, n > 0 and n % 6 == 0, setting("hands_played", since + 5, since)))
    if "Card Sharp" in names:
        # X3 on each hand after the first that repeats the main poker hand: over a round that takes every hand, the
        # round's total 1 + (hands - 1)(1 + 2p) times the first hand's, against hands times; counted as that ratio,
        # so the rounds that are hard to win are where it is weighed. (It was 0.5 (hands - 1) / hands of log 3:
        # a third of the hands at 3 a round, below Steel Joker's X1.8 with four Steel cards on a Pair build.)
        played = run.round_hand_types
        p = repeat_chance(seen)
        gain = math.log((1 + (hands - 1) * (1 + 2 * p)) / max(1, hands)) / math.log(3)
        out.append((strength(bot, "Card Sharp") * gain, False if not played else None,
                    setting("round_hand_types", Counter(dict.fromkeys(run.hand_levels, 1)), Counter())))
    if "Mystic Summit" in names:
        out.append((strength(bot, "Mystic Summit") * 0.5, run.discards_left == 0,
                    setting("discards_left", 0, max(1, run.discards_left))))
    return out
