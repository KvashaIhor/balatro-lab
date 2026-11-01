"""What a seeded run shows along one fixed path, ante by ante (the Seed Finder's projection): each ante's boss, skip
tags and voucher; each blind's deck order (the first hand, then the draws in order); each shop's cards and packs, with
the packs' contents.

It walks the Lab's own Run with the game's random streams (gameseed.py, exact for what it models), so it shows what
the bots see on that seed. The path: every blind played and beaten (no skips), nothing bought, no rerolls, the deck as
dealt, White Stake. Pack contents are drawn as if each shop's packs were opened in order: an earlier pack opened or
not changes what a later one holds. Standard packs and playing cards in the shop come from the Lab's own streams (the
game model doesn't cover them), and the deck order is the game's only for the 52-card decks the model knows (a deck
with other cards, such as the Abandoned Deck, deals in an order not checked against the game)."""
from __future__ import annotations

from .agent import Agent
from .cards import RANKS, SUITS, Card
from .jokers import Joker
from .run import Run
from .shop import Shop, cost_of, pack_cards

PATH = ("every blind played and beaten (no skips), nothing bought, no rerolls, the deck as dealt, White Stake; each "
        "shop's packs opened in order (opening one changes what the next holds)")
RANK_CODE = {10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}
STANDARD_52 = sorted((r, s) for r in RANKS for s in SUITS)


def card_code(c) -> str:
    """A playing card as the Seed Finder writes it: suit letter, then rank ("SK", "HT")."""
    return c.suit[0] + RANK_CODE.get(c.rank, str(c.rank))


def _card(c) -> dict:
    """A playing card offered or in a pack: its code and what it carries."""
    return {"type": "Playing card", "code": card_code(c), "name": card_code(c), "enhancement": c.enhancement,
            "edition": c.edition, "seal": c.seal, "exact": False}


def _item(item) -> dict:
    """A shop or pack card: a playing card (_card), else a joker or consumable by name and kind."""
    if isinstance(item, Card):
        return _card(item)
    return {"type": "Joker" if isinstance(item, Joker) else item.kind, "name": item.name,
            "edition": getattr(item, "edition", None), "exact": True}


def _shop(run) -> dict:
    """The shop after the blind just beaten: its cards in slot order, its voucher, and its two packs, each opened in
    turn (their contents)."""
    shop = Shop(run)
    run.shops_seen += 1
    cards = []
    for o in shop.cards:
        d = _item(o.item)
        d["price"] = cost_of(run, o)
        cards.append(d)
    packs = []
    for o in shop.packs:
        p = o.item
        inside = [_item(x) for x in pack_cards(run, p, run.rng["packs"])]
        packs.append({"name": p.name, "kind": p.kind, "price": cost_of(run, o), "choose": p.chosen,
                      "cards": inside, "exact": p.kind != "Standard"})
    return {"cards": cards, "voucher": shop.vouchers[0].name if shop.vouchers else None, "packs": packs}


def project(seed: str, deck: str = "Red Deck", antes: int = 4) -> dict:
    """The run of `seed` on `deck`, `antes` antes (1-8) along PATH: a dict of the path, what is exact, and per ante its
    boss, tags and voucher and its three blinds (target, first hand, the draws after it in order, the shop after it).
    Nothing outside the Run it makes is touched."""
    antes = max(1, min(8, int(antes)))
    run = Run(Agent(), game_seed=seed, deck=deck, stake="White Stake", max_ante=8)
    standard = len(run.deck) == 52 and sorted((c.rank, c.suit) for c in run.deck) == STANDARD_52
    out = {"seed": str(run.seed), "deck": deck, "stake": "White Stake", "antes_shown": antes, "path": PATH,
           "exact_deck_order": standard,
           "note": ("Boss, tags, vouchers, shop cards and packs follow the game's streams; Standard packs and shop "
                    "playing cards are the Lab's own." + ("" if standard else " This deck doesn't start with the 52 "
                    "standard cards: its deck order isn't checked against the game.")),
           "antes": []}
    for _ in range(antes):
        run.start_ante()
        ante = {"ante": run.ante, "boss": run.ante_boss.name, "tags": [t.name if t else None for t in run.ante_tags],
                "voucher": run.ante_voucher, "blinds": []}
        for kind in (0, 1, 2):
            run.blind = run.make_blind(kind)
            run.hand_size_delta = 0
            if run.active_boss:                       # its rule as the blind starts (The Manacle's hand size)
                run.active_boss.on_select(run)
            order = run.seedrng.shuffle(run, run.deck)[::-1]      # the game draws from the end of the pile
            n = min(run.hand_size, len(order))
            name = run.blind.boss.name if run.blind.boss is not None else run.blind.name
            blind = {"name": name, "kind": kind, "chips": run.blind.chips, "reward": run.blind.reward,
                     "hand": [card_code(c) for c in order[:n]], "draws": [card_code(c) for c in order[n:]]}
            run.hand_size_delta = 0
            if kind == 2:                             # the next ante starts as the boss falls: its shop belongs to it
                run.boss_defeated()
            blind["shop"] = _shop(run)
            ante["blinds"].append(blind)
        out["antes"].append(ante)
    return out
