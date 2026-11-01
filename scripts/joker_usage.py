"""Which jokers the value bot is offered and holds: how often each turns up in a run (shop or Buffoon pack),
how often the bot ends up holding it, and for how many shops. Ranks the jokers worth a behaviour modifier.

Usage:  python3 -u scripts/joker_usage.py [--seeds 192] [--workers 3]
Writes: runs/joker_usage.json
Log:    logs/joker_usage.log (append with >>)
"""
from __future__ import annotations

import argparse
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

from balatro.jokers import Joker  # noqa: E402
from balatro.modifiers import RULES  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot  # noqa: E402

CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
_rng = random.Random(31337)                     # not the evaluation's seeds
SEEDS = ["".join(_rng.choice(CHARS) for _ in range(8)) for _ in range(2000)]


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


class Recorder(ValueBot):
    """The value bot, noting the jokers it is offered and the ones it holds at each shop."""

    def __init__(self):
        super().__init__()
        self.offered, self.held, self._shop, self._seen = set(), Counter(), None, set()

    def shop_action(self, run, shop):
        if run.shops_seen != self._shop:
            self._shop = run.shops_seen
            self.held.update({j.name for j in run.jokers})
        for o in shop.cards:
            if isinstance(o.item, Joker) and id(o) not in self._seen:
                self._seen.add(id(o))
                self.offered.add(o.item.name)
        return super().shop_action(run, shop)

    def pack_action(self, run, pack):
        self.offered.update(x.name for x in pack.cards if isinstance(x, Joker))
        return super().pack_action(run, pack)


def play(seed: str):
    bot = Recorder()
    t = time.time()
    res = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8).play()
    return {"seed": seed, "progress": res.progress, "won": res.won, "offered": sorted(bot.offered),
            "held": dict(bot.held), "seconds": time.time() - t}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=192)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    t0 = time.time()
    log(f"joker usage: value bot (hand-set weights), {args.seeds} seeds, Red Deck to ante 8, {args.workers} workers")
    games = []
    try:
        with mp.get_context("fork").Pool(args.workers) as pool:
            for g in pool.imap_unordered(play, SEEDS[:args.seeds]):
                games.append(g)
                n = len(games)
                if n % 12 == 0 or n == args.seeds:
                    el = time.time() - t0
                    log(f"{n}/{args.seeds} games, {n / el * 60:.1f} a minute, ETA {(args.seeds - n) * el / n / 60:.1f} min")
    except Exception:
        import traceback
        log("failed:\n" + traceback.format_exc())
        return 1
    n = len(games)
    offered, held, shops = Counter(), Counter(), Counter()
    for g in games:
        offered.update(g["offered"])
        held.update(g["held"].keys())
        shops.update(g["held"])
    names = set(offered) | set(held)
    table = sorted(({"joker": j, "offered": offered[j] / n, "held": held[j] / n, "shops_held": shops[j] / n,
                     "rule": j in RULES} for j in names), key=lambda r: -r["shops_held"])
    out = {"games": n, "won": sum(g["won"] for g in games), "jokers": table, "runs": games}
    (ROOT / "runs").mkdir(exist_ok=True)
    (ROOT / "runs" / "joker_usage.json").write_text(json.dumps(out, indent=1))
    log(f"won {out['won']}/{n}; top jokers by shops held (offered in / held in share of runs, shops held a run):")
    for r in table[:60]:
        log(f"  {r['joker']:<22} {r['offered']:5.2f} {r['held']:5.2f} {r['shops_held']:5.2f}{'  (rule)' if r['rule'] else ''}")
    log(f"done in {(time.time() - t0) / 60:.1f} min; exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
