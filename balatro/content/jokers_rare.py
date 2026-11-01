"""The Rare jokers not in balatro/jokers.py, and the five Legendaries. Rules: data/jokers.json,
data/jokers_OPEN_QUESTIONS.md, and balatrowiki.org where those leave room.

Calls made where the data or the wiki is unclear:
- DNA: the copy goes straight into the hand, so it counts as a held card for the hand that made it (the
  game puts it in the hand before the held-card pass). Each Blueprint/Brainstorm copy adds another card.
- Ancient Joker: the suit is rolled when the joker joins (or taken from an Ancient Joker already owned).
  At each end of round, all owned Ancient Jokers move together to one of the other 3 suits.
- Obelisk: after this play is counted, it resets only if this hand type has strictly more plays than every
  other type. Ties gain X0.2, and the new value applies to this hand.
- Campfire resets after a Boss Blind's cash out. The data says end of the boss round, but nothing can be
  sold in between, so the result is the same.
- Invisible Joker counts rounds won while it is active. Sold with 2 or more rounds and not debuffed, it
  deep-copies a random other joker if a slot is free once it is gone. The copy keeps scaling, edition and
  stickers; Negative is removed; a copied Invisible Joker restarts at 0/2. The wiki's slot overflow from
  a Negative Invisible Joker is not modelled.
- Canio and Hit the Road ignore debuffed cards; Yorick counts every discarded card. Face cards follow
  Card.is_face, so a Stone card is never a face, even with Pareidolia.
- Chicot disables the boss once. The wiki says several Chicots reverse some bosses several times (The
  Wall, The Manacle); that is not modelled. Obtained during a boss round, Chicot disables the boss at once.
- Perkeo deep-copies a uniformly random held consumable, so extra sell value (Gift Card) is kept. A
  Blueprint copy acts after it and may pick the first copy.
- Legendaries cost $0 in the data because shops never sell them. Their price here is the internal $20,
  so they sell for $10.
"""
from __future__ import annotations

import copy

from ..cards import SUITS
from ..hands import evaluate
from ..jokers import JOKER_DATA, Joker, joker


def legendary(cls):
    """Register a Legendary; its price is the data's internal cost, so it sells for $10."""
    cls = joker(cls)
    cls.cost = JOKER_DATA[cls.name]["values"]["internal_cost"]
    return cls


class XMultJoker(Joker):
    """Gives its current X Mult, which starts at X1."""

    def __init__(self, edition=None):
        super().__init__(edition)
        self.xmult = 1

    def independent(self, ctx, score):
        score.x_mult(self.name, self.xmult)


class HandTypeJoker(Joker):
    """X Mult when the played cards contain a poker hand, scoring or not."""
    hand, xmult = "?", 1

    def independent(self, ctx, score):
        if self.hand in ctx.result.contains:
            score.x_mult(self.name, self.xmult)


# ---- Rare ------------------------------------------------------------------------------------------

@joker
class DNA(Joker):
    name = "DNA"

    def before(self, ctx):
        run = ctx.run
        if len(ctx.played) == 1 and not ctx.estimating and run.round_hands_played == 1:
            twin = run.copy_card(ctx.played[0])
            run.add_cards([twin], to_hand=True)
            ctx.held.append(twin)


@joker
class Vagabond(Joker):
    name = "Vagabond"

    def independent(self, ctx, score):
        if ctx.run.money <= 4 and not ctx.estimating:  # this hand's payouts arrive after scoring
            ctx.run.create_consumable("Tarot", source="vag")


@joker
class Baron(Joker):
    name = "Baron"

    def on_held(self, ctx, card, score):
        if card.rank == 13 and not card.is_stone:
            score.x_mult(self.name, 1.5)


@joker
class Obelisk(XMultJoker):
    name = "Obelisk"

    def before(self, ctx):
        if ctx.live:
            self.xmult = self._next(ctx)

    def _next(self, ctx):
        """The X Mult this hand scores with: +X0.2 unless it is the most played hand, which resets it. A live hand is
        counted in hand_plays before `before`; an estimate's isn't yet."""
        plays, hand = ctx.run.hand_plays, ctx.result.name
        n = plays[hand] + ctx.estimating
        return self.xmult + 0.2 if any(v >= n for h, v in plays.items() if h != hand) else 1

    def independent(self, ctx, score):
        # an estimate scores the hand as `before` would leave it (a live hand already has; a copy reads it after)
        score.x_mult(self.name, self._next(ctx) if ctx.estimating else self.xmult)


@joker
class AncientJoker(Joker):
    name = "Ancient Joker"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.suit = None

    def on_added(self, run):
        owned = [j.suit for j in run.jokers if isinstance(j, AncientJoker) and j is not self and j.suit]
        self.suit = owned[0] if owned else run.rng["misc"].choice(SUITS)

    def on_scored(self, ctx, card, score):
        if self.suit and card.has_suit(self.suit, ctx.run.smeared):
            score.x_mult(self.name, 1.5)

    def end_of_round(self, run, blind):
        """The first active Ancient Joker picks the next suit for all of them."""
        if next((j for j in run.active_jokers() if isinstance(j, AncientJoker)), self) is self:
            suit = run.rng["misc"].choice([s for s in SUITS if s != self.suit])
            for j in run.jokers:
                if isinstance(j, AncientJoker):
                    j.suit = suit
        return 0


@joker
class Campfire(XMultJoker):
    name = "Campfire"

    def on_sell(self, run, sold):
        if not run.copying:
            self.xmult += 0.25

    def on_boss_defeated(self, run):
        if not run.copying:
            self.xmult = 1


@joker
class WeeJoker(Joker):
    name = "Wee Joker"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.chips = 0

    def on_scored(self, ctx, card, score):
        if ctx.live and card.rank == 2 and not card.is_stone:
            self.chips += 8

    def independent(self, ctx, score):
        score.add_chips(self.name, self.chips)


@joker
class HitTheRoad(XMultJoker):
    name = "Hit the Road"

    def on_discard(self, run, cards, first):
        if not run.copying:
            self.xmult += 0.5 * sum(c.rank == 11 and not (c.is_stone or c.debuffed) for c in cards)

    def end_of_round(self, run, blind):
        self.xmult = 1
        return 0


@joker
class TheTrio(HandTypeJoker):
    name, hand, xmult = "The Trio", "Three of a Kind", 3


@joker
class TheFamily(HandTypeJoker):
    name, hand, xmult = "The Family", "Four of a Kind", 4


@joker
class TheOrder(HandTypeJoker):
    name, hand, xmult = "The Order", "Straight", 3


@joker
class TheTribe(HandTypeJoker):
    name, hand, xmult = "The Tribe", "Flush", 2


@joker
class Stuntman(Joker):
    name = "Stuntman"
    hand_size_bonus = -2

    def independent(self, ctx, score):
        score.add_chips(self.name, 250)


@joker
class InvisibleJoker(Joker):
    name = "Invisible Joker"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.rounds = 0

    def end_of_round(self, run, blind):
        self.rounds += 1
        return 0

    def jiggles(self, run):
        return self.rounds >= 2

    def on_sold(self, run):
        if self.rounds < 2 or self.perished or self.disabled or not run.jokers or not run.joker_room():
            return
        twin = copy.deepcopy(run.rng["misc"].choice(run.jokers), {id(run): run})
        if twin.edition == "Negative":
            twin.edition = None
        if isinstance(twin, InvisibleJoker):
            twin.rounds = 0
        run.add_joker(twin)


@joker
class DriversLicense(Joker):
    name = "Driver's License"

    def independent(self, ctx, score):
        if sum(c.enhancement is not None for c in ctx.run.deck) >= 16:
            score.x_mult(self.name, 3)


@joker
class BurntJoker(Joker):
    name = "Burnt Joker"

    def on_discard(self, run, cards, first):
        if first:
            run.level_up(evaluate(cards, run.rules).name)


# ---- Legendary -------------------------------------------------------------------------------------

@legendary
class Canio(XMultJoker):
    name = "Canio"

    def on_cards_destroyed(self, run, cards):
        if not run.copying:
            pareidolia = run.pareidolia
            self.xmult += sum(c.is_face(pareidolia) and not c.debuffed for c in cards)


@legendary
class Triboulet(Joker):
    name = "Triboulet"

    def on_scored(self, ctx, card, score):
        if card.rank in (12, 13) and not card.is_stone:
            score.x_mult(self.name, 2)


@legendary
class Yorick(XMultJoker):
    name = "Yorick"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.discarded = 0  # since it joined; X1 more every 23 cards

    def on_discard(self, run, cards, first):
        if not run.copying:
            self.discarded += len(cards)
            self.xmult = 1 + self.discarded // 23


@legendary
class Chicot(Joker):
    name = "Chicot"

    def on_blind_select(self, run, blind):
        run.disable_boss()

    def on_added(self, run):
        """Obtained during a boss round (The Soul used mid-round): the boss is disabled at once."""
        # TODO(engine): a run flag for "a round is in progress"; until then: an unbeaten blind with hands left.
        if run.active_boss is not None and run.hands_left > 0 and run.round_score < run.blind.chips:
            run.disable_boss()


@legendary
class Perkeo(Joker):
    name = "Perkeo"

    def on_shop_close(self, run, shop):
        if run.consumables:
            twin = copy.deepcopy(run.rng["misc"].choice(run.consumables), {id(run): run})
            twin.edition = "Negative"
            run.consumables.append(twin)
