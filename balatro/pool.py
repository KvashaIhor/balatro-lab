"""What can appear, with the game's odds and rules: jokers (rarity roll, no duplicates without Showman,
spawn conditions, editions, stake stickers), consumables, playing cards, vouchers, skip tags and boss
blinds. Sources: data/shop.json, data/modifiers.json, data/stakes.json, data/bosses.json, data/tags.json."""
from __future__ import annotations

import random

from .cards import ENHANCEMENTS, RANKS, SEALS, SUITS, Card
from .items import BOSSES, CONSUMABLES, TAGS, Boss, Tag, entries, make
from .jokers import CATALOG

FALLBACK = {"Joker": "Joker", "Tarot": "Strength", "Planet": "Pluto", "Spectral": "Incantation"}
PACK_ONLY = {"The Soul", "Black Hole"}  # never in the shop or from effects that create consumables
GUARANTEED_EDITION = (("Polychrome", 0.15), ("Holographic", 0.35), ("Foil", 0.5))  # Aura, Wheel of Fortune, Illusion


def roll_rarity(rng: random.Random) -> str:
    r = rng.random()
    return "Rare" if r > 0.95 else "Uncommon" if r > 0.7 else "Common"


def roll_edition(rng: random.Random, rate: float = 1, scale: float = 1, negative: bool = True) -> str | None:
    """One roll: jokers use scale 1 with Negative, Standard-pack cards scale 2 without it. `rate` is
    the edition rate from Hone (2) or Glow Up (4); it doesn't change the Negative chance."""
    r = rng.random()
    if negative and r > 1 - 0.003:
        return "Negative"
    for edition, threshold in (("Polychrome", 0.006), ("Holographic", 0.02), ("Foil", 0.04)):
        if r > 1 - threshold * rate * scale:
            return edition
    return None


def pick_edition(rng: random.Random) -> str:
    """A guaranteed edition, never Negative."""
    r, acc = rng.random(), 0.0
    for edition, p in GUARANTEED_EDITION:
        acc += p
        if r < acc:
            return edition
    return "Foil"


def taken(run, shown=()) -> set[str]:
    """Names that can't appear again: owned jokers and consumables plus what is already on offer."""
    if run.showman:
        return set()
    return {j.name for j in run.jokers} | {c.name for c in run.consumables} | set(shown)


def random_joker(run, rng: random.Random, rarity: str | None = None, shown=(), stickers: bool = False):
    rarity = rarity or roll_rarity(rng)
    gone = taken(run, shown)
    pool = sorted((cls for name, cls in CATALOG.items() if cls.rarity == rarity and name not in gone and cls.can_spawn(run)),
                  key=lambda cls: cls.number)
    j = (rng.choice(pool) if pool else CATALOG[FALLBACK["Joker"]])()
    j.edition = roll_edition(rng, run.edition_rate)
    if stickers:
        roll_stickers(run, j, rng)
    return j


def roll_stickers(run, j, rng: random.Random) -> None:
    """Stake stickers, for shop and Buffoon-pack jokers only: one roll for Eternal (>0.7) or Perishable
    (0.4-0.7), a separate roll for Rental (>0.7)."""
    rules = run.stake_rules
    if rules["eternal_chance"] or rules["perishable_chance"]:
        r = rng.random()
        if rules["eternal_chance"] and r > 0.7 and j.eternal_ok:
            j.eternal = True
        elif rules["perishable_chance"] and 0.4 < r <= 0.7 and j.perishable_ok:
            j.perishable = True
    if rules["rental_chance"] and rng.random() > 0.7:
        j.rental = True


def random_consumable(run, kind: str, rng: random.Random, shown=()):
    """A Tarot, Planet or Spectral card of `kind`, or None while that kind has no cards in code yet."""
    gone = taken(run, shown) | PACK_ONLY
    pool = sorted((cls for name, cls in CONSUMABLES.items() if cls.kind == kind and name not in gone and cls.can_spawn(run)),
                  key=lambda cls: cls.number)
    cls = rng.choice(pool) if pool else CONSUMABLES.get(FALLBACK[kind])
    return cls() if cls else None


def planet_for(hand: str):
    """The Planet card class that levels up `hand`."""
    return next((cls for cls in CONSUMABLES.values() if cls.kind == "Planet" and cls.hand == hand), None)


def random_playing_card(run, rng: random.Random, enhanced: float = 0.0, sealed: float = 0.0,
                        edition_scale: float = 0.0, illusion: bool = False) -> Card:
    """A random rank and suit; Standard packs: 40% enhanced, 20% sealed, editions at 2x rate. Illusion
    shop cards: 40% enhanced, 20% a guaranteed edition, no seal."""
    card = Card(rng.choice(RANKS), rng.choice(SUITS))
    if enhanced and rng.random() < enhanced:
        card.enhancement = rng.choice(ENHANCEMENTS)
    if illusion:
        if rng.random() < 0.2:
            card.edition = pick_edition(rng)
    elif edition_scale:
        card.edition = roll_edition(rng, run.edition_rate, scale=edition_scale, negative=False)
    if sealed and rng.random() < sealed:
        card.seal = rng.choice(SEALS)
    return card


def random_voucher(run, rng: random.Random, shown=()) -> str:
    """A voucher not yet redeemed whose prerequisite is; Blank when none is left."""
    pool = [v["name"] for v in entries("voucher")
            if v["name"] not in run.vouchers and v["name"] not in shown and (not v["requires"] or v["requires"] in run.vouchers)]
    return rng.choice(pool) if pool else "Blank"


def random_tag(run, rng: random.Random) -> Tag:
    pool = [t["name"] for t in entries("tag") if t["min_ante"] <= max(1, run.ante)]
    t = make(TAGS, Tag, rng.choice(pool))
    t.setup(run)
    return t


def random_boss(run, rng: random.Random) -> Boss:
    """Showdown bosses on antes 8, 16, ...; otherwise a regular boss whose minimum ante is reached.
    Only the bosses used least so far this run can come up, so none repeats before all have appeared."""
    showdown = run.ante >= 8 and run.ante % 8 == 0
    eligible = [b["name"] for b in entries("boss")
                if b["showdown"] == showdown and (showdown or b["min_ante"] <= max(1, run.ante))]
    fewest = min(run.boss_used[b] for b in eligible)
    name = rng.choice([b for b in eligible if run.boss_used[b] == fewest])
    run.boss_used[name] += 1
    return make(BOSSES, Boss, name)
