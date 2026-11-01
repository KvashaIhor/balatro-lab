"""Benchmark the Seed Planner: plan a fixed set of seeds and report how far each plan gets.

Usage:  python3 scripts/bench_planner.py [--label NAME] [--time 30] [--max-ante 16]
Log:    logs/bench_planner.log (tail -f it); results in runs/bench/<label>.json, compared with earlier labels.
Each plan runs as its own process (python3 -m balatro.planner), one at a time; a seed-table build is paused
meanwhile, as the app does, since the search needs every core.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# (seed, deck): seeds the player knows to be strong are the real test of the planner.
SEEDS = [("DD8JI5Y5", "Plasma Deck"), ("ALEEB", "Plasma Deck"), ("ALEEB", "Red Deck"), ("XX2XZ8K4", "Red Deck"),
         ("4Z7TWAWF", "Red Deck"), ("1PSV32J4", "Red Deck")]


def log(fh, msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def table_builds() -> list[int]:
    """Seed-table builds that are running (one another job paused is left to it)."""
    out = subprocess.run(["pgrep", "-f", r"^\./table build"], capture_output=True, text=True).stdout
    return [p for p in map(int, out.split()) if not subprocess.run(["ps", "-o", "stat=", "-p", str(p)],
                                                                 capture_output=True, text=True).stdout.strip().startswith("T")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--time", type=float, default=30)
    ap.add_argument("--max-ante", type=int, default=16)
    ap.add_argument("--horizon", type=int, default=None, help="passed to the planner (its default otherwise)")
    ap.add_argument("--beam", type=int, default=None, help="passed to the planner (its default otherwise)")
    ap.add_argument("--branch", type=int, default=None, help="passed to the planner (its default otherwise)")
    ap.add_argument("--detour", type=float, default=None, help="passed to the planner (its default otherwise)")
    args = ap.parse_args()
    extra = [*(["--horizon", str(args.horizon)] if args.horizon else []), *(["--beam", str(args.beam)] if args.beam else []),
             *(["--branch", str(args.branch)] if args.branch else []), *(["--detour", str(args.detour)] if args.detour else [])]
    out_dir = ROOT / "runs" / "bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    fh = open(ROOT / "logs" / "bench_planner.log", "a")
    paused = table_builds()
    for pid in paused:
        os.kill(pid, signal.SIGSTOP)
    results, t0 = [], time.time()
    log(fh, f"bench {args.label}: {len(SEEDS)} plans, {args.time:g} s each, up to ante {args.max_ante} {' '.join(extra)}"
            + (f"; table build {paused} paused" if paused else ""))
    try:
        for k, (seed, deck) in enumerate(SEEDS):
            out = out_dir / f"{args.label}-{seed}-{deck.split()[0]}.json"
            started = time.time()
            proc = subprocess.run([sys.executable, "-u", "-m", "balatro.planner", seed, "--deck", deck, "--max-ante",
                                   str(args.max_ante), "--time", str(args.time), "--json", str(out), *extra],
                                  cwd=ROOT, capture_output=True, text=True)
            if proc.returncode != 0:
                log(fh, f"  {seed} {deck}: FAILED (exit {proc.returncode})\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
                results.append({"seed": seed, "deck": deck, "failed": proc.returncode})
                continue
            r = json.loads(out.read_text())
            res = {"seed": seed, "deck": deck, "ante": r["ante"], "won": r["won"], "progress": round(r["progress"], 2),
                   "base_progress": round(r["base"]["progress"], 2), "rollouts": r["rollouts"],
                   "overrules": r.get("overrules"), "choices": len(r["decisions"]),
                   "seconds": round(time.time() - started, 1)}
            results.append(res)
            out.unlink()
            done = k + 1
            eta = (time.time() - t0) / done * (len(SEEDS) - done)
            log(fh, f"  [{done}/{len(SEEDS)}] {seed:9s} {deck:12s} reaches ante {res['ante']:2d} (progress {res['progress']:5.2f}, "
                    f"won {res['won']}), base {res['base_progress']:5.2f}, {res['overrules']}/{res['choices']} choices "
                    f"overrule the bot, {res['seconds']:.0f}s; ETA {eta:.0f}s")
    finally:
        for pid in paused:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        if paused:
            log(fh, f"table build {paused} resumed")
    scored = [r for r in results if "progress" in r]
    mean = sum(r["progress"] for r in scored) / max(1, len(scored))
    (out_dir / f"{args.label}.json").write_text(json.dumps({"label": args.label, "time": args.time,
                                                             "results": results, "mean_progress": mean}, indent=1))
    log(fh, f"bench {args.label}: mean progress {mean:.2f} over {len(scored)} plans, {time.time() - t0:.0f}s; exit 0")
    for prev in sorted(out_dir.glob("*.json")):
        if prev.stem != args.label:
            p = json.loads(prev.read_text())
            log(fh, f"  earlier {p['label']}: mean progress {p['mean_progress']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
