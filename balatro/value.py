"""A value network for whole runs: how far a run is likely to get from where it stands, learned from how many
simulated runs actually ended (scripts/selfplay.py plays and records them, scripts/train_value.py fits it).

The value bot (strategy.py) judges a purchase by how much it raises the score of today's hands, plus fixed
weights. That is short-sighted: it buys flat +Mult early, sits on money, and rarely builds the xMult and hand
levels that late antes need. ValueNetBot instead tries every option of a shop or pack decision on a copy of
the run (with a game seed the outcome is exact: what a pack holds, what a reroll brings), describes each
resulting position with `features`, and takes the one the network expects to go furthest (progress: blinds
beaten, so 24 is ante 8 beaten). Rounds are still played by the value bot's round play.

Features (FEATURE_NAMES): the network's 84 context facts (neural.facts: ante, money, slots, build power, the
deck's suits, ranks, enhancements, seals and editions, hand levels, vouchers), where the run is (the next
blind), this ante's boss, each joker owned and its edition, each consumable held, and hands and discards per
round, interest cap and money beyond $100.
"""
from __future__ import annotations

import copy
import math
import random
from pathlib import Path

import numpy as np

from .items import Consumable, entries
from .jokers import Joker
from .neural import CONSUMABLE_INDEX, CONSUMABLES, FACTS, JOKER_INDEX, JOKERS, facts
from .shop import cost_of
from .strategy import ValueBot

BOSSES = [b["name"] for b in entries("boss")]
BOSS_INDEX = {n: i for i, n in enumerate(BOSSES)}
EDITIONS = ["Foil", "Holographic", "Polychrome", "Negative"]
FEATURE_NAMES = (list(FACTS) + ["next blind / 24", "next is Small", "next is Big", "next is Boss"]
                 + [f"boss {b}" for b in BOSSES] + [f"owns {j}" for j in JOKERS]
                 + [f"jokers {e}" for e in EDITIONS] + [f"holds {c}" for c in CONSUMABLES]
                 + ["hands per round / 4", "discards per round / 3", "interest cap / 5", "log money / 5"])
N_FEATURES = len(FEATURE_NAMES)
_J0 = len(FACTS) + 4 + len(BOSSES)
_E0 = _J0 + len(JOKERS)
_C0 = _E0 + len(EDITIONS)
_R0 = _C0 + len(CONSUMABLES)


def features(run, power: float) -> np.ndarray:
    """A position as the value network reads it (FEATURE_NAMES), at a shop or pack decision."""
    x = np.zeros(N_FEATURES, dtype=np.float32)
    x[:len(FACTS)] = facts(run, power)
    nxt = (run.blind.kind + 1) % 3 if run.blind is not None else 0     # the ante moves on as the boss falls
    k = len(FACTS)
    x[k] = (3 * (run.ante - 1) + nxt) / 24
    x[k + 1 + nxt] = 1.0
    boss = getattr(run.ante_boss, "name", None)
    if boss in BOSS_INDEX:
        x[k + 4 + BOSS_INDEX[boss]] = 1.0
    for j in run.jokers:
        if j.name in JOKER_INDEX:
            x[_J0 + JOKER_INDEX[j.name]] += 1.0
        if j.edition in EDITIONS:
            x[_E0 + EDITIONS.index(j.edition)] += 1.0
    for c in run.consumables:
        if c.name in CONSUMABLE_INDEX:
            x[_C0 + CONSUMABLE_INDEX[c.name]] += 1.0
    active = run.active_jokers()
    x[_R0] = max(1, run.base_hands + sum(j.hands_bonus for j in active)) / 4
    x[_R0 + 1] = max(0, run.base_discards + sum(j.discards_bonus for j in active)) / 3
    x[_R0 + 2] = run.interest_cap / 5
    x[_R0 + 3] = math.log1p(max(0, run.money)) / 5
    return x


class ValueNet:
    """The trained network (an .npz from scripts/train_value.py), run with numpy: inputs are standardised, then
    layers of ReLU units, then one output, the expected progress."""

    def __init__(self, path):
        d = np.load(path)
        self.path = str(path)
        self.mean, self.std = d["mean"], d["std"]
        n = sum(1 for k in d.files if k.startswith("W"))
        self.layers = [(d[f"W{i}"], d[f"b{i}"]) for i in range(n)]
        if self.mean.shape[0] != N_FEATURES:
            raise ValueError(f"{path} was trained on {self.mean.shape[0]} features, not {N_FEATURES}")

    def predict(self, x: np.ndarray) -> np.ndarray:
        h = (np.atleast_2d(x) - self.mean) / self.std
        for k, (w, b) in enumerate(self.layers):
            h = h @ w + b
            if k < len(self.layers) - 1:
                np.maximum(h, 0, out=h)
        return h[:, 0]


class ValueNetBot(ValueBot):
    """The value bot's round play, with shop and pack decisions made by the value network: each option is
    tried on a copy of the run and the position the network rates highest is taken. `epsilon` > 0 takes a
    random option that often instead (for self-play, so the games show more than one way to play)."""

    net = None                     # no correction network: the value network decides
    epsilon = 0.0
    real = None                    # the run being played (set by self-play): copies tried never explore
    MARGIN = 0.02                  # progress an option must beat leaving or skipping by

    def __init__(self, value: ValueNet, epsilon: float = 0.0, seed: int = 0):
        self.value, self.epsilon, self.rng = value, epsilon, random.Random(seed)

    def _rate(self, runs) -> np.ndarray:
        return self.value.predict(np.stack([features(r, self.power(r)) for r in runs]))

    def _choose(self, run, options, values, stay: float):
        """The best option (index), or None to stay put; random with chance epsilon in the run being played."""
        if self.epsilon and run is self.real and self.rng.random() < self.epsilon:
            k = self.rng.randrange(len(options) + 1)
            return None if k == len(options) else k
        if not options:
            return None
        k = int(np.argmax(values))
        return k if values[k] > stay + self.MARGIN else None

    # ---- the shop ---------------------------------------------------------------------------------
    def shop_action(self, run, shop):
        reorder = self._reorder(run)
        if reorder:
            return reorder
        use = self._use(run)
        if use:
            return use
        options = shop_options(run, shop)
        if not options:
            return ("leave",)
        values = self._rate([after_shop(self, run, shop, o) for o in options])
        k = self._choose(run, options, values, float(self._rate([run])[0]))
        return ("leave",) if k is None else as_action(options[k])

    # ---- packs ------------------------------------------------------------------------------------
    def pack_action(self, run, pack):
        options = pack_options(self, run, pack)
        if not options:
            return ("skip",)
        values = self._rate([after_pack(self, run, o) for o in options])
        k = self._choose(run, options, values, float(self._rate([run])[0]))
        return ("skip",) if k is None else options[k]


class GuidedBot(ValueBot):
    """The value bot choosing, and the value network overruling it only where it expects another option to go
    at least `confidence` progress further. A network trained on the bot's own positions errs more the further
    play strays from them, and its errors compound over a run; stepping in only where it is sure keeps play
    near what it knows."""

    def __init__(self, value: ValueNet, confidence: float = 0.5):
        self.value, self.confidence, self.queued = value, confidence, None

    def _overrule(self, run, options, afters, action):
        own = [k for k, o in enumerate(options) if as_action(o) == action]
        if not own:
            return None
        values = self.value.predict(np.stack([features(r, self.power(r)) for r in afters]))
        k = int(np.argmax(values))
        return options[k] if values[k] > max(values[i] for i in own) + self.confidence else None

    def shop_action(self, run, shop):
        if self.queued:                                    # the buy after a sale for another joker
            action, self.queued = self.queued, None
            return action
        action = super().shop_action(run, shop)
        if action[0] not in ("buy", "buy_use", "sell_joker", "reroll", "leave"):
            return action
        options = [("leave",)] + shop_options(run, shop)
        if len(options) < 2:
            return action
        better = self._overrule(run, options, [run] + [after_shop(self, run, shop, o) for o in options[1:]], action)
        if better is None:
            return action
        if better[0] == "sell_joker":
            self.queued = ("buy", "card", better[2])
        return as_action(better)

    def pack_action(self, run, pack):
        action = super().pack_action(run, pack)
        options = [("skip",)] + pack_options(self, run, pack)
        if len(options) < 2:
            return action
        better = self._overrule(run, options, [run] + [after_pack(self, run, o) for o in options[1:]], action)
        return action if better is None else better


def trial_copy(bot, *objs):
    """Copies of the run (first) and whatever goes with it, sharing the bot (and leaving out frames and log)."""
    run = objs[0]
    frames, log = run.frames, run.log
    run.frames = run.log = None
    try:
        return copy.deepcopy(objs, {id(bot): bot})
    finally:
        run.frames, run.log = frames, log


def after_shop(bot, run, shop, option):
    """The position after a shop option, tried on a copy (a pack bought is opened, and picked from, there)."""
    trial_run, trial_shop = trial_copy(bot, run, shop)
    apply_shop(trial_run, trial_shop, option)
    return trial_run


def after_pack(bot, run, option):
    (trial,) = trial_copy(bot, run)
    trial.take_from_pack(trial.open_pack_state, option[1], option[2])
    return trial


def shop_options(run, shop) -> list[tuple]:
    """Every move a shop allows now, besides leaving: buy (or buy and use) each card, pack and voucher that can
    be afforded, sell a joker to buy another (("sell_joker", k, i): one move, made over two calls), reroll."""
    spend = run.money - run.debt_limit
    options, jokers_offered = [], []
    for i, o in enumerate(shop.cards):
        cost, item = cost_of(run, o), o.item
        if isinstance(item, Joker):
            if run.joker_room(item):
                if cost <= spend:
                    options.append(("buy", "card", i))
            else:
                jokers_offered.append(i)
        elif cost > spend:
            continue
        elif isinstance(item, Consumable):
            if item.can_use(run, []):
                options.append(("buy_use", i, []))
            if run.consumable_room(item):
                options.append(("buy", "card", i))
        else:
            options.append(("buy", "card", i))
    for i, o in enumerate(shop.packs):
        if cost_of(run, o) <= spend:
            options.append(("buy", "pack", i))
    for i, o in enumerate(shop.vouchers):
        if cost_of(run, o) <= spend:
            options.append(("buy", "voucher", i))
    for i in jokers_offered:
        for k, j in enumerate(run.jokers):
            if not j.eternal and j.edition != "Negative" and cost_of(run, shop.cards[i]) <= spend + run.sell_value(j):
                options.append(("sell_joker", k, i))
    if shop.reroll_cost <= spend:
        options.append(("reroll",))
    return options


def apply_shop(run, shop, option) -> None:
    if option[0] == "buy":
        shop.buy(option[1], option[2])
    elif option[0] == "buy_use":
        shop.buy("card", option[1], use=True, targets=option[2])
    elif option[0] == "sell_joker":
        run.sell_joker(option[1])
        shop.buy("card", option[2])
    elif option[0] == "reroll":
        shop.reroll()


def as_action(option) -> tuple:
    """The action a shop option starts with (a sale for another joker sells first; the buy comes next call)."""
    return option[:2] if option[0] == "sell_joker" else option


def pack_options(bot, run, pack) -> list[tuple]:
    """Every pick a pack allows now, besides skipping: each joker there is room for, each consumable with each
    way to use it (bot._uses), each playing card."""
    options = []
    for i, item in enumerate(pack.cards):
        if isinstance(item, Joker):
            if run.joker_room(item):
                options.append(("pick", i, []))
        elif isinstance(item, Consumable):
            for targets, _ in bot._uses(run, item, run.hand):
                options.append(("pick", i, targets))
        else:
            options.append(("pick", i, []))
    return options


def load(path: str | Path) -> ValueNet:
    return ValueNet(path)
