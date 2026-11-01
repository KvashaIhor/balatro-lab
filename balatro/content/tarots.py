"""The 22 Tarot cards. Selection limits, enhancements, suits, caps and odds come from data/consumables.json
and data/modifiers.json; `spec` is the card's data entry.

Calls where the data is thin (checked on balatrowiki.org, 2026-10-25):
- Room: a card used from the consumable area frees its own slot first, so The Fool, The High Priestess and
  The Emperor can be used there with full slots (the game checks `self.area == G.consumeables`). Bought-and-
  used and pack cards need a free slot; a card that could create nothing is refused.
- The Fool records itself as the last card used, so a second Fool waits until another Tarot or Planet is
  used (wiki: "you cannot use The Fool again until you use a different card"). The run skips The Fool when
  it records `last_tarot_planet`, so The Fool's `use` sets it.
- Death copies every attribute of the right card onto the left one except its identity, the debuff
  included (wiki: converting into a debuffed card gives a debuffed card).
- Cards that act on the hand need one: a round in play, or the hand an Arcana or Spectral pack deals.
- During a round, changed cards get the boss's debuffs checked again (The Star turns a Club debuffed by
  The Club into a live Diamond).
- The Hermit and Temperance can always be used: The Hermit gives nothing in debt, Temperance counts
  debuffed jokers and gives $0 with none.
- The Wheel of Fortune's 1 in 4 is a listed probability (Oops! All 6s doubles it) and only picks among
  edition-less jokers, debuffed ones included; a miss still uses the card.
"""
from __future__ import annotations

from dataclasses import fields

from .. import pool
from ..cards import Card
from ..items import Consumable, consumable, data, info

ENHANCEMENTS = {e["key"]: e["name"].removesuffix(" Card") for e in data("modifiers.json")["enhancements"]}


def register(kind: str):
    """Register a consumable with its data entry as `spec` and its selection limits."""
    def decorate(cls):
        cls.spec = info(kind, cls.name)
        select = cls.spec.get("select")
        if select:
            cls.min_targets, cls.max_targets = select["min"], select["max"]
        return consumable(cls)
    return decorate


tarot = register("tarot")


def has_hand(run) -> bool:
    """Is there a hand to act on: a round in play, or the hand an Arcana or Spectral pack deals?"""
    if run.open_pack_state is not None:
        return run.open_pack_state.pack.kind in ("Arcana", "Spectral")
    # TODO(engine): run.hand keeps the last round's cards in the shop and in packs opened by tags; an empty
    # run.hand outside rounds and Arcana/Spectral packs (or a run.in_round flag) would replace this check
    return run.current_shop is None


def recheck_debuffs(run) -> None:
    """During a round, changed or new cards get the boss's debuffs."""
    # TODO(engine): apply_consumable / add_cards(to_hand=True) could refresh debuffs themselves
    if run.current_shop is None and run.open_pack_state is None:
        run.refresh_debuffs()


def consumable_room(run, card) -> bool:
    """Room for a new consumable once `card` is used (used from the consumable area, it frees its slot)."""
    return run.consumable_room() or (card in run.consumables and card.edition != "Negative")


def editionless_jokers(run) -> list:
    return [j for j in run.jokers if j.edition is None]


class OnCards(Consumable):
    """Acts on the selected cards in hand."""

    def can_use(self, run, targets):
        return super().can_use(run, targets) and has_hand(run)


class Enhance(OnCards):
    def use(self, run, targets):
        for c in targets:
            c.enhancement = ENHANCEMENTS[self.spec["enhancement"]]
        recheck_debuffs(run)


class ChangeSuit(OnCards):
    def use(self, run, targets):
        for c in targets:
            c.suit = self.spec["suit"]
        recheck_debuffs(run)


class CreateConsumables(Consumable):
    def can_use(self, run, targets):
        return super().can_use(run, targets) and consumable_room(run, self)

    def use(self, run, targets):
        source = {"The Emperor": "emp", "The High Priestess": "pri"}.get(self.name)
        for kind, n in self.spec["creates"].items():
            for _ in range(n):
                run.create_consumable(kind, source=source)


@tarot
class TheFool(Consumable):
    name = "The Fool"

    def can_use(self, run, targets):
        last = run.last_tarot_planet
        return super().can_use(run, targets) and last not in (None, self.name) and consumable_room(run, self)

    def use(self, run, targets):
        run.create_consumable(name=run.last_tarot_planet)
        run.last_tarot_planet = self.name


@tarot
class TheMagician(Enhance):
    name = "The Magician"


@tarot
class TheHighPriestess(CreateConsumables):
    name = "The High Priestess"


@tarot
class TheEmpress(Enhance):
    name = "The Empress"


@tarot
class TheEmperor(CreateConsumables):
    name = "The Emperor"


@tarot
class TheHierophant(Enhance):
    name = "The Hierophant"


@tarot
class TheLovers(Enhance):
    name = "The Lovers"


@tarot
class TheChariot(Enhance):
    name = "The Chariot"


@tarot
class Justice(Enhance):
    name = "Justice"


@tarot
class TheHermit(Consumable):
    name = "The Hermit"

    def use(self, run, targets):
        run.money += min(self.spec["dollars_cap"], max(0, run.money))


@tarot
class TheWheelOfFortune(Consumable):
    name = "The Wheel of Fortune"

    def can_use(self, run, targets):
        return super().can_use(run, targets) and bool(editionless_jokers(run))

    def use(self, run, targets):
        if run.chance(self.spec["odds"][1], "misc"):
            rng = run.rng["misc"]
            rng.choice(editionless_jokers(run)).edition = pool.pick_edition(rng)


@tarot
class Strength(OnCards):
    name = "Strength"

    def use(self, run, targets):
        for c in targets:
            c.rank = 2 if c.rank == 14 else c.rank + 1
        recheck_debuffs(run)


@tarot
class TheHangedMan(OnCards):
    name = "The Hanged Man"

    def use(self, run, targets):
        run.destroy_cards(targets)


@tarot
class Death(OnCards):
    name = "Death"

    def use(self, run, targets):
        left, right = targets  # in hand order
        for f in fields(Card):
            if f.name not in ("uid", "face_down"):
                setattr(left, f.name, getattr(right, f.name))


@tarot
class Temperance(Consumable):
    name = "Temperance"

    def use(self, run, targets):
        run.money += min(self.spec["dollars_cap"], sum(run.sell_value(j) for j in run.jokers))


@tarot
class TheDevil(Enhance):
    name = "The Devil"


@tarot
class TheTower(Enhance):
    name = "The Tower"


@tarot
class TheStar(ChangeSuit):
    name = "The Star"


@tarot
class TheMoon(ChangeSuit):
    name = "The Moon"


@tarot
class TheSun(ChangeSuit):
    name = "The Sun"


@tarot
class Judgement(Consumable):
    name = "Judgement"

    def can_use(self, run, targets):
        return super().can_use(run, targets) and run.joker_room()

    def use(self, run, targets):
        run.create_joker(source="jud")


@tarot
class TheWorld(ChangeSuit):
    name = "The World"
