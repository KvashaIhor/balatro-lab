"""How often a bot beats ante 8: 480 fresh seeds (Red Deck), never used for training or picking a model.

Usage:  python3 -u scripts/eval_value.py --bot BOT --label NAME [--seeds 480] [--workers W] [--rng 90210]
        BOT: base (the value bot, hand-set weights), champion[:<run id>] (plus that evolution run's best network),
             value:<path to .npz> (the value network's bot), model:<id> (a run viewer model, e.g. model:jev)
Writes: runs/value/eval_<label>.json (and, per game, its seed, progress and ante)
Log:    logs/value_eval.log (append with >>)
"""
from __future__ import annotations

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

from balatro.neural import Network  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot, weights_of  # noqa: E402
from balatro.value import GuidedBot, ValueNet, ValueNetBot  # noqa: E402

CHAMPION = ROOT / "runs" / "evolve" / "20261025-220949" / "champion.json"
CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
_rng = random.Random(90210)
SEEDS = ["".join(_rng.choice(CHARS) for _ in range(8)) for _ in range(480)]
BOT = None
MAX_ANTE = 8                                           # --max-ante: play on past ante 8 (depth), 16 at most


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def make_bot():
    if BOT == "base":
        return ValueBot()
    if BOT.startswith("model:"):                           # model:<id>, any model of the run viewer (balatro/models.py)
        from balatro.models import make
        return make(BOT.split(":", 1)[1])
    if BOT == "champion" or BOT.startswith("champion:"):     # champion:<run id> for another evolution run's
        bot = ValueBot()
        path = ROOT / "runs" / "evolve" / BOT.split(":", 1)[1] / "champion.json" if ":" in BOT else CHAMPION
        champ = json.loads(path.read_text())
        bot.w = weights_of(champ["genome"])
        bot.net = Network(champ["network"]["params"]) if champ.get("network") else None
        return bot
    if BOT.startswith("guided:"):                          # guided:<npz>:<confidence>, on the champion
        bot = GuidedBot(VALUE, float(BOT.rsplit(":", 1)[1]))
        champ = json.loads(CHAMPION.read_text())
        bot.w, bot.net = weights_of(champ["genome"]), Network(champ["network"]["params"])
        return bot
    return ValueNetBot(VALUE)


def play(seed: str):
    t = time.time()
    bot = make_bot()
    res = Run(bot, game_seed=seed, deck="Red Deck", max_ante=MAX_ANTE).play()
    out = {"seed": seed, "progress": res.progress, "won": res.won, "ante": res.ante, "seconds": time.time() - t}
    if getattr(bot, "plan_log", None):                   # the build plan's changes (strategy.py PLAN)
        out["plan"] = bot.plan_log
    if getattr(bot, "jev", None) is not None:                # what Jev was asked, and what it cost
        out["jev"] = {**bot.jev.usage, "dollars": bot.jev.cost()}
    return out


def main() -> int:
    global BOT, VALUE, MAX_ANTE
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--seeds", type=int, default=480)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--rng", type=int, default=90210)   # another set of fresh seeds (e.g. to check what was tuned on these)
    ap.add_argument("--max-ante", type=int, default=8)   # play on past ante 8 to see how deep runs go (the plan's depth)
    args = ap.parse_args()
    MAX_ANTE = max(8, min(16, args.max_ante))
    seeds = SEEDS
    if args.rng != 90210:
        rng = random.Random(args.rng)
        seeds = ["".join(rng.choice(CHARS) for _ in range(8)) for _ in range(480)]
    BOT = args.bot
    if BOT.startswith("value:"):
        VALUE = ValueNet(BOT.split(":", 1)[1])
    elif BOT.startswith("guided:"):
        VALUE = ValueNet(BOT.split(":")[1])
    t0 = time.time()
    log(f"eval {args.label}: bot {BOT}, {args.seeds} fresh seeds (set {args.rng}), Red Deck to ante {MAX_ANTE}")
    games = []
    with mp.get_context("fork").Pool(args.workers) as pool:
        for g in pool.imap(play, seeds[:args.seeds], chunksize=2):
            games.append(g)
            if len(games) % 48 == 0:
                el = time.time() - t0
                won = sum(x["won"] for x in games)
                log(f"{args.label}: {len(games)}/{args.seeds} games, ETA {(args.seeds - len(games)) * el / len(games) / 60:.1f} min; "
                    f"so far beat ante 8 in {won} ({won / len(games):.1%})")
    won = sum(g["won"] for g in games)
    out = {"label": args.label, "bot": BOT, "games": len(games), "won": won, "won_share": won / len(games),
           "progress": st.mean(g["progress"] for g in games),
           "ends": dict(sorted(Counter(g["ante"] for g in games if not g["won"]).items())),
           "seconds_per_game": st.mean(g["seconds"] for g in games), "runs": games}
    (ROOT / "runs" / "value").mkdir(parents=True, exist_ok=True)
    (ROOT / "runs" / "value" / f"eval_{args.label}.json").write_text(json.dumps(out, indent=1))
    asked = [g["jev"] for g in games if "jev" in g]
    if asked:
        n = sum(a.get("decisions", 0) for a in asked)
        log(f"{args.label}: Jev decided {n:,} moves, agreed with the value bot on {100 * sum(a.get('agreed', 0) for a in asked) / max(1, n):.0f}%, "
            f"{sum(a.get('calls', 0) for a in asked):,} calls ({sum(a.get('cached', 0) for a in asked):,} cached), "
            f"${sum(a['dollars'] for a in asked):.4f}")
    log(f"{args.label}: beat ante 8 in {won}/{len(games)} ({100 * out['won_share']:.1f}%), mean progress {out['progress']:.2f}, "
        f"runs end at ante {out['ends']}, {out['seconds_per_game']:.2f}s a game; {(time.time() - t0) / 60:.1f} min; exit 0")
    return 0


VALUE = None

if __name__ == "__main__":
    raise SystemExit(main())
