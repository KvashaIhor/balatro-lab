"""Self-play for the value network: play many games and record, at every shop and pack decision, the position
(balatro.value.features) and how far that game went in the end (progress, 24 = ante 8 beaten).

Usage:  python3 -u scripts/selfplay.py --round R --games N [--value runs/value/vK.npz] [--epsilon 0.1] [--workers W]
Writes: runs/value/data/round<R>.npz (X float16 [rows, features], y progress, game index per row)
Log:    logs/value_selfplay.log (append with >>)

With no --value (round 0) the value bot plays, with the best correction network from evolution
(runs/evolve/20261025-220949, its champion) and a random option `epsilon` of the time; with --value the value
network's bot plays. Seeds are new for each round (Red Deck, up to ante 8) and never the evaluation's.
"""
from __future__ import annotations

import argparse
import json
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

from balatro.neural import Network  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot, action_key, weights_of  # noqa: E402
from balatro.value import N_FEATURES, ValueNet, ValueNetBot, features  # noqa: E402

DATA = ROOT / "runs" / "value" / "data"
CHAMPION = ROOT / "runs" / "evolve" / "20261025-220949" / "champion.json"
CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
ARGS = None
VALUE = None


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def unkey(key: tuple) -> tuple:
    """An action back from action_key (target tuples become lists again)."""
    return tuple(list(x) if isinstance(x, tuple) else x for x in key)


def recording(cls):
    """`cls` noting the position at each of its own shop and pack decisions (not the copies it tries), and with
    the value bot, taking a random one of the options it weighed `explore` of the time."""

    class Recording(cls):
        def _note(self, run):
            if run is self.real:
                self.rows.append(features(run, self.power(run)))

        def _maybe_explore(self, run, action):
            if (self.explore and run is self.real and action_key(action) in getattr(self, "worths", {})
                    and self.rng.random() < self.explore):
                return unkey(self.rng.choice(sorted(self.worths, key=str)))
            return action

        def shop_action(self, run, shop):
            self._note(run)
            return self._maybe_explore(run, super().shop_action(run, shop))

        def pack_action(self, run, pack):
            self._note(run)
            return self._maybe_explore(run, super().pack_action(run, pack))

    return Recording


def make_bot(game: int):
    if VALUE is not None:
        bot = recording(ValueNetBot)(VALUE, epsilon=ARGS.epsilon, seed=game)
        bot.explore = 0.0                                  # ValueNetBot explores by itself
    else:
        bot = recording(ValueBot)()
        champ = json.loads(CHAMPION.read_text())
        bot.w, bot.net = weights_of(champ["genome"]), Network(champ["network"]["params"])
        bot.explore = ARGS.epsilon
    bot.rng, bot.rows = random.Random(f"{ARGS.round}:{game}"), []
    return bot


def play(game: int):
    bot = make_bot(game)
    seed = "".join(random.Random(f"selfplay:{ARGS.round}:{game}").choice(CHARS) for _ in range(8))
    run = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8)
    bot.real = run
    t = time.time()
    try:
        res = run.play()
    except Exception as exc:  # noqa: BLE001 - one broken game shouldn't end the round
        return game, None, 0.0, False, f"{seed}: {type(exc).__name__}: {exc}", time.time() - t
    rows = np.stack(bot.rows).astype(np.float16) if bot.rows else np.zeros((0, N_FEATURES), np.float16)
    return game, rows, res.progress, res.won, None, time.time() - t


def main() -> int:
    global ARGS, VALUE
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--value", help="a trained value network (.npz); none: the value bot plays")
    ap.add_argument("--epsilon", type=float, default=0.1)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ARGS = ap.parse_args()
    if ARGS.value:
        VALUE = ValueNet(ARGS.value)
    DATA.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log(f"selfplay round {ARGS.round}: {ARGS.games} games, bot {ARGS.value or 'value bot + correction network'}, "
        f"epsilon {ARGS.epsilon}, {ARGS.workers} workers")
    xs, ys, gs, progress, won, failed, secs = [], [], [], [], 0, 0, 0.0
    with mp.get_context("fork").Pool(ARGS.workers) as pool:
        for n, (game, rows, prog, w, err, sec) in enumerate(pool.imap_unordered(play, range(ARGS.games), chunksize=2), 1):
            if err:
                failed += 1
                if failed <= 10:
                    log(f"game {game} failed: {err}")
            elif len(rows):
                xs.append(rows)
                ys.append(np.full(len(rows), prog, np.float32))
                gs.append(np.full(len(rows), game, np.int32))
                progress.append(prog)
                won += w
                secs += sec
            if n % 250 == 0 or n == ARGS.games:
                el = time.time() - t0
                log(f"{n}/{ARGS.games} games, {sum(map(len, xs))} positions, mean progress {np.mean(progress):.2f}, "
                    f"beat ante 8 {won}/{len(progress)} ({100 * won / max(1, len(progress)):.1f}%), {secs / max(1, len(progress)):.2f}s a game; "
                    f"{el / 60:.1f} min, about {el / n * (ARGS.games - n) / 60:.1f} min left")
    out = DATA / f"round{ARGS.round}.npz"
    np.savez(out, X=np.concatenate(xs), y=np.concatenate(ys), game=np.concatenate(gs))
    log(f"wrote {out.relative_to(ROOT)}: {sum(map(len, xs))} positions from {len(progress)} games ({failed} failed), "
        f"mean progress {np.mean(progress):.2f}, beat ante 8 {100 * won / max(1, len(progress)):.1f}%, "
        f"{(time.time() - t0) / 60:.1f} min; exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
