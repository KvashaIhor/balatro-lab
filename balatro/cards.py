"""Playing cards: rank, suit and the modifiers a card can carry (enhancement, edition, seal)."""
from __future__ import annotations

from dataclasses import dataclass, field

SUITS = ("Spades", "Hearts", "Clubs", "Diamonds")
RANKS = tuple(range(2, 15))  # 11 = Jack, 12 = Queen, 13 = King, 14 = Ace
RANK_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}
FACE_RANKS = (11, 12, 13)

ENHANCEMENTS = ("Bonus", "Mult", "Wild", "Glass", "Steel", "Stone", "Gold", "Lucky")
EDITIONS = ("Foil", "Holographic", "Polychrome", "Negative")
SEALS = ("Gold", "Red", "Blue", "Purple")


def rank_chips(rank: int) -> int:
    """Chips a card adds when it scores: number cards their value, faces 10, Ace 11."""
    return 11 if rank == 14 else min(rank, 10)


@dataclass
class Card:
    rank: int
    suit: str
    enhancement: str | None = None
    edition: str | None = None
    seal: str | None = None
    bonus_chips: int = 0  # permanent extra chips (Hiker)
    debuffed: bool = False  # set by boss blinds for the round
    face_down: bool = False  # hidden from the player (some boss blinds)
    uid: int = field(default=0, compare=False)

    @property
    def is_stone(self) -> bool:
        return self.enhancement == "Stone"

    def is_face(self, everything_is_face: bool = False) -> bool:
        """Jack, Queen or King; Pareidolia makes every card a face card. Stone cards have no rank."""
        return not self.is_stone and (everything_is_face or self.rank in FACE_RANKS)

    def has_suit(self, suit: str, smeared: bool = False) -> bool:
        """Wild cards are every suit; Stone cards are none; Smeared Joker pairs red and black suits."""
        if self.is_stone:
            return False
        if self.enhancement == "Wild":
            return True
        if smeared:
            red = ("Hearts", "Diamonds")
            return (self.suit in red) == (suit in red)
        return self.suit == suit

    def to_dict(self) -> dict:
        return {"rank": self.rank, "suit": self.suit, "enhancement": self.enhancement, "edition": self.edition,
                "seal": self.seal, "bonus_chips": self.bonus_chips, "debuffed": self.debuffed,
                "face_down": self.face_down, "label": self.label(), "uid": self.uid}

    def label(self) -> str:
        if self.is_stone:
            return "Stone"
        return f"{RANK_NAMES.get(self.rank, self.rank)}{self.suit[0]}"

    def __repr__(self) -> str:
        extras = [x for x in (self.enhancement, self.edition, self.seal and f"{self.seal} seal") if x]
        return self.label() + (f"[{', '.join(extras)}]" if extras else "")


def standard_deck(start_uid: int = 1) -> list[Card]:
    return [Card(rank, suit, uid=start_uid + i) for i, (suit, rank) in enumerate((s, r) for s in SUITS for r in RANKS)]
