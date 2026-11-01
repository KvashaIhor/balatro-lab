"""Does the value bot use what a player can't see? At every decision of N games the bot also decides on a twin of the
game where the hidden things are changed, and an honest bot decides the same there:
- the run's random streams reseeded (what a Lucky card, Misprint, Wheel of Fortune, a pack or a reroll will give);
- the game seed's streams too (the jokers and cards Judgement, Familiar, Sigil... will make);
- each face-down card swapped with a card from the draw pile (The House, The Wheel, The Mark, The Fish).
Each difference is listed with the decision and what was in play.

Usage:  python3 -u scripts/probe_leaks.py [--seeds 40] [--workers 8] [--rng 90210] [--label NAME]
Writes: runs/value/probe_leaks_<label>.json
Log:    logs/probe_leaks.log (append with >>)
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VALUEBOT_WEIGHTS", "hand")

from balatro.gameseed import SeedRNG  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot  # noqa: E402

CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
DECISIONS = ("round_action", "shop_action", "pack_action", "skip_blind", "reroll_boss")


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


HIDE = {"streams", "seed", "down", "pile"}   # what hide() changes (--hide; none: a control, the twin as it is)


def hide(twin, rnd: random.Random) -> list[str]:
    """Change what a player can't see in `twin`; returns what was changed."""
    changed = []
    if "streams" in HIDE:
        for name in twin.rng:
            twin.rng[name].seed(rnd.random())      # in place: the shop holds its stream too
        changed.append("streams")
    if twin.seedrng is not None and "seed" in HIDE:
        twin.seedrng = SeedRNG("".join(rnd.choice(CHARS) for _ in range(8)))
        changed.append("game seed")
    down = [i for i, c in enumerate(twin.hand) if c.face_down]
    if down and twin.draw_pile and "down" in HIDE:
        for i in down:
            j = rnd.randrange(len(twin.draw_pile))
            out, into = twin.hand[i], twin.draw_pile[j]
            out.face_down, into.face_down = False, True
            twin.hand[i], twin.draw_pile[j] = into, out
        changed.append(f"{len(down)} face down")
    if len(twin.draw_pile) > 1 and "pile" in HIDE:    # the pile's order (a discard's draws once sampled from it as it
        rnd.shuffle(twin.draw_pile)                   # lay: the replay review's m6, 29 Oct)
        changed.append("pile order")
    return changed


def describe(run, action) -> str:
    """The action with the items it names, for reading."""
    if not isinstance(action, tuple) or not action:
        return repr(action)
    kind = action[0]
    try:
        if kind in ("use", "sell_consumable"):
            return f"{action!r} [{run.consumables[action[1]].name}]"
        if kind == "sell_joker":
            return f"{action!r} [{run.jokers[action[1]].name}]"
        if kind == "play" or kind == "discard":
            return f"{kind} " + " ".join(run.hand[i].label() + ("(down)" if run.hand[i].face_down else "") for i in action[1])
    except (IndexError, AttributeError, TypeError):
        pass
    return repr(action)


class Probe(ValueBot):
    twin = False

    def __init__(self, seed: str):
        super().__init__()
        self.rnd = random.Random(f"probe|{seed}")
        self.diffs: list[dict] = []
        self.asked: Counter = Counter()
        self.failed: Counter = Counter()


def copy_game(run, args):
    """A copy of the game and the decision's arguments, its bot (copied with it) marked a twin. The bot's memory
    keyed by id() (shops seen, how long a consumable is held, its caches) is re-keyed to the copies, so the twin
    remembers what the bot does."""
    frames, log_ = run.frames, run.log
    run.frames = run.log = None
    try:
        memo: dict = {}
        twin = copy.deepcopy(run, memo)
        twin_args = copy.deepcopy(args, memo)
    finally:
        run.frames, run.log = frames, log_
    skip = id(memo)

    def retag(x):
        if type(x) is int:
            return id(memo[x]) if x != skip and x in memo else x
        if type(x) is tuple:
            return tuple(retag(v) for v in x)
        if type(x) is list:
            return [retag(v) for v in x]
        if type(x) is set:
            return {retag(v) for v in x}
        if type(x) is dict:
            return {retag(k): retag(v) for k, v in x.items()}
        return x
    bot = twin.agent
    for k, v in list(vars(bot).items()):
        if k not in ("rnd", "diffs", "asked", "failed", "w", "net"):
            setattr(bot, k, retag(v))
    bot.twin = True
    return twin, twin_args


def _probed(name):
    real = getattr(ValueBot, name)

    def decide(self, run, *args):
        if self.twin:
            return real(self, run, *args)
        same, same_args = copy_game(run, args)             # the control: nothing changed
        hidden, hidden_args = copy_game(run, args)
        changed = hide(hidden, self.rnd)
        action = real(self, run, *args)
        self.asked[name] += 1
        try:
            control = real(same.agent, same, *same_args)
            other = real(hidden.agent, hidden, *hidden_args)
        except Exception as e:          # noqa: BLE001 - a twin the bot can't handle is reported, not fatal
            self.failed[f"{name}: {type(e).__name__}: {e}"[:160]] += 1
            return action
        boss = run.active_boss
        offers = []
        if name == "shop_action":
            offers = [o.name for o in args[0].cards + args[0].packs + args[0].vouchers]
        elif name == "pack_action":
            offers = [getattr(x, "name", None) or x.label() for x in args[0].cards]
        for kind, a, b, game in (("copy", action, control, same), ("leak", control, other, hidden)):
            if repr(a) != repr(b):
                self.diffs.append({"kind": kind, "decision": name, "ante": run.ante, "blind": getattr(run.blind, "name", None),
                                   "boss": boss.name if boss else None, "changed": changed,
                                   "real": describe(run, a), "twin": describe(game, b), "offers": offers,
                                   "jokers": [j.name for j in run.jokers], "consumables": [c.name for c in run.consumables],
                                   "face_down": sum(c.face_down for c in run.hand)})
        return action
    return decide


for _name in DECISIONS:
    setattr(Probe, _name, _probed(_name))


def play(seed: str) -> dict:
    t = time.time()
    bot = Probe(seed)
    res = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8).play()
    return {"seed": seed, "won": res.won, "ante": res.ante, "asked": dict(bot.asked), "diffs": bot.diffs,
            "failed": dict(bot.failed), "seconds": time.time() - t}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rng", type=int, default=90210)
    ap.add_argument("--label", default="now")
    ap.add_argument("--hide", default="streams,seed,down,pile")   # 'none' for the control
    a = ap.parse_args()
    HIDE.clear()
    HIDE.update(h for h in a.hide.split(",") if h != "none")
    rng = random.Random(a.rng)
    seeds = ["".join(rng.choice(CHARS) for _ in range(8)) for _ in range(480)][:a.seeds]
    log(f"probe {a.label}: {len(seeds)} seeds (set {a.rng}), {a.workers} workers")
    t0, games = time.time(), []
    with mp.get_context("fork").Pool(a.workers) as pool:
        for g in pool.imap_unordered(play, seeds):
            games.append(g)
            done = len(games)
            eta = (time.time() - t0) / done * (len(seeds) - done)
            log(f"{done}/{len(seeds)} {g['seed']}: {'won' if g['won'] else 'lost at ante ' + str(g['ante'])}, "
                f"{sum(g['asked'].values())} decisions, {len(g['diffs'])} differ ({g['seconds']:.0f}s); ETA {eta / 60:.0f} min")
    asked = sum((Counter(g["asked"]) for g in games), Counter())
    diffs = [dict(d, seed=g["seed"]) for g in games for d in g["diffs"]]
    failed = sum((Counter(g["failed"]) for g in games), Counter())
    log(f"decisions probed: {dict(asked)}")
    for kind, what in (("copy", "the bot against an unchanged copy (memory or caches a copy loses)"),
                       ("leak", "an unchanged copy against one with the hidden things changed")):
        ds = [d for d in diffs if d["kind"] == kind]
        log(f"{kind}: {what}: {len(ds)} differ {dict(Counter(d['decision'] for d in ds))}; "
            f"with face-down cards {sum(d['face_down'] > 0 for d in ds)}; by boss {Counter(d['boss'] for d in ds).most_common(6)}")
        for d in ds[:30]:
            log(f"  {d['seed']} ante {d['ante']} {d['blind']} {d['decision']}: {d['real']}  |  twin: {d['twin']}  "
                f"(offers {', '.join(d['offers']) or '-'}; jokers {', '.join(d['jokers'])}; "
                f"held {', '.join(d['consumables']) or '-'}; {d['face_down']} down)")
    for k, n in failed.most_common(10):
        log(f"  twin failed x{n}: {k}")
    out = ROOT / "runs" / "value" / f"probe_leaks_{a.label}.json"
    out.write_text(json.dumps({"asked": asked, "diffs": diffs, "failed": failed, "games": len(games)}, indent=1))
    log(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
