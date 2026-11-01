"""The game's own randomness for a given seed, for the parts of a run modelled exactly.

seedfinder/opening.py reproduces Balatro's random streams (each purpose has its own key, so a stream
only advances when that kind of thing happens). Given a seed, these are exact:
  * the deck order at every blind (the deck is re-sorted by creation order, then shuffled with "nr<ante>");
  * the boss of every ante, the two skip tags and the shop voucher;
  * every shop card slot, rerolls included, booster packs and their contents (Standard packs excepted);
  * The Soul's Legendary joker.
Everything else (Lucky cards, Glass breaks, Wheel of Fortune, Misprint and other chances, Standard pack
cards, jokers created by other effects) uses the simulator's own random streams, seeded by the seed too,
so a plan is reproducible but those parts can differ from the game.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "seedfinder"))
import opening as game  # noqa: E402  (seedfinder/opening.py)

from .cards import RANKS, SUITS, Card  # noqa: E402
from .items import entries  # noqa: E402

EXACT = ["deck order at every blind", "bosses", "skip tags", "shop vouchers", "shop cards and rerolls",
         "booster packs and their contents (not Standard packs)", "jokers and cards created by Judgement, Riff-Raff, "
         "The Emperor, The High Priestess, Cartomancer, 8 Ball, Purple Seals and similar effects",
         "Lucky card and Glass card rolls"]
SIMULATED = ["other in-round chances (Misprint, Bloodstone, Business Card, Space Joker, ...)",
             "Wheel of Fortune, Aura, Sigil, Ouija and other spectral or tarot rolls", "Standard pack cards",
             "anything after the game and the simulator part ways (a rule the simulator gets wrong)"]

_SUIT = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}
_RANK = {11: "J", 12: "Q", 13: "K", 14: "A", 10: "T"}
# The game's creation order of the 52 starting cards (opening.DECK_ORDER) for our starting deck, whose
# uid k is SUITS[(k-1)//13], RANKS[(k-1)%13].
_START_SORT = {k + 1: game.DECK_ORDER.index(_SUIT[SUITS[k // 13]] + _RANK.get(RANKS[k % 13], str(RANKS[k % 13])))
               for k in range(52)}
_BOSSES = sorted(entries("boss"), key=lambda b: b["key"])   # pseudorandom_element sorts by key
_ENHANCED_FOR = {"Stone Joker": "Stone", "Steel Joker": "Steel", "Glass Joker": "Glass", "Golden Ticket": "Gold",
                 "Lucky Cat": "Lucky"}
_SECRET_HAND = {"Planet X": "Five of a Kind", "Ceres": "Flush House", "Eris": "Flush Five"}


class _Model(game.Run):
    """opening.Run with the pools that change during a run (gated jokers, secret planets, edition rate,
    shop rates) read from the simulator's state."""

    def __init__(self, seed: str):
        super().__init__(seed)
        self.gated: set = set()
        self.softlocked: set = set(game.SOFTLOCKED_PLANETS)
        self.edition_rate = 1.0
        self.rates = list(game.SHOP_RATES)

    def joker(self, append, ante, rarity=None):
        if rarity is None:
            r = self.rng.random(f"rarity{ante}{append}")
            rarity = 3 if r > 0.95 else 2 if r > 0.7 else 1
        pool = self.joker_pools[rarity]
        name = self.pick(f"Joker{rarity}{append}{ante}", pool, set(self.profile.locked_jokers) | self.gated | self.used)
        poll, rate = self.rng.random(f"edi{append}{ante}"), self.edition_rate
        edition = ("Negative" if poll > 0.997 else "Polychrome" if poll > 1 - 0.006 * rate
                   else "Holographic" if poll > 1 - 0.02 * rate else "Foil" if poll > 1 - 0.04 * rate else None)
        self.used.add(name)
        return {"type": "Joker", "name": name, "rarity": game.RARITY_NAME[rarity], "edition": edition}

    def consumable(self, kind, append, ante, soulable):
        """opening.Run.consumable, with secret planets unlocked once their hand is played."""
        forced = None
        if soulable:
            if kind in ("Tarot", "Spectral") and "The Soul" not in self.used:
                if self.rng.random(f"soul_{kind}{ante}") > 0.997:
                    forced = "The Soul"
            if kind in ("Planet", "Spectral") and "Black Hole" not in self.used:
                if self.rng.random(f"soul_{kind}{ante}") > 0.997:
                    forced = "Black Hole"
        if forced:
            name = forced
        elif kind == "Tarot":
            name = self.pick(f"Tarot{append}{ante}", game.TAROTS, self.used)
        elif kind == "Planet":
            name = self.pick(f"Planet{append}{ante}", game.PLANETS, self.softlocked | self.used)
        else:
            name = self.pick(f"Spectral{append}{ante}", game.SPECTRALS, {"The Soul", "Black Hole"} | self.used)
        self.used.add(name)
        return {"type": "Spectral" if forced else kind, "name": name}

    def shop_card(self, ante, tags=None):
        total = sum(w for _, w in self.rates)
        poll = self.rng.random(f"cdt{ante}") * total
        check, kind = 0.0, self.rates[-1][0]
        for name, w in self.rates:
            if check < poll <= check + w:
                kind = name
                break
            check += w
        if kind == "Joker":
            return self.joker("sho", ante)
        if kind == "Playing card":
            return {"type": "Playing card", "name": "(playing card)"}
        return self.consumable(kind, "sho", ante, soulable=False)


class SeedRNG:
    def __init__(self, seed: str):
        self.seed = game.normalize_seed(seed)
        self.model = _Model(self.seed)

    # ---- state the pools depend on -------------------------------------------------------------
    def sync(self, run, shown=()) -> None:
        """Cards that exist now (owned or on offer) can't be drawn again; gates follow the deck."""
        m = self.model
        m.used = {j.name for j in run.jokers} | {c.name for c in run.consumables} | set(shown)
        enh = {c.enhancement for c in run.deck}
        m.gated = {j for j, e in _ENHANCED_FOR.items() if e not in enh}
        # and each joker's own rule for appearing (the unseeded pools ask the same): an extinct Gros Michel never
        # comes back, Cavendish only comes after it
        from .jokers import CATALOG
        m.gated |= {name for name, cls in CATALOG.items() if not cls.can_spawn(run)}
        m.softlocked = {p for p, h in _SECRET_HAND.items() if not run.hand_plays[h]}
        m.edition_rate = run.edition_rate
        w = run.shop_weights()
        m.rates = [("Joker", w["Joker"]), ("Tarot", w["Tarot"]), ("Planet", w["Planet"])]
        if w.get("Playing card"):
            m.rates.append(("Playing card", w["Playing card"]))
        if w.get("Spectral"):
            m.rates.append(("Spectral", w["Spectral"]))
        m.vouchers_bought = set(run.vouchers)

    # ---- the blind select screen -----------------------------------------------------------------
    def boss(self, run) -> str:
        """get_new_boss: eligible bosses for the ante, least used first, chosen by key "boss"."""
        ante = max(1, run.ante)
        showdown = run.ante >= 2 and run.ante % 8 == 0
        pool = [b for b in _BOSSES if (b["showdown"] if showdown else not b["showdown"] and b["min_ante"] <= ante)]
        fewest = min(run.boss_used[b["name"]] for b in pool)
        pool = [b for b in pool if run.boss_used[b["name"]] == fewest]
        name = pool[self.model.rng.element_index("boss", len(pool))]["name"]
        run.boss_used[name] += 1
        return name

    def tag(self, run) -> str:
        return self.model.tag(run.ante)

    def voucher(self, run) -> str:
        self.sync(run)
        return self.model.voucher(run.ante)

    # ---- the deck -------------------------------------------------------------------------------
    @staticmethod
    def sort_id(card: Card) -> int:
        return _START_SORT[card.uid] if card.uid in _START_SORT else 52 + card.uid

    def shuffle(self, run, cards: list[Card]) -> list[Card]:
        """The draw pile for a blind: cards in creation order, Fisher-Yates with "nr<ante>"; the game
        draws from the end of the list, as the simulator does."""
        ordered = sorted(cards, key=self.sort_id)
        return self.model.rng.shuffle(f"nr{run.ante}", ordered)

    # ---- shop -----------------------------------------------------------------------------------
    def shop_card(self, run, shown) -> dict:
        self.sync(run, shown)
        return self.model.shop_card(run.ante)

    def tag_joker(self, run, rarity: str, shown) -> dict:
        """Uncommon / Rare Tag: the shop's first slot is that rarity's joker (keys "uta" / "rta")."""
        self.sync(run, shown)
        return self.model.joker("rta" if rarity == "Rare" else "uta", run.ante, rarity=3 if rarity == "Rare" else 2)

    def pack(self, run) -> str:
        return self.model.pack(run.ante)

    def open_pack(self, run, name: str) -> list[dict]:
        self.sync(run)
        return self.model.open_pack(name, run.ante)

    def created_joker(self, run, source: str, rarity: str | None) -> dict:
        """A joker made by an effect: create_card with the effect's key ("jud" Judgement, "rif" Riff-raff,
        "wra" Wraith, "top" Top-up Tag)."""
        self.sync(run)
        code = {"Common": 1, "Uncommon": 2, "Rare": 3}.get(rarity)
        return self.model.joker(source, run.ante, rarity=code)

    def created_consumable(self, run, kind: str, source: str) -> dict:
        """A Tarot, Planet or Spectral made by an effect ("emp" The Emperor, "pri" The High Priestess,
        "8ba" 8 Ball and Purple Seals, "car" Cartomancer, "sea" Seance, "sixth" Sixth Sense, ...)."""
        self.sync(run)
        return self.model.consumable(kind, source, run.ante, soulable=False)

    def roll(self, key: str) -> float:
        """pseudorandom(key), for in-round chances the game draws from a named stream (Lucky cards, Glass)."""
        return self.model.rng.random(key)

    def legendary(self, run) -> dict:
        self.sync(run)
        return self.model.legendary(run.ante)
