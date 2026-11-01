"""Tune each behaviour modifier's strength on its own: every game starts with that joker, and only its strength
changes, on the same fresh seeds (Red Deck, to ante 8). A rule's gene in a whole-weights evolution only matters
in the few games where the bot holds that joker; here it matters in all of them.

Usage:  python3 -u scripts/sweep_mods.py [--rules "Runner,Supernova"] [--strengths 0,0.5,1,1.5,2,3] [--seeds 480]
                                         [--workers W] [--weights GENOME.json]
Writes: runs/sweeps/<rule>.json per rule as it finishes (a rerun skips those), runs/sweeps/strengths.json (the
        strength to use per rule: the one that beats ante 8 most often, if it beats 1 at that by more than twice
        its standard error, else 1)
Log:    logs/sweep_mods.log (append with >>)
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import os
import random
import signal
import statistics as st
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VALUEBOT_WEIGHTS", "hand")

from balatro.jokers import CATALOG  # noqa: E402
from balatro.modifiers import RULES  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot, Weights, weights_of  # noqa: E402

OUT = ROOT / "runs" / "sweeps"
CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
_rng = random.Random(90210)                     # the evaluation's fresh seeds (scripts/eval_value.py)
SEEDS = ["".join(_rng.choice(CHARS) for _ in range(8)) for _ in range(480)]
BASE: Weights | None = None


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def play(task):
    rule, strength, seed = task
    bot = ValueBot()
    bot.w = copy.deepcopy(BASE)
    bot.w.mods[rule] = strength
    run = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8)
    j = CATALOG[rule]()
    run.jokers = [j]
    j.on_added(run)
    res = run.play()
    return rule, strength, seed, res.progress, res.won


def _worker_init() -> None:
    signal.signal(signal.SIGTERM, signal.SIG_DFL)      # workers just end; the sweep itself handles a stop


def running_table_builds() -> list[int]:
    """Seed-table builds running now (one paused by another job stays paused, and isn't resumed here)."""
    pids = [int(p) for p in subprocess.run(["pgrep", "-f", r"^\./table build"], capture_output=True, text=True).stdout.split()]
    return [p for p in pids if not subprocess.run(["ps", "-o", "stat=", "-p", str(p)], capture_output=True,
                                                  text=True).stdout.strip().startswith("T")]


def summary(rule: str, games: dict, strengths: list) -> dict:
    """games: strength -> {seed: (progress, won)}. The goal is beating ante 8, so the best strength is the one
    that beats it most often (progress breaks ties): mean progress alone can favour surviving the early antes
    over winning (the weights evolution of 20261026 did)."""
    ref = games[1.0]
    rows = []
    for s in strengths:
        g = games[s]
        dw = [g[k][1] - ref[k][1] for k in g]
        dp = [g[k][0] - ref[k][0] for k in g]
        se = (lambda d: st.stdev(d) / len(d) ** 0.5 if s != 1.0 else 0.0)
        rows.append({"strength": s, "won": sum(w for _, w in g.values()) / len(g),
                     "progress": st.mean(p for p, _ in g.values()),
                     "won_vs_1": st.mean(dw), "won_se": se(dw), "progress_vs_1": st.mean(dp), "progress_se": se(dp)})
    best = max(rows, key=lambda r: (r["won"], r["progress"]))
    use = best["strength"] if best["strength"] != 1.0 and best["won_vs_1"] > 2 * best["won_se"] else 1.0
    return {"rule": rule, "seeds": len(ref), "rows": rows, "best": best["strength"], "use": use}


def write_partial(path: Path, games: dict, strengths: list) -> None:
    """The jokers still playing, so far: each one's summary over the seeds every strength has finished."""
    rules = {}
    for rule, by_s in games.items():
        seeds = set.intersection(*(set(by_s.get(s, {})) for s in strengths))
        if len(seeds) >= 2:
            res = summary(rule, {s: {k: by_s[s][k] for k in seeds} for s in strengths}, strengths)
            rules[rule] = {**res, "games": sum(len(v) for v in by_s.values())}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "rules": rules}))
    os.replace(tmp, path)


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default="")
    ap.add_argument("--strengths", default="0,0.5,1,1.5,2,3")
    ap.add_argument("--seeds", type=int, default=480)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--weights", default="")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    out = Path(args.out)
    BASE = weights_of(json.loads(Path(args.weights).read_text()).get("genome", {})) if args.weights else Weights()
    strengths = sorted({float(s) for s in args.strengths.split(",")} | {1.0})
    rules = [r.strip() for r in args.rules.split(",") if r.strip()] or [r for r in RULES if r in CATALOG]
    out.mkdir(parents=True, exist_ok=True)
    todo = [r for r in rules if not (out / f"{r}.json").exists()]
    # seed by seed, every strength of a seed together: a joker's partial results compare strengths on the same seeds
    tasks = [(r, s, seed) for r in todo for seed in SEEDS[:args.seeds] for s in strengths]
    (out / "plan.json").write_text(json.dumps({"rules": rules, "strengths": strengths, "seeds": args.seeds,
                                               "weights": args.weights or "hand-set",
                                               "started": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1))
    log(f"sweep: {len(todo)} rules ({len(rules) - len(todo)} done before), strengths {strengths}, {args.seeds} seeds, "
        f"{len(tasks)} games, {args.workers} workers, weights {args.weights or 'hand-set'}")
    t0, done = time.time(), 0
    games: dict = defaultdict(lambda: defaultdict(dict))
    per_rule = len(strengths) * args.seeds
    paused = running_table_builds()                 # the seed-table build would take half the cores
    for pid in paused:
        os.kill(pid, signal.SIGSTOP)
    if paused:
        log(f"table build {paused} paused")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    saved = time.time()
    try:
        with mp.get_context("fork").Pool(args.workers, initializer=_worker_init) as pool:
            for rule, s, seed, progress, won in pool.imap_unordered(play, tasks, chunksize=4):
                games[rule][s][seed] = (progress, won)
                done += 1
                if done % 240 == 0:
                    el = time.time() - t0
                    log(f"{done}/{len(tasks)} games, {done / el * 60:.0f} a minute, ETA {(len(tasks) - done) * el / done / 60:.0f} min")
                if sum(len(v) for v in games[rule].values()) == per_rule:
                    res = summary(rule, games[rule], strengths)
                    (out / f"{rule}.json").write_text(json.dumps(res, indent=1))
                    cells = ", ".join(f"{r['strength']:g}: {100 * r['won']:.1f}% ({100 * r['won_vs_1']:+.1f}±{100 * r['won_se']:.1f}), "
                                      f"progress {r['progress']:.2f}" for r in res["rows"])
                    log(f"{rule}: {cells}; use {res['use']:g}")
                    del games[rule]
                    saved = 0.0                                    # the partial file drops it at once
                if time.time() - saved > 20:
                    write_partial(out / "partial.json", games, strengths)
                    saved = time.time()
        (out / "partial.json").unlink(missing_ok=True)
    except Exception:
        import traceback
        log("failed:\n" + traceback.format_exc())
        return 1
    finally:
        for pid in paused:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        if paused:
            log(f"table build {paused} resumed")
    use = {}
    for r in rules:
        path = out / f"{r}.json"
        if path.exists():
            use[r] = json.loads(path.read_text())["use"]
    (out / "strengths.json").write_text(json.dumps(use, indent=1))
    changed = {r: s for r, s in use.items() if s != 1.0}
    log(f"done in {(time.time() - t0) / 60:.0f} min: {len(use)} rules, changed {changed}; exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
