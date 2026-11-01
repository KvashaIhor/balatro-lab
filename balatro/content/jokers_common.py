"""The Common jokers: 57 of the 61 (Joker, Greedy Joker, Jolly Joker and Hanging Chad are in balatro/jokers.py).
Rules: data/jokers.json and data/jokers_OPEN_QUESTIONS.md; Chaos the Clown, Red Card and To Do List checked on
balatrowiki.org.

Calls where the data left room:
- Rolls outside a hand (Gros Michel, Cavendish, Hallucination, To Do List, Mail-In Rebate) use the "misc"
  stream; Misprint draws from the hand's rng like the 1-in-N rolls.
- Ride the Bus, Runner, Square Joker and Green Joker grow in `before`. A bot's estimate gives the value this
  hand would reach without keeping it; Supernova likewise counts the hand being estimated, which the run's
  counters include only once the hand is really played.
- Cards made during a hand (8 Ball, Superposition) wait for a real hand. Money earned while scoring (Business
  Card, Reserved Parking, Golden Ticket) goes into the Score, like Gold Seals; To Do List pays in `before`.
- Raised Fist: lowest rank held (Ace high, Stone cards skipped), the rightmost on ties; nothing if that card
  is debuffed (the run skips debuffed held cards).
- Faceless Joker and Mail-In Rebate ignore debuffed discards; Superposition counts any scoring Ace.
- Riff-Raff makes min(2, free slots) jokers, counted before the first is made, as the game does.
- To Do List and Mail-In Rebate roll their target when added (High Card / Ace for a joker put straight into
  run.jokers) and again at each round's end; To Do List never rolls its current hand.
- Chaos the Clown bought mid-shop makes a reroll free at once; sold, it takes an unused free reroll away.
  Drunkard changes the current discards at once when added or sold.
"""
from __future__ import annotations

from ..cards import rank_chips
from ..hands import HAND_ORDER
from ..items import data
from ..jokers import Joker, SuitMultJoker, joker

SECRET_HANDS = frozenset(h["name"] for h in data("hands.json")["hands"] if h["secret"])


# ---- +3 Mult per scoring card of a suit -------------------------------------------------------------

@joker
class LustyJoker(SuitMultJoker):
    name, suit = "Lusty Joker", "Hearts"


@joker
class WrathfulJoker(SuitMultJoker):
    name, suit = "Wrathful Joker", "Spades"


@joker
class GluttonousJoker(SuitMultJoker):
    name, suit = "Gluttonous Joker", "Clubs"


# ---- when the played hand contains a poker hand -----------------------------------------------------

class HandTypeJoker(Joker):
    """+chips and +mult when the played hand contains `hand_type`."""
    hand_type, chips, mult = "?", 0, 0

    def independent(self, ctx, score):
        if self.hand_type in ctx.result.contains:
            score.add_chips(self.name, self.chips)
            score.add_mult(self.name, self.mult)


@joker
class ZanyJoker(HandTypeJoker):
    name, hand_type, mult = "Zany Joker", "Three of a Kind", 12


@joker
class MadJoker(HandTypeJoker):
    name, hand_type, mult = "Mad Joker", "Two Pair", 10


@joker
class CrazyJoker(HandTypeJoker):
    name, hand_type, mult = "Crazy Joker", "Straight", 12


@joker
class DrollJoker(HandTypeJoker):
    name, hand_type, mult = "Droll Joker", "Flush", 10


@joker
class SlyJoker(HandTypeJoker):
    name, hand_type, chips = "Sly Joker", "Pair", 50


@joker
class WilyJoker(HandTypeJoker):
    name, hand_type, chips = "Wily Joker", "Three of a Kind", 100


@joker
class CleverJoker(HandTypeJoker):
    name, hand_type, chips = "Clever Joker", "Two Pair", 80


@joker
class DeviousJoker(HandTypeJoker):
    name, hand_type, chips = "Devious Joker", "Straight", 100


@joker
class CraftyJoker(HandTypeJoker):
    name, hand_type, chips = "Crafty Joker", "Flush", 80


# ---- per scoring card -------------------------------------------------------------------------------

class RankJoker(Joker):
    """+chips and +mult for each scoring card of one of `ranks`."""
    ranks: frozenset[int] = frozenset()
    chips = mult = 0

    def on_scored(self, ctx, card, score):
        if card.rank in self.ranks and not card.is_stone:
            score.add_chips(self.name, self.chips)
            score.add_mult(self.name, self.mult)


@joker
class EvenSteven(RankJoker):
    name, ranks, mult = "Even Steven", frozenset({2, 4, 6, 8, 10}), 4


@joker
class OddTodd(RankJoker):
    name, ranks, chips = "Odd Todd", frozenset({14, 3, 5, 7, 9}), 31


@joker
class Scholar(RankJoker):
    name, ranks, chips, mult = "Scholar", frozenset({14}), 20, 4


@joker
class WalkieTalkie(RankJoker):
    name, ranks, chips, mult = "Walkie Talkie", frozenset({10, 4}), 10, 4


@joker
class ScaryFace(Joker):
    name = "Scary Face"

    def on_scored(self, ctx, card, score):
        if card.is_face(ctx.run.pareidolia):
            score.add_chips(self.name, 30)


@joker
class SmileyFace(Joker):
    name = "Smiley Face"

    def on_scored(self, ctx, card, score):
        if card.is_face(ctx.run.pareidolia):
            score.add_mult(self.name, 5)


@joker
class BusinessCard(Joker):
    name = "Business Card"

    def on_scored(self, ctx, card, score):
        if card.is_face(ctx.run.pareidolia) and ctx.chance(2):
            score.add_money(self.name, 2)


@joker
class Photograph(Joker):
    """X2 Mult each time the first scoring face card scores."""
    name = "Photograph"

    def on_scored(self, ctx, card, score):
        p = ctx.run.pareidolia
        if card.is_face(p) and next((c for c in ctx.scoring_cards if not c.debuffed and c.is_face(p)), None) is card:
            score.x_mult(self.name, 2)


@joker
class GoldenTicket(Joker):
    name = "Golden Ticket"

    @classmethod
    def can_spawn(cls, run):
        return any(c.enhancement == "Gold" for c in run.deck)

    def on_scored(self, ctx, card, score):
        if card.enhancement == "Gold":
            score.add_money(self.name, 4)


@joker
class EightBall(Joker):
    name = "8 Ball"

    def on_scored(self, ctx, card, score):
        if not ctx.estimating and card.rank == 8 and not card.is_stone and ctx.chance(4, "8ball"):
            ctx.run.create_consumable("Tarot", source="8ba")


# ---- per card held in hand --------------------------------------------------------------------------

@joker
class RaisedFist(Joker):
    """+2x the chip value of the lowest-ranked held card (the rightmost on ties)."""
    name = "Raised Fist"

    def on_held(self, ctx, card, score):
        if card.is_stone:
            return
        lowest = min((c for c in reversed(ctx.held) if not c.is_stone), key=lambda c: c.rank)
        if lowest is card:
            score.add_mult(self.name, 2 * rank_chips(card.rank))


@joker
class ShootTheMoon(Joker):
    name = "Shoot the Moon"

    def on_held(self, ctx, card, score):
        if card.rank == 12 and not card.is_stone:
            score.add_mult(self.name, 13)


@joker
class ReservedParking(Joker):
    name = "Reserved Parking"

    def on_held(self, ctx, card, score):
        # TODO(engine): Mime / Red Seal retrigger a held card only if its first trigger did something; the
        # run retriggers every held card, so a failed roll here gets another try.
        if card.is_face(ctx.run.pareidolia) and ctx.chance(2):
            score.add_money(self.name, 1)


# ---- independent -------------------------------------------------------------------------------------

@joker
class HalfJoker(Joker):
    name = "Half Joker"

    def independent(self, ctx, score):
        if len(ctx.played) <= 3:
            score.add_mult(self.name, 20)


@joker
class Banner(Joker):
    name = "Banner"

    def independent(self, ctx, score):
        score.add_chips(self.name, 30 * max(0, ctx.run.discards_left))


@joker
class MysticSummit(Joker):
    name = "Mystic Summit"

    def independent(self, ctx, score):
        if ctx.run.discards_left == 0:
            score.add_mult(self.name, 15)


@joker
class Misprint(Joker):
    name = "Misprint"

    def independent(self, ctx, score):
        score.add_mult(self.name, ctx.rng.randint(0, 23))


@joker
class AbstractJoker(Joker):
    name = "Abstract Joker"

    def independent(self, ctx, score):
        score.add_mult(self.name, 3 * len(ctx.run.jokers))


@joker
class Supernova(Joker):
    name = "Supernova"

    def independent(self, ctx, score):
        plays = ctx.run.hand_plays[ctx.result.name] + (1 if ctx.estimating else 0)
        score.add_mult(self.name, plays)


@joker
class BlueJoker(Joker):
    name = "Blue Joker"

    def independent(self, ctx, score):
        score.add_chips(self.name, 2 * len(ctx.run.draw_pile))


@joker
class FortuneTeller(Joker):
    name = "Fortune Teller"

    def independent(self, ctx, score):
        score.add_mult(self.name, ctx.run.consumables_used["Tarot"])


@joker
class Swashbuckler(Joker):
    name = "Swashbuckler"

    def independent(self, ctx, score):
        run = ctx.run
        score.add_mult(self.name, sum(run.sell_value(j) for j in run.jokers if j is not self))


@joker
class Superposition(Joker):
    name = "Superposition"

    def independent(self, ctx, score):
        if (not ctx.estimating and "Straight" in ctx.result.contains
                and any(c.rank == 14 and not c.is_stone for c in ctx.scoring_cards)):
            ctx.run.create_consumable("Tarot", source="sup")


@joker
class GrosMichel(Joker):
    name = "Gros Michel"

    @classmethod
    def can_spawn(cls, run):
        return "Gros Michel" not in run.extinct

    def independent(self, ctx, score):
        score.add_mult(self.name, 15)

    def end_of_round(self, run, blind):
        if run.chance(6, "misc") and run.remove_joker(self):
            run.extinct.add(self.name)
        return 0


@joker
class Cavendish(Joker):
    name = "Cavendish"

    @classmethod
    def can_spawn(cls, run):
        return "Gros Michel" in run.extinct

    def independent(self, ctx, score):
        score.x_mult(self.name, 3)

    def end_of_round(self, run, blind):
        if run.chance(1000, "misc"):
            run.remove_joker(self)
        return 0


@joker
class IceCream(Joker):
    """+100 Chips, 5 fewer after each hand; melts after the 20th."""
    name = "Ice Cream"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.chips = 100

    def independent(self, ctx, score):
        score.add_chips(self.name, self.chips)

    def after(self, ctx, score):
        # TODO(engine): hands a boss doesn't allow melt it too; the run calls `after` only for allowed hands.
        if not ctx.live:
            return
        if self.chips <= 5:
            ctx.run.remove_joker(self)
        else:
            self.chips -= 5


@joker
class Popcorn(Joker):
    """+20 Mult, 4 fewer at each round's end; gone after the 5th."""
    name = "Popcorn"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.mult = 20

    def independent(self, ctx, score):
        score.add_mult(self.name, self.mult)

    def end_of_round(self, run, blind):
        if self.mult <= 4:
            run.remove_joker(self)
        else:
            self.mult -= 4
        return 0


@joker
class RedCard(Joker):
    name = "Red Card"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.mult = 0

    def on_pack_skip(self, run, pack):
        # TODO(engine): skipping a Mega pack after taking a card counts too; the run calls on_pack_skip only
        # when nothing was taken.
        if not run.copying:
            self.mult += 3

    def independent(self, ctx, score):
        score.add_mult(self.name, self.mult)


# ---- grow before scoring, then give the total --------------------------------------------------------

class ScalingJoker(Joker):
    """Grows (or resets) in `before` to `grow(ctx)`, then gives `value` as +`gives` ("mult" or "chips").
    A bot's estimate sees this hand's growth without keeping it."""
    gives = "mult"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.value = 0

    def grow(self, ctx) -> int:
        return self.value

    def before(self, ctx):
        if ctx.live:
            self.value = self.grow(ctx)

    def independent(self, ctx, score):
        value = self.grow(ctx) if ctx.estimating else self.value
        if self.gives == "chips":
            score.add_chips(self.name, value)
        else:
            score.add_mult(self.name, value)


@joker
class RideTheBus(ScalingJoker):
    """+1 Mult per hand in a row without a scoring face card; a scoring face card resets it."""
    name = "Ride the Bus"

    def grow(self, ctx):
        p = ctx.run.pareidolia
        return 0 if any(not c.debuffed and c.is_face(p) for c in ctx.scoring_cards) else self.value + 1


@joker
class Runner(ScalingJoker):
    name, gives = "Runner", "chips"

    def grow(self, ctx):
        return self.value + 15 if "Straight" in ctx.result.contains else self.value


@joker
class SquareJoker(ScalingJoker):
    name, gives = "Square Joker", "chips"

    def grow(self, ctx):
        return self.value + 4 if len(ctx.played) == 4 else self.value


@joker
class GreenJoker(ScalingJoker):
    """+1 Mult per hand played, -1 per discard, never below 0."""
    name = "Green Joker"

    def grow(self, ctx):
        return self.value + 1

    def on_discard(self, run, cards, first):
        if not run.copying:
            self.value = max(0, self.value - 1)


# ---- money and targets --------------------------------------------------------------------------------

@joker
class ToDoList(Joker):
    """$4 when the played hand is `target`; the target changes at each round's end."""
    name = "To Do List"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.target = "High Card"

    def roll(self, run, exclude=None):
        hands = [h for h in HAND_ORDER if h != exclude and (h not in SECRET_HANDS or run.hand_plays[h])]
        self.target = run.rng["misc"].choice(hands)

    def on_added(self, run):
        self.roll(run)

    def before(self, ctx):
        if ctx.result.name == self.target and not ctx.estimating:
            ctx.run.money += 4

    def end_of_round(self, run, blind):
        self.roll(run, self.target)
        return 0


@joker
class MailInRebate(Joker):
    """$5 per discarded card of `rank`, the rank of a random card in the deck, rolled again each round."""
    name = "Mail-In Rebate"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.rank = 14

    def roll(self, run):
        # TODO(engine): the game keeps one rank per run (rolled at run start and each round's end) that all
        # copies share; here each copy rolls its own.
        ranked = [c for c in run.deck if not c.is_stone]
        self.rank = run.rng["misc"].choice(ranked).rank if ranked else 14

    def on_added(self, run):
        self.roll(run)

    def on_discard(self, run, cards, first):
        run.money += 5 * sum(c.rank == self.rank and not c.is_stone and not c.debuffed for c in cards)

    def end_of_round(self, run, blind):
        self.roll(run)
        return 0


@joker
class FacelessJoker(Joker):
    name = "Faceless Joker"

    def on_discard(self, run, cards, first):
        p = run.pareidolia
        if sum(not c.debuffed and c.is_face(p) for c in cards) >= 3:
            run.money += 5


@joker
class DelayedGratification(Joker):
    name = "Delayed Gratification"

    def end_of_round(self, run, blind):
        return 2 * run.discards_left if run.discards_used == 0 else 0


@joker
class GoldenJoker(Joker):
    name = "Golden Joker"

    def end_of_round(self, run, blind):
        return 4


@joker
class Egg(Joker):
    name = "Egg"

    def end_of_round(self, run, blind):
        self.extra_sell += 3
        return 0


@joker
class CreditCard(Joker):
    name = "Credit Card"
    debt = 20  # TODO(engine): copies stack in the game ($20 each); run.debt_limit takes the largest


# ---- creating things ----------------------------------------------------------------------------------

@joker
class RiffRaff(Joker):
    name = "Riff-Raff"

    def on_blind_select(self, run, blind):
        free = run.joker_slots - sum(j.edition != "Negative" for j in run.jokers)
        for _ in range(min(2, free)):
            run.create_joker("Common", source="rif")


@joker
class Hallucination(Joker):
    name = "Hallucination"

    def on_pack_open(self, run, pack):
        if run.chance(2, "misc"):
            run.create_consumable("Tarot", source="hal")


# ---- passives -------------------------------------------------------------------------------------------

@joker
class ChaosTheClown(Joker):
    """One free reroll per shop (the shop counts Chaos the Clowns by name)."""
    name = "Chaos the Clown"

    def on_added(self, run):
        if run.current_shop is not None:
            run.current_shop.free_rerolls += 1

    def on_sold(self, run):
        shop = run.current_shop
        if shop is not None and not self.perished:
            shop.free_rerolls = max(0, shop.free_rerolls - 1)


@joker
class Splash(Joker):
    name = "Splash"
    rules = {"splash": True}


@joker
class Juggler(Joker):
    name = "Juggler"
    hand_size_bonus = 1


@joker
class Drunkard(Joker):
    name = "Drunkard"
    discards_bonus = 1

    def on_added(self, run):
        run.discards_left += 1

    def on_sold(self, run):
        # TODO(engine): a hook for a joker destroyed rather than sold (Madness, Ceremonial Dagger) would take
        # the discard back then too.
        if not self.perished:
            run.discards_left = max(0, run.discards_left - 1)
