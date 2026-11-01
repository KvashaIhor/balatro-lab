"""How a network run's champion values every card at each ante: what the Evolution tab's "Value by ante" shows.

Usage:  python3 -u scripts/timing.py RUN_ID [--seeds 16]
Writes: runs/evolve/<run id>/timing_<gen>.json (gen: the champion's generation)

The champion (its weights and network) plays benchmark seeds, side by side; at the first shop of every ante it
values each item there and then: total worth (what the value bot would pay for it: build power gained plus
weights, plus the network's correction) and the network's correction alone. Values are averaged per ante over the
games that got that far: with few seeds the late antes are one game's build (4 seeds left antes 7-10 to a single
Joker Stencil build, where any joker added was worth less), so 16 is the default. Tarots and spectrals that need
cards in hand to use are valued as bought to keep. Takes a minute or two.
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from balatro.items import CONSUMABLES  # noqa: E402
from balatro.jokers import CATALOG  # noqa: E402
from balatro.neural import ITEMS, Network  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.shop import PACKS  # noqa: E402
from balatro.strategy import PACK_SIZE, ValueBot, weights_of  # noqa: E402
from evolve_valuebot import BENCH, RUNS, write  # noqa: E402


class Appraiser(ValueBot):
    """The champion's value bot, noting at the first shop of each ante what every item would be worth."""

    def __init__(self):
        self.notes, self.seen = defaultdict(lambda: defaultdict(list)), set()

    def shop_action(self, run, shop):
        if run.ante not in self.seen:
            self.seen.add(run.ante)
            base = self.power(run)
            adj = self.adjust(run, base)
            for key in ITEMS:
                kind, name = key
                correction = adj(key)
                total = None
                if kind == "joker" and name in CATALOG:
                    total = self.joker_worth(run, CATALOG[name](), base) + correction
                elif kind in ("tarot", "planet", "spectral") and name in CONSUMABLES:
                    item = CONSUMABLES[name]()
                    if item.can_use(run, []):
                        worth = self.planet_worth(run, item)
                        if worth is None:
                            worth = self.effect_worth(run, lambda trial, it=item: trial.apply_consumable(copy.deepcopy(it), []))
                        total = worth + correction
                    else:
                        total = self.w.keep + adj(("keep", item.kind)) + correction
                elif kind == "pack":
                    p = PACKS[name]
                    total = self.w.packs.get(p.kind, 0.0) * PACK_SIZE.get(p.size, 1.0) + correction
                elif kind == "voucher":
                    total = self.w.vouchers.get(name, 0.1) + correction
                elif kind == "keep":
                    total = self.w.keep + correction
                self.notes[run.ante][key].append((total, correction))
        return super().shop_action(run, shop)


CHAMP = None


def appraise(task) -> dict:
    """One benchmark game: what every item was worth at the first shop of each ante."""
    seed, deck = task
    bot = Appraiser()
    bot.w, bot.net = weights_of(CHAMP["genome"]), Network(CHAMP["network"]["params"])
    Run(bot, game_seed=seed, deck=deck, max_ante=16).play()
    return {ante: dict(items) for ante, items in bot.notes.items()}


def main() -> int:
    global CHAMP
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    run_dir = RUNS / args.run_id
    CHAMP = champ = json.loads((run_dir / "champion.json").read_text())
    t0 = time.time()
    notes = defaultdict(lambda: defaultdict(list))
    with mp.get_context("fork").Pool(min(args.workers, args.seeds)) as pool:
        for game in pool.imap_unordered(appraise, BENCH[:args.seeds]):
            for ante, items in game.items():
                for key, values in items.items():
                    notes[ante][key].extend(values)
    antes = sorted(notes)
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    out = {"gen": champ["gen"], "antes": antes, "seeds": args.seeds, "items": [list(k) for k in ITEMS],
           "shops": [len(next(iter(notes[a].values()))) for a in antes],
           "total": [[mean([t for t, _ in notes[a][k] if t is not None]) for a in antes] for k in ITEMS],
           "correction": [[mean([c for _, c in notes[a][k]]) for a in antes] for k in ITEMS],
           "seconds": round(time.time() - t0, 1)}
    write(run_dir / f"timing_{champ['gen']}.json", out)
    print(f"timing {args.run_id} gen {champ['gen']}: antes {antes}, {out['seconds']}s; exit 0", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
