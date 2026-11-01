"""The shop between blinds and booster packs: card slots, two packs and the ante's voucher, with prices,
rerolls and what each pack holds. Rules: data/shop.json, data/modifiers.json."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import pool
from .cards import Card
from .items import CONSUMABLES, Consumable, data, info
from .jokers import CATALOG, Joker

EDITION_SURCHARGE = {"Foil": 2, "Holographic": 3, "Polychrome": 5, "Negative": 5}


@dataclass(frozen=True)
class Pack:
    name: str
    kind: str  # Arcana, Celestial, Standard, Buffoon, Spectral
    size: str  # Normal, Jumbo, Mega
    cost: int
    shown: int
    chosen: int


_PACK_DATA = data("shop.json")["booster_packs"]["packs"]
PACKS = {p["name"]: Pack(p["name"], p["kind"], p["size"], p["cost"], p["cards_shown"], p["cards_chosen"]) for p in _PACK_DATA}
PACK_WEIGHTS = [p["weight"] for p in _PACK_DATA]


def price(run, base: int, edition: str | None = None) -> int:
    """Buy price: base cost plus edition surcharge, discounted (Clearance Sale, Liquidation), at least $1."""
    return max(1, math.floor((base + EDITION_SURCHARGE.get(edition, 0) + 0.5) * (100 - run.discount_percent) / 100))


def sell_value(run, item) -> int:
    """Half the current buy price (at least $1) plus extra sell value; rentals cost and sell for $1."""
    buy = 1 if getattr(item, "rental", False) else price(run, item.cost, item.edition)
    return max(1, buy // 2) + item.extra_sell


@dataclass
class Offer:
    kind: str  # Joker, Tarot, Planet, Spectral, Playing card, Pack, Voucher
    item: object  # Joker, Consumable, Card, Pack, or a voucher name
    free: bool = False  # Coupon Tag, edition / Uncommon / Rare tags

    @property
    def name(self) -> str:
        if isinstance(self.item, Card):
            return self.item.label()
        return self.item if isinstance(self.item, str) else self.item.name

    def to_dict(self, run) -> dict:
        d = {"kind": self.kind, "name": self.name, "price": cost_of(run, self)}
        if isinstance(self.item, Card):
            d["card"] = self.item.to_dict()
        elif isinstance(self.item, Joker):
            d.update(edition=self.item.edition, eternal=self.item.eternal, perishable=self.item.perishable,
                     rental=self.item.rental)
        return d


def cost_of(run, offer: Offer) -> int:
    if offer.free:
        return 0
    item = offer.item
    if offer.kind == "Joker":
        return 1 if item.rental else price(run, item.cost, item.edition)
    if offer.kind == "Planet" or (offer.kind == "Pack" and item.kind == "Celestial"):
        if run.has_joker("Astronomer"):
            return 0
    if offer.kind == "Pack":
        return price(run, item.cost)
    if offer.kind == "Voucher":
        return price(run, info("voucher", item)["cost"])
    if offer.kind == "Playing card":
        return price(run, 1, item.edition)
    return price(run, item.cost, item.edition)


class Shop:
    def __init__(self, run):
        self.run = run
        self.rng = run.rng["shop"]
        self.rerolls = 0
        self.free_rerolls = sum(j.name == "Chaos the Clown" for j in run.active_jokers())
        self.reroll_base: int | None = None  # D6 Tag sets this shop's base to 0
        self.cards: list[Offer] = []
        for _ in range(run.shop_card_slots):
            self.cards.append(self.tag_card() if run.seedrng else self.new_card())
        if run.seedrng:                                  # the game's first pack of a run is a Buffoon Pack too
            self.packs = [Offer("Pack", PACKS[run.seedrng.pack(run)]) for _ in range(2)]
        else:
            first = run.shops_seen == 0
            self.packs = [Offer("Pack", PACKS["Buffoon Pack"] if first and k == 0 else self.rng.choices(list(PACKS.values()), PACK_WEIGHTS)[0])
                          for k in range(2)]
        self.vouchers = [Offer("Voucher", run.ante_voucher)] if run.ante_voucher else []
        for t in list(run.tags):
            if t.on_shop_open(run, self):
                run.tags.remove(t)
        for j in list(run.active_jokers()):
            j.on_shop_open(run, self)

    # ---- stock ----------------------------------------------------------------------------------------
    def shown(self) -> list[str]:
        return [o.name for o in self.cards]

    def tag_card(self) -> Offer:
        """Seed-exact shops: a held Rare or Uncommon Tag fills the slot (free) before the slot's own draw."""
        run = self.run
        tag = next((t for t in run.tags if t.name in ("Rare Tag", "Uncommon Tag")), None)
        if tag is None:
            return self.new_card()
        run.tags.remove(tag)
        d = run.seedrng.tag_joker(run, tag.name.split()[0], self.shown())
        return self.with_tags(Offer("Joker", game_item(d), free=True))

    def new_card(self) -> Offer:
        """A card slot: its type by weight (Joker 20, Tarot 4, Planet 4, more with vouchers), then a card of that type."""
        run = self.run
        if run.seedrng:
            d = run.seedrng.shop_card(run, self.shown())
            if d["type"] == "Playing card":
                illusion = run.has_voucher("Illusion")
                return Offer("Playing card", pool.random_playing_card(run, self.rng, enhanced=0.4 if illusion else 0, illusion=illusion))
            item = game_item(d)
            if d["type"] == "Joker":
                pool.roll_stickers(run, item, self.rng)
                return self.with_tags(Offer("Joker", item))
            return Offer(item.kind, item)
        weights = run.shop_weights()
        kinds = [k for k in weights if weights[k] > 0]
        kind = self.rng.choices(kinds, [weights[k] for k in kinds])[0]
        if kind == "Playing card":
            illusion = run.has_voucher("Illusion")
            card = pool.random_playing_card(run, self.rng, enhanced=0.4 if illusion else 0, illusion=illusion)
            return Offer(kind, card)
        if kind != "Joker":
            c = pool.random_consumable(run, kind, self.rng, self.shown())
            if c is not None:
                return Offer(kind, c)
        return self.joker_offer()

    def joker_offer(self, rarity: str | None = None, free: bool = False) -> Offer:
        return self.with_tags(Offer("Joker", pool.random_joker(self.run, self.rng, rarity, self.shown(), stickers=True), free))

    def with_tags(self, offer: Offer) -> Offer:
        """Edition tags change the first edition-less joker put on sale."""
        for t in list(self.run.tags):
            if t.on_shop_offer(self.run, self, offer):
                self.run.tags.remove(t)
        return offer

    def add_card_slot(self) -> None:
        """Overstock bought mid-shop: the new slot fills at once."""
        self.cards.append(self.new_card())

    # ---- actions --------------------------------------------------------------------------------------
    @property
    def reroll_cost(self) -> int:
        if self.free_rerolls:
            return 0
        return (self.run.reroll_base if self.reroll_base is None else self.reroll_base) + self.rerolls

    def reroll(self) -> bool:
        """Replace the card slots (not packs or vouchers); the cost rises $1 per reroll this shop."""
        run, cost = self.run, self.reroll_cost
        if run.money - cost < run.debt_limit:
            return False
        run.money -= cost
        run.rerolls_done += 1
        if self.free_rerolls:
            self.free_rerolls -= 1
        else:
            self.rerolls += 1
        self.cards = []
        for _ in range(run.shop_card_slots):
            self.cards.append(self.new_card())
        for j in list(run.active_jokers()):
            j.on_reroll(run, self)
        run.emit("reroll", cost)
        return True

    def buy(self, where: str, i: int, use: bool = False, targets=()) -> bool:
        """Buy card/pack/voucher number `i`. A bought pack opens at once; `use` uses a bought consumable
        right away (no slot needed)."""
        run = self.run
        offers = {"card": self.cards, "pack": self.packs, "voucher": self.vouchers}.get(where)
        if offers is None or not 0 <= i < len(offers):
            return False
        offer = offers[i]
        cost = cost_of(run, offer)
        if run.money - cost < run.debt_limit:
            return False
        item = offer.item
        if isinstance(item, Joker) and not run.joker_room(item):
            return False
        if isinstance(item, Consumable):
            cards = run.cards_at(targets)
            if use and not item.can_use(run, cards):
                return False
            if not use and not run.consumable_room(item):
                return False
        run.money -= cost
        run.cards_bought += 1
        offers.pop(i)
        run.emit("buy", offer.kind, offer.name, cost)
        if isinstance(item, Joker):
            run.add_joker(item)
        elif isinstance(item, Consumable):
            if use:
                run.apply_consumable(item, cards)
            else:
                run.consumables.append(item)
        elif isinstance(item, Card):
            run.add_cards([item])
        elif offer.kind == "Voucher":
            run.redeem_voucher(item)
        else:
            run.open_pack(item)
        return True

    def to_dict(self) -> dict:
        run = self.run
        return {"cards": [o.to_dict(run) for o in self.cards], "packs": [o.to_dict(run) for o in self.packs],
                "vouchers": [o.to_dict(run) for o in self.vouchers], "reroll_cost": self.reroll_cost}


# ---- booster packs --------------------------------------------------------------------------------

@dataclass
class OpenPack:
    """A booster pack being opened: what it shows and how many picks remain. Arcana and Spectral packs
    deal a hand from the deck (run.hand while the pack is open) for cards that need targets."""
    pack: Pack
    cards: list
    picks_left: int
    log: list = field(default_factory=list)

    def to_dict(self, run) -> dict:
        def item(x):
            if isinstance(x, Card):
                return {"kind": "Playing card", "name": x.label(), "card": x.to_dict()}
            return {"kind": "Joker" if isinstance(x, Joker) else x.kind, "name": x.name, "edition": x.edition}
        return {"name": self.pack.name, "kind": self.pack.kind, "picks_left": self.picks_left,
                "cards": [item(x) for x in self.cards]}


def _special(rng, soul: bool, black_hole: bool):
    """The 0.3% per card chance of The Soul (Arcana, Spectral) or Black Hole (Celestial, Spectral)."""
    if soul and rng.random() > 0.997 and "The Soul" in CONSUMABLES:
        return CONSUMABLES["The Soul"]()
    if black_hole and rng.random() > 0.997 and "Black Hole" in CONSUMABLES:
        return CONSUMABLES["Black Hole"]()
    return None


def _seeded_vouchers(run, pack: Pack, cards: list, rng) -> list:
    """The vouchers that change a pack's cards, on a seeded pack (the game model doesn't apply them): Telescope
    makes a Celestial pack's first card the Planet of the most played hand (unless it is The Soul or Black Hole;
    already in the pack, it moves to the front), Omen Globe turns each Arcana card Spectral 1 time in 5."""
    if pack.kind == "Celestial" and run.has_voucher("Telescope") and cards and cards[0].name not in ("The Soul", "Black Hole"):
        planet = pool.planet_for(run.most_played_hand())
        if planet:
            k = next((i for i, c in enumerate(cards) if c.name == planet.name), None)
            if k is None:
                cards[0] = planet()
            else:
                cards.insert(0, cards.pop(k))
    if pack.kind == "Arcana" and run.has_voucher("Omen Globe"):
        for i, c in enumerate(cards):
            if c.name != "The Soul" and rng.random() > 0.8:
                spectral = pool.random_consumable(run, "Spectral", rng, [x.name for x in cards])
                if spectral is not None:
                    cards[i] = spectral
    return cards


def game_item(d: dict):
    """A card from the game model (gameseed.py) as a simulator object."""
    if d["type"] == "Joker":
        return CATALOG[d["name"]](d.get("edition"))
    return CONSUMABLES[d["name"]]()


def pack_cards(run, pack: Pack, rng) -> list:
    if run.seedrng and pack.kind != "Standard":
        return _seeded_vouchers(run, pack, [game_item(d) for d in run.seedrng.open_pack(run, pack.name)], rng)
    cards: list = []
    shown = lambda: [getattr(x, "name", None) for x in cards]  # noqa: E731
    for k in range(pack.shown):
        if pack.kind == "Standard":
            cards.append(pool.random_playing_card(run, rng, enhanced=0.4, sealed=0.2, edition_scale=2))
            continue
        if pack.kind == "Buffoon":
            cards.append(pool.random_joker(run, rng, shown=shown(), stickers=True))
            continue
        kind = {"Arcana": "Tarot", "Celestial": "Planet", "Spectral": "Spectral"}[pack.kind]
        if pack.kind == "Arcana" and run.has_voucher("Omen Globe") and rng.random() > 0.8:
            kind = "Spectral"
        card = _special(rng, kind in ("Tarot", "Spectral"), kind in ("Planet", "Spectral"))
        if card is None and k == 0 and pack.kind == "Celestial" and run.has_voucher("Telescope"):
            planet = pool.planet_for(run.most_played_hand())
            card = planet() if planet else None
        if card is None:
            card = pool.random_consumable(run, kind, rng, shown())
        if card is not None:
            cards.append(card)
    return cards
