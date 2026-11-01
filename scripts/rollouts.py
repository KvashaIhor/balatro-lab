"""Paired outcomes for the value network. At sampled shop and pack decisions of a game, the game is played on
once for each option (a forked process takes the option and plays the rest as the bot would; the seed makes
everything else the same), so the outcomes differ only by that choice: its real effect, with no luck mixed in.

Usage:  python3 -u scripts/rollouts.py --decisions 50000 --tag NAME [--sample 0.15] [--max-options 8] [--workers W]
Writes: runs/value/data/pairs_<tag>.npz: X (float16 [rows, features]: the position after each option, as
        balatro.value.features reads it), y (the progress the game reached with it), group (the decision),
        kind (KINDS index), chosen (1 for the bot's own pick)
Log:    logs/value_rollouts.log (append with >>)

The bot is the value bot with evolution's best correction network (beats ante 8 in 10% of games); its games
take a random option a tenth of the time, so the decisions sampled cover more than it would play. Seeds are
new (Red Deck, up to ante 8) and never the evaluation's.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VALUEBOT_WEIGHTS", "hand")

import numpy as np  # noqa: E402

from balatro.items import Consumable  # noqa: E402
from balatro.jokers import Joker  # noqa: E402
from balatro.neural import Network  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot, action_key, weights_of  # noqa: E402
from balatro.value import after_pack, after_shop, as_action, features, pack_options, shop_options  # noqa: E402

DATA = ROOT / "runs" / "value" / "data"
CHAMPION = ROOT / "runs" / "evolve" / "20261025-220949" / "champion.json"
CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
KINDS = ["leave", "buy joker", "buy to keep", "buy and use", "buy playing card", "buy pack", "buy voucher",
         "sell for a joker", "reroll", "skip pack", "pick joker", "pick consumable", "pick playing card"]
ARGS = None


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def kind_of(option, offers) -> int:
    k = option[0]
    if k in ("leave", "skip", "reroll"):
        return KINDS.index({"leave": "leave", "skip": "skip pack", "reroll": "reroll"}[k])
    if k == "sell_joker":
        return KINDS.index("sell for a joker")
    if k == "buy_use":
        return KINDS.index("buy and use")
    if k == "pick":
        item = offers[option[1]]
        return KINDS.index("pick joker" if isinstance(item, Joker) else "pick consumable" if isinstance(item, Consumable)
                           else "pick playing card")
    where, i = option[1], option[2]
    if where == "pack":
        return KINDS.index("buy pack")
    if where == "voucher":
        return KINDS.index("buy voucher")
    item = offers[i].item
    return KINDS.index("buy joker" if isinstance(item, Joker) else "buy to keep" if isinstance(item, Consumable)
                       else "buy playing card")


class Collector(ValueBot):
    """The bot, which at sampled decisions of its own game plays each option on in a fork and notes the result."""

    def setup(self, rng):
        self.rng, self.real, self.pipe, self.queued, self.groups = rng, None, None, None, []

    def _branch(self, run, options, afters, chosen, offers):
        """Fork once per option: the child returns its option (True), the parent notes each outcome (False)."""
        outcomes = []
        for opt in options:
            r, w = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(r)
                self.pipe, self.real = w, None                  # the child plays the rest as the bot, untouched
                self.forced = opt
                return True
            os.close(w)
            chunks = []
            while True:
                b = os.read(r, 64)
                if not b:
                    break
                chunks.append(b)
            os.close(r)
            os.waitpid(pid, 0)
            try:
                outcomes.append(float(b"".join(chunks)))
            except ValueError:
                outcomes.append(math.nan)
        y = np.array(outcomes, np.float32)
        if np.isfinite(y).all():
            self.groups.append({"X": np.stack(afters).astype(np.float16), "y": y, "ante": run.ante,
                                "kind": np.array([kind_of(o, offers) for o in options], np.int8),
                                "chosen": np.array([o == chosen for o in options], np.int8)})
        return False

    def _pick(self, run, options, policy):
        """Options to try (at most --max-options: leaving or skipping, the bot's own, the rest at random, with at
        most two sales for another joker, which would otherwise crowd the rest out)."""
        own = next((o for o in options if action_key(as_action(o)) == action_key(policy)), None)
        keep = [o for o in options if o in (options[0], own)]
        sells = [o for o in options if o not in keep and o[0] == "sell_joker"]
        rest = [o for o in options if o not in keep and o[0] != "sell_joker"]
        self.rng.shuffle(sells)
        rest += sells[:2]
        self.rng.shuffle(rest)
        return keep + rest[:max(0, ARGS.max_options - len(keep))], own

    def shop_action(self, run, shop):
        if self.queued:                                          # the buy after a sale for another joker
            action, self.queued = self.queued, None
            return action
        if getattr(self, "forced", None) is not None:
            opt, self.forced = self.forced, None
            if opt[0] == "sell_joker":
                self.queued = ("buy", "card", opt[2])
            return as_action(opt)
        policy = super().shop_action(run, shop)
        if run is not self.real or policy[0] not in ("buy", "buy_use", "sell_joker", "reroll", "leave"):
            return policy
        options = [("leave",)] + shop_options(run, shop)
        explore = self.rng.random() < ARGS.epsilon
        if len(options) >= 2 and self.rng.random() < ARGS.sample:
            tried, own = self._pick(run, options, policy)
            afters = [features(run, self.power(run))] + [features(t, self.power(t)) for t in
                                                          (after_shop(self, run, shop, o) for o in tried[1:])]
            if self._branch(run, tried, afters, own, shop.cards):
                return self.shop_action(run, shop)               # in the child: take the forced option
        if explore:
            opt = self.rng.choice(options)
            if opt[0] == "sell_joker":
                self.queued = ("buy", "card", opt[2])
            return as_action(opt)
        return policy

    def pack_action(self, run, pack):
        if getattr(self, "forced", None) is not None:
            opt, self.forced = self.forced, None
            return opt
        policy = super().pack_action(run, pack)
        if run is not self.real:
            return policy
        options = [("skip",)] + pack_options(self, run, pack)
        explore = self.rng.random() < ARGS.epsilon
        if len(options) >= 2 and self.rng.random() < ARGS.sample:
            tried, own = self._pick(run, options, policy)
            afters = [features(run, self.power(run))] + [features(t, self.power(t)) for t in
                                                          (after_pack(self, run, o) for o in tried[1:])]
            if self._branch(run, tried, afters, own, pack.cards):
                return self.pack_action(run, pack)
        if explore:
            return self.rng.choice(options)
        return policy


def play(game: int):
    bot = Collector()
    champ = json.loads(CHAMPION.read_text())
    bot.w, bot.net = weights_of(champ["genome"]), Network(champ["network"]["params"])
    bot.setup(random.Random(f"rollouts:{ARGS.tag}:{game}"))
    seed = "".join(random.Random(f"rollouts-seed:{ARGS.tag}:{game}").choice(CHARS) for _ in range(8))
    run = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8)
    bot.real = run
    t = time.time()
    progress, err = math.nan, None
    try:
        progress = run.play().progress
    except BaseException as exc:  # noqa: BLE001
        err = f"{seed}: {type(exc).__name__}: {exc}"
    finally:
        if bot.pipe is not None:                                 # a fork: report the outcome and vanish
            os.write(bot.pipe, repr(progress).encode())
            os._exit(0)
    return game, bot.groups, progress, err, time.time() - t


def save(out: Path, groups: list[dict]) -> None:
    gid = np.concatenate([np.full(len(g["y"]), k, np.int32) for k, g in enumerate(groups)])
    tmp = out.with_suffix(".tmp.npz")
    np.savez(tmp, X=np.concatenate([g["X"] for g in groups]), y=np.concatenate([g["y"] for g in groups]), group=gid,
             kind=np.concatenate([g["kind"] for g in groups]), chosen=np.concatenate([g["chosen"] for g in groups]),
             ante=np.array([g["ante"] for g in groups], np.int8), kinds=np.array(KINDS))
    tmp.replace(out)


def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", type=int, default=50000)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sample", type=float, default=0.15)
    ap.add_argument("--max-options", type=int, default=8)
    ap.add_argument("--epsilon", type=float, default=0.1)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ARGS = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / f"pairs_{ARGS.tag}.npz"
    t0 = time.time()
    log(f"rollouts {ARGS.tag}: until {ARGS.decisions} decisions, sampling {ARGS.sample} of them, "
        f"at most {ARGS.max_options} options each, {ARGS.workers} workers")
    groups, games, failed, last, saved = [], 0, 0, 0, 0
    enough = False

    def tasks():
        game = 0
        while not enough:
            yield game
            game += 1

    with mp.get_context("fork").Pool(ARGS.workers) as pool:
        for game, gs, progress, err, sec in pool.imap_unordered(play, tasks(), chunksize=1):
            games += 1
            if err:
                failed += 1
                if failed <= 10:
                    log(f"game {game} failed: {err}")
            groups.extend(gs)
            n = len(groups)
            if n - last >= 1000 or n >= ARGS.decisions:
                last = n
                el = time.time() - t0
                rows = sum(len(g["y"]) for g in groups)
                log(f"{n}/{ARGS.decisions} decisions ({rows} option outcomes) from {games} games, {el / 60:.1f} min, "
                    f"about {el / n * (ARGS.decisions - n) / 60:.0f} min left")
            if n - saved >= 5000:                                  # so far, for an early look
                saved = n
                save(out, groups)
            if n >= ARGS.decisions:
                enough = True
                pool.terminate()
                break
    save(out, groups)
    gid = np.concatenate([np.full(len(g["y"]), k, np.int32) for k, g in enumerate(groups)])
    spread = np.mean([g["y"].max() - g["y"].min() for g in groups])
    log(f"wrote {out.relative_to(ROOT)}: {len(groups)} decisions, {len(gid)} option outcomes from {games} games "
        f"({failed} failed); best and worst option of a decision differ by {spread:.2f} progress on average; "
        f"{(time.time() - t0) / 60:.1f} min; exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
