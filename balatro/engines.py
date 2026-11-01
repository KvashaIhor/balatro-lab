"""The build plan's engines (docs/superpowers/specs/2026-10-29-build-planning-layer-design.md): what each needs, how far
a run is toward it, the changes it can expect over the next antes (at the shops' odds, never the seed's future), and how
it plays. Strategies (held, flush) win rounds; tools (DNA) shape the deck toward whichever strategy is main, through its
key card. The value bot (strategy.py) chooses and values plans; this module knows only what it is passed."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .bots import copy_fires
from .items import CONSUMABLES
from .jokers import CATALOG
from .pool import PACK_ONLY, taken
from .shop import PACK_WEIGHTS, PACKS

RARITY_SHARE = {"Common": 0.7, "Uncommon": 0.25, "Rare": 0.05}     # data/shop.json joker_generation
SHOPS_AN_ANTE = 3
PACK_KIND = {"Tarot": "Arcana", "Planet": "Celestial", "Spectral": "Spectral"}


def shops_ahead(run, antes: int) -> int:
    """The shops in the next `antes` antes, none past the run's last boss."""
    return max(0, min(antes, run.max_ante + 1 - run.ante)) * SHOPS_AN_ANTE


def cards_seen(run, shops: int) -> float:
    """Shop cards seen over `shops` shops: the card slots, and 2 more a reroll at the run's own rate so far."""
    return shops * (run.shop_card_slots + 2 * run.rerolls_done / max(1, run.shops_seen))


def joker_chance(run, names, cards: float, buffoon: float = 0.0) -> float:
    """The chance one of the jokers `names` (not owned or on offer, able to appear: spawn conditions such as Steel
    Joker's Steel cards) is among `cards` shop cards or `buffoon` Buffoon pack cards: each shop card a joker at the
    slots' odds (a Buffoon card always), of its rarity at the rarity's share, then any of that rarity's jokers able to
    come."""
    weights = run.shop_weights()
    share = weights["Joker"] / sum(weights.values())
    gone = taken(run)
    live = {n: c for n, c in CATALOG.items() if n not in gone and c.can_spawn(run)}
    q = 0.0                                          # a joker card being one of them
    for n in names:
        cls = live.get(n)
        if cls is not None:
            q += RARITY_SHARE.get(cls.rarity, 0.0) / sum(1 for c in live.values() if c.rarity == cls.rarity)
    q = min(q, 1.0)
    return 1 - (1 - share * q) ** cards * (1 - q) ** buffoon


def pack_cards_seen(kind: str, shops: int) -> float:
    """Cards of a pack kind ("Arcana", "Celestial", "Spectral", "Standard", "Buffoon") seen over `shops` shops, opening
    one pack a shop as the packs come (their weights)."""
    per = sum(w * p.shown for p, w in zip(PACKS.values(), PACK_WEIGHTS) if p.kind == kind) / sum(PACK_WEIGHTS)
    return shops * per


def consumable_expected(run, name: str, shops: int) -> float:
    """How many of consumable `name` the run can expect to come by over `shops` shops: its share of the shop's slots of
    its kind (cards_seen) and of the packs of its kind (pack_cards_seen)."""
    cls = CONSUMABLES[name]
    gone = taken(run) | PACK_ONLY
    if name in gone or not cls.can_spawn(run):
        return 0.0
    pool = sum(1 for n, c in CONSUMABLES.items() if c.kind == cls.kind and n not in gone and c.can_spawn(run))
    weights = run.shop_weights()
    slots = cards_seen(run, shops) * weights.get(cls.kind, 0) / sum(weights.values())
    return (slots + pack_cards_seen(PACK_KIND[cls.kind], shops)) / max(1, pool)


def expected_changes(trial, expected: float, apply_one) -> list:
    """Makes the whole number of an expected count of changes on `trial` (`apply_one(trial)` makes one, False when no
    card takes it); returns the fraction left as [(fraction, apply_one)], nothing once no card takes the change."""
    whole = int(expected)
    for _ in range(whole):
        if not apply_one(trial):
            return []
    rest = expected - whole
    return [(rest, apply_one)] if rest > 0.01 else []


@dataclass(frozen=True)
class Engine:
    """A strategy (what wins rounds: scored, and the plan's main engine is one) or a tool (DNA: shapes the deck toward
    whichever strategy is main, worth only what it adds to it; never scored, never the main engine). Spec section 5."""
    name: str
    stage: str                     # when its changes are projected: "cards", "levels" or "copies" (spec 4.2's order)
    fits: frozenset                # the strategies it combines with (a tool fits every one)
    required: tuple                # an any-of group: the engine needs one of these jokers (empty: none)
    support: tuple                 # jokers that add to it, not needed
    consumables: tuple             # the consumables that make its cards (their uses and keeps get plan worth)
    progress: Callable             # (run) -> 0..1: what the run has added toward it, not what every deck starts with
    project: Callable              # (run, trial, shops, key) -> the fractions left: the whole changes made on `trial`;
                                   # `key`: the main strategy's key card (a tool's target), None for a strategy's own
    holds: Callable = field(default=lambda run, c: False)            # a card it keeps in hand
    prefers: Callable = field(default=lambda run, name, c: False)    # a card it wants consumable `name` used on
    kind: str = "strategy"                                           # or "tool"
    key: Callable = field(default=lambda trial: None)                # (trial) -> the card a tool should copy, or None

    def owned(self, run) -> bool:
        return not self.required or any(j.name in self.required for j in run.jokers)

    def pieces(self) -> set:
        return set(self.required) | set(self.support)


def _king(c) -> bool:
    return c.rank == 13 and not c.is_stone


def _first(trial, wants, change) -> bool:
    """`change` made on the first card of the deck that each of `wants` in turn accepts; False when none does."""
    for want in wants:
        for c in trial.deck:
            if want(c):
                change(c)
                return True
    return False


# ---- held Steel / Kings (spec 5.1) --------------------------------------------------------------------------
HELD_GROUP = ("Baron", "Mime", "Shoot the Moon", "Steel Joker")


def _held_progress(run) -> float:
    """Half for the group owned; half for the engine cards the run has made against 4: Steel cards, a Steel King once
    more, Red Seal Kings. Plain Kings don't count: every deck starts with them (they made a third of it in every run)."""
    group = 0.5 if any(j.name in HELD_GROUP for j in run.jokers) else 0.0
    steel = lambda c: c.enhancement == "Steel"                                    # noqa: E731
    cards = sum(steel(c) + (steel(c) and _king(c)) + (c.seal == "Red" and _king(c)) for c in run.deck)
    return group + 0.5 * min(1.0, cards / 4)


def _held_key(trial):
    """The card a tool copies for the held engine: a Steel Red Seal King, then a Steel King, then a Red Seal King or
    a Steel card, then a King; None without a Steel card or a King."""
    def score(c):
        steel = c.enhancement == "Steel"
        return 2 * (steel and _king(c)) + steel + _king(c) + 0.5 * (c.seal == "Red")
    best = max((c for c in trial.deck if not c.is_stone), key=lambda c: (score(c), c.uid), default=None)
    return best if best is not None and score(best) >= 1 else None


def _steel(trial) -> bool:
    """The Chariot as the held engine uses it: on a King, else a Queen (Strength's way to a King), else any card."""
    plain = lambda c: c.enhancement is None and not c.is_stone                # noqa: E731
    return _first(trial, (lambda c: plain(c) and _king(c), lambda c: plain(c) and c.rank == 12, plain),
                  lambda c: setattr(c, "enhancement", "Steel"))


def _red_seal(trial) -> bool:
    """Deja Vu as the held engine uses it: a Red Seal on a Steel King, else a King, else a Steel card."""
    free = lambda c: c.seal is None                                             # noqa: E731
    return _first(trial, (lambda c: free(c) and _king(c) and c.enhancement == "Steel", lambda c: free(c) and _king(c),
                          lambda c: free(c) and c.enhancement == "Steel"), lambda c: setattr(c, "seal", "Red"))


def _held_project(run, trial, shops, key=None) -> list:
    return (expected_changes(trial, consumable_expected(run, "The Chariot", shops), _steel)
            + expected_changes(trial, consumable_expected(run, "Deja Vu", shops), _red_seal))


def _held_holds(run, c) -> bool:
    names = {j.name for j in run.active_jokers()}
    return c.enhancement == "Steel" or (_king(c) and "Baron" in names) or (c.rank == 12 and "Shoot the Moon" in names)


def _held_prefers(run, name, c) -> bool:
    if name == "The Chariot":
        return _king(c) and c.enhancement is None
    if name == "Deja Vu":
        return _king(c) and c.seal is None
    return name == "Strength" and c.rank == 12


HELD = Engine("held", "cards", frozenset({"levels"}), HELD_GROUP,
              ("Blueprint", "Brainstorm", "Juggler", "Turtle Bean", "Raised Fist"),
              ("The Chariot", "Strength", "Deja Vu"), _held_progress, _held_project, _held_holds, _held_prefers,
              key=_held_key)


# ---- Flush (spec 5.4) -------------------------------------------------------------------------------------------
SUIT_JOKERS = {"Greedy Joker": "Diamonds", "Lusty Joker": "Hearts", "Wrathful Joker": "Spades",
               "Gluttonous Joker": "Clubs", "Rough Gem": "Diamonds", "Bloodstone": "Hearts", "Arrowhead": "Spades",
               "Onyx Agate": "Clubs"}
FLUSH_GROUP = tuple(SUIT_JOKERS) + ("The Tribe", "Droll Joker", "Crafty Joker")
SUIT_TAROTS = {"Diamonds": "The Star", "Clubs": "The Moon", "Hearts": "The Sun", "Spades": "The World"}
SUIT_ORDER = ("Spades", "Hearts", "Clubs", "Diamonds")


def flush_suit(run) -> str:
    """The flush engine's suit: that of the first suit joker owned, else the deck's most common (Wild cards and Stone
    cards aside; a tie by the deck's suit order)."""
    for j in run.jokers:
        if j.name in SUIT_JOKERS:
            return SUIT_JOKERS[j.name]
    counts = {s: 0 for s in SUIT_ORDER}
    for c in run.deck:
        if not c.is_stone and c.enhancement != "Wild" and c.suit in counts:
            counts[c.suit] += 1
    return max(SUIT_ORDER, key=lambda s: counts[s])


def _suited(c, suit) -> bool:
    return not c.is_stone and (c.suit == suit or c.enhancement == "Wild")


def _flush_progress(run) -> float:
    """Half for the group owned; half for the deck's share of its suit above the 25% every deck starts with, full at
    60%."""
    group = 0.5 if any(j.name in FLUSH_GROUP for j in run.jokers) else 0.0
    suit, cards = flush_suit(run), [c for c in run.deck if not c.is_stone]
    share = sum(_suited(c, suit) for c in cards) / max(1, len(cards))
    return group + 0.5 * min(1.0, max(0.0, share - 0.25) / 0.35)


def _off_suit(trial, suit, plain_only=False) -> list:
    """The deck's cards off the suit, plain ones first, then low ranks first (by the card, never the draw pile's order)."""
    plain = lambda c: c.enhancement is None and c.seal is None and c.edition is None    # noqa: E731
    off = [c for c in trial.deck if not _suited(c, suit) and not c.is_stone and (plain(c) or not plain_only)]
    return sorted(off, key=lambda c: (not plain(c), c.rank, c.uid))


def _turn(trial, suit) -> bool:
    """The suit's Tarot on three off-suit cards."""
    cards = _off_suit(trial, suit)[:3]
    for c in cards:
        c.suit = suit
    return bool(cards)


def _hang(trial, suit) -> bool:
    """The Hanged Man on two plain off-suit cards."""
    cards = _off_suit(trial, suit, plain_only=True)[:2]
    if cards:
        trial.destroy_cards(cards)
    return bool(cards)


# one function a suit, made once: the bot remembers a projected change's worth by its function (_one_change)
TURN = {s: (lambda t, s=s: _turn(t, s)) for s in SUIT_ORDER}
HANG = {s: (lambda t, s=s: _hang(t, s)) for s in SUIT_ORDER}


def _flush_project(run, trial, shops, key=None) -> list:
    """The suit's Tarot over the horizon on three off-suit cards each, and The Hanged Man on two plain off-suit ones."""
    suit = flush_suit(run)
    return (expected_changes(trial, consumable_expected(run, SUIT_TAROTS[suit], shops), TURN[suit])
            + expected_changes(trial, consumable_expected(run, "The Hanged Man", shops), HANG[suit]))


def _flush_prefers(run, name, c) -> bool:
    """The suit's Tarot on an off-suit card; The Hanged Man on a plain off-suit one."""
    suit = flush_suit(run)
    if name == SUIT_TAROTS[suit]:
        return not _suited(c, suit) and not c.is_stone
    if name == "The Hanged Man":
        return not _suited(c, suit) and not c.is_stone and c.enhancement is None and c.seal is None and c.edition is None
    return False


def _flush_key(trial):
    """The card a tool copies for the flush engine: the best card of its suit (enhanced, sealed, with an edition, then
    high)."""
    suit = flush_suit(trial)
    return max((c for c in trial.deck if _suited(c, suit)), default=None,
               key=lambda c: ((c.enhancement is not None) + (c.seal is not None) + (c.edition is not None), c.rank, c.uid))


FLUSH = Engine("flush", "cards", frozenset(), FLUSH_GROUP, ("Smeared Joker", "Four Fingers"),
               tuple(SUIT_TAROTS.values()) + ("The Hanged Man",), _flush_progress, _flush_project,
               prefers=_flush_prefers, key=_flush_key)


# ---- DNA / one-card (spec 5.2): a tool ---------------------------------------------------------------------------
def _dna_progress(run) -> float:
    return 1.0 if any(j.name == "DNA" for j in run.jokers) else 0.0


def _dna_project(run, trial, shops, key=None) -> list:
    """The main strategy's key card copied once a round for each time DNA fires (copy_fires: DNA and the copiers that
    reach it); nothing without one."""
    fires = sum(n for j, n in zip(trial.jokers, copy_fires(trial.jokers)) if j.name == "DNA")
    best = key(trial) if key is not None else None
    if fires and best is not None:
        trial.add_cards([trial.copy_card(best) for _ in range(fires * shops)])
    return []


DNA = Engine("dna", "copies", frozenset({"held", "levels", "flush"}), ("DNA",), ("Blueprint", "Brainstorm", "Hanging Chad"),
             (), _dna_progress, _dna_project, kind="tool")

ENGINES = {e.name: e for e in (HELD, FLUSH, DNA)}
