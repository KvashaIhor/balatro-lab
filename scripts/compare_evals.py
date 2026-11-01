"""Paired comparison of evaluations on the same fresh seeds (scripts/eval_value.py): each label against the first.

Usage:  python3 scripts/compare_evals.py BASE_LABEL LABEL [LABEL ...]
Reads:  runs/value/eval_<label>.json
"""
from __future__ import annotations

import json
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(label: str) -> dict:
    return json.loads((ROOT / "runs" / "value" / f"eval_{label}.json").read_text())


def main() -> int:
    base, *others = sys.argv[1:]
    a = load(base)
    by_seed = {g["seed"]: g for g in a["runs"]}
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp}  {base}: beat ante 8 in {a['won']}/{a['games']} ({100 * a['won_share']:.1f}%), progress {a['progress']:.2f}")
    for label in others:
        b = load(label)
        pairs = [(by_seed[g["seed"]], g) for g in b["runs"] if g["seed"] in by_seed]
        d = [y["progress"] - x["progress"] for x, y in pairs]
        w = [y["won"] - x["won"] for x, y in pairs]
        se = st.stdev(d) / len(d) ** 0.5 if len(d) > 1 else float("nan")
        sw = st.stdev(w) / len(w) ** 0.5 if len(w) > 1 else float("nan")
        print(f"{stamp}  {label}: beat ante 8 in {b['won']}/{b['games']} ({100 * b['won_share']:.1f}%), progress "
              f"{b['progress']:.2f}; against {base} on {len(d)} seeds: progress {st.mean(d):+.2f} ± {se:.2f}, "
              f"ante 8 beaten {100 * st.mean(w):+.1f} ± {100 * sw:.1f} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
