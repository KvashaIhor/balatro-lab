"""A Balatro run: antes of Small, Big and Boss blinds, cashing out and shopping after each win.

The run keeps going past ante 8 (the win) into endless antes until a blind is failed or `max_ante`
is passed, so strategies that keep scaling score higher. The agent (balatro/agent.py) makes every
decision; the run checks and applies them.

Content (jokers, consumables, bosses, tags, vouchers, decks) changes the run through the methods under
"for content" below and the attributes set in __init__. Rules: data/blinds.json, data/stakes.json.
"""
from __future__ import annotations

import copy
import dataclasses
import random
from collections import Counter
from dataclasses import dataclass, field

from . import content  # noqa: F401  registers every joker, consumable, boss, tag, voucher and deck
from . import pool
from .cards import Card, standard_deck
from .hands import HAND_ORDER, HandResult, Rules, evaluate
from .gameseed import SeedRNG
from .items import BOSSES, CONSUMABLES, DECKS, TAGS, VOUCHERS, Boss, Tag, Voucher, data, info, make
from .jokers import CATALOG, Joker, joker_now
from .modifiers import lucky_triggers
from .scoring import HAND_BASE, HandContext, Score, score_hand
from .shop import OpenPack, Shop, cost_of, pack_cards, sell_value

_BLINDS = data("blinds.json")
# Base chips per ante (the Small Blind's target; Big x1.5, Boss x2), antes 0-39, by stake scaling.
# The highest antes overflow in the game itself; the table marks them with a note, read here as unreachable.
ANTE_TABLES = {name: {int(a): float(v) if isinstance(v, (int, float)) else float("inf") for a, v in table.items()}
               for name, table in _BLINDS["full_table_antes_0_to_39"].items()}
TABLE_BY_SCALING = dict(enumerate(ANTE_TABLES, start=1))  # 1 White/Red, 2 Green/Black/Blue, 3 Purple/Orange/Gold
ANTE_BASE = ANTE_TABLES["scaling_1_white_red"]
BLIND_NAMES = ("Small Blind", "Big Blind", "Boss Blind")
BLIND_MULT = (1.0, 1.5)
BIG_REWARD = 4
WIN_ANTE = 8
FREE_ACTIONS = 40  # uses, sales and reorders allowed per decision, against agents that loop
SUIT_ORDER = ("Spades", "Hearts", "Clubs", "Diamonds")   # the game's sort order (and tie order by rank)


def hand_key(mode: str):
    """The game's hand order: by "rank", Ace high, ties Spades, Hearts, Clubs, Diamonds; or by "suit" in that order,
    rank within it. Stone cards, with neither, go last."""
    def key(c):
        rank, suit = (0, len(SUIT_ORDER)) if c.is_stone else (c.rank, SUIT_ORDER.index(c.suit))
        return (-rank, suit) if mode == "rank" else (suit, -rank)
    return key


@dataclass
class Blind:
    name: str
    kind: int  # 0 small, 1 big, 2 boss
    chips: int
    reward: int
    boss: object = None  # the ante's Boss for kind 2


@dataclass
class RunResult:
    won: bool  # beat ante 8
    ante: int  # ante reached
    blinds_beaten: int
    progress: float  # blinds passed (beaten or skipped) + share of the failed blind's target reached
    best_hand: int  # highest single-hand score
    money: int
    log: list = field(default_factory=list)
    frames: list = field(default_factory=list)


class Run:
    def __init__(self, agent, seed: int = 0, max_ante: int = 16, record: bool = False,
                 deck: str | None = None, stake: str = "White Stake", game_seed: str | None = None):
        """game_seed: a Balatro seed; the parts of the run gameseed.py models then follow the game exactly."""
        self.agent = agent
        self.seed = game_seed or seed
        self.max_ante = max_ante
        self.rng = {name: random.Random(f"{self.seed}:{name}")
                    for name in ("deck", "luck", "shop", "packs", "boss", "tags", "voucher", "misc")}
        self.seedrng = SeedRNG(game_seed) if game_seed else None
        self.deck: list[Card] = standard_deck()
        self.next_uid = len(self.deck) + 1
        self.jokers: list = []
        self.consumables: list = []
        self.vouchers: list[str] = []
        self.tags: list = []
        self.money = 4
        self.ante = 1
        self.joker_slots, self.consumable_slots = 5, 2
        self.base_hands, self.base_discards, self.base_hand_size = 4, 3, 8
        # economy and shop, changed by vouchers and decks
        self.interest_cap = 5  # dollars of interest per round at most
        self.interest_enabled = True
        self.money_per_hand, self.money_per_discard = 1, 0
        self.discount_percent = 0
        self.edition_rate = 1
        self.reroll_base = 5
        self.shop_card_slots = 2
        self.spectral_weight = 0  # Ghost Deck: Spectral cards in the shop
        self.blind_scale = 1  # Plasma Deck: 2
        self.plasma = False  # Plasma Deck: chips and mult balanced
        self.double_tag_after_boss = False  # Anaglyph Deck
        # stake
        self.stake = stake
        self.stake_rules = dict(info("stake", stake)["cumulative"])
        self.base_discards += self.stake_rules["discards_delta"]
        self.ante_table = ANTE_TABLES[TABLE_BY_SCALING[self.stake_rules["ante_scaling_table"]]]
        # history
        self.hand_levels = {h: 1 for h in HAND_BASE}
        self.hand_plays = Counter()  # this run, including the hand being scored
        self.consumables_used = Counter()  # by kind: Tarot, Planet, Spectral
        self.planets_used: set[str] = set()  # Satellite
        self.last_tarot_planet: str | None = None  # The Fool
        self.extinct: set[str] = set()  # Gros Michel once it has died
        self.boss_used = Counter()
        self.blinds_beaten = self.skips = self.hands_played = self.unused_discards = 0
        # run totals the value bot reads growth rates from (Flash Card, Red Card, Hologram, Campfire, Castle, Yorick)
        self.rerolls_done = self.packs_skipped = self.cards_added = self.cards_sold = self.cards_discarded = 0
        self.discards_made = 0
        self.cards_played = self.cards_bought = 0   # (for the end screen's stats)
        # over the hands played: face cards, Diamonds and Gold cards scored, face cards held (what Business Card, Rough
        # Gem, Golden Ticket and Reserved Parking pay on, as this run plays)
        self.pay_seen = Counter()
        self.rounds_played = 0
        self.shops_seen = 0
        self.best_hand = 0
        self.won = False
        self.lucky_triggers = 0
        self.log: list | None = [] if record else None
        self.frames: list | None = [] if record else None  # one per event, for the viewer
        # ante state
        self.ante_boss = None
        self.ante_tags: list = [None, None]
        self.ante_voucher: str | None = None
        self.vouchers_rolled = 0
        self.boss_rerolled = False
        self.played_this_ante: set[int] = set()  # card uids (The Pillar)
        # round state
        self.blind: Blind | None = None
        self.hand: list[Card] = []
        # None: the hand keeps the order it was dealt in (the bots, for now); "rank" or "suit": it is sorted after
        # every draw, as the game keeps it (a hand arranged by hand lasts until the next draw)
        self.hand_sort: str | None = None
        # True: draw after the hand that ends a round, as this engine did before 2026-10-26 (the game doesn't; Gold
        # cards drawn then were paid). Play-tab games saved before then replay with it: their money, and with Bull
        # their scores, depend on it.
        self.draw_after_win = False
        self.draw_pile: list[Card] = []
        self.round_score = 0
        self.hands_left = self.discards_left = 0
        self.round_hand_types: Counter = Counter()
        self.discards_used = 0
        self.hand_size_delta = 0  # this round only (Juggle Tag, The Manacle)
        self.last_hand: str | None = None
        self.current_shop: Shop | None = None
        self.open_pack_state: OpenPack | None = None
        self.copying = False  # Blueprint / Brainstorm is running another joker's run hook
        self.in_round = False  # a blind is being played (the hand is live)
        self.deck_name = deck
        if deck is not None:
            if deck not in DECKS:
                raise ValueError(f"deck {deck!r} has no code yet")
            DECKS[deck]().apply(self)
        self.starting_deck_size = len(self.deck)  # Erosion

    # ---- derived state ------------------------------------------------------------------------------
    def active_jokers(self) -> list:
        return [j for j in self.jokers if not (j.disabled or j.perished)]

    def each_joker(self):
        """Active jokers, left to right, for telling them about an event. A joker destroyed or debuffed by an
        earlier one is skipped, and each reacts as itself even when a copied effect (Blueprint) caused the event."""
        was, self.copying = self.copying, False
        try:
            for j in list(self.active_jokers()):
                if j in self.jokers and not (j.disabled or j.perished):
                    yield j
        finally:
            self.copying = was

    def _rule(self, name: str) -> bool:
        return any(j.rules.get(name) for j in self.active_jokers())

    @property
    def rules(self) -> Rules:
        return Rules(self._rule("four_fingers"), self._rule("shortcut"), self._rule("smeared"), self._rule("splash"))

    @property
    def smeared(self) -> bool:
        return self._rule("smeared")

    @property
    def pareidolia(self) -> bool:
        return self._rule("pareidolia")

    @property
    def showman(self) -> bool:
        return self._rule("showman")

    @property
    def probability_scale(self) -> int:
        return 2 ** sum(j.name == "Oops! All 6s" for j in self.active_jokers())

    @property
    def hand_size(self) -> int:
        return max(1, self.base_hand_size + self.hand_size_delta + sum(j.hand_size_bonus for j in self.active_jokers()))

    @property
    def debt_limit(self) -> int:
        return -sum(j.debt for j in self.active_jokers())

    @property
    def active_boss(self):
        b = self.blind
        return b.boss if b is not None and b.boss is not None and not b.boss.disabled else None

    @property
    def round_hands_played(self) -> int:
        """Hands played this round, including the one being scored (1 during the first hand)."""
        return sum(self.round_hand_types.values())

    def has_voucher(self, name: str) -> bool:
        return name in self.vouchers

    def has_joker(self, name: str) -> bool:
        return any(j.name == name for j in self.active_jokers())

    def joker_room(self, joker=None) -> bool:
        if joker is not None and joker.edition == "Negative":
            return True
        return sum(j.edition != "Negative" for j in self.jokers) < self.joker_slots

    def consumable_room(self, item=None) -> bool:
        if item is not None and item.edition == "Negative":
            return True
        return sum(c.edition != "Negative" for c in self.consumables) < self.consumable_slots

    def sell_value(self, item) -> int:
        return sell_value(self, item)

    def most_played_hand(self) -> str | None:
        """Most played this run; ties go to the higher hand; None before any hand is played."""
        best = max(HAND_ORDER, key=lambda h: (self.hand_plays[h], -HAND_ORDER.index(h)))
        return best if self.hand_plays[best] else None

    def shop_weights(self) -> dict[str, float]:
        v = self.has_voucher
        return {"Joker": 20,
                "Tarot": 32 if v("Tarot Tycoon") else 9.6 if v("Tarot Merchant") else 4,
                "Planet": 32 if v("Planet Tycoon") else 9.6 if v("Planet Merchant") else 4,
                "Playing card": 4 if v("Magic Trick") else 0,
                "Spectral": self.spectral_weight}

    def cards_at(self, indexes) -> list[Card]:
        return [self.hand[i] for i in sorted({i for i in indexes if 0 <= i < len(self.hand)})]

    # ---- recording ----------------------------------------------------------------------------------
    def emit(self, *event):
        if self.log is not None:
            self.log.append((self.ante, self.blind.name if self.blind else None, *event))

    def frame(self, kind: str, **extra) -> None:
        """Record what the viewer shows after an event: the whole visible state plus event details."""
        if self.frames is None:
            return
        b = self.blind
        boss = b.boss if b else None
        self.frames.append({
            "kind": kind, "ante": self.ante, "money": self.money,
            "blind": {"name": boss.name if boss else b.name, "kind": b.kind, "chips": b.chips, "reward": b.reward,
                      "disabled": bool(boss and boss.disabled)} if b else None,
            "round_score": self.round_score, "hands_left": self.hands_left, "discards_left": self.discards_left,
            "hand": [c.to_dict() for c in self.hand], "deck_left": len(self.draw_pile), "deck_size": len(self.deck),
            "jokers": [{"name": j.name, "edition": j.edition, "sell": self.sell_value(j), "eternal": j.eternal,
                        "perishable": j.perishable, "rental": j.rental, "debuffed": j.perished or j.disabled,
                        "now": joker_now(j, self), **({"jiggle": True} if j.jiggles(self) else {})}
                       for j in self.jokers],
            "consumables": [{"name": c.name, "kind": c.kind, "edition": c.edition} for c in self.consumables],
            "joker_slots": self.joker_slots, "consumable_slots": self.consumable_slots, "hand_size": self.hand_size,
            "round": self.rounds_played + 1,
            "vouchers": list(self.vouchers), "tags": [t.name for t in self.tags],
            "hand_levels": dict(self.hand_levels), "hand_plays": {h: n for h, n in self.hand_plays.items() if n},
            "ante_blinds": self.ante_blinds(kind == "select"), **self._deck_change(), **extra})

    def _deck_change(self) -> dict:
        """The deck for a frame, only when it differs from the last frame's (the viewer carries it forward)."""
        cards = self.deck_cards()
        if cards == getattr(self, "_framed_deck", None):
            return {}
        self._framed_deck = cards
        return {"deck_cards": cards}

    def ante_blinds(self, choosing: bool = False) -> list[dict]:
        """This ante's three blinds for the viewer's Run Info and blind choice: name, target, reward and the boss's
        effect (the next ante's boss isn't drawn until it starts, so in the shop after a boss it shows as "Boss
        Blind"; while `choosing` the next blind, it is this ante's)."""
        boss_known = self.ante_boss is not None and (choosing or not (self.blind is not None and self.blind.kind == 2 and not self.in_round))
        out = []
        for kind in range(3):
            if kind == 2 and not boss_known:
                base = self.ante_table[min(max(self.ante, 0), max(self.ante_table))]
                out.append({"name": BLIND_NAMES[2], "kind": 2, "chips": int(base * 2 * self.blind_scale), "reward": 5, "effect": ""})
                continue
            b = self.make_blind(kind)
            out.append({"name": b.boss.name if b.boss else b.name, "kind": kind, "chips": b.chips, "reward": b.reward,
                        "effect": info("boss", b.boss.name)["effect"] if b.boss else ""})
        return out

    def deck_cards(self) -> list[list]:
        """Every card of the deck for the viewer's deck view, compactly: uid, rank, suit, enhancement, edition, seal,
        extra chips, still to draw (1/0; out of a round every card is), debuffed (1/0)."""
        pile = {id(c) for c in self.draw_pile} if self.in_round else None
        return [[c.uid, c.rank, c.suit, c.enhancement, c.edition, c.seal, c.bonus_chips,
                 int(pile is None or id(c) in pile), int(c.debuffed)] for c in self.deck]

    def on_lucky_trigger(self):
        self.lucky_triggers += 1

    # ---- the run ------------------------------------------------------------------------------------
    def make_blind(self, kind: int) -> Blind:
        base = self.ante_table[min(max(self.ante, 0), max(self.ante_table))]
        if kind < 2:
            reward = self.stake_rules["small_blind_reward"] if kind == 0 else BIG_REWARD
            return Blind(BLIND_NAMES[kind], kind, int(base * BLIND_MULT[kind] * self.blind_scale), reward)
        boss = self.ante_boss
        mult = min(boss.chip_mult, 2) if boss.disabled else boss.chip_mult  # disabled Wall / Violet Vessel go back to 2x
        return Blind(BLIND_NAMES[2], 2, int(base * mult * self.blind_scale), boss.reward, boss)

    def position(self, kind: int) -> int:
        """Blinds passed before this one: 3 per ante."""
        return 3 * (self.ante - 1) + kind

    def play(self) -> RunResult:
        while self.ante <= self.max_ante:
            self.start_ante()
            for kind in (0, 1, 2):
                self.blind = self.make_blind(kind)
                self.frame("select", skip_tags=[t.name if t else None for t in self.ante_tags])   # choose your next blind
                if kind == 2:
                    self.offer_boss_reroll()
                elif self.agent.skip_blind(self, self.blind, self.ante_tags[kind]):
                    self.skip(kind)
                    continue
                if not self.play_round():
                    return self.finish(self.position(kind) + min(1.0, self.round_score / self.blind.chips))
                self.blinds_beaten += 1
                self.end_round()
                self.leave_round()
                if kind == 2:
                    self.boss_defeated()
                self.shop()
        return self.finish(float(3 * self.max_ante))

    def finish(self, progress: float) -> RunResult:
        most = self.hand_plays.most_common(1)
        self.frame("end", won=self.won, progress=progress, blinds_beaten=self.blinds_beaten, best_hand=self.best_hand,
                   stats={"most_played": list(most[0]) if most else None, "cards_played": self.cards_played,
                          "cards_discarded": self.cards_discarded, "cards_bought": self.cards_bought,
                          "rerolls": self.rerolls_done, "rounds": self.rounds_played, "seed": str(self.seed),
                          "max_ante": self.max_ante})
        return RunResult(self.won, self.ante, self.blinds_beaten, progress, self.best_hand, self.money, self.log or [],
                         self.frames or [])

    def start_ante(self) -> None:
        """A new ante rolls its boss and the two skip tags (and the run's first voucher)."""
        self.played_this_ante = set()
        self.boss_rerolled = False
        if self.vouchers_rolled == 0:
            self.roll_voucher()
        if self.seedrng:
            self.ante_boss = make(BOSSES, Boss, self.seedrng.boss(self))
            self.ante_tags = [make(TAGS, Tag, self.seedrng.tag(self)) for _ in range(2)]
            for t in self.ante_tags:
                t.setup(self)
            return
        self.ante_boss = pool.random_boss(self, self.rng["boss"])
        self.ante_tags = [pool.random_tag(self, self.rng["tags"]) for _ in range(2)]

    def roll_voucher(self) -> None:
        """The shop's voucher for this ante: rolled when the run starts and when a boss falls."""
        self.vouchers_rolled += 1
        self.ante_voucher = self.seedrng.voucher(self) if self.seedrng else pool.random_voucher(self, self.rng["voucher"])

    def reroll_boss(self, paid: bool = True) -> None:
        if paid:
            self.money -= 10
            self.boss_rerolled = True
        self.ante_boss = (make(BOSSES, Boss, self.seedrng.boss(self)) if self.seedrng
                          else pool.random_boss(self, self.rng["boss"]))
        if self.blind is not None and self.blind.kind == 2:
            self.blind = self.make_blind(2)
        self.emit("boss reroll", self.ante_boss.name)
        self.frame("boss_reroll", boss=self.ante_boss.name)

    def offer_boss_reroll(self) -> None:
        for _ in range(20):
            can = self.has_voucher("Retcon") or (self.has_voucher("Director's Cut") and not self.boss_rerolled)
            if not can or self.money - 10 < self.debt_limit or not self.agent.reroll_boss(self, self.ante_boss):
                return
            self.reroll_boss()

    def skip(self, kind: int) -> None:
        self.skips += 1
        tag = self.ante_tags[kind]
        self.emit("skip", self.blind.name, tag.name if tag else None)
        self.frame("skip", tag=tag.name if tag else None)
        if tag is not None:
            self.gain_tag(tag)

    def gain_tag(self, tag: Tag) -> None:
        """Take a tag; each held Double Tag turns into a copy of it."""
        doubles = [t for t in self.tags if t.name == "Double Tag"] if tag.name != "Double Tag" else []
        for d in doubles:
            self.tags.remove(d)
        for t in [tag] + [copy.deepcopy(tag) for _ in doubles]:
            self.emit("tag", t.name)
            if not t.on_gain(self):
                self.tags.append(t)

    # ---- a round ------------------------------------------------------------------------------------
    def play_round(self) -> bool:
        self.in_round = True
        self.round_score = 0
        self.hand_size_delta = 0
        self.round_hand_types = Counter()
        self.discards_used = 0
        self.hands_left = max(1, self.base_hands + sum(j.hands_bonus for j in self.active_jokers()))
        self.discards_left = max(0, self.base_discards + sum(j.discards_bonus for j in self.active_jokers()))
        for t in list(self.tags):
            if t.on_blind_select(self, self.blind):
                self.tags.remove(t)
        if self.active_boss:
            self.active_boss.on_select(self)
        for j in self.each_joker():
            j.on_blind_select(self, self.blind)
        if self.seedrng:
            self.draw_pile = self.seedrng.shuffle(self, self.deck)
        else:
            self.draw_pile = list(self.deck)
            self.rng["deck"].shuffle(self.draw_pile)
        self.hand = []
        self.draw("start")
        for j in self.each_joker():
            j.on_round_start(self)
        boss = self.blind.boss
        self.emit("blind", boss.name if boss else self.blind.name, self.blind.chips)
        self.frame("blind")
        won = False
        for _ in range(500):  # guards against agents that never play
            if self.round_score >= self.blind.chips:
                won = True
                break
            if self.hands_left <= 0 or not self.hand:   # no cards to play (hand size 0, deck empty): lost
                break
            action = self.ask(self.agent.round_action)
            if not self.hand:                           # a consumable used up the hand, and no cards are left to deal
                break
            if action[0] == "discard" and self.discards_left > 0:
                self.discard(action[1])
            else:
                self.play_hand(action[1] if action[0] in ("play", "discard") and len(action) > 1 else [0])
        if not won:
            won = any(j.on_fail(self) for j in self.each_joker())
            if won:
                self.emit("saved")
                self.frame("saved")
        self.rounds_played += 1
        self.end_round_cleanup()
        return won

    def ask(self, decide, *args) -> tuple:
        """The agent's next action that isn't a free one (use, sell, reorder), applying those as they come."""
        action = decide(self, *args)
        for _ in range(FREE_ACTIONS):
            if not self.free_action(action):
                return action
            action = decide(self, *args)
        return action

    def free_action(self, action) -> bool:
        kind = action[0] if action else None
        if kind == "use":
            self.use_consumable(action[1], action[2] if len(action) > 2 else [])
            if self.in_round and not self.hand and self.draw_pile:
                # A hand used up mid-blind (Immolate on 5 cards) is dealt again, costing no hand or discard (players'
                # reports, steamcommunity.com/app/2379780/discussions/0/7410182519535314914; the wiki doesn't say).
                self.draw("refill")
                self.frame("draw")
        elif kind == "sell_joker":
            self.sell_joker(action[1])
        elif kind == "sell_consumable":
            self.sell_consumable(action[1])
        elif kind == "order_jokers":
            before = list(self.jokers)
            self.jokers = self._permute(self.jokers, action[1])
            if self.jokers != before:
                self.emit("order", [j.name for j in self.jokers])
                self.frame("order")
        elif kind == "order_hand":
            self.hand = self._permute(self.hand, action[1])
        elif kind == "sort_hand":
            if len(action) > 1 and action[1] in ("rank", "suit"):
                self.hand_sort = action[1]
                self.sort_hand()
        else:
            return False
        return True

    @staticmethod
    def _permute(items: list, order) -> list:
        order = list(order)
        return [items[i] for i in order] if sorted(order) == list(range(len(items))) else items

    def selection(self, indexes) -> list[int]:
        """Valid, distinct positions, at most 5, including a card the boss forces (Cerulean Bell)."""
        idx = sorted({i for i in indexes if 0 <= i < len(self.hand)})[:5] or [0]
        forced = self.active_boss.forced_selection(self) if self.active_boss else None
        if forced is not None and forced not in idx:
            idx = sorted(idx[:4] + [forced])
        return idx

    def draw(self, when: str) -> None:
        """Fill the hand (The Serpent draws exactly 3 after a play or discard); the boss decides which
        drawn cards are face down and which cards are debuffed."""
        boss = self.active_boss
        n = self.hand_size - len(self.hand)
        if boss and when != "start":
            n = boss.draw_count(self, n, when)
        drawn = []
        for _ in range(max(0, n)):
            if not self.draw_pile:
                break
            drawn.append(self.draw_pile.pop())
        self.hand.extend(drawn)
        self.sort_hand()
        if boss:
            for c in drawn:
                c.face_down = boss.face_down(self, c, when)
        self.refresh_debuffs()
        if boss:
            boss.after_draw(self)

    def refresh_debuffs(self) -> None:
        boss = self.active_boss
        for c in self.hand + self.draw_pile:
            c.debuffed = bool(boss) and boss.debuffs(self, c)

    def play_hand(self, indexes) -> int:
        before = [c.to_dict() for c in self.hand] if self.frames is not None else None
        picked = self.selection(indexes)
        played = [self.hand[i] for i in picked]
        self.hand = [c for i, c in enumerate(self.hand) if i not in picked]
        boss = self.active_boss
        if boss:
            boss.press_play(self, played)
        for c in played:
            c.face_down = False
        result = evaluate(played, self.rules)
        name = result.name
        allowed = boss is None or boss.allows(self, result, played)
        self.hands_left -= 1
        self.hands_played += 1
        self.cards_played += len(played)
        self.hand_plays[name] += 1
        self.round_hand_types[name] += 1
        self.last_hand = name
        ctx = HandContext(self, played, list(self.hand), result, self.rng["luck"])
        if allowed:
            live = [played[i] for i in result.scoring if not played[i].debuffed]
            seen = self.pay_seen
            seen["faces"] += sum(c.is_face(self.pareidolia) for c in live)
            seen["diamonds"] += sum(c.has_suit("Diamonds", self.smeared) for c in live)
            seen["gold"] += sum(c.enhancement == "Gold" for c in live)
            seen["held faces"] += sum(not c.debuffed and c.is_face(self.pareidolia) for c in self.hand)
            first = played[result.scoring[0]] if result.scoring else None
            if first is not None and first.enhancement == "Lucky" and not first.debuffed:
                seen["lucky first"] += 1
            if any(c.enhancement == "Lucky" for c in live):     # Lucky cards scored, retriggers too: the rolls of
                seen["lucky"] += lucky_triggers(self, played, result)   # their $20 this run's rounds make
            if boss:
                boss.before_score(self, result)
            score = score_hand(ctx, boss=boss)
            for j in self.each_joker():
                j.after(ctx, score)
        else:
            score = Score(0, 0, log=[(name, "not allowed", 0)])
        total = score.total
        self.round_score += total
        self.money += score.money
        self.best_hand = max(self.best_hand, total)
        self.played_this_ante.update(c.uid for c in played)
        self.emit("play", [c.label() for c in played], name, total)
        if ctx.destroyed:
            self.destroy_cards(ctx.destroyed)
        if self.frames is not None:
            self.frame("play", before=before, picked=picked, played=[c.to_dict() for c in played], hand_name=name,
                       level=self.hand_levels[name], scoring=result.scoring, chips=score.chips, mult=score.mult,
                       total=total, earned=score.money, score_log=score.log, score_trail=score.trail, score_who=score.who,
                       destroyed=[c.label() for c in ctx.destroyed])
        if boss:
            if hasattr(boss, "noticed"):                 # Amber Acorn: what the hand showed of the face-down jokers
                boss.noticed(self, score)
            boss.after_hand(self)
        if not self.draw_after_win and (self.round_score >= self.blind.chips or self.hands_left < 1):
            return total     # the round is over: nothing is drawn, and the cards held stay for its end (Gold cards)
        self.draw("play")
        if self.frames is not None:
            self.frame("draw")
        return total

    def discard(self, indexes) -> None:
        before = [c.to_dict() for c in self.hand] if self.frames is not None else None
        picked = self.selection(indexes)
        cards = [self.hand[i] for i in picked]
        self.hand = [c for i, c in enumerate(self.hand) if i not in picked]
        first = self.discards_used == 0
        self.discards_left -= 1
        self.discards_used += 1
        self.cards_discarded += len(cards)
        self.discards_made += 1
        for j in self.each_joker():
            j.on_discard(self, cards, first)
        for c in cards:
            if c.seal == "Purple" and not c.debuffed:
                self.create_consumable("Tarot", source="8ba")
        self.emit("discard", [c.label() for c in cards])
        self.frame("discard", before=before, picked=picked, discarded=[c.to_dict() for c in cards])
        self.draw("discard")
        self.frame("draw")

    def end_round_cleanup(self) -> None:
        """The round is over: debuffs, face-down cards and disabled jokers clear."""
        for c in self.deck:
            c.debuffed = c.face_down = False
        for j in self.jokers:
            j.disabled = False
        self.hand_size_delta = 0

    def leave_round(self) -> None:
        """After cash out the hand goes back into the deck, so shop cards can't target it."""
        self.in_round = False
        self.hand = []

    # ---- after a won round --------------------------------------------------------------------------
    def end_round(self) -> None:
        """Held Gold cards pay $3 and Blue seals make the Planet of the last hand; jokers' end-of-round
        effects; perishable and rental stickers; then cash out."""
        ctx = HandContext(self, [], list(self.hand), HandResult("High Card", [], set()), self.rng["luck"])
        jokers = self.active_jokers()
        paid = []                                       # (hand position, $) of each Gold card held, for the viewer
        for i, c in enumerate(self.hand):
            if c.debuffed:
                continue
            triggers = 1 + (c.seal == "Red") + sum(j.held_retriggers(ctx, c) for j in jokers)
            if c.enhancement == "Gold":
                self.money += 3 * triggers
                paid.append((i, 3 * triggers))
            if c.seal == "Blue" and self.last_hand:
                planet = pool.planet_for(self.last_hand)
                for _ in range(triggers):
                    if planet and self.consumable_room():
                        self.consumables.append(planet())
        if paid:
            self.emit("held money", sum(m for _, m in paid))
            self.frame("held", paid=paid, earned=sum(m for _, m in paid))
        joker_money = sum(j.end_of_round(self, self.blind) for j in self.each_joker())
        for j in self.jokers:
            if j.perishable and not j.perished:
                j.perish_rounds -= 1
                j.perished = j.perish_rounds <= 0
            if j.rental:
                self.money -= 3
        self.unused_discards += self.discards_left
        self.cash_out(joker_money)

    def cash_out(self, joker_money: int = 0) -> None:
        parts = [("blind", self.blind.reward), ("hands", self.hands_left * self.money_per_hand),
                 ("discards", self.discards_left * self.money_per_discard), ("jokers", joker_money)]
        if self.interest_enabled:
            parts.append(("interest", min(self.interest_cap, max(0, self.money) // 5)))
        earned = sum(amount for _, amount in parts)
        self.money += earned
        self.emit("cash out", earned, self.money)
        self.frame("cash_out", earned=earned, parts=[p for p in parts if p[1]], cap=self.interest_cap)

    def boss_defeated(self) -> None:
        for t in list(self.tags):
            if t.on_boss_defeated(self):
                self.tags.remove(t)
        for j in self.each_joker():
            j.on_boss_defeated(self)
        if self.double_tag_after_boss:
            self.gain_tag(make(TAGS, Tag, "Double Tag"))
        if self.ante == WIN_ANTE:
            self.won = True
        # As in the game, the next ante starts as the boss falls: cash out and the shop after a boss belong to
        # it (its shop streams, packs and voucher).
        self.ante += 1
        self.roll_voucher()

    def shop(self) -> None:
        shop = self.current_shop = Shop(self)
        self.shops_seen += 1
        self.emit("shop")
        self.frame("shop", shop=shop.to_dict())
        for _ in range(200):
            action = self.ask(self.agent.shop_action, shop)
            if action[0] in ("buy", "buy_use"):
                where, i = (action[1], action[2]) if action[0] == "buy" and len(action) >= 3 else ("card", action[1])
                offers = {"card": shop.cards, "pack": shop.packs, "voucher": shop.vouchers}.get(where, [])
                did = f"Bought {offers[i].name} for ${cost_of(self, offers[i])}" if 0 <= i < len(offers) else ""
                use = action[0] == "buy_use"
                act = {"do": "buy", "use": use, "item": offers[i].to_dict(self)} if did else None
                ok = shop.buy(where, i, use=use, targets=action[2] if use and len(action) > 2 else [])
                did += " and used it" if use else ""
            elif action[0] == "reroll":
                did = f"Rerolled for ${shop.reroll_cost}"
                act = {"do": "reroll", "cost": shop.reroll_cost}
                ok = shop.reroll()
            else:
                break
            self.frame("shop", shop=shop.to_dict(), did=did if ok else f"Couldn't: {did or action[0]}",
                       act=act if ok else None)
        for j in self.each_joker():
            j.on_shop_close(self, shop)
        self.current_shop = None

    def open_pack(self, pack) -> None:
        """Open a booster pack: pick from it (Arcana and Spectral packs deal a hand to use cards on), or skip."""
        rng = self.rng["packs"]
        for j in self.each_joker():
            j.on_pack_open(self, pack)
        state = self.open_pack_state = OpenPack(pack, pack_cards(self, pack, rng), pack.chosen)
        saved = self.hand
        if pack.kind in ("Arcana", "Spectral"):
            pile = list(self.deck)
            rng.shuffle(pile)
            self.hand = pile[:self.hand_size]
            self.sort_hand()
        self.emit("open", pack.name, [getattr(x, "name", None) or x.label() for x in state.cards])
        self.frame("pack", pack=state.to_dict(self), did=f"Opened a {pack.name}")
        skipped = True
        while state.picks_left > 0 and state.cards:
            action = self.ask(self.agent.pack_action, state)
            picked = action[0] == "pick" and self.take_from_pack(state, action[1], action[2] if len(action) > 2 else [])
            if not picked:
                break
            state.picks_left -= 1
            skipped = False
            self.frame("pack", pack=state.to_dict(self), did=f"Picked {picked}")
        if skipped:
            self.packs_skipped += 1
            self.frame("pack", pack=state.to_dict(self), did=f"Skipped the {pack.name}")
            for j in self.each_joker():
                j.on_pack_skip(self, pack)
        self.hand = saved
        self.open_pack_state = None

    def take_from_pack(self, state: OpenPack, i: int, targets) -> str | None:
        """Take card i from the open pack; returns its name, or None if it can't be taken."""
        if not 0 <= i < len(state.cards):
            return None
        item = state.cards[i]
        if isinstance(item, Card):
            self.add_cards([item])
        elif hasattr(item, "use"):
            cards = self.cards_at(targets)
            if not item.can_use(self, cards):
                return None
            self.apply_consumable(item, cards)
        else:
            if not self.joker_room(item):
                return None
            self.add_joker(item)
        state.cards.pop(i)
        name = getattr(item, "name", None) or item.label()
        self.emit("pick", name)
        return name

    # ---- for content: jokers, consumables, tags, vouchers, decks call these -------------------------
    def chance(self, n: int, stream: str = "luck") -> bool:
        """A 1-in-n roll; each Oops! All 6s doubles the odds."""
        return self.rng[stream].random() * n < self.probability_scale

    def level_up(self, hand: str, n: int = 1) -> None:
        self.hand_levels[hand] = max(1, self.hand_levels[hand] + n)

    def add_joker(self, joker) -> None:
        self.jokers.append(joker)
        joker.on_added(self)
        self.emit("joker", joker.name)

    def create_joker(self, rarity: str | None = None, name: str | None = None, edition: str | None = None,
                     source: str | None = None):
        """A new joker if there is room (Judgement, Riff-raff, The Soul, Wraith, Top-up Tag); None otherwise.
        A named joker gets `edition`; a random one rolls its own unless `edition` is given. `source` is the
        game's key for the effect ("jud", "rif", ...): with a game seed the joker is the game's own."""
        if name is None and source and self.seedrng and rarity != "Legendary":
            d = self.seedrng.created_joker(self, source, rarity)
            j = CATALOG[d["name"]](edition or d["edition"])
            if not self.joker_room(j):
                return None
            self.add_joker(j)
            return j
        if name is not None:
            j = CATALOG[name](edition)
        elif rarity == "Legendary" and self.seedrng:          # The Soul
            d = self.seedrng.legendary(self)
            j = CATALOG[d["name"]](edition or d["edition"])
        else:
            j = pool.random_joker(self, self.rng["misc"], rarity)
            if edition is not None:
                j.edition = edition
        if not self.joker_room(j):
            return None
        self.add_joker(j)
        return j

    def remove_joker(self, joker) -> bool:
        """Destroy a joker (Madness, Ceremonial Dagger, Hex, Ankh); Eternal jokers survive."""
        if joker.eternal or joker not in self.jokers:
            return False
        self.jokers.remove(joker)
        self.emit("joker destroyed", joker.name)
        return True

    def create_consumable(self, kind: str | None = None, name: str | None = None, edition: str | None = None,
                          source: str | None = None):
        """A new Tarot / Planet / Spectral (random of `kind`, or `name`) if there is room; None otherwise.
        `source`: the game's key for the effect ("emp", "8ba", ...), used with a game seed."""
        if name is None and source and self.seedrng:
            if not self.consumable_room():
                return None
            name = self.seedrng.created_consumable(self, kind, source)["name"]
        c = CONSUMABLES[name]() if name else pool.random_consumable(self, kind, self.rng["misc"])
        if c is None:
            return None
        c.edition = edition
        if not self.consumable_room(c):
            return None
        self.consumables.append(c)
        return c

    def use_consumable(self, i: int, targets) -> bool:
        if not 0 <= i < len(self.consumables):
            return False
        c = self.consumables[i]
        cards = self.cards_at(targets)
        if not c.can_use(self, cards):
            return False
        self.consumables.pop(i)
        self.apply_consumable(c, cards)
        return True

    def apply_consumable(self, c, cards: list[Card]) -> None:
        selected = [x.to_dict() for x in cards] if self.frames is not None else None
        c.use(self, cards)
        self.consumables_used[c.kind] += 1
        if c.kind == "Planet":
            self.planets_used.add(c.name)
        if c.kind in ("Tarot", "Planet") and c.name != "The Fool":
            self.last_tarot_planet = c.name
        for j in self.each_joker():
            j.on_consumable_used(self, c)
        if self.in_round:
            self.refresh_debuffs()
        self.emit("use", c.name, [x.label() for x in cards])
        self.frame("use", used=c.name, targets=selected)

    def sell_joker(self, i: int) -> bool:
        if not 0 <= i < len(self.jokers) or self.jokers[i].eternal:
            return False
        j = self.jokers.pop(i)
        value = self.sell_value(j)
        self.money += value
        j.on_sold(self)
        self._sold(j, value)
        return True

    def sell_consumable(self, i: int) -> bool:
        if not 0 <= i < len(self.consumables):
            return False
        c = self.consumables.pop(i)
        value = self.sell_value(c)
        self.money += value
        self._sold(c, value)
        return True

    def _sold(self, item, value: int) -> None:
        self.cards_sold += 1
        for j in self.each_joker():
            j.on_sell(self, item)
        if self.active_boss:
            self.active_boss.on_sell(self, item)
            self.refresh_debuffs()
        self.emit("sell", item.name, value)
        self.frame("sell", item={"name": item.name, "kind": "Joker" if isinstance(item, Joker) else item.kind,
                                 "edition": item.edition}, value=value)

    def disable_boss(self) -> None:
        """Chicot, Luchador: the boss effect ends; requirements, hands and hand size go back to normal."""
        boss = self.active_boss
        if boss is None:
            return
        boss.disabled = True
        boss.on_disable(self)
        self.blind.chips = self.make_blind(2).chips
        for c in self.hand + self.draw_pile:
            c.face_down = False
        self.refresh_debuffs()
        self.emit("boss disabled", boss.name)

    def redeem_voucher(self, name: str) -> None:
        self.vouchers.append(name)
        if name == self.ante_voucher:
            self.ante_voucher = None
        make(VOUCHERS, Voucher, name).apply(self)
        self.emit("voucher", name)

    def set_deck(self, cards: list[Card]) -> None:
        """Replace the whole deck (Abandoned, Checkered, Erratic decks), giving each card its own uid."""
        self.deck = []
        self.add_cards(cards)

    def copy_card(self, card: Card) -> Card:
        """A copy with its own identity (Cryptid, DNA, Certificate)."""
        return dataclasses.replace(card, debuffed=False, face_down=False)

    def add_cards(self, cards: list[Card], to_hand: bool = False) -> None:
        """New playing cards join the deck (and the hand, during a round)."""
        for c in cards:
            c.uid = self.next_uid
            self.next_uid += 1
        self.deck.extend(cards)
        self.cards_added += len(cards)
        if to_hand:
            self.hand.extend(cards)
            self.sort_hand()
        for j in self.each_joker():
            j.on_cards_added(self, cards)

    def sort_hand(self) -> None:
        """Sort the hand as the game keeps it (hand_sort, see hand_key); nothing without a hand_sort."""
        if self.hand_sort:
            self.hand.sort(key=hand_key(self.hand_sort))

    def destroy_cards(self, cards: list[Card]) -> None:
        gone = {c.uid for c in cards}
        self.deck = [c for c in self.deck if c.uid not in gone]
        self.hand = [c for c in self.hand if c.uid not in gone]
        self.draw_pile = [c for c in self.draw_pile if c.uid not in gone]
        for j in self.each_joker():
            j.on_cards_destroyed(self, cards)
