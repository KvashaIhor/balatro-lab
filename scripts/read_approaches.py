"""Read the approach experiment's games so far (runs/value/approaches_games.jsonl, written as games finish): on the
seeds played all 19 ways, each variant against the mean of the six luck-only replays (null1..6: the bot as it is,
measured on other sample hands), a steadier yardstick than the one base run; and the best of six approaches against
the best of six replays (the most a perfect chooser could gain beyond luck). Usage: python3 scripts/read_approaches.py"""
import collections
import json
import math
import os

PATH = os.path.join(os.path.dirname(__file__), "..", "runs", "value", "approaches_games.jsonl")
HANDS = ["High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush"]
NULLS = [f"null{k}" for k in range(1, 7)]


def mean_se(xs):
    m = sum(xs) / len(xs)
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1) / len(xs)) if len(xs) > 1 else float("nan")


games = [json.loads(line) for line in open(PATH)]
by = {(g["seed"], g["label"]): g for g in games}
count = collections.Counter(g["seed"] for g in games)
seeds = [s for s, k in count.items() if k == 1 + len(NULLS) + 2 * len(HANDS)]
n = len(seeds)
print(f"{len(games)} games; {n} seeds played all {1 + len(NULLS) + 2 * len(HANDS)} ways")
if n >= 2:
    luck = {s: sum(by[(s, l)]["won"] for l in NULLS) / len(NULLS) for s in seeds}
    luck_p = {s: sum(by[(s, l)]["progress"] for l in NULLS) / len(NULLS) for s in seeds}
    print(f"the bot as it is, mean of six replays: beat ante 8 in {100 * sum(luck.values()) / n:.1f}%")
    rows = [("base (one run)", "base")] + [(f"{h} from ante {a}", f"{h}@{a}") for a in (1, 3) for h in HANDS]
    for name, label in rows:
        w = mean_se([by[(s, label)]["won"] - luck[s] for s in seeds])
        p = mean_se([by[(s, label)]["progress"] - luck_p[s] for s in seeds])
        print(f"  {name:26s} {100 * sum(by[(s, label)]['won'] for s in seeds) / n:5.1f}%  against the replays "
              f"{100 * w[0]:+5.1f} ± {100 * w[1]:.1f} points, progress {p[0]:+.2f} ± {p[1]:.2f}")
    for a in (1, 3):
        d = mean_se([max(by[(s, f"{h}@{a}")]["won"] for h in HANDS) - max(by[(s, l)]["won"] for l in NULLS) for s in seeds])
        print(f"  best of six approaches from ante {a} against best of six replays: {100 * d[0]:+.1f} ± {100 * d[1]:.1f} points")
