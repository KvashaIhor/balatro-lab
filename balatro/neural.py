"""A small neural network that corrects the value bot's worth of a joker, consumable, pack or voucher, given
the situation it is bought, taken or kept in.

The value bot already measures what an item adds to the hands the deck deals today (build power) and adds
fixed weights for what that can't show. What fixed weights can't do is depend on the build: a joker that grows
is worth more in some builds than in others, a planet kept is worth much more with Perkeo, a second +Mult
joker less once there is xMult. The network learns those corrections:

  context  84 facts, computed once per decision, card by card where it matters: ante, money, slots, the
           build's power, deck size, hand size; the deck's share of each suit, each rank (2 to Ace), each
           enhancement, each seal and each edition; the level of each of the 12 poker hands; and each of the 32
           vouchers held. Plus the jokers owned and the consumables held, each through its own learned
           8-number embedding (summed per kind), so it can learn what owning a particular joker or holding a
           particular planet does
  hidden   16 tanh units over that context
  output   each item (150 jokers, 52 consumables, 15 packs, 32 vouchers, and keeping a tarot, planet or
           spectral) has its own bias and 16 weights over the hidden units: correction = bias + weights . hidden,
           soft-clipped to +-1.5 power (a factor of about 4.5 in score either way)

The output weights start at zero, so an untrained network corrects nothing and the bot plays exactly like the
value bot; training (scripts/evolve_neural.py) learns only where the fixed valuation is off.
"""
from __future__ import annotations

import math

import numpy as np

from .items import data, entries
from .scoring import HAND_BASE
from .shop import PACKS

JOKERS = [j["name"] for j in sorted(data("jokers.json"), key=lambda j: j["n"])]
CONSUMABLES = [e["name"] for k in ("tarot", "planet", "spectral") for e in entries(k)]
ITEMS = ([("joker", n) for n in JOKERS] + [("tarot", e["name"]) for e in entries("tarot")]
         + [("planet", e["name"]) for e in entries("planet")] + [("spectral", e["name"]) for e in entries("spectral")]
         + [("pack", n) for n in PACKS] + [("voucher", e["name"]) for e in entries("voucher")]
         + [("keep", k) for k in ("Tarot", "Planet", "Spectral")])
ITEM_INDEX = {k: i for i, k in enumerate(ITEMS)}
JOKER_INDEX = {n: i for i, n in enumerate(JOKERS)}
CONSUMABLE_INDEX = {n: i for i, n in enumerate(CONSUMABLES)}
HANDS = list(HAND_BASE)
SUITS = ["Spades", "Hearts", "Clubs", "Diamonds"]
RANKS = list(range(2, 15))
RANK_NAMES = {11: "Jack", 12: "Queen", 13: "King", 14: "Ace"}
ENHANCEMENTS = ["Bonus", "Mult", "Wild", "Glass", "Steel", "Stone", "Gold", "Lucky"]
SEALS = ["Gold", "Red", "Blue", "Purple"]
EDITIONS = ["Foil", "Holographic", "Polychrome"]
VOUCHERS = [e["name"] for e in entries("voucher")]

# Plain-language names of the context facts, for the Evolution tab.
FACTS = (["ante / 16", "money / $50", "joker slots filled", "free joker slots / 5", "consumable slots filled",
          "build power / 10", "deck size / 52", "hand size / 8"] + [f"share of {s}" for s in SUITS]
         + [f"share of {RANK_NAMES.get(r, r)}s" for r in RANKS] + [f"share of {e} cards" for e in ENHANCEMENTS]
         + [f"share with a {s} seal" for s in SEALS] + [f"share that is {e}" for e in EDITIONS]
         + [f"{h} level" for h in HANDS] + [f"has {v}" for v in VOUCHERS])
N_FACTS = len(FACTS)
EMBED, HIDDEN = 8, 16
MAX_CORRECTION = 1.5
SHAPES = {"embed": (len(JOKERS), EMBED), "cembed": (len(CONSUMABLES), EMBED), "w1": (HIDDEN, N_FACTS + 2 * EMBED),
          "b1": (HIDDEN,), "out": (len(ITEMS), HIDDEN + 1)}
N_PARAMS = sum(math.prod(s) for s in SHAPES.values())


def facts(run, power: float) -> np.ndarray:
    """The context of a decision, scaled to about 0-1 (FACTS names each number)."""
    deck = run.deck
    n = max(1, len(deck))
    slots = max(1, run.joker_slots)
    held = sum(j.edition != "Negative" for j in run.jokers)
    f = [run.ante / 16, min(max(run.money, -20), 100) / 50, held / slots, max(0, slots - held) / 5,
         len(run.consumables) / max(1, run.consumable_slots), power / 10, len(deck) / 52, run.hand_size / 8]
    f += [sum(c.suit == s and not c.is_stone for c in deck) / n for s in SUITS]
    f += [sum(c.rank == r and not c.is_stone for c in deck) / n for r in RANKS]
    f += [sum(c.enhancement == e for c in deck) / n for e in ENHANCEMENTS]
    f += [sum(c.seal == s for c in deck) / n for s in SEALS]
    f += [sum(c.edition == e for c in deck) / n for e in EDITIONS]
    f += [(run.hand_levels[h] - 1) / 5 for h in HANDS]
    f += [float(v in run.vouchers) for v in VOUCHERS]
    return np.asarray(f, dtype=np.float64)


class Network:
    """The network's parameters as one flat vector (what training nudges) and as matrices (what plays)."""

    def __init__(self, params: np.ndarray):
        self.params = np.asarray(params, dtype=np.float64)
        k = 0
        for name, shape in SHAPES.items():
            size = math.prod(shape)
            setattr(self, name, self.params[k:k + size].reshape(shape))
            k += size

    @classmethod
    def initial(cls, seed: int = 0) -> "Network":
        """Random embeddings and hidden layer, zero output: corrects nothing until trained."""
        rng = np.random.default_rng(seed)
        parts = {"embed": rng.normal(0, 0.3, SHAPES["embed"]), "cembed": rng.normal(0, 0.3, SHAPES["cembed"]),
                 "w1": rng.normal(0, 1 / math.sqrt(N_FACTS + 2 * EMBED), SHAPES["w1"]),
                 "b1": np.zeros(SHAPES["b1"]), "out": np.zeros(SHAPES["out"])}
        return cls(np.concatenate([parts[n].ravel() for n in SHAPES]))

    def hidden(self, run, power: float) -> np.ndarray:
        owned = [JOKER_INDEX[j.name] for j in run.jokers if j.name in JOKER_INDEX]
        held = [CONSUMABLE_INDEX[c.name] for c in run.consumables if c.name in CONSUMABLE_INDEX]
        jokers = self.embed[owned].sum(axis=0) if owned else np.zeros(EMBED)
        consumables = self.cembed[held].sum(axis=0) if held else np.zeros(EMBED)
        h = np.tanh(self.w1 @ np.concatenate([facts(run, power), jokers, consumables]) + self.b1)
        return np.concatenate([[1.0], h])

    def correction(self, h: np.ndarray, key: tuple) -> float:
        i = ITEM_INDEX.get(key)
        if i is None:
            return 0.0
        raw = float(self.out[i] @ h)
        return MAX_CORRECTION * math.tanh(raw / MAX_CORRECTION)

    def learned(self) -> list[tuple[tuple, float]]:
        """Each item's bias (its correction in a neutral situation), largest first."""
        return sorted(((k, float(self.out[i, 0])) for k, i in ITEM_INDEX.items()), key=lambda t: -abs(t[1]))
