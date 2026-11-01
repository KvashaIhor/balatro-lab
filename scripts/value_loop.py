"""The value network's training loop, unattended: train on every game so far, measure on fresh seeds, play a
new round of games with the best network yet, and again, until a deadline.

Usage:  python3 -u scripts/value_loop.py --until 07:45 [--games 20000] [--epochs 25]
Log:    logs/value_loop.log (each step also logs to its own logs/value_<step>.log)
Writes: runs/value/v<N>.npz (+ .json), runs/value/eval_<label>.json, runs/value/data/round<R>.npz,
        runs/value/summary.json (every version: how often it beat ante 8, mean progress)

Resumable: a step whose output exists is skipped. Round 0 (the value bot's games) may already be running; the
loop waits for it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALUE = ROOT / "runs" / "value"
DATA = VALUE / "data"


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def step(name: str, args: list[str], logname: str) -> None:
    log(f"{name}: {' '.join(args)}")
    t = time.time()
    with open(ROOT / "logs" / f"value_{logname}.log", "a") as fh:
        code = subprocess.run([sys.executable, "-u", *args], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT).returncode
    if code != 0:
        raise RuntimeError(f"{name} exited with {code}; see logs/value_{logname}.log")
    log(f"{name}: done in {(time.time() - t) / 60:.1f} min")


def evaluate(label: str, bot: str) -> dict:
    out = VALUE / f"eval_{label}.json"
    if not out.exists():
        step(f"eval {label}", ["scripts/eval_value.py", "--bot", bot, "--label", label], "eval")
    return json.loads(out.read_text())


def summary(rows: list[dict]) -> None:
    (VALUE / "summary.json").write_text(json.dumps(rows, indent=1))
    for r in rows:
        log(f"  {r['label']:>9}: beat ante 8 {100 * r['won_share']:5.1f}%  mean progress {r['progress']:.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", required=True, help="HH:MM: no new step starts that can't finish by then")
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--epochs", type=int, default=25)
    args = ap.parse_args()
    now = datetime.now()
    deadline = datetime.combine(now.date(), datetime.strptime(args.until, "%H:%M").time())
    if deadline < now:
        deadline += timedelta(days=1)
    log(f"value loop until {deadline:%Y-%m-%d %H:%M}, {args.games} games a round")
    while not (DATA / "round0.npz").exists():
        if subprocess.run(["pgrep", "-f", "selfplay.py --round 0"], capture_output=True).returncode != 0:
            step("selfplay round 0", ["scripts/selfplay.py", "--round", "0", "--games", "40000"], "selfplay")
            break
        time.sleep(30)
    rows = [{"label": lab, **{k: v for k, v in evaluate(lab, bot).items() if k != "runs"}}
            for lab, bot in (("base", "base"), ("champion", "champion"))]
    summary(rows)
    best, cycle = None, timedelta(minutes=50)
    k = 0
    while True:
        version = k + 1
        model = VALUE / f"v{version}.npz"
        started = datetime.now()
        if not model.exists():
            step(f"train v{version}", ["scripts/train_value.py", "--out", str(model), "--rounds", *map(str, range(k + 1)),
                                       "--epochs", str(args.epochs)], "train")
        res = evaluate(f"v{version}", f"value:{model}")
        rows.append({"label": f"v{version}", **{x: y for x, y in res.items() if x != "runs"}})
        summary(rows)
        if best is None or res["won_share"] >= best[1]:
            best = (model, res["won_share"])
        log(f"best so far: {best[0].name} ({100 * best[1]:.1f}% beat ante 8)")
        if not (DATA / f"round{k + 1}.npz").exists():
            if datetime.now() + cycle > deadline:
                log("no time for another round before the deadline")
                break
            step(f"selfplay round {k + 1}", ["scripts/selfplay.py", "--round", str(k + 1), "--games", str(args.games),
                                             "--value", str(best[0])], "selfplay")
        cycle = max(cycle, datetime.now() - started)
        k += 1
    log(f"value loop finished; best {best[0].name}; exit 0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        log(f"value loop failed: {exc!r}; exit 1")
        raise SystemExit(1)
