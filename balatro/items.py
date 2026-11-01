"""Base classes and registries for everything in a run besides jokers and playing cards: consumables
(Tarot, Planet, Spectral), boss blinds, vouchers, tags and decks. Stakes need no code: the run reads
their rules from data/stakes.json.

Each kind has one base class whose methods are the moments the run calls it; content modules
(balatro/content/*.py) subclass them and register with a decorator, which fills costs and other numbers
from data/*.json. `info(kind, name)` returns an item's data entry.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .cards import Card

DATA = Path(__file__).resolve().parent.parent / "data"

CONSUMABLES: dict[str, type] = {}
BOSSES: dict[str, type] = {}
VOUCHERS: dict[str, type] = {}
TAGS: dict[str, type] = {}
DECKS: dict[str, type] = {}


@lru_cache(maxsize=None)
def data(file: str):
    return json.loads((DATA / file).read_text())


SECTIONS = {"tarot": ("consumables.json", "tarots"), "planet": ("consumables.json", "planets"),
            "spectral": ("consumables.json", "spectrals"), "boss": ("bosses.json", "bosses"),
            "voucher": ("vouchers.json", "vouchers"), "tag": ("tags.json", "tags"),
            "deck": ("decks.json", "decks"), "stake": ("stakes.json", "stakes")}


def entries(kind: str) -> list[dict]:
    file, key = SECTIONS[kind]
    return data(file)[key]


@lru_cache(maxsize=None)
def info(kind: str, name: str) -> dict:
    """The data entry for an item: kind is tarot, planet, spectral, boss, voucher, tag, deck or stake."""
    return next(e for e in entries(kind) if e["name"] == name)


def consumable(cls):
    d = next(e for k in ("tarot", "planet", "spectral") for e in entries(k) if e["name"] == cls.name)
    cls.number, cls.kind, cls.cost = d["number"], d["type"], d["cost"]
    if cls.kind == "Planet":
        cls.hand = d["hand"]
    CONSUMABLES[cls.name] = cls
    return cls


def _boss_numbers(cls):
    d = info("boss", cls.name)
    cls.min_ante, cls.chip_mult, cls.reward, cls.showdown = d["min_ante"], d["chip_mult"], d["reward"], d["showdown"]


def _voucher_numbers(cls):
    d = info("voucher", cls.name)
    cls.cost, cls.requires = d["cost"], d["requires"]


def _tag_numbers(cls):
    cls.min_ante = info("tag", cls.name)["min_ante"]


def boss(cls):
    _boss_numbers(cls)
    BOSSES[cls.name] = cls
    return cls


def voucher(cls):
    _voucher_numbers(cls)
    VOUCHERS[cls.name] = cls
    return cls


def tag(cls):
    _tag_numbers(cls)
    TAGS[cls.name] = cls
    return cls


def deck(cls):
    info("deck", cls.name)  # fails loudly on a misspelled name
    DECKS[cls.name] = cls
    return cls


def make(registry: dict, base: type, name: str):
    """An instance of the registered class for `name`, or of `base` with the data's numbers and no
    effect while that item has no code yet."""
    cls = registry.get(name)
    if cls is None:
        cls = type(name, (base,), {"name": name})
        {Boss: _boss_numbers, Voucher: _voucher_numbers, Tag: _tag_numbers}[base](cls)
    return cls()


# ---- consumables --------------------------------------------------------------------------------

class Consumable:
    """A Tarot, Planet or Spectral card. `use` gets the selected cards in hand (`targets`); cards that
    need no selection get an empty list. Creation effects respect free slots (the run checks room)."""
    name = "?"
    number = 0
    kind = "Tarot"  # Tarot, Planet or Spectral
    cost = 3
    min_targets = 0
    max_targets = 0

    def __init__(self, edition: str | None = None):
        self.edition = edition  # only Negative is possible (Perkeo, Negative Tag copies)
        self.extra_sell = 0  # Gift Card

    @classmethod
    def can_spawn(cls, run) -> bool:
        """Can it appear right now (secret Planets need their hand played this run)?"""
        return True

    def can_use(self, run, targets: list[Card]) -> bool:
        return self.min_targets <= len(targets) <= self.max_targets

    def use(self, run, targets: list[Card]) -> None:
        raise NotImplementedError(self.name)

    def __repr__(self) -> str:
        return self.name + (" (Negative)" if self.edition == "Negative" else "")


class Planet(Consumable):
    """Levels up one poker hand. Content only needs to set `name`; `hand` comes from the data."""
    kind, cost, hand = "Planet", 3, "?"

    @classmethod
    def can_spawn(cls, run) -> bool:
        return not info("planet", cls.name)["secret"] or run.hand_plays[cls.hand] > 0

    def use(self, run, targets):
        run.level_up(self.hand, 1)


# ---- boss blinds --------------------------------------------------------------------------------

class Boss:
    """A boss blind's effect. The run calls each hook at its moment while the boss is active; once
    disabled (Chicot, Luchador) it is skipped, and `on_disable` undoes lasting changes. The run resets
    hands, discards, hand size, debuffs, face-down cards and disabled jokers when the round ends."""
    name = "?"
    min_ante = 1
    chip_mult = 2.0
    reward = 5
    showdown = False

    def __init__(self):
        self.disabled = False
        self.triggered = False  # set when its ability affected a hand this round (Matador)

    def on_select(self, run) -> None:
        """Blind selected, before the first draw: change hands, discards, hand size, jokers
        (The Needle, The Water, The Manacle, Amber Acorn)."""

    def on_disable(self, run) -> None:
        """Undo what on_select changed when the boss gets disabled mid-round."""

    def debuffs(self, run, card: Card) -> bool:
        """Is this playing card debuffed this round (The Goad, The Head, The Club, The Window, The Plant, The Pillar, Verdant Leaf)?"""
        return False

    def face_down(self, run, card: Card, when: str) -> bool:
        """Is this card drawn face down? `when` is "start" (first hand of the round), "play" or "discard"
        (The Wheel, The House, The Mark, The Fish)."""
        return False

    def draw_count(self, run, default: int, when: str) -> int:
        """How many cards to draw after a play or discard (`when`); The Serpent draws exactly 3."""
        return default

    def after_draw(self, run) -> None:
        """Cards were drawn (Cerulean Bell picks the card it forces)."""

    def press_play(self, run, played: list[Card]) -> None:
        """Play pressed, before scoring (The Hook discards 2 held cards, The Tooth takes $1 per card)."""

    def allows(self, run, result, played: list[Card]) -> bool:
        """False makes the hand score nothing (The Psychic, The Mouth, The Eye). A pure check: bots call it
        to estimate, and the run's hand counters (round_hand_types) don't include this hand yet."""
        return True

    def before_score(self, run, result) -> None:
        """After the hand is allowed, before jokers' on-played effects (The Arm, The Ox)."""

    def money_when_scored(self, run, result, played: list[Card]) -> int:
        """The money this hand would be scored with, after press_play and before_score take theirs (The Tooth,
        The Ox): what Bull and Bootstraps see. A pure check, for bots' estimates."""
        return run.money

    def modify_base(self, ctx, score) -> None:
        """Change base chips and mult (The Flint). Also runs when a bot estimates a hand, so no other changes."""

    def after_hand(self, run) -> None:
        """After a hand has scored (Crimson Heart re-picks a disabled joker)."""

    def forced_selection(self, run) -> int | None:
        """Index in hand of a card that must be part of any play or discard (Cerulean Bell)."""
        return None

    def on_sell(self, run, item) -> None:
        """A joker or consumable was sold (Verdant Leaf ends when a joker is sold)."""


# ---- vouchers, tags, decks ----------------------------------------------------------------------

class Voucher:
    """Bought once per run. `apply` makes its permanent change; vouchers the run checks by name
    (Telescope, Omen Globe, Director's Cut, ...) keep the default."""
    name = "?"
    cost = 10
    requires: str | None = None

    def apply(self, run) -> None:
        pass


class Tag:
    """A skip reward. `on_gain` fires when the tag is taken (True means it's used up at once); otherwise
    the run keeps it and offers it each later moment until a hook returns True (used up)."""
    name = "?"
    min_ante = 1

    def setup(self, run) -> None:
        """The tag was rolled for a blind (Orbital Tag picks its hand here)."""

    def on_gain(self, run) -> bool:
        return False

    def on_blind_select(self, run, blind) -> bool:
        return False

    def on_shop_open(self, run, shop) -> bool:
        return False

    def on_shop_offer(self, run, shop, offer) -> bool:
        """A joker was put on sale (initial stock or a reroll): edition tags change the first edition-less one."""
        return False

    def on_boss_defeated(self, run) -> bool:
        return False


class Deck:
    """A starting deck: `apply` sets up the run (cards, money, slots, vouchers, consumables)."""
    name = "?"

    def apply(self, run) -> None:
        pass
