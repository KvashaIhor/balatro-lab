"""The best line for one seed: a run plan, step by step.

With a game seed the simulator knows the deck order of every blind and every shop and pack (gameseed.py),
so a strategy can be tested exactly against this seed before it is played. The planner runs a beam search
over the run's decisions (skip a blind or play it, each shop purchase or reroll, each pack pick): it keeps
the best few lines, tries every option of each, and scores an option by playing a few antes on with the base
strategy. Within rounds the base strategy plays; it chooses discards by looking at the cards the deck will
actually deal.

Usage: python3 -m balatro.planner SEED [--deck "Red Deck"] [--max-ante 12] [--beam 6] [--horizon 3] [--time 30]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import pickle
import select
import signal
import threading
import time
from collections import Counter
from dataclasses import dataclass, field

from .cards import Card
from .gameseed import EXACT, SIMULATED
from .items import Consumable
from .jokers import Joker
from .run import Run
from .shop import cost_of
from .strategy import ValueBot, action_key, card_text

# ---- decisions --------------------------------------------------------------------------------------

class PlanAgent(ValueBot):
    """ValueBot whose decisions can be overridden: decision k takes option prefix[k]; every decision and its
    options are recorded, so the planner can try the others. Besides skips, shops and packs, the decisions
    include each consumable: use it now (on which cards) or keep it for good (Perkeo copies one at the end of
    each shop; Observatory pays for Planets held)."""
    PEEK = True      # a planned seed is known, and so its deck order

    def __init__(self, prefix=()):
        self.prefix = list(prefix)
        self.trace: list[dict] = []
        self.kept: list = []

    BRANCH = 3                     # options per shop or pack decision the search tries, by the value bot's estimate

    def _decide(self, run, kind, options, labels, default):
        k = len(self.trace)
        choice = self.prefix[k] if k < len(self.prefix) and 0 <= self.prefix[k] < len(options) else default
        self.trace.append({"kind": kind, "ante": run.ante, "blind": run.blind.name if run.blind else None,
                           "money": run.money, "options": labels, "choice": choice, "default": default})
        return options[choice]

    def skip_blind(self, run, blind, tag):
        if tag is None:
            return False
        default = 1 if ValueBot.skip_blind(self, run, blind, tag) else 0        # the value bot's own choice
        return self._decide(run, "blind", [False, True], [f"Play the {blind.name}", f"Skip it for the {tag.name}"], default)

    def _use_or_keep(self, run, c, uses) -> list[int] | None:
        """Decide once per consumable: use it now (which way) or keep it. Returns the targets, or None to keep.
        The value bot's choice is the default."""
        if self.is_kept(c):
            return None
        default = self.consumable_choice(run, c, uses)
        choice = self._decide(run, "keep", list(range(len(uses) + 1)), [u[1] for u in uses] + [f"Keep {c.name}"], default)
        if choice < len(uses):
            return uses[choice][0]
        self.kept.append(c)
        if run.frames is not None:
            run.frame("keep", item={"name": c.name, "kind": c.kind, "edition": c.edition})
        return None

    def shop_action(self, run, shop):
        if getattr(self, "_queued", None):          # the buy that goes with a sale made to make room for it
            action, self._queued = self._queued, None
            return action
        base = super().shop_action(run, shop)
        offered = [i for i, o in enumerate(shop.cards) if isinstance(o.item, Joker)]
        make_room = base[0] == "sell_joker" and not run.joker_room() and bool(offered)
        if base[0] in ("use", "order_jokers", "sell_joker", "sell_consumable") and not make_room:
            return base
        spend = run.money - run.debt_limit
        options, labels = [("leave",)], ["Leave the shop"]
        for i, o in enumerate(shop.cards):
            cost = cost_of(run, o)
            if cost > spend:
                continue
            if isinstance(o.item, Joker):
                if run.joker_room(o.item):
                    options.append(("buy", "card", i))
                    labels.append(f"Buy {o.name}{f' ({o.item.edition})' if o.item.edition else ''} for ${cost}")
            elif isinstance(o.item, Consumable):
                if o.item.can_use(run, []):
                    options.append(("buy_use", i, []))
                    labels.append(f"Buy and use {o.name} for ${cost}")
                elif run.consumable_room(o.item):
                    options.append(("buy", "card", i))
                    labels.append(f"Buy {o.name} for ${cost}")
            elif isinstance(o.item, Card) and cost <= spend:
                options.append(("buy", "card", i))
                labels.append(f"Buy the {card_text(o.item)} card for ${cost}")
        for i, o in enumerate(shop.packs):
            cost = cost_of(run, o)
            if cost <= spend:
                options.append(("buy", "pack", i))
                labels.append(f"Open {o.name} for ${cost}")
        for i, o in enumerate(shop.vouchers):
            cost = cost_of(run, o)
            if cost <= spend:
                options.append(("buy", "voucher", i))
                labels.append(f"Redeem {o.name} for ${cost}")
        if shop.reroll_cost <= spend:
            options.append(("reroll",))
            labels.append(f"Reroll for ${shop.reroll_cost}")
        if not run.joker_room() and offered:        # make room for a joker: sell one and buy it, as one move
            for j, jk in enumerate(run.jokers):
                if jk.eternal or jk.edition == "Negative":                       # selling a Negative frees no slot
                    continue
                for i in offered:
                    cost = cost_of(run, shop.cards[i])
                    if cost <= spend + run.sell_value(jk):
                        options.append(("sell_joker", j, i))
                        labels.append(f"Sell {jk.name} (+${run.sell_value(jk)}) and buy {shop.cards[i].name} for ${cost}")
        if make_room:                               # the bot's own: its sale, for the joker it values most
            power = self.power(run)
            adj = self.adjust(run, power)
            target = max(offered, key=lambda i: self.joker_worth(run, shop.cards[i].item, power) + adj(("joker", shop.cards[i].name)))
            default = next((k for k, o in enumerate(options) if o == ("sell_joker", base[1], target)), 0)
        else:
            base_key = tuple(base[:3]) if base[0] == "buy" else tuple(base[:2]) if base[0] == "buy_use" else (base[0],)
            default = next((k for k, o in enumerate(options) if tuple(o[:len(base_key)]) == base_key), 0)
        action = self._decide(run, "shop", *self._prune(options, labels, default))
        if action[0] == "sell_joker":
            self._queued = ("buy", "card", action[2])
            return action[:2]
        return action

    def pack_action(self, run, pack):
        base = super().pack_action(run, pack)
        if base[0] == "use":
            return base
        options, labels = [("skip",)], ["Skip the rest of the pack"]
        for i, item in enumerate(pack.cards):
            if isinstance(item, Joker):
                if run.joker_room(item):
                    options.append(("pick", i, []))
                    labels.append(f"Take {item.name}{f' ({item.edition})' if item.edition else ''}")
            elif isinstance(item, Consumable):
                for targets, label in self._uses(run, item, run.hand):
                    options.append(("pick", i, targets))
                    labels.append("Take and " + label[0].lower() + label[1:])
            elif isinstance(item, Card):
                options.append(("pick", i, []))
                labels.append(f"Take the {card_text(item)} card")
        default = 0
        if base[0] == "pick":
            default = next((k for k, o in enumerate(options) if o[0] == "pick" and o[1] == base[1]
                            and (len(base) < 3 or list(o[2]) == sorted(set(base[2])))), None)
            default = default if default is not None else next((k for k, o in enumerate(options) if o[0] == "pick" and o[1] == base[1]), 0)
        return self._decide(run, "pack", *self._prune(options, labels, default))

    def _prune(self, options, labels, default):
        """Keep the value bot's best BRANCH options by its own estimates, its choice, and leaving or skipping
        (option 0): the search then spends its time on the options that might be best."""
        worths = getattr(self, "worths", {})
        key = lambda o: action_key(o[:2] if o[0] == "sell_joker" else o)       # a sale for a joker: by the sale
        ranked = sorted(range(len(options)), key=lambda k: -worths.get(key(options[k]), float("-inf")))
        keep = sorted(set(ranked[:self.BRANCH]) | {0, default})
        return [options[k] for k in keep], [labels[k] for k in keep], keep.index(default)


# ---- rollouts -------------------------------------------------------------------------------------

@dataclass
class Rollout:
    score: tuple
    progress: float
    ante: int
    won: bool
    trace: list = field(default_factory=list)


def rollout(seed: str, deck: str, prefix: list[int], max_ante: int, record: bool = False):
    agent = PlanAgent(prefix)
    run = Run(agent, game_seed=seed, deck=deck, max_ante=max_ante, record=record)
    res = run.play()
    r = Rollout((res.progress, res.best_hand, res.money), res.progress, res.ante, res.won, agent.trace)
    return (r, run) if record else r


def _whole_run(args) -> Rollout:
    return rollout(*args)


class _Undecided(Exception):
    pass


class _SettledAgent(PlanAgent):
    """Replays a prefix of choices and stops at the first later decision that has a choice."""

    def _decide(self, run, kind, options, labels, default):
        if len(self.trace) >= len(self.prefix) and len(options) > 1:
            raise _Undecided
        return super()._decide(run, kind, options, labels, default)


def settled_steps(seed: str, deck: str, max_ante: int, prefix: list[int]) -> list[dict]:
    """The steps a line takes up to its first decision past `prefix` (the play in between follows from it)."""
    run = Run(_SettledAgent(prefix), game_seed=seed, deck=deck, max_ante=max_ante, record=True)
    try:
        run.play()
    except _Undecided:
        pass
    return steps(run)


# ---- beam search -----------------------------------------------------------------------------------
#
# Each line of the beam is a live process paused at its next decision, so no line is ever replayed from the
# start. To expand a line the coordinator signals it and it forks one child per option. Each child takes its
# option and forks a scorer, which plays on with the base strategy for `horizon` antes and reports its
# score; the child itself plays on to its own next decision, reports, and pauses. The coordinator keeps the
# best `width` children and kills the rest. Forking copies the whole game state and the warm caches.

LINE_PATIENCE = 300          # seconds a paused line waits to be expanded before it ends itself


class _Wire:
    """Pickled messages from any process of the search to the coordinator. Each fits in one pipe write, which
    the system keeps whole, so senders need no lock (a process killed holding one would block the rest)."""

    def __init__(self):
        self.r, self.w = os.pipe()
        self.owner = os.getpid()
        self.buf = b""

    def send(self, msg) -> None:
        try:
            os.kill(self.owner, 0)
        except ProcessLookupError:                          # the planner is gone (stopped): so is the point
            os._exit(0)
        data = pickle.dumps(msg)
        data = len(data).to_bytes(4, "little") + data
        if len(data) > select.PIPE_BUF:
            raise ValueError(f"message of {len(data)} bytes is too long for one pipe write")
        os.write(self.w, data)

    def recv(self, timeout: float):
        while True:
            if len(self.buf) >= 4:
                n = int.from_bytes(self.buf[:4], "little")
                if len(self.buf) >= 4 + n:
                    msg, self.buf = pickle.loads(self.buf[4:4 + n]), self.buf[4 + n:]
                    return msg
            if not select.select([self.r], [], [], timeout)[0]:
                return None
            self.buf += os.read(self.r, 1 << 16)

    def close(self) -> None:
        os.close(self.r)
        os.close(self.w)


class ForkAgent(PlanAgent):
    """PlanAgent in a forked line: at each decision with a choice it reports and waits to be expanded. `key`
    holds its choices so far, the prefix that replays it."""

    def __init__(self, wire: _Wire, horizon: int):
        super().__init__()
        self.wire, self.horizon = wire, horizon
        self.scoring = False
        self.key: list[int] = []
        self.overrules = 0             # choices other than the value bot's own so far
        self.ident = (os.getpid(), time.time_ns())

    def _decide(self, run, kind, options, labels, default):
        if self.scoring or len(options) == 1:
            self.key.append(default)
            return options[default]
        self.wire.send(("line", self.ident, bytes(self.key), len(options), hash(tuple(sorted(j.name for j in run.jokers))),
                        self.overrules))
        signal.alarm(LINE_PATIENCE)
        signal.sigwait({signal.SIGUSR1})
        signal.alarm(0)
        for i in range(len(options)):
            if os.fork() == 0:
                self.ident = (os.getpid(), time.time_ns())
                self.key.append(i)
                self.overrules += i != default
                if os.fork() == 0:
                    self.scoring = True
                    run.max_ante = min(run.max_ante, run.ante + self.horizon)
                return options[i]
        os._exit(0)


def _play_line(seed: str, deck: str, max_ante: int, horizon: int, wire: _Wire):
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)          # children are reaped as they end
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    agent = ForkAgent(wire, horizon)
    try:
        res = Run(agent, game_seed=seed, deck=deck, max_ante=max_ante).play()
        wire.send(("score" if agent.scoring else "done", agent.ident, b"" if agent.scoring else bytes(agent.key),
                   (res.progress, res.best_hand, res.money), res.ante, res.won, agent.overrules))
    except Exception as e:
        wire.send(("fail", agent.ident, agent.scoring, repr(e)[:200]))
    finally:
        os._exit(0)


def _gather(wire: _Wire, lines: int, scores: int):
    """Messages until `lines` children have paused, finished or failed and `scores` scorers have reported."""
    paused, done, scored = {}, {}, {}
    n_lines = n_scores = 0
    while n_lines < lines or n_scores < scores:
        m = wire.recv(60)
        if m is None:
            print(f"{time.strftime('%H:%M:%S')} search stalled: {n_lines}/{lines} lines and {n_scores}/{scores} "
                  "scores after 60 s without a message; stopping here", flush=True)
            break
        kind, ident = m[0], m[1]
        if kind == "line":
            paused[ident] = (list(m[2]), *m[3:])
        elif kind == "done":
            done[ident] = (list(m[2]), *m[3:])
        elif kind == "score":
            scored[ident] = m[3:]
        elif kind == "fail":
            print(f"{time.strftime('%H:%M:%S')} a {'scorer' if m[2] else 'line'} failed: {m[3]}", flush=True)
        n_scores += kind == "score" or (kind == "fail" and m[2])
        n_lines += kind in ("line", "done") or (kind == "fail" and not m[2])
    return paused, done, scored


def _terminate(signum, frame):
    raise SystemExit(143)


def overrules(trace: list[dict]) -> int:
    """Choices in a run other than the value bot's own."""
    return sum(t["choice"] != t["default"] for t in trace)


def beam_plan(seed: str, deck: str = "Red Deck", max_ante: int = 12, width: int = 6, horizon: int = 3,
              time_limit: float | None = None, on_progress=None, detour: float = 0.0) -> dict:
    """Beam search: keep the `width` best lines; at each decision branch every line into its options (the value
    bot's `PlanAgent.BRANCH` most promising ones in shops and packs) and score each branch by playing on with
    the value bot for `horizon` antes (ties: best hand score, then money), keep the best `width`. Combinations
    of moves that pay off together (sell this, save, buy that later) survive long enough to show it. With
    `time_limit` the search stops when time is up. The plan is the best whole run among the best line, the
    lines left, the best that finished and the value bot's own run. `detour` (progress) is charged for each
    choice other than the value bot's: a move that only wins by a hair, through the knock-on effects of a
    chaotic game, then loses to the bot's own, and plans keep fewer pointless moves."""

    def merit(result: tuple, n: int) -> tuple:
        return (result[0] - detour * n, *result[1:])

    t0 = time.time()
    base = rollout(seed, deck, [], max_ante)
    wire = _Wire()
    old = {sig: signal.signal(sig, handler) for sig, handler in
           ((signal.SIGCHLD, signal.SIG_IGN), (signal.SIGTERM, _terminate))}
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})     # lines inherit the mask and sigwait on it
    if os.fork() == 0:
        _play_line(seed, deck, max_ante, horizon, wire)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGUSR1})
    paused, best, rollouts, depth = {}, None, 1, 0
    finished = None                # the best line that played to its end (its result is a whole run's)
    settled: list[int] = []        # the choices reported settled: every candidate for the plan starts with them
    try:
        paused, done, _ = _gather(wire, 1, 0)
        if done:                                                   # a run with no choices at all
            best = next(iter(done.values()))
        beam = list(paused)
        while beam and not (time_limit and time.time() - t0 > time_limit):
            for ident in beam:
                os.kill(ident[0], signal.SIGUSR1)
            n = sum(paused[ident][1] for ident in beam)
            new, done, scored = _gather(wire, n, n)
            rollouts += len(scored)
            for ident, (key, *result) in done.items():              # a finished line's own result is final
                scored[ident] = tuple(result)
                if finished is None or result[0] > finished[1]:
                    finished = (key, result[0])
            keys = {ident: (new.get(ident) or done[ident])[0] for ident in scored if ident in new or ident in done}
            # Best score first, ties by the choices made, so the beam doesn't depend on which process reports
            # first. An equal score over the horizon means the same position (moves in another order): one is kept.
            ranked, seen = [], set()
            for ident in sorted(keys, key=lambda i: (merit(scored[i][0], scored[i][3]), [-k for k in keys[i]]), reverse=True):
                if scored[ident][0] not in seen:
                    seen.add(scored[ident][0])
                    ranked.append(ident)
            if ranked and (best is None or merit(scored[ranked[0]][0], scored[ranked[0]][3]) > merit(best[1], best[4])):
                best = (keys[ranked[0]], *scored[ranked[0]])
            # At most two lines per joker lineup first, so different builds stay alive; the best of the rest
            # fill any open slot.
            live = [ident for ident in ranked if ident in new]
            per_build: Counter = Counter()
            diverse = []
            for ident in live:
                per_build[new[ident][2]] += 1
                if per_build[new[ident][2]] <= 2:
                    diverse.append(ident)
            beam = (diverse + [ident for ident in live if ident not in diverse])[:width]
            for ident in new:
                if ident not in beam:
                    os.kill(ident[0], signal.SIGKILL)
            paused = {ident: new[ident] for ident in beam}
            depth += 1
            if on_progress and best:
                # The plan will be the best line or a descendant of one in the beam: the choices they all
                # share are settled.
                settled = list(os.path.commonprefix([new[ident][0] for ident in beam] + [best[0]]))
                on_progress({"decision": depth, "rollouts": rollouts, "progress": best[1][0], "ante": best[2],
                             "won": best[3], "base_progress": base.progress, "elapsed": time.time() - t0,
                             "limit": time_limit, "settled": settled})
    finally:
        for ident in paused:
            try:
                os.kill(ident[0], signal.SIGKILL)
            except ProcessLookupError:
                pass
        wire.close()
        for sig, handler in old.items():
            signal.signal(sig, handler)
    # The plan is the best whole run among the best line, the lines left in the beam, the best line that
    # finished, and the base strategy's own run: a line ahead after a few antes can fall behind later, and the
    # plan is never worse than the base strategy. Ties go to a line that starts with the steps already shown as
    # settled; if the winner doesn't, the result says so (left_settled).
    keys = {tuple(best[0]) if best else (), tuple(t["choice"] for t in base.trace)} | {tuple(v[0]) for v in paused.values()}
    if finished:
        keys.add(tuple(finished[0]))
    keys = sorted(keys)
    with mp.get_context("fork").Pool(min(len(keys), os.cpu_count() or 4)) as pool:
        whole = pool.map(_whole_run, [(seed, deck, list(k), max_ante) for k in keys])
    rollouts += len(keys)
    keeps = [list(k[:len(settled)]) == settled for k in keys]
    pick = max(range(len(keys)), key=lambda k: (merit(whole[k].score, overrules(whole[k].trace)), keeps[k]))
    final, run = rollout(seed, deck, list(keys[pick]), max_ante, record=True)
    return {"seed": seed, "deck": deck, "max_ante": max_ante, "progress": final.progress, "ante": final.ante,
            "won": final.won, "base": {"progress": base.progress, "ante": base.ante, "won": base.won},
            "rollouts": rollouts, "seconds": time.time() - t0, "decisions": final.trace, "beam": width,
            "horizon": horizon, "searched": depth, "steps": steps(run), "frames": run.frames,
            "left_settled": not keeps[pick], "detour": detour, "overrules": overrules(final.trace)}


# ---- the plan as steps a player can follow --------------------------------------------------------

SUIT_OF = {"S": "♠", "H": "♥", "C": "♣", "D": "♦"}


def sym(label: str) -> str:
    """'10H' -> '10♥' (labels from Card.label)."""
    return label if label == "Stone" else label[:-1] + SUIT_OF.get(label[-1], label[-1])


SUIT_ORDER = {"Spades": 0, "Hearts": 1, "Clubs": 2, "Diamonds": 3}


def game_order(cards: list[dict]) -> list[int]:
    """Indexes of `cards` in the order the game keeps a hand: by rank, high first, then ♠ ♥ ♣ ♦, Stone cards
    last (its default sort, which places face-down cards too)."""
    def key(i):
        c = cards[i]
        return (1, 0, 0) if c["enhancement"] == "Stone" else (0, -c["rank"], SUIT_ORDER[c["suit"]])
    return sorted(range(len(cards)), key=key)


def _card_names(cards: list[dict]) -> str:
    return " ".join(sym(c["label"]) for c in cards)


def _hand_step(kind: str, f: dict) -> dict:
    """A play or discard: the hand as the game shows it and the positions to select (1 = leftmost)."""
    order = game_order(f["before"])
    hand = [f["before"][i] for i in order]
    picked = sorted(order.index(i) for i in f["picked"])
    chosen = [hand[k] for k in picked]
    which = _card_names(chosen)
    if any(c["face_down"] for c in chosen):
        which = f"cards {', '.join(str(k + 1) for k in picked)} from the left (face down: {which})"
    step = {"kind": kind, "hand": hand, "picked": picked}
    if kind == "play":
        step.update(text=f"Play {which}: {f['hand_name']} for {f['total']:,}", hand_name=f["hand_name"],
                    level=f["level"], chips=f["chips"], mult=f["mult"], total=f["total"],
                    round_score=f["round_score"], target=f["blind"]["chips"])
    else:
        step["text"] = f"Discard {which}"
    return step


def _item(x: dict) -> dict:
    """An item as the page draws it: kind, name, edition, price, and the card for playing cards."""
    return {k: x[k] for k in ("kind", "name", "edition", "price", "card") if k in x}


def steps(run) -> list[dict]:
    """The recorded run as sections (each skip, blind and shop) of steps a player can follow, with what the
    screen shows at each: the hand in the game's order, the shop's offers, a pack's contents. Steps are only
    ever appended, so the steps of part of a run are the start of the steps of all of it."""
    sections: list[dict] = []
    cur = None
    pack = None                    # the pack being opened
    shop_packs: list = []          # the shop's packs on offer: a pack opens as it's bought, before the shop says so
    pack_bought = False
    held_use = None                # a use in the shop, until the next frame says whether it was "buy and use"

    def section(kind, title, f, **extra):
        nonlocal cur
        cur = {"kind": kind, "title": title, "ante": f["ante"], "money": f["money"],
               "jokers": [_item({"kind": "Joker", **j}) for j in f["jokers"]],
               "consumables": [_item(c) for c in f["consumables"]], "steps": [], **extra}
        sections.append(cur)

    def add(step):
        if cur is None:
            section("start", "Run start", {"ante": 1, "money": 0, "jokers": [], "consumables": []})
        cur["steps"].append(step)

    def buy_step(offer, use=False):
        item = _item(offer)
        return {"kind": "buy", "text": f"{'Buy and use' if use else 'Buy'} {item['name']} (${item['price']})", "item": item}

    for f in run.frames or []:
        kind = f["kind"]
        act = f.get("act")
        if held_use and not (kind == "shop" and act and act.get("use")):
            add(held_use)
            held_use = None
        if kind == "skip":
            b = f["blind"]
            section("skip", f"Skip the {b['name']}" + (f" for the {f['tag']}" if f["tag"] else ""), f,
                    blind=b, tag=f["tag"])
        elif kind == "blind":
            b = f["blind"]
            section("blind", f"{b['name']}: score {b['chips']:,}", f, blind=b)
        elif kind == "shop" and "act" not in f:
            section("shop", "Shop", f, offers={k: [_item(x) for x in f["shop"][k]] for k in ("cards", "packs", "vouchers")}
                    | {"reroll_cost": f["shop"]["reroll_cost"]})
            shop_packs = f["shop"]["packs"]
        elif kind == "shop" and act:
            shop_packs = f["shop"]["packs"]
            if act["do"] == "reroll":
                add({"kind": "reroll", "text": f"Reroll the shop (${act['cost']})", "cost": act["cost"],
                     "offers": [_item(x) for x in f["shop"]["cards"]]})
            elif act["item"]["kind"] == "Pack" and pack_bought:
                pack_bought = False                              # its step came as it opened
            else:
                step = buy_step(act["item"], act["use"])
                if act["use"] and held_use and held_use["item"]["name"] == step["item"]["name"]:
                    step["targets"] = held_use["targets"]
                    held_use = None
                add(step)
        elif kind == "play":
            add(_hand_step("play", f))
            cur["scored"] = f["round_score"]
        elif kind == "discard":
            add(_hand_step("discard", f))
        elif kind == "use":
            on = f" on {_card_names(f['targets'])}" if f["targets"] else ""
            if f["used"] == "Death" and len(f["targets"]) == 2:
                on = f": {sym(f['targets'][0]['label'])} becomes {sym(f['targets'][1]['label'])}"
            step = {"kind": "use", "text": f"Use {f['used']}{on}", "item": {"name": f["used"]}, "targets": f["targets"]}
            if cur is not None and cur["kind"] == "shop" and pack is None:
                held_use = step
            else:
                add(step)
        elif kind == "pack":
            p, did = f["pack"], f["did"]
            if did.startswith("Opened"):
                offer = next((o for o in shop_packs if o["name"] == p["name"]), None)
                if cur is not None and cur["kind"] == "shop" and offer:
                    add(buy_step(offer))
                    pack_bought = True
                pack = p
                add({"kind": "open", "text": f"Open the {p['name']}", "pack": {"name": p["name"], "kind": p["kind"],
                     "cards": [_item(x) for x in p["cards"]]}, "picks": p["picks_left"]})
            elif did.startswith("Picked"):
                name = did[len("Picked "):]
                item = next((_item(x) for x in pack["cards"] if x["name"] == name), {"name": name}) if pack else {"name": name}
                last = cur["steps"][-1] if cur and cur["steps"] else None
                use = cur["steps"].pop() if last and last["kind"] == "use" and last["item"]["name"] == name else None
                text = f"Take {sym(name) if item.get('kind') == 'Playing card' else name}"
                if use:
                    text = "Take and use " + name + (f" on {_card_names(use['targets'])}" if use["targets"] else "")
                add({"kind": "pick", "text": text, "item": item, "targets": use["targets"] if use else []})
                pack = p if p["picks_left"] > 0 and p["cards"] else None
            else:
                add({"kind": "skip pack", "text": f"Skip the rest of the {p['name']}"})
                pack = None
        elif kind == "sell":
            add({"kind": "sell", "text": f"Sell {f['item']['name']} (+${f['value']})", "item": f["item"], "value": f["value"]})
        elif kind == "order":
            add({"kind": "order", "text": "Put jokers in this order: " + ", ".join(j["name"] for j in f["jokers"]),
                 "jokers": [_item({"kind": "Joker", **j}) for j in f["jokers"]]})
        elif kind == "boss_reroll":
            add({"kind": "boss reroll", "text": f"Reroll the boss (now {f['boss']})", "boss": f["boss"]})
        elif kind == "cash_out":
            add({"kind": "cash out", "text": f"Cash out: +${f['earned']}, now ${f['money']}", "earned": f["earned"],
                 "money": f["money"]})
        elif kind == "saved":
            add({"kind": "saved", "text": "Saved by Mr. Bones"})
        elif kind == "keep":
            add({"kind": "keep", "text": f"Keep {f['item']['name']}: don't use it", "item": f["item"]})
    if held_use:
        add(held_use)
    return sections


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("seed")
    ap.add_argument("--deck", default="Red Deck")
    ap.add_argument("--max-ante", type=int, default=12)
    ap.add_argument("--json", help="write the plan here (steps, decisions, frames for the viewer)")
    ap.add_argument("--progress", help="keep this file updated with progress (JSON)")
    ap.add_argument("--beam", type=int, default=6, help="lines kept at each decision")
    ap.add_argument("--horizon", type=int, default=3, help="antes played past each decision to score it")
    ap.add_argument("--time", type=float, default=30, help="stop searching after this many seconds (0: no limit)")
    ap.add_argument("--branch", type=int, default=PlanAgent.BRANCH, help="options per shop or pack decision tried")
    ap.add_argument("--detour", type=float, default=0.0, help="progress charged per choice other than the value bot's")
    args = ap.parse_args()
    PlanAgent.BRANCH = args.branch
    t0 = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{t0} plan {args.seed}, {args.deck}, up to ante {args.max_ante}, beam {args.beam}, horizon "
          f"{args.horizon}, branch {args.branch}, {args.time:g} s", flush=True)

    # The settled steps are replayed on a thread, so the search doesn't wait; the progress file carries the
    # latest ones.
    settled = {"key": [], "steps": [], "busy": False}

    def replay(key):
        settled.update(key=key, steps=settled_steps(args.seed, args.deck, args.max_ante, key), busy=False)

    def show(p):
        print(f"{time.strftime('%H:%M:%S')} decision {p['decision']}  rollouts {p['rollouts']}  "
              f"best: ante {p['ante']}, progress {p['progress']:.2f} (base {p['base_progress']:.2f})  "
              f"settled {len(p['settled'])}  {p['elapsed']:.0f}s", flush=True)
        if args.progress:
            if len(p["settled"]) > len(settled["key"]) and not settled["busy"]:
                settled["busy"] = True
                threading.Thread(target=replay, args=(p["settled"],), daemon=True).start()
            with open(args.progress + ".tmp", "w") as fh:
                json.dump({**p, "steps": settled["steps"]}, fh)
            os.replace(args.progress + ".tmp", args.progress)
    res = beam_plan(args.seed, args.deck, args.max_ante, args.beam, args.horizon, args.time or None, show, args.detour)
    print(f"plan: reaches ante {res['ante']} (progress {res['progress']:.2f}, won: {res['won']}; {res['overrules']} of "
          f"{len(res['decisions'])} choices overrule the value bot); base strategy "
          f"ante {res['base']['ante']} ({res['base']['progress']:.2f}); {res['rollouts']} rollouts in "
          f"{res['seconds']:.0f}s; exit 0", flush=True)
    if args.json:
        res["exact"], res["simulated"] = EXACT, SIMULATED
        with open(args.json + ".tmp", "w") as fh:
            json.dump(res, fh)
        os.replace(args.json + ".tmp", args.json)
    else:
        for sec in res["steps"][:14]:
            print(f"  ante {sec['ante']}  {sec['title']}")
            for st in sec["steps"]:
                print(f"      {st['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
