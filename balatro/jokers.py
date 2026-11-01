"""Jokers: a base class with one hook per moment a joker can act, and the catalog.

Blueprint and Brainstorm forward every hook in HAND_HOOKS and RUN_HOOKS to the joker they copy, as the
game does; not end_of_round (dollars at cash out), on_added, on_sold, on_fail or the passives. So a
joker's own lasting state (scaling counters) may change only when it isn't being copied:
    hand hooks (first argument ctx): only when `ctx.live` (not a copy, not a bot's estimate);
    run hooks (first argument run): only when `not run.copying`.
Effects on the run itself (money, creating or destroying cards, levelling hands) do happen for a copy;
in hand hooks they wait for `not ctx.estimating`.

Rarity, cost, Blueprint compatibility and sticker compatibility come from data/jokers.json, so a joker
class only sets its name and the hooks it uses.
"""
from __future__ import annotations

from .cards import Card
from .items import data
from .scoring import HandContext, Score

CATALOG: dict[str, type] = {}
JOKER_DATA = {e["name"]: e for e in data("jokers.json")}


def joker(cls):
    """Register a joker class under its name, filling its rarity, cost and compatibility from the data."""
    d = JOKER_DATA[cls.name]
    cls.number, cls.rarity, cls.cost = d["n"], d["rarity"], d["cost"]
    cls.copyable = d["blueprint_compatible"]
    cls.eternal_ok, cls.perishable_ok = d["eternal_compatible"], d["perishable_compatible"]
    CATALOG[cls.name] = cls
    return cls


class Joker:
    name = "?"
    number = 0
    rarity = "Common"
    cost = 0
    copyable = True  # Blueprint / Brainstorm can copy it
    eternal_ok = perishable_ok = True
    debt = 0  # how far into debt it lets you go (Credit Card: 20)

    def __init__(self, edition: str | None = None):
        self.edition = edition
        self.eternal = self.perishable = self.rental = False
        self.perish_rounds = 5  # rounds left before a perishable joker is debuffed
        self.perished = False
        self.extra_sell = 0  # Egg, Gift Card
        self.disabled = False  # for this hand or round (Crimson Heart); the run clears it after the round

    @classmethod
    def can_spawn(cls, run) -> bool:
        """Can it appear in the shop or a pack right now (Cavendish after Gros Michel dies, Steel Joker with Steel cards)?"""
        return True

    def on_added(self, run) -> None:
        """It joined your jokers (bought, created or taken from a pack)."""

    def on_fail(self, run) -> bool:
        """The round is about to be lost; return True to survive it (Mr. Bones)."""
        return False

    # ---- hand hooks: while a hand is played ---------------------------------------------------------
    def retriggers(self, ctx: HandContext, card: Card, position: int) -> int:
        return 0

    def on_scored(self, ctx: HandContext, card: Card, score: Score) -> None:
        pass

    def held_retriggers(self, ctx: HandContext, card: Card) -> int:
        return 0

    def on_held(self, ctx: HandContext, card: Card, score: Score) -> None:
        pass

    def independent(self, ctx: HandContext, score: Score) -> None:
        pass

    def on_joker(self, ctx: HandContext, other: "Joker", score: Score) -> None:
        """Called when another joker (or this one) finishes its own effect (Baseball Card)."""

    def before(self, ctx: HandContext) -> None:
        """After the hand is chosen, before anything scores (Space Joker, Midas Mask, Vampire)."""

    def after(self, ctx: HandContext, score: Score) -> None:
        """After the hand has scored (Ice Cream melts, Seltzer counts down)."""

    # ---- run hooks ---------------------------------------------------------------------------------
    def on_blind_select(self, run, blind) -> None:
        pass

    def on_round_start(self, run) -> None:
        """After the first hand of the round is drawn (Certificate)."""

    def on_discard(self, run, cards: list[Card], first: bool) -> None:
        pass

    def end_of_round(self, run, blind) -> int:
        """Called when a blind is beaten, before cash out; returns dollars paid at cash out (Golden Joker,
        Rocket, Cloud 9). Not copied by Blueprint."""
        return 0

    def on_boss_defeated(self, run) -> None:
        pass

    def on_shop_open(self, run, shop) -> None:
        pass

    def on_reroll(self, run, shop) -> None:
        pass

    def on_shop_close(self, run, shop) -> None:
        pass

    def on_sell(self, run, sold) -> None:
        """Another joker or a consumable was sold (Campfire)."""

    def on_sold(self, run) -> None:
        """This joker was sold (Luchador, Diet Cola, Invisible Joker)."""

    def jiggles(self, run) -> bool:
        """Does the game shake this card now, to say it is ready (Invisible Joker once it can be sold to copy)?"""
        return False

    def on_pack_open(self, run, pack) -> None:
        pass

    def on_pack_skip(self, run, pack) -> None:
        pass

    def on_consumable_used(self, run, consumable) -> None:
        pass

    def on_cards_added(self, run, cards: list[Card]) -> None:
        pass

    def on_cards_destroyed(self, run, cards: list[Card]) -> None:
        pass

    # ---- passive modifiers read by the run ---------------------------------------------------------
    hand_size_bonus = 0  # Juggler +1, Stuntman -2, Turtle Bean, Troubadour, Merry Andy
    hands_bonus = 0  # Troubadour -1
    discards_bonus = 0  # Drunkard +1, Merry Andy +3
    rules: dict[str, bool] = {}  # four_fingers, shortcut, smeared, splash, pareidolia, showman

    def __repr__(self) -> str:
        return self.name + (f" ({self.edition})" if self.edition else "")


# ---- a first handful, one per kind of hook; the rest of the catalog is in content/jokers_*.py --------

@joker
class PlainJoker(Joker):
    name = "Joker"

    def independent(self, ctx, score):
        score.add_mult(self.name, 4)


class SuitMultJoker(Joker):
    suit = "?"

    def on_scored(self, ctx, card, score):
        if card.has_suit(self.suit, ctx.run.smeared):
            score.add_mult(self.name, 3)


@joker
class GreedyJoker(SuitMultJoker):
    name, suit = "Greedy Joker", "Diamonds"


@joker
class JollyJoker(Joker):
    name = "Jolly Joker"

    def independent(self, ctx, score):
        if "Pair" in ctx.result.contains:
            score.add_mult(self.name, 8)


@joker
class TheDuo(Joker):
    name = "The Duo"

    def independent(self, ctx, score):
        if "Pair" in ctx.result.contains:
            score.x_mult(self.name, 2)


@joker
class HangingChad(Joker):
    name = "Hanging Chad"

    def retriggers(self, ctx, card, position):
        return 2 if position == 0 else 0


@joker
class BaseballCard(Joker):
    name = "Baseball Card"

    def on_joker(self, ctx, other, score):
        if other.rarity == "Uncommon":
            score.x_mult(f"{self.name} ({other.name})", 1.5)


HAND_HOOKS = ("retriggers", "on_scored", "held_retriggers", "on_held", "independent", "on_joker", "before", "after")
RUN_HOOKS = ("on_blind_select", "on_round_start", "on_discard", "on_boss_defeated", "on_shop_open", "on_reroll",
             "on_shop_close", "on_sell", "on_pack_open", "on_pack_skip", "on_consumable_used", "on_cards_added",
             "on_cards_destroyed")


def _forward(hook: str, hand: bool):
    def method(self, first, *args):
        run = first.run if hand else first
        t = self.target(run)
        if t is None or self._copying:  # a Blueprint already copying can't be reached again (Blueprint <-> Brainstorm)
            return 0
        self._copying = True
        was_run = getattr(run, "copying", False)
        was_ctx = first.copying if hand else None
        run.copying = True
        if hand:
            first.copying = True
        try:
            return getattr(t, hook)(first, *args) or 0
        finally:
            self._copying = False
            run.copying = was_run
            if hand:
                first.copying = was_ctx
    method.__name__ = hook
    return method


@joker
class Blueprint(Joker):
    """Copies the joker to its right: every hand and run hook, marked as a copy."""
    name = "Blueprint"
    _copying = False

    def target(self, run):
        jokers = run.active_jokers()
        i = jokers.index(self) + 1 if self in jokers else len(jokers)
        return jokers[i] if i < len(jokers) and jokers[i].copyable else None


for _hook in HAND_HOOKS:
    setattr(Blueprint, _hook, _forward(_hook, True))
for _hook in RUN_HOOKS:
    setattr(Blueprint, _hook, _forward(_hook, False))


@joker
class Brainstorm(Blueprint):
    """Copies the leftmost joker."""
    name = "Brainstorm"

    def target(self, run):
        jokers = run.active_jokers()
        return jokers[0] if jokers and jokers[0] is not self and jokers[0].copyable else None


RANK_NAMES = {11: "Jack", 12: "Queen", 13: "King", 14: "Ace"}


def _loyalty(j, run) -> str:
    left = (6 - (run.hands_played + 1 - (j.since or run.hands_played)) % 6) % 6   # (X4 on every 6th hand since it joined)
    return "active on the next hand" if left == 0 else f"{left} hands to go"


# Jokers whose effect comes from the run's state, not from a value of their own (as each one's effect reads it): their
# "(Currently ...)" (asked 28 Oct: Cloud 9 and Satellite showed none).
NOW = {
    "Abstract Joker": lambda j, run: f"+{3 * len(run.jokers)} Mult",
    "Blue Joker": lambda j, run: f"+{2 * len(run.draw_pile if run.in_round else run.deck)} Chips",
    "Fortune Teller": lambda j, run: f"+{run.consumables_used['Tarot']} Mult",
    "Swashbuckler": lambda j, run: f"+{sum(run.sell_value(o) for o in run.jokers if o is not j)} Mult",
    "Driver's License": lambda j, run: f"{sum(c.enhancement is not None for c in run.deck)} enhanced cards of 16",
    "Joker Stencil": lambda j, run: f"X{max(1, run.joker_slots - sum(o.edition != 'Negative' for o in run.jokers) + sum(o.name == j.name for o in run.jokers))} Mult",
    "Steel Joker": lambda j, run: f"X{round(1 + sum(c.enhancement == 'Steel' for c in run.deck) / 5, 2):g} Mult",
    "Stone Joker": lambda j, run: f"+{25 * sum(c.is_stone for c in run.deck)} Chips",
    "Erosion": lambda j, run: f"+{4 * max(0, run.starting_deck_size - len(run.deck))} Mult",
    "Bull": lambda j, run: f"+{2 * max(0, run.money)} Chips",
    "Bootstraps": lambda j, run: f"+{2 * (max(0, run.money) // 5)} Mult",
    "Throwback": lambda j, run: f"X{1 + 0.25 * run.skips:g} Mult",
    "Cloud 9": lambda j, run: f"${sum(c.rank == 9 and not c.is_stone for c in run.deck)} a round",
    "Satellite": lambda j, run: f"${len(run.planets_used)} a round",
    "Rocket": lambda j, run: f"${j.dollars} a round",
    "Invisible Joker": lambda j, run: f"{min(j.rounds, 2)}/2 rounds",
    "Loyalty Card": _loyalty,
    "Seltzer": lambda j, run: f"{j.hands} hands left",
    "Turtle Bean": lambda j, run: f"+{j.hand_size_bonus} hand size",
}


def joker_now(j, run=None) -> str:
    """What a joker has built up, or aims at, right now (the game's "(Currently ...)" line); "" if nothing. With the
    run, also what one whose effect reads the run comes to (NOW)."""
    parts = [NOW[j.name](j, run)] if run is not None and j.name in NOW else []
    own = vars(j)
    for attr, fmt in (("chips", "+{} Chips"), ("mult", "+{} Mult"), ("xmult", "X{} Mult")):
        v = own.get(attr)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            parts.append(fmt.format(f"{round(v, 2):g}"))
    if getattr(j, "gives", None) and isinstance(own.get("value"), (int, float)):
        parts.append(f"+{j.value} {'Chips' if j.gives == 'chips' else 'Mult'}")
    rank, suit = own.get("rank"), own.get("suit")
    if rank is not None or suit is not None:
        parts.append(" of ".join(str(x) for x in (RANK_NAMES.get(rank, rank), suit) if x is not None))
    if own.get("target") is not None:
        parts.append(str(own["target"]))
    return ", ".join(parts)
