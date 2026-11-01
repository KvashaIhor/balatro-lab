"""Train the value bot's neural correction (balatro/neural.py) with an evolution strategy.

Usage:  python3 -u scripts/evolve_neural.py [--run-id ID] [--generations 150] [--pairs 32] [--seeds 24]
                                           [--sigma 0.05] [--lr 0.02] [--base hand|<run id>] [--init <run id>]
Writes: runs/evolve/<run id>/ like a weight run (config.json, status.json, generations.jsonl, champion.json),
        so the Evolution tab shows it; the champion carries the network. Log: logs/evolve_<run id>.log.

The value bot's weights stay fixed (--base: the hand-set ones, or a run's champion); only the network learns.
Each generation samples `pairs` random directions and plays the network nudged both ways (+sigma, -sigma) on
the same fresh seeds, so each pair differs only by its nudge; the network then moves toward the better side of
each pair (by rank, so one lucky seed can't dominate), with Adam. After each step the network plays the fixed
benchmark of 48 seeds (bot alone); the best becomes the champion. --init starts from an earlier network run's
champion. Fitness is progress (blinds beaten plus the share of the failed blind; ante = progress / 3 + 1).
Seed-table builds are paused while it runs.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import signal
import statistics
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from balatro.neural import FACTS, ITEMS, N_PARAMS, Network  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import GENES, ValueBot, Weights, genome_of, load_planner, weights_of  # noqa: E402
from evolve_valuebot import BENCH, RUNS, SEED_CHARS, Stop, running_table_builds, write  # noqa: E402


def _worker_init() -> None:
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def play(task) -> tuple[int, float]:
    """A network (with fixed base weights) over some seeds: (index, total progress)."""
    ind, params, genome, seeds = task
    total = 0.0
    for seed, deck in seeds:
        try:
            bot = ValueBot()
            bot.w = weights_of(genome)
            bot.net = Network(params) if params is not None else None
            total += Run(bot, game_seed=seed, deck=deck, max_ante=16).play().progress
        except Exception:
            traceback.print_exc()
    return ind, total


def score(pool, nets: list, genome: dict, seeds: list, chunk: int = 24) -> list[float]:
    """Mean progress of each network (None: no network) over the seeds."""
    tasks = [(i, p, genome, seeds[k:k + chunk]) for i, p in enumerate(nets) for k in range(0, len(seeds), chunk)]
    totals = [0.0] * len(nets)
    for i, t in pool.imap_unordered(play, tasks):
        totals[i] += t
    return [t / len(seeds) for t in totals]


def ranks(values: list[float]) -> np.ndarray:
    """Centred ranks in [-0.5, 0.5]: the step depends on order, not on how lucky a seed was."""
    order = np.argsort(values)
    r = np.empty(len(values))
    r[order] = np.arange(len(values))
    return r / (len(values) - 1) - 0.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--generations", type=int, default=150)
    ap.add_argument("--pairs", type=int, default=32)
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--sigma", type=float, default=0.05)
    ap.add_argument("--lr", type=float, default=0.02)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--base", default="hand", help="the fixed weights: hand, or an evolution run whose champion's weights to use")
    ap.add_argument("--init", default="", help="start from this network run's champion")
    args = ap.parse_args()
    run_dir = RUNS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fh = open(ROOT / "logs" / f"evolve_{args.run_id}.log", "a")
    t0 = time.time()

    def log(msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
        print(line, flush=True)
        fh.write(line + "\n")
        fh.flush()

    status = {"state": "running", "gen": 0, "generations": args.generations, "pid": os.getpid(),
              "started": time.strftime("%Y-%m-%d %H:%M:%S"), "updated": None, "error": None}

    def set_status(**kw) -> None:
        status.update(kw, updated=time.strftime("%Y-%m-%d %H:%M:%S"))
        write(run_dir / "status.json", status)

    def on_term(signum, frame):
        raise Stop()

    signal.signal(signal.SIGTERM, on_term)
    set_status()
    base = genome_of(Weights()) if args.base == "hand" else json.loads((RUNS / args.base / "champion.json").read_text())["genome"]
    theta = (np.asarray(json.loads((RUNS / args.init / "champion.json").read_text())["network"]["params"])
             if args.init else Network.initial(int(time.time()) % 1000).params.copy())
    rng = np.random.default_rng(int("".join(c for c in args.run_id if c.isdigit()) or "0") % 2**32)
    seed_rng = random.Random(args.run_id)
    m, v = np.zeros(N_PARAMS), np.zeros(N_PARAMS)
    paused = running_table_builds()
    for pid in paused:
        os.kill(pid, signal.SIGSTOP)
    best, base_bench = None, float("nan")
    planner_w, planner_net = load_planner()
    try:
        with mp.get_context("fork").Pool(args.workers, initializer=_worker_init) as pool:
            log(f"evolve-neural {args.run_id}: {args.generations} generations x {2 * args.pairs} networks x {args.seeds} seeds, "
                f"{N_PARAMS} parameters, sigma {args.sigma}, lr {args.lr}, base weights {args.base}"
                + (f", from {args.init}" if args.init else "") + (f"; table build {paused} paused" if paused else ""))
            base_bench = score(pool, [None], base, BENCH, chunk=12)[0]
            planner_bench = score(pool, [planner_net.params if planner_net else None], genome_of(planner_w), BENCH, chunk=12)[0]
            log(f"benchmark: base weights with no network {base_bench:.2f}, the planner's current value bot {planner_bench:.2f}")
            write(run_dir / "config.json", {"kind": "neural", "started": status["started"], "config": vars(args), "genes": GENES,
                                            "bench_seeds": BENCH, "baseline": {"genome": base, "benchmark": base_bench},
                                            "active": {"genome": genome_of(planner_w), "benchmark": planner_bench},
                                            "network": {"parameters": N_PARAMS, "facts": FACTS, "items": [list(k) for k in ITEMS],
                                                        "init": args.init or None}})
            for gen in range(1, args.generations + 1):
                g0 = time.time()
                seeds = [("".join(seed_rng.choice(SEED_CHARS) for _ in range(8)), "Plasma Deck" if k % 4 == 0 else "Red Deck")
                         for k in range(args.seeds)]
                eps = rng.standard_normal((args.pairs, N_PARAMS))
                nets = [theta + s * args.sigma * e for e in eps for s in (1, -1)]
                fitness = score(pool, nets, base, seeds)
                u = ranks(fitness)
                grad = ((u[0::2] - u[1::2]) @ eps) / (2 * args.pairs * args.sigma)
                m = 0.9 * m + 0.1 * grad
                v = 0.999 * v + 0.001 * grad ** 2
                theta = theta + args.lr * (m / (1 - 0.9 ** gen)) / (np.sqrt(v / (1 - 0.999 ** gen)) + 1e-8)
                bench = score(pool, [theta], base, BENCH, chunk=12)[0]
                net = Network(theta)
                if best is None or bench > best["benchmark"]:
                    best = {"gen": gen, "benchmark": bench, "fitness": max(fitness), "genome": base,
                            "network": {"params": theta.tolist()}}
                    write(run_dir / "champion.json", best)
                q = statistics.quantiles(fitness, n=10)
                learned = [{"kind": k[0], "name": k[1], "bias": round(b, 4)} for k, b in net.learned()[:40]]
                (run_dir / "params").mkdir(exist_ok=True)                    # the whole network, each generation
                np.save(run_dir / "params" / f"{gen:04d}.npy", theta.astype(np.float32))
                record = {"gen": gen, "best": max(fitness), "mean": statistics.fmean(fitness), "p10": q[0],
                          "median": statistics.median(fitness), "p90": q[-1], "benchmark": bench, "champion": base,
                          "learned": learned, "biases": [round(float(b), 4) for b in net.out[:, 0]],
                          "elapsed": time.time() - t0, "seconds": time.time() - g0,
                          "step": float(np.linalg.norm(theta))}
                with open(run_dir / "generations.jsonl", "a") as out:
                    out.write(json.dumps(record) + "\n")
                set_status(gen=gen)
                per_gen = (time.time() - t0) / gen
                top = ", ".join(f"{d['name']} {d['bias']:+.2f}" for d in learned[:4])
                log(f"gen {gen}/{args.generations}: candidates best {record['best']:.2f}, median {record['median']:.2f}; "
                    f"benchmark {bench:.2f} (champion {best['benchmark']:.2f}, gen {best['gen']}); learned most: {top}; "
                    f"{record['seconds']:.0f}s, ETA {per_gen * (args.generations - gen) / 60:.0f} min")
        state = "done"
    except Stop:
        state = "stopped"
        log("stopped on request")
    except Exception as exc:
        state = "error"
        log(f"error: {exc!r}\n{traceback.format_exc()}")
        set_status(state="error", error=repr(exc))
    finally:
        for pid in paused:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        if paused:
            log(f"table build {paused} resumed")
    if best:
        log(f"champion (gen {best['gen']}) benchmark {best['benchmark']:.2f} with the bot alone, against {base_bench:.2f} "
            f"for the base weights without a network; the planner keeps its value bot until the Evolution tab's "
            f"'Use these weights'")
    if state != "error":
        set_status(state=state)
    log(f"evolve-neural {args.run_id} {state} in {(time.time() - t0) / 60:.0f} min; exit {0 if state != 'error' else 1}")
    return 0 if state != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
