"""Evolve the value bot's weights: how much it pays for jokers that grow or pay, packs, vouchers, money.

Usage:  python3 -u scripts/evolve_valuebot.py [--run-id ID] [--generations 40] [--population 24] [--seeds 24]
                                              [--workers 16] [--fitness progress|wins] [--init GENOME.json]
                                              [--freeze mod:]
Writes: runs/evolve/<run id>/config.json, status.json, generations.jsonl (a line per generation) and
        champion.json (the weights that did best on the benchmark). Log: logs/evolve_<run id>.log.

Fitness "progress" (the default) is progress (blinds beaten, plus the share of the failed blind's target reached;
ante = progress / 3 + 1) of the value bot playing whole runs on its own, up to ante 16. Each generation every
individual plays the same fresh random seeds (a quarter on the Plasma Deck); the generation's best then plays a
fixed benchmark of 48 seeds, the same in every generation and every run, so the benchmark line shows real
progress. Fitness "wins" is the goal itself: the percentage of runs that beat ante 8, on the Red Deck, played to
ante 8 (progress breaks ties), with a benchmark of 96 Red Deck seeds; mean progress alone can favour surviving the
early antes over winning (the run of 20261026-132856 did: more progress, fewer wins). --init starts from a saved
genome instead of the planner's weights, and --freeze keeps the genes whose names start with these prefixes
(comma-separated) as they start, e.g. "mod:" for the behaviour modifiers' strengths; --seeds-from names the
generations' seed sequence, so runs compared side by side can play the same games. The planner's weights
(runs/evolve/planner.json) change only when a champion is chosen in the Evolution tab: weights that help the bot
alone don't always help the planner's search. Seed-table builds are paused while it runs.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import signal
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from balatro.run import Run  # noqa: E402
from balatro.strategy import GENES, ValueBot, Weights, genome_of, load_weights, weights_of  # noqa: E402

SEED_CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
RUNS = ROOT / "runs" / "evolve"
RANGE = {g["name"]: (g["low"], g["high"]) for g in GENES}
_bench_rng = random.Random(1234)
BENCH = [("".join(_bench_rng.choice(SEED_CHARS) for _ in range(8)), "Plasma Deck" if k % 4 == 0 else "Red Deck")
         for k in range(48)]
_wins_rng = random.Random(5678)                  # not the evaluation's seeds (scripts/eval_value.py)
BENCH_WINS = [("".join(_wins_rng.choice(SEED_CHARS) for _ in range(8)), "Red Deck") for _ in range(96)]
MAX_ANTE = 16


class Stop(Exception):
    pass


def _worker_init() -> None:
    signal.signal(signal.SIGTERM, signal.SIG_DFL)      # workers just end; the run itself handles the stop


def mutate(g: dict, rng: random.Random, rate: float = 0.3, frozen: tuple = ()) -> dict:
    out = {}
    for k, v in g.items():
        lo, hi = RANGE[k]
        moves = not k.startswith(frozen) if frozen else True
        out[k] = min(hi, max(lo, v + rng.gauss(0, 0.1 * (hi - lo)))) if moves and rng.random() < rate else v
    return out


def cross(a: dict, b: dict, rng: random.Random) -> dict:
    return {k: a[k] if rng.random() < 0.5 else b[k] for k in a}


def play(task) -> tuple[int, float, bool]:
    """One run of the value bot with a genome: (index, progress, beat ante 8)."""
    ind, genome, seed, deck = task
    try:
        bot = ValueBot()
        bot.w = weights_of(genome)
        res = Run(bot, game_seed=seed, deck=deck, max_ante=MAX_ANTE).play()
        return ind, res.progress, res.won
    except Exception:
        traceback.print_exc()
        return ind, 0.0, False


def score(pool, genomes: list[dict], seeds: list[tuple[str, str]]) -> tuple[list[float], list[float]]:
    """Each genome's mean progress over the seeds, and the percentage of them it beat ante 8 on."""
    totals, wins = [0.0] * len(genomes), [0] * len(genomes)
    for ind, progress, won in pool.imap_unordered(play, [(i, g, s, d) for i, g in enumerate(genomes) for s, d in seeds], chunksize=4):
        totals[ind] += progress
        wins[ind] += won
    return [t / len(seeds) for t in totals], [100 * w / len(seeds) for w in wins]


def running_table_builds() -> list[int]:
    """Seed-table builds that are running now (one another job paused stays paused, and isn't resumed here)."""
    pids = [int(p) for p in subprocess.run(["pgrep", "-f", r"^\./table build"], capture_output=True, text=True).stdout.split()]
    return [p for p in pids if not subprocess.run(["ps", "-o", "stat=", "-p", str(p)], capture_output=True,
                                                  text=True).stdout.strip().startswith("T")]


def write(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--generations", type=int, default=40)
    ap.add_argument("--population", type=int, default=24)
    ap.add_argument("--seeds", type=int, default=24)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--elite", type=int, default=4)
    ap.add_argument("--fitness", choices=("progress", "wins"), default="progress")
    ap.add_argument("--init", default="")
    ap.add_argument("--freeze", default="")
    ap.add_argument("--bench", type=int, default=0)   # fewer benchmark seeds (a quick test)
    ap.add_argument("--seeds-from", default="")       # name of the generations' seed sequence (default: the run id);
                                                      # runs compared side by side share one, so they play the same games
    args = ap.parse_args()
    global MAX_ANTE
    wins = args.fitness == "wins"
    MAX_ANTE = 8 if wins else 16                   # set before the pool forks, so its workers play to it
    bench_seeds = (BENCH_WINS if wins else BENCH)[:args.bench or None]
    frozen = tuple(p for p in args.freeze.split(",") if p)
    fmt = (lambda v: f"{v:.1f}%") if wins else (lambda v: f"{v:.2f}")
    run_dir = RUNS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
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
    rng = random.Random(args.run_id)
    seed_rng = random.Random(f"{args.seeds_from or args.run_id}:seeds")
    paused = running_table_builds()
    for pid in paused:
        os.kill(pid, signal.SIGSTOP)
    hand = genome_of(Weights())
    start = json.loads(Path(args.init).read_text())["genome"] if args.init else None
    active = genome_of(weights_of(start) if start is not None else load_weights())
    best, active_bench = None, float("inf")

    def measure(pool, genomes, seeds) -> tuple[list[float], list[tuple]]:
        """Each genome's fitness, and its sort key (with wins, progress breaks ties)."""
        progress, won = score(pool, genomes, seeds)
        return (won, list(zip(won, progress))) if wins else (progress, [(p,) for p in progress])

    try:
        with mp.get_context("fork").Pool(args.workers, initializer=_worker_init) as pool:
            log(f"evolve {args.run_id}: {args.generations} generations x {args.population} individuals x {args.seeds} seeds, "
                f"benchmark {len(bench_seeds)} seeds, {args.workers} workers, fitness {args.fitness}"
                + (f" (beat ante 8, Red Deck, to ante {MAX_ANTE})" if wins else "") + (f", from {args.init}" if args.init else "")
                + (f", frozen {list(frozen)}" if frozen else "") + (f"; table build {paused} paused" if paused else ""))
            (hand_bench, active_bench), _ = measure(pool, [hand, active], bench_seeds)
            log(f"benchmark: hand-set weights {fmt(hand_bench)}, {'the starting' if args.init else 'the planner' + chr(39) + 's current'} "
                f"weights {fmt(active_bench)}")
            write(run_dir / "config.json", {"started": status["started"], "config": vars(args), "genes": GENES,
                                            "bench_seeds": bench_seeds, "baseline": {"genome": hand, "benchmark": hand_bench},
                                            "active": {"genome": active, "benchmark": active_bench}})
            population = [active] + [mutate(active, rng, rate=0.5, frozen=frozen) for _ in range(args.population - 1)]
            for gen in range(1, args.generations + 1):
                g0 = time.time()
                seeds = [("".join(seed_rng.choice(SEED_CHARS) for _ in range(8)),
                          "Red Deck" if wins or k % 4 else "Plasma Deck") for k in range(args.seeds)]
                fitness, keys = measure(pool, population, seeds)
                order = sorted(range(len(population)), key=lambda i: keys[i], reverse=True)
                top = population[order[0]]
                (bench,), (bench_key,) = measure(pool, [top], bench_seeds)
                if best is None or bench_key > best["key"]:
                    best = {"gen": gen, "benchmark": bench, "fitness": fitness[order[0]], "genome": top,
                            "fitness_kind": args.fitness, "key": bench_key}
                    write(run_dir / "champion.json", best)
                q = statistics.quantiles(fitness, n=10)
                record = {"gen": gen, "best": fitness[order[0]], "mean": statistics.fmean(fitness), "p10": q[0],
                          "median": statistics.median(fitness), "p90": q[-1], "benchmark": bench,
                          "champion": top, "elapsed": time.time() - t0, "seconds": time.time() - g0,
                          "pop_mean": {k: statistics.fmean(g[k] for g in population) for k in top},
                          "pop_sd": {k: statistics.pstdev(g[k] for g in population) for k in top}}
                with open(run_dir / "generations.jsonl", "a") as out:
                    out.write(json.dumps(record) + "\n")
                set_status(gen=gen)
                per_gen = (time.time() - t0) / gen
                log(f"gen {gen}/{args.generations}: best {fmt(record['best'])}, median {fmt(record['median'])}, benchmark "
                    f"{fmt(bench)} (champion {fmt(best['benchmark'])}, gen {best['gen']}); {record['seconds']:.0f}s, "
                    f"ETA {per_gen * (args.generations - gen) / 60:.0f} min")
                elite = [population[i] for i in order[:args.elite]]

                def pick():
                    a, b, c = rng.sample(range(len(population)), 3)
                    return population[max((a, b, c), key=lambda i: keys[i])]
                population = elite + [mutate(cross(pick(), pick(), rng), rng, frozen=frozen)
                                      for _ in range(args.population - args.elite)]
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
        verdict = "beats" if best["benchmark"] > active_bench else "doesn't beat"
        log(f"champion (gen {best['gen']}) benchmark {fmt(best['benchmark'])} {verdict} the "
            f"{'starting' if args.init else 'planner' + chr(39) + 's'} weights ({fmt(active_bench)}) with the bot alone; the planner keeps its weights until the Evolution tab's "
            f"'Use these weights' (the bot alone and the planner don't always agree)")
    if state != "error":
        set_status(state=state)
    log(f"evolve {args.run_id} {state} in {(time.time() - t0) / 60:.0f} min; exit {0 if state != 'error' else 1}")
    return 0 if state != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
