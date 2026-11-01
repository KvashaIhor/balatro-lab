"""Why a change moved the win rate: where two versions of the bot part on the games whose outcome changed, and which
switch of the new version parts them there.

1. The changed seeds:   python3 scripts/diverge.py --old d-base --new e-base --changed
2. Their traces, each in its own frozen copy of the code (scripts/trace_game.py):
       ROOT=<old snapshot> python3 scripts/trace_game.py runs/traces/d-vs-e/old SEED ...
       ROOT=<new snapshot> python3 scripts/trace_game.py runs/traces/d-vs-e/new SEED ...
3. The split points:   python3 scripts/diverge.py --old d-base --new e-base --traces runs/traces/d-vs-e \\
                           --switch LEVEL1_CANDIDATES=0 --switch MAKER_WAIT=0 ...
   At each seed's first differing decision, a bot of the live code follows the new trace up to there (working out
   its own move at each step, so its memory is the game's) and answers that step with each switch set in turn. The
   switch whose setting gives the old move is the one that parts them. The tally is a pointer, not a verdict: after a
   split the games differ, and their outcomes carry luck; read the decisions at the splits (30 Oct, the user: a change
   that lowers the win rate is investigated before it is switched off, since it may have surfaced something else).
Writes <traces>/diverge.json."""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("VALUEBOT_WEIGHTS", "hand")
from balatro.interactive import plain, to_action  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot  # noqa: E402


class Stop(Exception):
    pass


class Follower(ValueBot):
    """Takes the recorded steps, working out its own move at each, and keeps its own move at step `at`."""

    def __init__(self, steps, at):
        super().__init__()
        self.steps, self.at, self.i, self.own = steps, at, 0, None

    def _step(self, kind, own):
        if self.i == self.at:
            self.own = own
            raise Stop
        rec = self.steps[self.i]
        assert rec["kind"] == kind, (self.i, rec["kind"], kind)
        self.i += 1
        return rec["action"]

    def skip_blind(self, run, blind, tag):
        own = ["skip" if super().skip_blind(run, blind, tag) else "select"]
        return self._step("select", own)[0] == "skip"

    def reroll_boss(self, run, boss):
        own = ["reroll" if super().reroll_boss(run, boss) else "keep"]
        return self._step("boss", own)[0] == "reroll"

    def round_action(self, run):
        return to_action(self._step("round", plain(super().round_action(run))))

    def shop_action(self, run, shop):
        return to_action(self._step("shop", plain(super().shop_action(run, shop))))

    def pack_action(self, run, pack):
        return to_action(self._step("pack", plain(super().pack_action(run, pack))))


def evals(label):
    return {r["seed"]: r for r in json.load(open(os.path.join(ROOT, "runs", "value", f"eval_{label}.json")))["runs"]}


def own_move(seed, steps, at, switches):
    bot = Follower(steps, at)
    for k, v in switches.items():
        setattr(bot, k, v)
    try:
        Run(bot, game_seed=seed, deck="Red Deck", max_ante=8).play()
    except Stop:
        return bot.own
    return None


def first_split(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if (x["kind"], x["action"]) != (y["kind"], y["action"]):
            return i
    return min(len(a), len(b))


def parse_switch(text):
    name, value = text.split("=")
    now = getattr(ValueBot, name)
    return name, (type(now)(float(value)) if not isinstance(now, str) else value)


def one_seed(job):
    seed, traces, olds, news, switches = job
    try:
        old, new = (json.load(open(os.path.join(traces, side, f"{seed}.json"))) for side in ("old", "new"))
    except OSError:
        return None
    ok = all((t["won"], t["ante"]) == (ev[seed]["won"], ev[seed]["ante"]) for t, ev in ((old, olds), (new, news)))
    i = first_split(old["steps"], new["steps"])
    if i >= min(len(old["steps"]), len(new["steps"])):
        return {"seed": seed, "reproduced": ok, "split": None}
    step = new["steps"][i]
    live = own_move(seed, new["steps"], i, {})
    causes = [f"{k}={v}" for k, v in switches if own_move(seed, new["steps"], i, {k: v}) == old["steps"][i]["action"]]
    return {"seed": seed, "reproduced": ok, "split": i, "ante": step.get("ante"), "kind": step["kind"],
            "old": old["steps"][i]["action"], "new": step["action"], "live == new": live == step["action"], "causes": causes,
            "old won": old["won"], "new won": new["won"], "old ante": old["ante"], "new ante": new["ante"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--traces")
    ap.add_argument("--changed", action="store_true", help="print the seeds whose outcome (won, ante) changed")
    ap.add_argument("--switch", action="append", default=[], help="NAME=VALUE, a setting of the new version to try")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("seeds", nargs="*")
    a = ap.parse_args()
    olds, news = evals(a.old), evals(a.new)
    if a.changed:
        print(" ".join(s for s in olds if (olds[s]["won"], olds[s]["ante"]) != (news[s]["won"], news[s]["ante"])))
        return
    switches = [parse_switch(t) for t in a.switch]
    seeds = a.seeds or sorted(f[:-5] for f in os.listdir(os.path.join(a.traces, "new")) if f.endswith(".json"))
    rows = []
    with Pool(a.workers) as pool:
        for k, row in enumerate(pool.imap_unordered(one_seed, [(s, a.traces, olds, news, switches) for s in seeds]), 1):
            if row is not None:
                rows.append(row)
                print(f"{k}/{len(seeds)}", json.dumps(row), flush=True)
    json.dump(rows, open(os.path.join(a.traces, "diverge.json"), "w"), indent=1)
    tally = defaultdict(Counter)
    for r in rows:
        if r.get("split") is None:
            tally["(no split)"]["same"] += 1
            continue
        for c in r["causes"] or ["(none of the switches)"]:
            tally[c]["new won, old lost" if r["new won"] and not r["old won"] else
                     "new lost, old won" if r["old won"] and not r["new won"] else "same outcome"] += 1
    print(f"\n{len(rows)} seeds, {sum(r['reproduced'] for r in rows)} reproduced")
    for c, n in sorted(tally.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {c:32s} splits {sum(n.values()):3d}: new won where old lost {n['new won, old lost']}, "
              f"new lost where old won {n['new lost, old won']}, same outcome {n['same outcome']}")


if __name__ == "__main__":
    main()
