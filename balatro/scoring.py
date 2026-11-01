"""Scoring a played hand: chips x mult, built up in the game's order.

1. Jokers' "before" (on played) effects run (Space Joker, Midas Mask, Vampire, ...).
2. Then the hand's level sets base chips and mult, so a Space Joker level-up counts for this hand;
   a boss blind may change them (The Flint halves both, rounding up).
3. Each scoring card, left to right, as many times as it triggers (1 + Red Seal + retrigger jokers):
   rank chips and extra chips, its enhancement, its edition, its seal, then every joker's
   on-scored-card effect, left to right.
4. Each card held in hand, left to right, as many times as it triggers (Red Seal, Mime): Steel x1.5,
   then every joker's on-held-card effect.
5. Each joker, left to right: Foil/Holographic edition, its own effect, effects other jokers give
   when it triggers (Baseball Card), then Polychrome.
6. Observatory: x1.5 per held Planet card of the played hand. Plasma Deck: chips and mult averaged.
7. Score = floor(chips x mult).
Every change is logged as (source, effect, amount) so a coach can explain a score.

The order follows the community-documented evaluation order; data/scoring.md records the sources and
any points still in doubt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .cards import Card, rank_chips
from .hands import HandResult

# name: (base chips, base mult, chips per level, mult per level). Source: data/hands.json (balatrowiki.org).
HAND_BASE = {
    "High Card": (5, 1, 10, 1), "Pair": (10, 2, 15, 1), "Two Pair": (20, 2, 20, 1),
    "Three of a Kind": (30, 3, 20, 2), "Straight": (30, 4, 30, 3), "Flush": (35, 4, 15, 2),
    "Full House": (40, 4, 25, 2), "Four of a Kind": (60, 7, 30, 3), "Straight Flush": (100, 8, 40, 4),
    "Five of a Kind": (120, 12, 35, 3), "Flush House": (140, 14, 40, 4), "Flush Five": (160, 16, 50, 3),
}


def hand_base(name: str, level: int) -> tuple[float, float]:
    chips, mult, dc, dm = HAND_BASE[name]
    return chips + dc * (level - 1), mult + dm * (level - 1)


@dataclass
class Score:
    chips: float
    mult: float
    money: int = 0  # dollars earned while scoring (Gold Seal, Lucky cards, Business Card, ...)
    log: list[tuple[str, str, float]] = field(default_factory=list)
    trail: list[tuple[float, float]] = field(default_factory=list)  # (chips, mult) after each log entry
    who: list[int | None] = field(default_factory=list)  # each entry's acting joker, its place in run.jokers (or None):
    actor: int | None = None                             # a copier's place for what it copies, each of two twins its own

    def note(self, source: str, kind: str, amount: float) -> None:
        self.log.append((source, kind, amount))
        self.trail.append((self.chips, self.mult))
        self.who.append(self.actor)

    def add_chips(self, source: str, amount: float) -> None:
        if amount:
            self.chips += amount
            self.note(source, "+chips", amount)

    def add_mult(self, source: str, amount: float) -> None:
        if amount:
            self.mult += amount
            self.note(source, "+mult", amount)

    def x_mult(self, source: str, factor: float) -> None:
        if factor != 1:
            self.mult *= factor
            self.note(source, "xmult", factor)

    def add_money(self, source: str, amount: int) -> None:
        if amount:
            self.money += amount
            self.note(source, "$", amount)

    @property
    def total(self) -> int:
        return math.floor(self.chips * self.mult)


@dataclass
class HandContext:
    """What scoring effects can see about the hand being played. `run` is the run state (jokers,
    money, deck, hand levels, round counters); `rng` rolls the 1-in-N chances.

    `estimating` is set when a bot scores a hand it might play, and `copying` while Blueprint or
    Brainstorm runs another joker's effect. Effects change lasting state (scaling, money, cards) only
    when `live` is true. `expecting` (an estimate only): a chance that scores counts as its expectation
    (`odds`) instead of being rolled."""
    run: object
    played: list[Card]
    held: list[Card]
    result: HandResult
    rng: object
    destroyed: list[Card] = field(default_factory=list)  # cards to remove after scoring (Glass breaks)
    estimating: bool = False
    copying: bool = False
    copy_depth: int = 0
    expecting: bool = False

    @property
    def live(self) -> bool:
        return not (self.estimating or self.copying)

    @property
    def scoring_cards(self) -> list[Card]:
        return [self.played[i] for i in self.result.scoring]

    def chance(self, n: int, key: str | None = None) -> bool:
        """A 1-in-n roll; each Oops! All 6s doubles the odds. `key`: the game's stream for this roll, used
        when the run follows a game seed (never while estimating, so estimates don't advance it)."""
        seedrng = getattr(self.run, "seedrng", None)
        if key and seedrng and not self.estimating:
            return seedrng.roll(key) * n < getattr(self.run, "probability_scale", 1)
        return self.rng.random() * n < getattr(self.run, "probability_scale", 1)

    def odds(self, n: int) -> float:
        """The chance of a 1-in-n roll coming off (Oops! All 6s doubling it)."""
        return min(1.0, getattr(self.run, "probability_scale", 1) / n)


def score_card(ctx: HandContext, card: Card, score: Score) -> None:
    """One trigger of a scoring card: chips, enhancement, edition, seal."""
    name = card.label()
    if card.is_stone:
        score.add_chips(name, 50)
    else:
        score.add_chips(name, rank_chips(card.rank) + card.bonus_chips)
    if card.enhancement == "Bonus":
        score.add_chips(f"{name} (Bonus)", 30)
    elif card.enhancement == "Mult":
        score.add_mult(f"{name} (Mult)", 4)
    elif card.enhancement == "Glass":
        score.x_mult(f"{name} (Glass)", 2)
    elif card.enhancement == "Lucky":
        if ctx.expecting:                                   # +20 Mult 1 in 5: +4 on average (its $20 isn't score)
            score.add_mult(f"{name} (Lucky)", 20 * ctx.odds(5))
        elif ctx.chance(5, "lucky_mult"):
            score.add_mult(f"{name} (Lucky)", 20)
            if not ctx.estimating:
                ctx.run.on_lucky_trigger()
        if ctx.chance(15, "lucky_money"):
            score.add_money(f"{name} (Lucky)", 20)
            if not ctx.estimating:
                ctx.run.on_lucky_trigger()
    if card.edition == "Foil":
        score.add_chips(f"{name} (Foil)", 50)
    elif card.edition == "Holographic":
        score.add_mult(f"{name} (Holographic)", 10)
    elif card.edition == "Polychrome":
        score.x_mult(f"{name} (Polychrome)", 1.5)
    if card.seal == "Gold":
        score.add_money(f"{name} (Gold Seal)", 3)


def score_hand(ctx: HandContext, level: int | None = None, boss=None) -> Score:
    """`level` defaults to the run's level for the hand, read after the "before" effects (Space Joker)."""
    run = ctx.run
    jokers = run.active_jokers()
    at = {id(j): k for k, j in enumerate(run.jokers)}
    acts = [at.get(id(j)) for j in jokers]
    for j in jokers:
        j.before(ctx)
    if level is None:
        level = run.hand_levels[ctx.result.name]
    chips, mult = hand_base(ctx.result.name, level)
    score = Score(chips, mult)
    score.note(ctx.result.name, f"level {level}", chips * mult)
    if boss is not None:
        boss.modify_base(ctx, score)

    for position, index in enumerate(ctx.result.scoring):
        card = ctx.played[index]
        if card.debuffed:
            continue
        triggers = 1 + (card.seal == "Red") + sum(j.retriggers(ctx, card, position) for j in jokers)
        for _ in range(triggers):
            score.actor = None
            score_card(ctx, card, score)
            for j, a in zip(jokers, acts):
                score.actor = a
                j.on_scored(ctx, card, score)
        score.actor = None
        if card.enhancement == "Glass" and ctx.chance(4, "glass"):
            ctx.destroyed.append(card)

    for card in ctx.held:
        if card.debuffed:
            continue
        triggers = 1 + (card.seal == "Red") + sum(j.held_retriggers(ctx, card) for j in jokers)
        for _ in range(triggers):
            score.actor = None
            if card.enhancement == "Steel":
                score.x_mult(f"{card.label()} (Steel, held)", 1.5)
            for j, a in zip(jokers, acts):
                score.actor = a
                j.on_held(ctx, card, score)
        score.actor = None

    for j, a in zip(jokers, acts):
        score.actor = a
        if j.edition == "Foil":
            score.add_chips(f"{j.name} (Foil)", 50)
        elif j.edition == "Holographic":
            score.add_mult(f"{j.name} (Holographic)", 10)
        j.independent(ctx, score)
        for other, b in zip(jokers, acts):
            score.actor = b
            other.on_joker(ctx, j, score)
        score.actor = a
        if j.edition == "Polychrome":
            score.x_mult(f"{j.name} (Polychrome)", 1.5)
    score.actor = None

    if getattr(run, "has_voucher", lambda name: False)("Observatory"):
        for c in run.consumables:
            if getattr(c, "hand", None) == ctx.result.name:
                score.x_mult(f"{c.name} (Observatory)", 1.5)
    if getattr(run, "plasma", False):  # Plasma Deck: chips and mult both become their average
        half = math.floor((score.chips + score.mult) / 2)
        score.chips = score.mult = half
        score.note("Plasma Deck", "balance", half)
    return score
