"""What a White Stake, Red Deck run shows at its start, computed from the seed (Balatro 1.0.1).

Usage:
    python3 opening.py SEED [SEED ...] [--json] [--second-hand] [--locked-jokers "Blueprint,..."]

Outputs, in the order the player sees them:
  * ante-1 Small Blind tag and Big Blind tag  (key "Tag1", resamples "Tag1_resample2", ...)
  * ante-1 Boss Blind                          (key "boss")
  * first hand of 8 cards, as a set            (key "nr1": Fisher-Yates of the sorted 52-card deck)
  * first shop: the voucher                    (key "Voucher1")
  * first shop: the 2 cards                    (keys "cdt1", "rarity1sho", "Joker<r>sho1", "edisho1",
                                                "Tarotsho1", "Planetsho1")
  * first shop: the 2 booster packs            (slot 1 is always a normal Buffoon Pack in 1.0.1;
                                                slot 2 uses key "shop_pack1")

``Run`` also models what validation of published seeds needs: shops at any ante with Rare/Uncommon
tags, pack contents (Arcana/Celestial/Spectral/Buffoon), The Soul's legendary joker, and the
voucher chain when every voucher is bought.

Which keys, pools and orders are used was learned by reading Immolate (CC BY-NC-SA 4.0, see
REPORT.md); the code is ours.  Verification status per output: ``VERIFICATION`` and REPORT.md.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from rng import GameRNG, normalize_seed

# ---------------------------------------------------------------------------------------------
# Game data: names in the game's internal pool order (the prototypes' `order` field, which is the
# collection order).  validate.py section E cross-checks these lists against ../data/*.json.
# ---------------------------------------------------------------------------------------------

TAGS = [
    "Uncommon Tag", "Rare Tag", "Negative Tag", "Foil Tag", "Holographic Tag", "Polychrome Tag",
    "Investment Tag", "Voucher Tag", "Boss Tag", "Standard Tag", "Charm Tag", "Meteor Tag",
    "Buffoon Tag", "Handy Tag", "Garbage Tag", "Ethereal Tag", "Coupon Tag", "Double Tag",
    "Juggle Tag", "D6 Tag", "Top-up Tag", "Speed Tag", "Orbital Tag", "Economy Tag",
]
TAGS_MIN_ANTE_2 = {
    "Negative Tag", "Standard Tag", "Meteor Tag", "Buffoon Tag", "Handy Tag", "Garbage Tag",
    "Ethereal Tag", "Top-up Tag", "Orbital Tag",
}
#: Tag -> what must be *discovered* in the player's profile for the tag to be in the pool.
TAG_REQUIRES = {
    "Rare Tag": "Blueprint", "Negative Tag": "Negative", "Foil Tag": "Foil",
    "Holographic Tag": "Holographic", "Polychrome Tag": "Polychrome",
}

#: Non-showdown bosses allowed at ante 1 (boss.min <= 1), sorted by internal key (bl_club ...).
BOSSES_ANTE1 = [
    "The Club", "The Goad", "The Head", "The Hook", "The Manacle", "The Pillar", "The Psychic",
    "The Window",
]

VOUCHERS = [
    "Overstock", "Overstock Plus", "Clearance Sale", "Liquidation", "Hone", "Glow Up",
    "Reroll Surplus", "Reroll Glut", "Crystal Ball", "Omen Globe", "Telescope", "Observatory",
    "Grabber", "Nacho Tong", "Wasteful", "Recyclomancy", "Tarot Merchant", "Tarot Tycoon",
    "Planet Merchant", "Planet Tycoon", "Seed Money", "Money Tree", "Blank", "Antimatter",
    "Magic Trick", "Illusion", "Hieroglyph", "Petroglyph", "Director's Cut", "Retcon",
    "Paint Brush", "Palette",
]
#: Upgraded vouchers (odd positions) need their base voucher redeemed first.
BASE_VOUCHERS = VOUCHERS[0::2]

TAROTS = [
    "The Fool", "The Magician", "The High Priestess", "The Empress", "The Emperor",
    "The Hierophant", "The Lovers", "The Chariot", "Justice", "The Hermit",
    "The Wheel of Fortune", "Strength", "The Hanged Man", "Death", "Temperance", "The Devil",
    "The Tower", "The Star", "The Moon", "The Sun", "Judgement", "The World",
]
PLANETS = [
    "Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
    "Planet X", "Ceres", "Eris",
]
#: Secret-hand planets are soft-locked until their hand has been played this run.
SOFTLOCKED_PLANETS = {"Planet X", "Ceres", "Eris"}
#: The Soul and Black Hole sit in the Spectral pool but are never drawn from it.
SPECTRALS = [
    "Familiar", "Grim", "Incantation", "Talisman", "Aura", "Wraith", "Sigil", "Ouija",
    "Ectoplasm", "Immolate", "Ankh", "Deja Vu", "Hex", "Trance", "Medium", "Cryptid",
    "The Soul", "Black Hole",
]

COMMON_JOKERS = [
    "Joker", "Greedy Joker", "Lusty Joker", "Wrathful Joker", "Gluttonous Joker", "Jolly Joker",
    "Zany Joker", "Mad Joker", "Crazy Joker", "Droll Joker", "Sly Joker", "Wily Joker",
    "Clever Joker", "Devious Joker", "Crafty Joker", "Half Joker", "Credit Card", "Banner",
    "Mystic Summit", "8 Ball", "Misprint", "Raised Fist", "Chaos the Clown", "Scary Face",
    "Abstract Joker", "Delayed Gratification", "Gros Michel", "Even Steven", "Odd Todd",
    "Scholar", "Business Card", "Supernova", "Ride the Bus", "Egg", "Runner", "Ice Cream",
    "Splash", "Blue Joker", "Faceless Joker", "Green Joker", "Superposition", "To Do List",
    "Cavendish", "Red Card", "Square Joker", "Riff-Raff", "Photograph", "Reserved Parking",
    "Mail-In Rebate", "Hallucination", "Fortune Teller", "Juggler", "Drunkard", "Golden Joker",
    "Popcorn", "Walkie Talkie", "Smiley Face", "Golden Ticket", "Swashbuckler", "Hanging Chad",
    "Shoot the Moon",
]
UNCOMMON_JOKERS = [
    "Joker Stencil", "Four Fingers", "Mime", "Ceremonial Dagger", "Marble Joker",
    "Loyalty Card", "Dusk", "Fibonacci", "Steel Joker", "Hack", "Pareidolia", "Space Joker",
    "Burglar", "Blackboard", "Sixth Sense", "Constellation", "Hiker", "Card Sharp", "Madness",
    "Séance", "Vampire", "Shortcut", "Hologram", "Cloud 9", "Rocket", "Midas Mask", "Luchador",
    "Gift Card", "Turtle Bean", "Erosion", "To the Moon", "Stone Joker", "Lucky Cat", "Bull",
    "Diet Cola", "Trading Card", "Flash Card", "Spare Trousers", "Ramen", "Seltzer", "Castle",
    "Mr. Bones", "Acrobat", "Sock and Buskin", "Troubadour", "Certificate", "Smeared Joker",
    "Throwback", "Rough Gem", "Bloodstone", "Arrowhead", "Onyx Agate", "Glass Joker", "Showman",
    "Flower Pot", "Merry Andy", "Oops! All 6s", "The Idol", "Seeing Double", "Matador",
    "Satellite", "Cartomancer", "Astronomer", "Bootstraps",
]
RARE_JOKERS = [
    "DNA", "Vagabond", "Baron", "Obelisk", "Baseball Card", "Ancient Joker", "Campfire",
    "Blueprint", "Wee Joker", "Hit the Road", "The Duo", "The Trio", "The Family", "The Order",
    "The Tribe", "Stuntman", "Invisible Joker", "Brainstorm", "Driver's License", "Burnt Joker",
]
LEGENDARY_JOKERS = ["Canio", "Triboulet", "Yorick", "Chicot", "Perkeo"]

# Balatro 1.0.0 (before the 1.0.1 rarity rebalance) -- only used to test claims made in early 2024.
COMMON_JOKERS_100 = [j for j in COMMON_JOKERS if j != "Reserved Parking"]
UNCOMMON_JOKERS_100 = [
    "Joker Stencil", "Four Fingers", "Mime", "Ceremonial Dagger", "Marble Joker",
    "Loyalty Card", "Dusk", "Fibonacci", "Steel Joker", "Hack", "Pareidolia", "Space Joker",
    "Burglar", "Blackboard", "Constellation", "Hiker", "Card Sharp", "Madness", "Vampire",
    "Shortcut", "Hologram", "Vagabond", "Cloud 9", "Rocket", "Midas Mask", "Luchador",
    "Gift Card", "Turtle Bean", "Erosion", "Reserved Parking", "To the Moon", "Stone Joker",
    "Lucky Cat", "Bull", "Diet Cola", "Trading Card", "Flash Card", "Spare Trousers", "Ramen",
    "Seltzer", "Castle", "Mr. Bones", "Acrobat", "Sock and Buskin", "Troubadour", "Certificate",
    "Smeared Joker", "Throwback", "Rough Gem", "Bloodstone", "Arrowhead", "Onyx Agate",
    "Glass Joker", "Showman", "Flower Pot", "Merry Andy", "Oops! All 6s", "The Idol",
    "Seeing Double", "Matador", "Stuntman", "Satellite", "Cartomancer", "Astronomer",
    "Burnt Joker", "Bootstraps",
]
RARE_JOKERS_100 = [
    "DNA", "Sixth Sense", "Séance", "Baron", "Obelisk", "Baseball Card", "Ancient Joker",
    "Campfire", "Blueprint", "Wee Joker", "Hit the Road", "The Duo", "The Trio", "The Family",
    "The Order", "The Tribe", "Invisible Joker", "Brainstorm", "Driver's License",
]

RARITY_NAME = {1: "Common", 2: "Uncommon", 3: "Rare", 4: "Legendary"}
#: Jokers that need an enhanced card in the deck (Red Deck starts with none).
ENHANCEMENT_GATED = {"Stone Joker", "Steel Joker", "Glass Joker", "Golden Ticket", "Lucky Cat"}
#: Cavendish needs the "Gros Michel went extinct" pool flag.
POOL_FLAG_GATED = {"Cavendish"}

#: Booster kinds with their total weight, in the game's pool order (as in Immolate).
PACKS = [
    ("Arcana Pack", 4.0), ("Jumbo Arcana Pack", 2.0), ("Mega Arcana Pack", 0.5),
    ("Celestial Pack", 4.0), ("Jumbo Celestial Pack", 2.0), ("Mega Celestial Pack", 0.5),
    ("Standard Pack", 4.0), ("Jumbo Standard Pack", 2.0), ("Mega Standard Pack", 0.5),
    ("Buffoon Pack", 1.2), ("Jumbo Buffoon Pack", 0.6), ("Mega Buffoon Pack", 0.15),
    ("Spectral Pack", 0.6), ("Jumbo Spectral Pack", 0.3), ("Mega Spectral Pack", 0.07),
]
PACK_TOTAL = 22.42
PACK_SIZE = {"Arcana": (3, 5, 5), "Celestial": (3, 5, 5), "Standard": (3, 5, 5),
             "Buffoon": (2, 4, 4), "Spectral": (2, 4, 4)}

#: Shop card-type rates at the start of a Red Deck run (no vouchers).
SHOP_RATES = [("Joker", 20.0), ("Tarot", 4.0), ("Planet", 4.0)]

SUITS = "CDHS"                          # internal suit letters: Clubs, Diamonds, Hearts, Spades
RANKS_SORTED = "23456789AJKQT"          # ASCII order of the rank letters
#: Standard deck in creation (= sort_id) order: sorted by the string suit..rank.
DECK_ORDER = [s + r for s in SUITS for r in RANKS_SORTED]
RANK_DISPLAY = {"T": "10"}
SUIT_DISPLAY = {"C": "♣", "D": "♦", "H": "♥", "S": "♠"}
RANK_VALUE = {r: i for i, r in enumerate("23456789TJQKA", start=2)}

VERIFICATION = {
    "rng": "verified (published test vectors + in-game Erratic-deck facts), see validate.py",
    "voucher": "verified against a published 7-voucher chain (11EVFRPQ) and other claims",
    "tags": "verified against 10+ published tag claims",
    "shop_cards": "partly verified (e.g. Negative Blueprint in 99K6IUBD's first shop); 2 claims unmatched",
    "boss": "verified in-game 2026-10-25 (macOS): seed DD8JI5Y5 found from its opening, confirmed by the player",
    "first_hand": "verified in-game 2026-10-25 (macOS): seed DD8JI5Y5 found from its 8-card first hand, confirmed by the player",
    "packs": "slot 1 forced Buffoon (1.0.1 rule); slot 2 consistent with claims, not proven",
}


@dataclass(frozen=True)
class Profile:
    """The parts of a player's profile that change what can appear."""
    locked_jokers: frozenset = frozenset()          # jokers not yet unlocked in the profile
    discovered: frozenset = frozenset({"Blueprint", "Negative", "Foil", "Holographic", "Polychrome"})


FULL_PROFILE = Profile()


def joker_edition(poll: float) -> str | None:
    if poll > 0.997:
        return "Negative"
    if poll > 0.994:
        return "Polychrome"
    if poll > 0.98:
        return "Holographic"
    if poll > 0.96:
        return "Foil"
    return None


def pack_kind_size(pack: str) -> tuple[str, int]:
    words = pack.split()
    kind = words[-2]
    tier = 1 if words[0] == "Jumbo" else 2 if words[0] == "Mega" else 0
    return kind, PACK_SIZE[kind][tier]


class Run:
    """The random state of one run plus the bits of game state that change pools."""

    def __init__(self, seed: str, profile: Profile = FULL_PROFILE, version: str = "1.0.1"):
        self.seed = normalize_seed(seed)
        self.rng = GameRNG(self.seed)
        self.profile = profile
        self.version = version
        self.used: set = set()               # G.GAME.used_jokers: cards that currently exist
        self.vouchers_bought: set = set()
        self.first_pack_generated = False
        old = version.startswith("1.0.0")
        self.joker_pools = {1: COMMON_JOKERS_100 if old else COMMON_JOKERS,
                            2: UNCOMMON_JOKERS_100 if old else UNCOMMON_JOKERS,
                            3: RARE_JOKERS_100 if old else RARE_JOKERS}

    # -- generic pool draw ------------------------------------------------------------------
    def pick(self, key: str, pool: list, unavailable) -> str:
        """``pseudorandom_element`` over a pool with UNAVAILABLE slots, resampling with
        ``key``, ``key_resample2``, ``key_resample3``, ..."""
        item = pool[self.rng.element_index(key, len(pool))]
        it = 1
        while item in unavailable:
            it += 1
            item = pool[self.rng.element_index(f"{key}_resample{it}", len(pool))]
            if it > 1000:
                raise RuntimeError(f"resample loop for {key}")
        return item

    # -- blind select screen ----------------------------------------------------------------
    def tag(self, ante: int = 1) -> str:
        unavailable = {t for t, need in TAG_REQUIRES.items() if need not in self.profile.discovered}
        if ante < 2:
            unavailable |= TAGS_MIN_ANTE_2
        return self.pick(f"Tag{ante}", TAGS, unavailable)

    def boss_ante1(self) -> str:
        return BOSSES_ANTE1[self.rng.element_index("boss", len(BOSSES_ANTE1))]

    # -- hand -------------------------------------------------------------------------------
    def hand(self, ante: int = 1, hand_size: int = 8) -> list[str]:
        """Cards drawn at the start of a blind (top of the shuffled deck = end of the list).
        The deck is re-sorted by creation order before every shuffle, so only the number of
        earlier shuffles in this ante matters."""
        deck = self.rng.shuffle(f"nr{ante}", DECK_ORDER)
        return sort_cards(deck[-hand_size:])

    # -- vouchers ---------------------------------------------------------------------------
    def voucher(self, ante: int = 1) -> str:
        unavailable = set()
        for i, v in enumerate(VOUCHERS):
            if v in self.vouchers_bought or (i % 2 == 1 and VOUCHERS[i - 1] not in self.vouchers_bought):
                unavailable.add(v)
        return self.pick(f"Voucher{ante}", VOUCHERS, unavailable)

    # -- card creation (create_card) ---------------------------------------------------------
    def joker(self, append: str, ante: int, rarity: int | None = None) -> dict:
        if rarity is None:
            r = self.rng.random(f"rarity{ante}{append}")
            rarity = 3 if r > 0.95 else 2 if r > 0.7 else 1
        pool = self.joker_pools[rarity]
        unavailable = (set(self.profile.locked_jokers) | ENHANCEMENT_GATED | POOL_FLAG_GATED
                       | self.used)
        name = self.pick(f"Joker{rarity}{append}{ante}", pool, unavailable)
        card = {"type": "Joker", "name": name, "rarity": RARITY_NAME[rarity],
                "edition": joker_edition(self.rng.random(f"edi{append}{ante}"))}
        self.used.add(name)
        return card

    def legendary(self, ante: int) -> dict:
        """The joker created by using The Soul."""
        key = "Joker4" if not self.version.startswith("1.0.0") else f"Joker4sou{ante}"
        name = self.pick(key, LEGENDARY_JOKERS, self.used)
        card = {"type": "Joker", "name": name, "rarity": "Legendary",
                "edition": joker_edition(self.rng.random(f"edisou{ante}"))}
        self.used.add(name)
        return card

    def consumable(self, kind: str, append: str, ante: int, soulable: bool) -> dict:
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
            name = self.pick(f"Tarot{append}{ante}", TAROTS, self.used)
        elif kind == "Planet":
            name = self.pick(f"Planet{append}{ante}", PLANETS, SOFTLOCKED_PLANETS | self.used)
        else:
            name = self.pick(f"Spectral{append}{ante}", SPECTRALS,
                             {"The Soul", "Black Hole"} | self.used)
        self.used.add(name)
        return {"type": "Spectral" if forced else kind, "name": name}

    # -- shop -------------------------------------------------------------------------------
    def shop_card(self, ante: int, tags: list | None = None) -> dict:
        """One card slot.  A held Rare/Uncommon Tag fills the slot first (and is used up)."""
        if tags:
            for t in list(tags):
                if t in ("Rare Tag", "Uncommon Tag"):
                    tags.remove(t)
                    if t == "Rare Tag":
                        return self.joker("rta", ante, rarity=3)
                    return self.joker("uta", ante, rarity=2)
        total = sum(w for _, w in SHOP_RATES)
        poll = self.rng.random(f"cdt{ante}") * total
        check, kind = 0.0, SHOP_RATES[-1][0]
        for name, w in SHOP_RATES:
            if check < poll <= check + w:
                kind = name
                break
            check += w
        if kind == "Joker":
            return self.joker("sho", ante)
        return self.consumable(kind, "sho", ante, soulable=False)

    def pack(self, ante: int) -> str:
        if not self.version.startswith("1.0.0") and not self.first_pack_generated:
            self.first_pack_generated = True       # 1.0.1: first pack of the run is a Buffoon Pack
            return "Buffoon Pack"
        poll = self.rng.random(f"shop_pack{ante}") * PACK_TOTAL
        cum = 0.0
        for name, w in PACKS:
            cum += w
            if cum >= poll:
                return name
        return PACKS[-1][0]

    def shop(self, ante: int, tags: list | None = None) -> dict:
        cards = [self.shop_card(ante, tags) for _ in range(2)]
        packs = [self.pack(ante), self.pack(ante)]
        return {"voucher": None, "cards": cards, "packs": packs}

    def open_pack(self, pack: str, ante: int) -> list[dict]:
        """Contents of a pack.  Cards in one pack cannot repeat; they leave ``used`` afterwards
        unless the caller re-adds the one that was taken."""
        kind, size = pack_kind_size(pack)
        out = []
        for _ in range(size):
            if kind == "Arcana":
                out.append(self.consumable("Tarot", "ar1", ante, soulable=True))
            elif kind == "Celestial":
                out.append(self.consumable("Planet", "pl1", ante, soulable=True))
            elif kind == "Spectral":
                out.append(self.consumable("Spectral", "spe", ante, soulable=True))
            elif kind == "Buffoon":
                out.append(self.joker("buf", ante))
            else:
                out.append({"type": "Playing card", "name": "(Standard Pack not modelled)"})
        for c in out:
            self.used.discard(c["name"])
        return out

    def end_shop(self, cards: list[dict], bought: tuple = ()) -> None:
        """Cards left in a shop disappear when it closes (bought ones stay owned)."""
        for c in cards:
            if c["name"] not in bought:
                self.used.discard(c["name"])


# ---------------------------------------------------------------------------------------------
# The opening of a run
# ---------------------------------------------------------------------------------------------

def sort_cards(cards) -> list[str]:
    return sorted(cards, key=lambda c: (-RANK_VALUE[c[1]], SUITS.index(c[0])))


def card_label(c: str) -> str:
    return RANK_DISPLAY.get(c[1], c[1]) + SUIT_DISPLAY[c[0]]


def parse_card(text: str) -> str:
    """'10h', 'Th', 'AS', 'qd', '7♣' -> internal 'HT', 'HT', 'SA', 'DQ', 'C7'."""
    t = text.strip().upper()
    for sym, letter in (("♣", "C"), ("♦", "D"), ("♥", "H"), ("♠", "S")):
        t = t.replace(sym, letter)
    suit, rank = t[-1], t[:-1].replace("10", "T")
    if suit not in SUITS or rank not in RANK_VALUE:
        raise ValueError(f"bad card {text!r}")
    return suit + rank


def opening(seed: str, profile: Profile = FULL_PROFILE, second_hand: bool = False,
            version: str = "1.0.1") -> dict:
    """Everything visible from run start through the first shop, if the player plays the Small
    Blind (no skip), uses no consumables and does not reroll."""
    run = Run(seed, profile, version)
    out = {"seed": run.seed}
    # Run start (separate keys, so their relative order does not matter; the two tags share
    # "Tag1" and are drawn Small first, then Big).
    out["boss"] = run.boss_ante1()
    out["voucher"] = run.voucher(1)
    out["small_tag"] = run.tag(1)
    out["big_tag"] = run.tag(1)
    out["first_hand"] = run.hand(1)
    if second_hand:                      # first hand of the 2nd blind (2nd use of "nr1")
        out["second_blind_hand"] = run.hand(1)
    shop = run.shop(1)
    out["shop_cards"] = shop["cards"]
    out["packs"] = shop["packs"]
    return out


def format_opening(o: dict) -> str:
    def card_txt(c):
        if c["type"] == "Joker":
            ed = f" ({c['edition']})" if c.get("edition") else ""
            return f"{c['name']}{ed} [{c['rarity']} Joker]"
        return f"{c['name']} [{c['type']}]"
    lines = [
        f"Seed {o['seed']}  (White Stake, Red Deck, Balatro 1.0.1)",
        f"  Small Blind tag : {o['small_tag']}",
        f"  Big Blind tag   : {o['big_tag']}",
        f"  Boss Blind      : {o['boss']}",
        f"  First hand      : {' '.join(card_label(c) for c in o['first_hand'])}",
    ]
    if "second_blind_hand" in o:
        lines.append(f"  2nd blind hand  : {' '.join(card_label(c) for c in o['second_blind_hand'])}")
    lines += [
        f"  Shop voucher    : {o['voucher']}",
        f"  Shop cards      : {card_txt(o['shop_cards'][0])}; {card_txt(o['shop_cards'][1])}",
        f"  Shop packs      : {o['packs'][0]}; {o['packs'][1]}",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("seeds", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--second-hand", action="store_true", help="also show the 2nd blind's hand")
    ap.add_argument("--locked-jokers", default="", help="comma-separated jokers locked in profile")
    ap.add_argument("--version", default="1.0.1", choices=["1.0.1", "1.0.0"])
    args = ap.parse_args(argv)
    prof = Profile(locked_jokers=frozenset(x.strip() for x in args.locked_jokers.split(",") if x.strip()))
    for s in args.seeds:
        o = opening(s, prof, second_hand=args.second_hand, version=args.version)
        print(json.dumps(o, ensure_ascii=False) if args.json else format_opening(o))


if __name__ == "__main__":
    main()
