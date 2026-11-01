"""The 24 skip tags (data/tags.json). Minimum antes come from the data; the run copies tags for Double
Tag itself, so that one is an empty class.

Judgement calls (data/tags.json, data/shop.json, balatrowiki.org):
- Uncommon and Rare Tag replace the first card slot of the next shop's initial stock that another of them
  hasn't taken, with a free joker of their rarity. The game makes that joker first, so edition tags land
  on it: pending edition tags apply to it, and an edition a tag already gave the joker it replaces moves
  to it (an edition tag used on a joker in another slot leaves that joker free too). The tag gives nothing
  when no joker of its rarity can appear (the game: Rare Tag only). With every slot taken it waits for the
  next shop (the wiki: the next reroll).
- Edition tags change the first edition-less joker put on sale (initial stock or reroll) and make it free.
- Coupon Tag frees the initial cards and packs; rerolled cards and vouchers keep their prices.
- Voucher Tag adds a voucher not redeemed, not on sale and whose prerequisite is redeemed.
- Orbital Tag picks its hand when rolled, among the hands visible then (secret hands once played).
- Top-up Tag makes a Common joker per free slot, at most 2, with a rolled edition and no stickers.
"""
from __future__ import annotations

import weakref

from .. import pool
from ..items import Tag, data, tag
from ..shop import PACKS, Offer

HANDS = data("hands.json")["hands"]


@tag
class DoubleTag(Tag):
    name = "Double Tag"


# ---- money --------------------------------------------------------------------------------------

@tag
class EconomyTag(Tag):
    name = "Economy Tag"

    def on_gain(self, run):
        run.money += min(40, max(0, run.money))
        return True


@tag
class HandyTag(Tag):
    name = "Handy Tag"

    def on_gain(self, run):
        run.money += run.hands_played
        return True


@tag
class GarbageTag(Tag):
    name = "Garbage Tag"

    def on_gain(self, run):
        run.money += run.unused_discards
        return True


@tag
class SpeedTag(Tag):
    name = "Speed Tag"

    def on_gain(self, run):
        run.money += 5 * run.skips
        return True


@tag
class InvestmentTag(Tag):
    name = "Investment Tag"

    def on_boss_defeated(self, run):
        run.money += 25
        return True


# ---- immediate ----------------------------------------------------------------------------------

@tag
class TopUpTag(Tag):
    name = "Top-up Tag"

    def on_gain(self, run):
        for _ in range(2):
            if run.joker_room():
                run.create_joker(rarity="Common", source="top")
        return True


@tag
class OrbitalTag(Tag):
    name = "Orbital Tag"
    hand: str | None = None

    def setup(self, run):
        visible = [h["name"] for h in HANDS if not h["secret"] or run.hand_plays[h["name"]] > 0]
        self.hand = run.rng["misc"].choice(visible)

    def on_gain(self, run):
        if self.hand is None:
            self.setup(run)
        run.level_up(self.hand, 3)
        return True


@tag
class BossTag(Tag):
    name = "Boss Tag"

    def on_gain(self, run):
        run.reroll_boss(paid=False)
        return True


class _PackTag(Tag):
    pack = "?"

    def on_gain(self, run):
        run.open_pack(PACKS[self.pack])
        return True


@tag
class StandardTag(_PackTag):
    name, pack = "Standard Tag", "Mega Standard Pack"


@tag
class CharmTag(_PackTag):
    name, pack = "Charm Tag", "Mega Arcana Pack"


@tag
class MeteorTag(_PackTag):
    name, pack = "Meteor Tag", "Mega Celestial Pack"


@tag
class BuffoonTag(_PackTag):
    name, pack = "Buffoon Tag", "Mega Buffoon Pack"


@tag
class EtherealTag(_PackTag):
    name, pack = "Ethereal Tag", "Spectral Pack"


# ---- next round ---------------------------------------------------------------------------------

@tag
class JuggleTag(Tag):
    name = "Juggle Tag"

    def on_blind_select(self, run, blind):
        run.hand_size_delta += 3
        return True


# ---- next shop ----------------------------------------------------------------------------------

_PLACED: weakref.WeakSet = weakref.WeakSet()  # jokers that Uncommon and Rare Tags put on sale


class _JokerTag(Tag):
    rarity = "?"

    def on_shop_open(self, run, shop):
        # TODO(engine): a tag hook when the shop fills each card slot (the game's store_joker_create) would
        # let these take the first slot before edition tags apply, and wait for a reroll when slots run out.
        slot = next((i for i, o in enumerate(shop.cards) if not (o.kind == "Joker" and o.item in _PLACED)), None)
        if slot is None:
            return False
        old, offer = shop.cards[slot], shop.joker_offer(self.rarity, free=True)
        if offer.item.rarity != self.rarity:  # the fallback Joker of an exhausted pool
            return True
        if old.free and old.kind == "Joker" and offer.item.edition is None:
            offer.item.edition = old.item.edition  # an edition tag already used on the joker it replaces
        _PLACED.add(offer.item)
        shop.cards[slot] = offer
        return True


@tag
class UncommonTag(_JokerTag):
    name, rarity = "Uncommon Tag", "Uncommon"


@tag
class RareTag(_JokerTag):
    name, rarity = "Rare Tag", "Rare"


class _EditionTag(Tag):
    edition = "?"

    def on_shop_offer(self, run, shop, offer):
        if offer.item.edition is not None:
            return False
        offer.item.edition = self.edition
        offer.free = True
        return True


@tag
class FoilTag(_EditionTag):
    name, edition = "Foil Tag", "Foil"


@tag
class HolographicTag(_EditionTag):
    name, edition = "Holographic Tag", "Holographic"


@tag
class PolychromeTag(_EditionTag):
    name, edition = "Polychrome Tag", "Polychrome"


@tag
class NegativeTag(_EditionTag):
    name, edition = "Negative Tag", "Negative"


@tag
class CouponTag(Tag):
    name = "Coupon Tag"

    def on_shop_open(self, run, shop):
        for offer in shop.cards + shop.packs:
            offer.free = True
        return True


@tag
class D6Tag(Tag):
    name = "D6 Tag"

    def on_shop_open(self, run, shop):
        shop.reroll_base = 0
        return True


@tag
class VoucherTag(Tag):
    name = "Voucher Tag"

    def on_shop_open(self, run, shop):
        name = pool.random_voucher(run, run.rng["misc"], shown=[o.item for o in shop.vouchers])
        shop.vouchers.append(Offer("Voucher", name))
        return True
