"""The value bot on its own (hand-set weights, no network) over the 48 benchmark seeds: how a change to how it
plays rounds shows, before any search or evolution.

Usage:  python3 -u scripts/bench_bot.py --label NAME [--workers N]
Writes: runs/bench/bot_<label>.json   Log: logs/bench_bot.log (append with >>)
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["VALUEBOT_WEIGHTS"] = "hand"

from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot  # noqa: E402
from evolve_valuebot import BENCH  # noqa: E402


class Counting(ValueBot):
    def round_action(self, run):
        action = super().round_action(run)
        self.counts[action[0]] += 1
        return action


def play(task):
    seed, deck = task
    bot = Counting()
    bot.counts = Counter()
    t = time.time()
    res = Run(bot, game_seed=seed, deck=deck, max_ante=16).play()
    return {"seed": seed, "deck": deck, "progress": res.progress, "ante": res.ante, "won": res.won,
            "plays": bot.counts["play"], "discards": bot.counts["discard"], "seconds": time.time() - t}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--discard-gain", type=float, help="ValueBot.DISCARD_GAIN to try instead of its own")
    args = ap.parse_args()
    if args.discard_gain is not None:
        ValueBot.DISCARD_GAIN = args.discard_gain
    t0 = time.time()
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  bench_bot {args.label}: {len(BENCH)} seeds, {args.workers} workers", flush=True)
    with mp.get_context("fork").Pool(args.workers) as pool:
        runs = pool.map(play, BENCH)
    n = len(runs)
    mean = lambda k: sum(r[k] for r in runs) / n
    out = {"label": args.label, "progress": round(mean("progress"), 3), "won": sum(r["won"] for r in runs),
           "plays": round(mean("plays"), 1), "discards": round(mean("discards"), 1),
           "seconds_per_run": round(mean("seconds"), 3), "runs": runs}
    (ROOT / "runs" / "bench").mkdir(parents=True, exist_ok=True)
    (ROOT / "runs" / "bench" / f"bot_{args.label}.json").write_text(json.dumps(out, indent=1))
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {args.label}: progress {out['progress']}, won to ante 8 {out['won']}/{n}, "
          f"per run {out['plays']} hands played, {out['discards']} discards, {out['seconds_per_run']}s; "
          f"{time.time() - t0:.0f}s in all; exit 0", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
