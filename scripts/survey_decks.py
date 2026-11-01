"""How the value bot (hand-set weights) does across decks and stakes: every deck at White Stake and every stake on
the Red Deck, the same fresh seeds in each (a set no choice was tuned on), played to ante 8.

    python3 -u scripts/survey_decks.py [--seeds 160] [--workers 8] >> logs/survey_decks.log 2>&1

Writes runs/value/survey.json (rewritten as each deck or stake finishes): per deck and stake, the share of runs
that beat ante 8, mean progress (blinds passed, plus the share of the failed blind's target reached) and where runs
end."""
import argparse
import json
import multiprocessing as mp
import os
import random
import statistics as st
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VALUEBOT_WEIGHTS", "hand")

import balatro.content  # noqa: E402,F401  (registers the decks)
from balatro.items import DECKS, entries  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot  # noqa: E402

CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
OUT = ROOT / "runs" / "value" / "survey.json"


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def play(task):
    deck, stake, seed = task
    res = Run(ValueBot(), game_seed=seed, deck=deck, stake=stake, max_ante=8).play()
    return deck, stake, seed, res.won, res.progress, res.ante


def summary(games: list) -> dict:
    return {"games": len(games), "won": sum(g[3] for g in games), "won_share": st.mean(g[3] for g in games),
            "progress": st.mean(g[4] for g in games),
            "ends": dict(sorted(Counter(g[5] for g in games if not g[3]).items()))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=160)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    rng = random.Random(2024)
    seeds = ["".join(rng.choice(CHARS) for _ in range(8)) for _ in range(args.seeds)]
    cells = [(d, "White Stake") for d in sorted(DECKS)] + [("Red Deck", s["name"]) for s in entries("stake")
                                                            if s["name"] != "White Stake"]
    tasks = [(d, s, seed) for d, s in cells for seed in seeds]
    log(f"survey: {len(cells)} deck/stake pairs x {len(seeds)} seeds = {len(tasks)} games, {args.workers} workers")
    done, out, t0 = {}, {"seeds": f"{len(seeds)} from set 2024", "cells": {}}, time.time()
    with mp.get_context("fork").Pool(args.workers) as pool:
        for n, g in enumerate(pool.imap_unordered(play, tasks, chunksize=2), 1):
            key = (g[0], g[1])
            done.setdefault(key, []).append(g)
            if len(done[key]) == len(seeds):
                s = out["cells"][f"{key[0]} / {key[1]}"] = summary(done[key])
                log(f"{key[0]}, {key[1]}: beat ante 8 in {s['won']}/{s['games']} ({100 * s['won_share']:.1f}%), "
                    f"progress {s['progress']:.2f}, lost at ante {s['ends']}")
                OUT.write_text(json.dumps(out, indent=1))
            if n % 160 == 0:
                el = time.time() - t0
                log(f"{n}/{len(tasks)} games, ETA {(len(tasks) - n) * el / n / 60:.0f} min")
    log(f"survey done in {(time.time() - t0) / 60:.0f} min; wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
