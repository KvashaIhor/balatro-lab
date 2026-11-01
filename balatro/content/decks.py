"""The 15 starting decks. Each applies its `modifications` from data/decks.json (deltas to hands, discards,
money, slots and hand size; starting vouchers and consumables; money and shop rules); Abandoned,
Checkered and Erratic also replace the cards.

Judgement calls:
- Starting consumables are skipped while their card has no code (The Fool, Hex come from tarots.py and
  spectrals.py).
- Checkered turns Clubs into Spades and Diamonds into Hearts, as the game does: each rank twice per suit.
- Erratic draws each of the 52 cards uniformly from the 52 rank and suit pairs, so duplicates can occur
  (data/OPEN_QUESTIONS.md).
"""
from __future__ import annotations

from ..cards import FACE_RANKS, RANKS, SUITS, Card, standard_deck
from ..items import CONSUMABLES, Deck, deck, info

ADD = {"hands": "base_hands", "discards": "base_discards", "hand_size": "base_hand_size",
       "starting_money": "money", "joker_slots": "joker_slots", "consumable_slots": "consumable_slots"}
SET = {"money_per_remaining_hand": "money_per_hand", "money_per_remaining_discard": "money_per_discard",
       "interest": "interest_enabled", "shop_spectral_rate": "spectral_weight",
       "double_tag_after_boss": "double_tag_after_boss", "balance_chips_mult": "plasma", "ante_scaling": "blind_scale"}
CARDS = ("no_face_cards", "deck_size", "suits", "random_ranks_and_suits")  # read by the decks' cards()
HANDLED = set(ADD) | set(SET) | set(CARDS) | {"vouchers", "consumables"}


class _Deck(Deck):
    def apply(self, run):
        mods = info("deck", self.name)["modifications"]
        for key, attr in ADD.items():
            if key in mods:
                setattr(run, attr, getattr(run, attr) + mods[key])
        for key, attr in SET.items():
            if key in mods:
                setattr(run, attr, mods[key])
        for name in mods.get("vouchers", []):
            run.redeem_voucher(name)
        for name in mods.get("consumables", []):
            if name in CONSUMABLES:
                run.create_consumable(name=name)
        cards = self.cards(run)
        if cards is not None:
            run.set_deck(cards)

    def cards(self, run) -> list[Card] | None:
        """The starting cards, when not the standard 52."""
        return None


@deck
class RedDeck(_Deck):
    name = "Red Deck"


@deck
class BlueDeck(_Deck):
    name = "Blue Deck"


@deck
class YellowDeck(_Deck):
    name = "Yellow Deck"


@deck
class GreenDeck(_Deck):
    name = "Green Deck"


@deck
class BlackDeck(_Deck):
    name = "Black Deck"


@deck
class MagicDeck(_Deck):
    name = "Magic Deck"


@deck
class NebulaDeck(_Deck):
    name = "Nebula Deck"


@deck
class GhostDeck(_Deck):
    name = "Ghost Deck"


@deck
class AbandonedDeck(_Deck):
    name = "Abandoned Deck"

    def cards(self, run):
        return [c for c in standard_deck() if c.rank not in FACE_RANKS]


@deck
class CheckeredDeck(_Deck):
    name = "Checkered Deck"

    def cards(self, run):
        return [Card(c.rank, "Spades" if c.suit in ("Spades", "Clubs") else "Hearts") for c in standard_deck()]


@deck
class ZodiacDeck(_Deck):
    name = "Zodiac Deck"


@deck
class PaintedDeck(_Deck):
    name = "Painted Deck"


@deck
class AnaglyphDeck(_Deck):
    name = "Anaglyph Deck"


@deck
class PlasmaDeck(_Deck):
    name = "Plasma Deck"


@deck
class ErraticDeck(_Deck):
    name = "Erratic Deck"

    def cards(self, run):
        rng = run.rng["misc"]
        return [Card(rng.choice(RANKS), rng.choice(SUITS)) for _ in range(52)]
