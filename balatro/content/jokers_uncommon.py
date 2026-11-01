"""The 64 Uncommon jokers. Rules: data/jokers.json and data/jokers_OPEN_QUESTIONS.md.

Calls made where the data or the engine left a choice:
- Castle and The Idol: each copy rolls its own target (on joining and at every end of round) from a random
  non-Stone card of the deck. In the game all copies share one target; the run has no slot for it.
- Lucky Cat watches `run.lucky_triggers` after each scored card, so a Lucky card that hits both its Mult
  and its money roll counts once, as in the game. A Lucky card counts only while Lucky Cat is active.
- Loyalty Card counts `run.hands_played` from when it joined (a copy made by deep-copying keeps it):
  X4 on the 6th, 12th, ... hand since then. Hands a boss disallows still count, as in the game.
- Vampire strips and grows only as the original (not as a copy, not in a bot's estimate); Midas Mask turns
  cards Gold only in real play, so a bot's estimate still sees the old enhancement.
- A bot's estimate runs before the run counts the hand: Acrobat and Dusk see the final hand as the one with a
  hand left, Card Sharp and Loyalty Card count the hand being estimated (as Supernova does).
- Ceremonial Dagger and Madness destroy and grow only as the original; a copy gives their current value.
- Sixth Sense acts after scoring: the 6 joins the cards destroyed after the hand (also when the 6 is debuffed
  or there is no room for the Spectral). A Stone card is not a 6.
- Mr. Bones also clears the Blind's reward (no reward after a save) and does not save a round lost with hands
  still left (out of cards). Both per the wiki page.
- Luchador disables the boss only while that boss's round is on (not in the shop after it), per the wiki page.
  Luchador and Diet Cola do nothing when sold while debuffed.
- To the Moon pays its extra interest through end_of_round, from the money held before rent is charged.
- Rocket's +$2 for a boss applies before that round's payout. Turtle Bean is destroyed at its 5th round end.
- Glass Joker counts every Glass card destroyed, including by Spectral cards (the game misses those, a bug).
"""
from __future__ import annotations

from ..cards import RANKS, SEALS, SUITS, Card
from ..items import TAGS, Tag, make
from ..jokers import Joker, joker

BLACK = ("Spades", "Clubs")
FLOWER_SUITS = ("Hearts", "Diamonds", "Spades", "Clubs")
FIBONACCI = (14, 2, 3, 5, 8)


def _deck_card(run) -> Card | None:
    """A uniformly random non-Stone card of the full deck (Castle, The Idol)."""
    cards = [c for c in run.deck if not c.is_stone]
    return run.rng["misc"].choice(cards) if cards else None


class MultScaler(Joker):
    """Gives its running +Mult in the joker pass."""

    def __init__(self, edition=None):
        super().__init__(edition)
        self.mult = 0

    def independent(self, ctx, score):
        score.add_mult(self.name, self.mult)


class XMultScaler(Joker):
    """Gives its running XMult in the joker pass."""

    def __init__(self, edition=None):
        super().__init__(edition)
        self.xmult = 1.0

    def independent(self, ctx, score):
        score.x_mult(self.name, self.xmult)


# ---- rules and passives ---------------------------------------------------------------------------

@joker
class FourFingers(Joker):
    name = "Four Fingers"
    rules = {"four_fingers": True}


@joker
class Shortcut(Joker):
    name = "Shortcut"
    rules = {"shortcut": True}


@joker
class SmearedJoker(Joker):
    name = "Smeared Joker"
    rules = {"smeared": True}


@joker
class Pareidolia(Joker):
    # TODO(engine): Card.is_face ignores Pareidolia for Stone cards; the game counts them as faces too
    name = "Pareidolia"
    rules = {"pareidolia": True}


@joker
class Showman(Joker):
    name = "Showman"
    rules = {"showman": True}


@joker
class OopsAll6s(Joker):
    """Doubles every listed chance; the run counts copies by name."""
    name = "Oops! All 6s"


@joker
class Astronomer(Joker):
    """Planet cards and Celestial packs are free; the shop checks it by name."""
    name = "Astronomer"


@joker
class Troubadour(Joker):
    name = "Troubadour"
    hand_size_bonus, hands_bonus = 2, -1


@joker
class MerryAndy(Joker):
    name = "Merry Andy"
    hand_size_bonus, discards_bonus = -1, 3


@joker
class TurtleBean(Joker):
    """+5 hand size, 1 less after each round; gone when it reaches 0."""
    name = "Turtle Bean"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.hand_size_bonus = 5

    def end_of_round(self, run, blind):
        self.hand_size_bonus -= 1
        if self.hand_size_bonus <= 0:
            run.remove_joker(self)
        return 0


# ---- per scored card ------------------------------------------------------------------------------

@joker
class Fibonacci(Joker):
    name = "Fibonacci"

    def on_scored(self, ctx, card, score):
        if card.rank in FIBONACCI and not card.is_stone:
            score.add_mult(self.name, 8)


@joker
class RoughGem(Joker):
    name = "Rough Gem"

    def on_scored(self, ctx, card, score):
        if card.has_suit("Diamonds", ctx.run.smeared):
            score.add_money(self.name, 1)


@joker
class Bloodstone(Joker):
    name = "Bloodstone"

    def on_scored(self, ctx, card, score):
        if not card.has_suit("Hearts", ctx.run.smeared):
            return
        if ctx.expecting:                                   # X1.5 1 in 2: X1.25 on average
            score.x_mult(self.name, 1 + 0.5 * ctx.odds(2))
        elif ctx.chance(2):
            score.x_mult(self.name, 1.5)


@joker
class Arrowhead(Joker):
    name = "Arrowhead"

    def on_scored(self, ctx, card, score):
        if card.has_suit("Spades", ctx.run.smeared):
            score.add_chips(self.name, 50)


@joker
class OnyxAgate(Joker):
    name = "Onyx Agate"

    def on_scored(self, ctx, card, score):
        if card.has_suit("Clubs", ctx.run.smeared):
            score.add_mult(self.name, 7)


@joker
class Hiker(Joker):
    """Each trigger of a scoring card adds +5 permanent chips to it (seen by its later triggers)."""
    name = "Hiker"

    def on_scored(self, ctx, card, score):
        if not ctx.estimating:
            card.bonus_chips += 5


@joker
class TheIdol(Joker):
    """X2 per scoring card of its rank and suit, re-rolled each round."""
    name = "The Idol"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.rank, self.suit = 14, "Spades"

    def roll(self, run):
        # TODO(engine): copies should share one target (a run-level slot, as for Castle and Mail-In Rebate)
        c = _deck_card(run)
        self.rank, self.suit = (c.rank, c.suit) if c else (14, "Spades")

    def on_added(self, run):
        self.roll(run)

    def end_of_round(self, run, blind):
        self.roll(run)
        return 0

    def on_scored(self, ctx, card, score):
        if card.rank == self.rank and not card.is_stone and card.has_suit(self.suit, ctx.run.smeared):
            score.x_mult(self.name, 2)


@joker
class LuckyCat(XMultScaler):
    """+X0.25 each time a scoring Lucky card hits (both rolls hitting count once)."""
    name = "Lucky Cat"
    seen = 0  # run.lucky_triggers already counted

    @classmethod
    def can_spawn(cls, run):
        return any(c.enhancement == "Lucky" for c in run.deck)

    def before(self, ctx):
        if ctx.live:
            self.seen = ctx.run.lucky_triggers

    def on_scored(self, ctx, card, score):
        n = ctx.run.lucky_triggers
        if ctx.live and n > self.seen:
            self.seen = n
            self.xmult += 0.25


# ---- retriggers -----------------------------------------------------------------------------------

@joker
class Hack(Joker):
    name = "Hack"

    def retriggers(self, ctx, card, position):
        return 1 if 2 <= card.rank <= 5 and not card.is_stone else 0


@joker
class SockAndBuskin(Joker):
    name = "Sock and Buskin"

    def retriggers(self, ctx, card, position):
        return 1 if card.is_face(ctx.run.pareidolia) else 0


@joker
class Dusk(Joker):
    name = "Dusk"

    def retriggers(self, ctx, card, position):
        return 1 if ctx.run.hands_left == (1 if ctx.estimating else 0) else 0


@joker
class Seltzer(Joker):
    """Retriggers every scoring card for 10 hands."""
    name = "Seltzer"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.hands = 10

    def retriggers(self, ctx, card, position):
        return 1

    def after(self, ctx, score):
        # TODO(engine): hands a boss disallows should count down too; the run calls no joker hook for them
        if ctx.live:
            self.hands -= 1
            if self.hands <= 0:
                ctx.run.remove_joker(self)


@joker
class Mime(Joker):
    # TODO(engine): the game retriggers only held cards that did something (matters for Reserved Parking)
    name = "Mime"

    def held_retriggers(self, ctx, card):
        return 1


# ---- before scoring -------------------------------------------------------------------------------

@joker
class SpaceJoker(Joker):
    name = "Space Joker"

    def before(self, ctx):
        if not ctx.estimating and ctx.chance(4):
            ctx.run.level_up(ctx.result.name)


@joker
class MidasMask(Joker):
    name = "Midas Mask"

    def before(self, ctx):
        if ctx.estimating:
            return
        pareidolia = ctx.run.pareidolia
        for c in ctx.scoring_cards:
            if not c.debuffed and c.is_face(pareidolia):
                c.enhancement = "Gold"


@joker
class Vampire(XMultScaler):
    """Strips the enhancement of every scoring card, +X0.1 each."""
    name = "Vampire"

    def before(self, ctx):
        if not ctx.live:
            return
        for c in ctx.scoring_cards:
            if c.enhancement and not c.debuffed:
                c.enhancement = None
                self.xmult = round(self.xmult + 0.1, 2)


@joker
class SpareTrousers(MultScaler):
    name = "Spare Trousers"

    def before(self, ctx):
        if ctx.live and "Two Pair" in ctx.result.contains:
            self.mult += 2


# ---- joker pass -----------------------------------------------------------------------------------

@joker
class JokerStencil(Joker):
    """X(empty slots), each Stencil counting as empty; Negative jokers take no slot."""
    name = "Joker Stencil"

    def independent(self, ctx, score):
        jokers = ctx.run.jokers
        x = ctx.run.joker_slots - sum(j.edition != "Negative" for j in jokers) + sum(j.name == self.name for j in jokers)
        if x > 1:
            score.x_mult(self.name, x)


@joker
class LoyaltyCard(Joker):
    name = "Loyalty Card"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.since: int | None = None  # run.hands_played when it joined

    def on_added(self, run):
        if self.since is None:
            self.since = run.hands_played

    def independent(self, ctx, score):
        n = ctx.run.hands_played + (1 if ctx.estimating else 0) - (self.since or 0)
        if n > 0 and n % 6 == 0:
            score.x_mult(self.name, 4)


@joker
class SteelJoker(Joker):
    name = "Steel Joker"

    @classmethod
    def can_spawn(cls, run):
        return any(c.enhancement == "Steel" for c in run.deck)

    def independent(self, ctx, score):
        n = sum(c.enhancement == "Steel" for c in ctx.run.deck)
        score.x_mult(self.name, 1 + n / 5)


@joker
class StoneJoker(Joker):
    name = "Stone Joker"

    @classmethod
    def can_spawn(cls, run):
        return any(c.is_stone for c in run.deck)

    def independent(self, ctx, score):
        score.add_chips(self.name, 25 * sum(c.is_stone for c in ctx.run.deck))


@joker
class Blackboard(Joker):
    """X3 if every held card is a Spade or Club (debuffed cards by printed suit; Stone breaks it)."""
    name = "Blackboard"

    def independent(self, ctx, score):
        if all(not c.is_stone and (c.suit in BLACK or (c.enhancement == "Wild" and not c.debuffed)) for c in ctx.held):
            score.x_mult(self.name, 3)


@joker
class CardSharp(Joker):
    name = "Card Sharp"

    def independent(self, ctx, score):
        if ctx.run.round_hand_types[ctx.result.name] + (1 if ctx.estimating else 0) > 1:
            score.x_mult(self.name, 3)


@joker
class Acrobat(Joker):
    name = "Acrobat"

    def independent(self, ctx, score):
        if ctx.run.hands_left == (1 if ctx.estimating else 0):
            score.x_mult(self.name, 3)


@joker
class Erosion(Joker):
    name = "Erosion"

    def independent(self, ctx, score):
        score.add_mult(self.name, 4 * max(0, ctx.run.starting_deck_size - len(ctx.run.deck)))


@joker
class Bull(Joker):
    """+2 Chips per $ held, counting money earned earlier in this hand."""
    name = "Bull"

    def independent(self, ctx, score):
        score.add_chips(self.name, 2 * max(0, ctx.run.money + score.money))


@joker
class Bootstraps(Joker):
    """+2 Mult per $5 held, counting money earned earlier in this hand."""
    name = "Bootstraps"

    def independent(self, ctx, score):
        score.add_mult(self.name, 2 * (max(0, ctx.run.money + score.money) // 5))


@joker
class Throwback(Joker):
    name = "Throwback"

    def independent(self, ctx, score):
        score.x_mult(self.name, 1 + 0.25 * ctx.run.skips)


@joker
class FlowerPot(Joker):
    """X3 if the scoring cards cover all four suits; each card fills one suit, Wild cards fill what's left."""
    name = "Flower Pot"

    def independent(self, ctx, score):
        smeared = ctx.run.smeared
        missing = list(FLOWER_SUITS)
        wild = 0
        for c in ctx.scoring_cards:
            if c.is_stone:
                continue
            if c.enhancement == "Wild":
                wild += not c.debuffed
                continue
            for s in missing:
                if c.has_suit(s, smeared):
                    missing.remove(s)
                    break
        if len(missing) <= wild:
            score.x_mult(self.name, 3)


@joker
class SeeingDouble(Joker):
    """X2 if the scoring cards include a Club and another suit; Wild cards fill Clubs first."""
    name = "Seeing Double"

    def independent(self, ctx, score):
        smeared = ctx.run.smeared
        clubs = other = False
        wild = 0
        for c in ctx.scoring_cards:
            if c.debuffed or c.is_stone:
                continue
            if c.enhancement == "Wild":
                wild += 1
                continue
            clubs = clubs or c.has_suit("Clubs", smeared)
            other = other or c.has_suit("Hearts", smeared) or c.has_suit("Diamonds", smeared) or c.has_suit("Spades", smeared)
        if wild and not clubs:
            clubs, wild = True, wild - 1
        if clubs and (other or wild):
            score.x_mult(self.name, 2)


@joker
class Seance(Joker):
    name = "Séance"

    def independent(self, ctx, score):
        if "Straight Flush" in ctx.result.contains and not ctx.estimating:
            ctx.run.create_consumable("Spectral", source="sea")


@joker
class Matador(Joker):
    """$8 when the played hand triggers the boss: its flag, or a debuffed scoring card."""
    name = "Matador"

    def independent(self, ctx, score):
        # TODO(engine): the run should clear boss.triggered before each hand (the game's flag is per hand),
        # and call a joker hook for hands the boss disallows (The Psychic, The Eye, The Mouth pay $8 too)
        boss = ctx.run.active_boss
        if boss is not None and (boss.triggered or any(c.debuffed for c in ctx.scoring_cards)):
            score.add_money(self.name, 8)


@joker
class Constellation(XMultScaler):
    name = "Constellation"

    def on_consumable_used(self, run, consumable):
        if consumable.kind == "Planet" and not run.copying:
            self.xmult = round(self.xmult + 0.1, 2)


@joker
class Hologram(XMultScaler):
    name = "Hologram"

    def on_cards_added(self, run, cards):
        if not run.copying:
            self.xmult += 0.25 * len(cards)


@joker
class GlassJoker(XMultScaler):
    name = "Glass Joker"

    @classmethod
    def can_spawn(cls, run):
        return any(c.enhancement == "Glass" for c in run.deck)

    def on_cards_destroyed(self, run, cards):
        # TODO(engine): destroy_cards doesn't say what destroyed them; the game ignores Spectral destruction
        if not run.copying:
            self.xmult += 0.75 * len({id(c) for c in cards if c.enhancement == "Glass"})


@joker
class FlashCard(MultScaler):
    name = "Flash Card"

    def on_reroll(self, run, shop):
        if not run.copying:
            self.mult += 2


@joker
class Ramen(Joker):
    """X2, losing X0.01 per discarded card; destroyed when it would reach X1."""
    name = "Ramen"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.xmult = 2.0

    def on_discard(self, run, cards, first):
        if run.copying:
            return
        self.xmult = round(self.xmult - 0.01 * len(cards), 2)
        if self.xmult <= 1:
            run.remove_joker(self)

    def independent(self, ctx, score):
        score.x_mult(self.name, self.xmult)


@joker
class Castle(Joker):
    """+3 Chips per discarded card of its suit, re-rolled each round."""
    name = "Castle"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.chips = 0
        self.suit = "Spades"

    def roll(self, run):
        # TODO(engine): copies should share one suit (a run-level slot, as for The Idol and Mail-In Rebate)
        c = _deck_card(run)
        self.suit = c.suit if c else "Spades"

    def on_added(self, run):
        self.roll(run)

    def end_of_round(self, run, blind):
        self.roll(run)
        return 0

    def on_discard(self, run, cards, first):
        if not run.copying:
            smeared = run.smeared
            self.chips += 3 * sum(not c.debuffed and c.has_suit(self.suit, smeared) for c in cards)

    def independent(self, ctx, score):
        score.add_chips(self.name, self.chips)


# ---- after scoring --------------------------------------------------------------------------------

@joker
class SixthSense(Joker):
    """A single 6 as the round's first hand is destroyed and makes a Spectral card."""
    name = "Sixth Sense"

    def after(self, ctx, score):
        if ctx.estimating or len(ctx.played) != 1 or ctx.run.round_hands_played != 1:
            return
        six = ctx.played[0]
        if six.rank != 6 or six.is_stone:
            return
        if not any(c is six for c in ctx.destroyed):
            ctx.destroyed.append(six)
        ctx.run.create_consumable("Spectral", source="sixth")


# ---- run hooks ------------------------------------------------------------------------------------

@joker
class CeremonialDagger(MultScaler):
    """On blind select, destroys the joker to its right and gains twice its sell value as Mult."""
    name = "Ceremonial Dagger"

    def on_blind_select(self, run, blind):
        # TODO(engine): the run calls on_blind_select on a snapshot, so a joker destroyed here still acts
        if run.copying or self not in run.jokers:
            return
        i = run.jokers.index(self) + 1
        if i < len(run.jokers):
            victim = run.jokers[i]
            value = run.sell_value(victim)
            if run.remove_joker(victim):
                self.mult += 2 * value


@joker
class Madness(XMultScaler):
    """On a Small or Big Blind, +X0.5 and destroys a random other joker."""
    name = "Madness"

    def on_blind_select(self, run, blind):
        if run.copying or blind.kind == 2 or self not in run.jokers:
            return
        self.xmult += 0.5
        others = [j for j in run.jokers if j is not self and not j.eternal]
        if others:
            run.remove_joker(run.rng["misc"].choice(others))


@joker
class MarbleJoker(Joker):
    name = "Marble Joker"

    def on_blind_select(self, run, blind):
        rng = run.rng["misc"]
        run.add_cards([Card(rng.choice(RANKS), rng.choice(SUITS), enhancement="Stone")])


@joker
class Burglar(Joker):
    name = "Burglar"

    def on_blind_select(self, run, blind):
        run.hands_left += 3
        run.discards_left = 0


@joker
class Cartomancer(Joker):
    name = "Cartomancer"

    def on_blind_select(self, run, blind):
        run.create_consumable("Tarot", source="car")


@joker
class Certificate(Joker):
    """A random card with a random seal joins the hand and the deck when the round starts."""
    name = "Certificate"

    def on_round_start(self, run):
        rng = run.rng["misc"]
        run.add_cards([Card(rng.choice(RANKS), rng.choice(SUITS), seal=rng.choice(SEALS))], to_hand=True)
        run.refresh_debuffs()


@joker
class TradingCard(Joker):
    """A first discard of exactly one card destroys it and pays $3."""
    name = "Trading Card"

    def on_discard(self, run, cards, first):
        if first and len(cards) == 1:
            run.money += 3
            if any(c is cards[0] for c in run.deck):
                run.destroy_cards(cards)


@joker
class Luchador(Joker):
    name = "Luchador"

    def on_sold(self, run):
        # TODO(engine): selling a Blueprint/Brainstorm that copies Luchador should disable the boss too
        if run.active_boss is not None and run.current_shop is None and not (self.disabled or self.perished):
            run.disable_boss()


@joker
class DietCola(Joker):
    name = "Diet Cola"

    def on_sold(self, run):
        # TODO(engine): selling a Blueprint/Brainstorm that copies Diet Cola should give a Double Tag too
        if not (self.disabled or self.perished):
            run.gain_tag(make(TAGS, Tag, "Double Tag"))


@joker
class MrBones(Joker):
    """Saves a lost round that reached 25% of the blind, then destroys itself; no blind reward."""
    name = "Mr. Bones"

    def on_fail(self, run):
        if run.hands_left > 0 or run.round_score * 4 < run.blind.chips:
            return False
        run.remove_joker(self)
        run.blind.reward = 0
        return True


# ---- end of round ---------------------------------------------------------------------------------

@joker
class Cloud9(Joker):
    name = "Cloud 9"

    def end_of_round(self, run, blind):
        return sum(c.rank == 9 and not c.is_stone for c in run.deck)


@joker
class Rocket(Joker):
    name = "Rocket"

    def __init__(self, edition=None):
        super().__init__(edition)
        self.dollars = 1

    def end_of_round(self, run, blind):
        if blind.kind == 2:
            self.dollars += 2
        return self.dollars


@joker
class GiftCard(Joker):
    name = "Gift Card"

    def end_of_round(self, run, blind):
        for item in run.jokers + run.consumables:
            item.extra_sell += 1
        return 0


@joker
class ToTheMoon(Joker):
    """+$1 interest per $5 held, up to the usual cap."""
    name = "To the Moon"

    def end_of_round(self, run, blind):
        # TODO(engine): an interest-per-$5 setting read by cash_out would be exact (rent is charged after this)
        return min(run.interest_cap, max(0, run.money) // 5) if run.interest_enabled else 0


@joker
class Satellite(Joker):
    name = "Satellite"

    def end_of_round(self, run, blind):
        return len(run.planets_used)
