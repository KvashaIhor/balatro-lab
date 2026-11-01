"""Poker hand detection: which hand a set of played cards makes, which of them score, and which smaller
hands it contains (jokers like Jolly Joker check "contains a Pair", which Full House also satisfies).

Rule changes from jokers arrive as flags: Four Fingers (flushes and straights of 4), Shortcut (straights
may skip one rank), Smeared Joker (red suits are one suit, black suits are one suit), Splash (every
played card scores). Wild cards count as every suit; Stone cards have no rank or suit but always score.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .cards import SUITS, Card

# Best first. Base chips / mult per level live in data/hands.json and run.py.
HAND_ORDER = ("Flush Five", "Flush House", "Five of a Kind", "Straight Flush", "Four of a Kind", "Full House",
              "Flush", "Straight", "Three of a Kind", "Two Pair", "Pair", "High Card")


@dataclass(frozen=True)
class Rules:
    four_fingers: bool = False
    shortcut: bool = False
    smeared: bool = False
    splash: bool = False


@dataclass
class HandResult:
    name: str
    scoring: list[int]  # indexes into the played cards, in played order
    contains: frozenset[str]


def _flush_cards(cards: list[tuple[int, Card]], need: int, rules: Rules) -> list[int] | None:
    best = None
    for suit in SUITS:
        idx = [i for i, c in cards if c.has_suit(suit, rules.smeared)]
        if len(idx) >= need and (best is None or len(idx) > len(best)):
            best = idx
    return best


def _straight_cards(cards: list[tuple[int, Card]], need: int, rules: Rules) -> list[int] | None:
    """Indexes of `need` or more cards with distinct ranks forming a straight (Ace high or low)."""
    by_rank: dict[int, int] = {}
    for i, c in cards:
        by_rank.setdefault(c.rank, i)
        if c.rank == 14:
            by_rank.setdefault(1, i)  # Ace low
    ranks = sorted(by_rank)
    max_gap = 2 if rules.shortcut else 1
    best: list[int] = []
    for size in (5, 4) if need == 4 else (5,):
        for combo in combinations(ranks, size):
            if all(0 < b - a <= max_gap for a, b in zip(combo, combo[1:])):
                idx = sorted({by_rank[r] for r in combo})
                if len(idx) == size and len(idx) > len(best):
                    best = idx
        if best:
            return best
    return None


_CACHE: dict = {}


def evaluate_cached(played: list[Card], rules: Rules = Rules()) -> HandResult:
    """evaluate(), remembered: the result depends only on each card's rank, suit and enhancement (in order)
    and the rules, and bots ask about the same cards over and over. Callers must not change the result."""
    key = (rules, tuple((c.rank, c.suit, c.enhancement) for c in played))
    r = _CACHE.get(key)
    if r is None:
        if len(_CACHE) > 500_000:
            _CACHE.clear()
        r = _CACHE[key] = evaluate(played, rules)
    return r


def evaluate(played: list[Card], rules: Rules = Rules()) -> HandResult:
    ranked = [(i, c) for i, c in enumerate(played) if not c.is_stone]
    stones = [i for i, c in enumerate(played) if c.is_stone]
    need = 4 if rules.four_fingers else 5
    counts: dict[int, list[int]] = {}
    for i, c in ranked:
        counts.setdefault(c.rank, []).append(i)
    groups = sorted(counts.values(), key=lambda g: (-len(g), -played[g[0]].rank))
    sizes = [len(g) for g in groups]
    flush = _flush_cards(ranked, need, rules) if len(ranked) >= need else None
    straight = _straight_cards(ranked, need, rules) if len(ranked) >= need else None
    straight_flush = None
    if flush and straight:
        sf = _straight_cards([(i, played[i]) for i in flush], need, rules)
        straight_flush = sf

    contains = {"High Card"} if ranked else set()
    if sizes and sizes[0] >= 2:
        contains.add("Pair")
    if sizes and sizes[0] >= 3:
        contains.add("Three of a Kind")
    if sizes and sizes[0] >= 4:
        contains.add("Four of a Kind")
    if sizes and sizes[0] >= 5:
        contains.add("Five of a Kind")
    if len(sizes) >= 2 and sizes[1] >= 2:
        contains.add("Two Pair")
        if sizes[0] >= 3:
            contains.add("Full House")
    if flush:
        contains.add("Flush")
    if straight:
        contains.add("Straight")
    if straight_flush:
        contains.add("Straight Flush")
    all_flush = flush is not None and len(flush) == len(ranked) == 5
    if "Full House" in contains and all_flush:
        contains.add("Flush House")
    if "Five of a Kind" in contains and all_flush:
        contains.add("Flush Five")

    name = next(h for h in HAND_ORDER if h in contains) if contains else "High Card"
    if name in ("Flush Five", "Flush House", "Five of a Kind", "Full House"):
        scoring = [i for g in groups[:2] for i in g] if name in ("Flush House", "Full House") else groups[0]
    elif name == "Straight Flush":
        scoring = straight_flush
    elif name == "Four of a Kind":
        scoring = groups[0]
    elif name == "Flush":
        scoring = flush
    elif name == "Straight":
        scoring = straight
    elif name == "Three of a Kind":
        scoring = groups[0]
    elif name == "Two Pair":
        scoring = groups[0] + groups[1]
    elif name == "Pair":
        scoring = groups[0]
    else:
        scoring = [max((i for i, _ in ranked), key=lambda i: played[i].rank)] if ranked else []
    if rules.splash:
        scoring = list(range(len(played)))
    else:
        scoring = sorted(set(scoring) | set(stones))
    return HandResult(name, sorted(scoring), frozenset(contains))
