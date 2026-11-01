"""How a Play-tab game goes from one of its decisions under each choice there, the rest played by a bot, over many
shuffles: does the line the bot took hold up, or would the other one have?

    python3 -u scripts/fork_test.py runs/played/<id>.json --branch 7 --at 125 --lines skip,select --shuffles 40

The game's first `at` steps are replayed as recorded, step `at` is set to each line's action, and the bot (by default
the Play tab's advisor) plays on. Shuffle 0 is the game's own; the others redraw every shuffle from the fork on (the
deck and the luck stream), the shops and packs staying the game's. Prints, per line, how often the run got past each
blind from the fork's ante on, and won."""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from balatro.interactive import ADVISOR, to_action  # noqa: E402
from balatro.models import make  # noqa: E402
from balatro.run import Run  # noqa: E402

KINDS = {"skip_blind": "select", "reroll_boss": "boss", "round_action": "round", "shop_action": "shop",
         "pack_action": "pack"}


def handoff(bot, steps, reshuffle):
    """`bot` answering from `steps` first, then by itself; `reshuffle(run)` at the hand-over."""
    state = {"i": 0}
    for name, kind in KINDS.items():
        own = getattr(bot, name)

        def answer(run, *args, own=own, kind=kind):
            if state["i"] < len(steps):
                step = steps[state["i"]]
                assert step["kind"] == kind, (state["i"], step["kind"], kind)
                state["i"] += 1
                a = step["action"]
                return a[0] == "skip" if kind == "select" else a[0] == "reroll" if kind == "boss" else to_action(a)
            if state["i"] == len(steps):
                state["i"] += 1
                reshuffle(run)
            return own(run, *args)
        setattr(bot, name, answer)
    return bot


def one(job):
    spec, steps, line, k, model = job
    rng = random.Random(f"fork:{k}")

    def reshuffle(run):
        if k == 0:
            return
        run.rng["luck"] = random.Random(f"fork:{k}:luck")
        run.seedrng.shuffle = lambda run_, deck: rng.sample(list(deck), len(deck))

    bot = handoff(make(model), steps, reshuffle)
    run = Run(bot, game_seed=spec["seed"], deck=spec["deck"], stake=spec["stake"], max_ante=spec["max_ante"])
    run.hand_sort = spec.get("hand_sort")
    run.draw_after_win = spec.get("draw_after_win", True)
    r = run.play()
    return {"line": line, "k": k, "progress": r.progress, "ante": r.ante, "won": r.won,
            "jokers": [j.name + (f" [{j.edition}]" if j.edition else "") for j in run.jokers]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("--branch", type=int)
    ap.add_argument("--at", type=int, required=True)
    ap.add_argument("--lines", default="skip,select", help="the actions to try at step `at`: their first word, or "
                    "whole actions in JSON (a list of them, e.g. '[[\"pick\", 1, []], [\"pick\", 3, []]]')")
    ap.add_argument("--shuffles", type=int, default=40)
    ap.add_argument("--kind", help="the decision's kind when `at` is the one the game waits at (shop, pack, round...)")
    ap.add_argument("--model", default=ADVISOR)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out")
    a = ap.parse_args()
    game = json.load(open(a.game))
    branch = next(b for b in game["branches"] if b["id"] == (game["current"] if a.branch is None else a.branch))
    spec = {k: v for k, v in game.items() if k != "branches"}
    head = [{"kind": s["kind"], "action": s["action"]} for s in branch["steps"][:a.at]]
    # (`at` one past the last step: the decision the game waits at, of --kind)
    at = branch["steps"][min(a.at, len(branch["steps"]) - 1)]
    kind = at["kind"] if a.at < len(branch["steps"]) else a.kind
    actions = json.loads(a.lines) if a.lines.startswith("[") else [[w] for w in a.lines.split(",")]
    # (a line may be several actions of the same decision in turn, e.g. a sale then the buy it makes room for)
    seqs = [act if act and isinstance(act[0], list) else [act] for act in actions]
    lines = [" then ".join(" ".join(str(x) for x in act if x != []) for act in seq) for seq in seqs]
    jobs = [(spec, head + [{"kind": kind, "action": act} for act in seq], line, k, a.model)
            for k in range(a.shuffles + 1) for line, seq in zip(lines, seqs)]
    ante = at.get("ante") or 1
    print(f"{time.strftime('%H:%M:%S')} {game['id']} branch {branch['id']} step {a.at} ({kind}, ante {ante}): "
          f"lines {lines}, {a.shuffles} shuffles + the game's own, bot {a.model}, {len(jobs)} games", flush=True)
    rows, t0 = [], time.time()
    with Pool(a.workers) as pool:
        for n, row in enumerate(pool.imap_unordered(one, jobs), 1):
            rows.append(row)
            el = time.time() - t0
            print(f"{time.strftime('%H:%M:%S')} {n}/{len(jobs)} {el:.0f}s eta {el / n * (len(jobs) - n):.0f}s "
                  f"{row['line']} k={row['k']} progress {row['progress']:.2f} ante {row['ante']} won {row['won']}",
                  flush=True)
    first = 3 * (ante - 1)
    print()
    for line in lines:
        rs = [r for r in rows if r["line"] == line]
        own = next(r for r in rs if r["k"] == 0)
        past = ", ".join(f"{('small', 'big', 'boss')[b % 3]} {ante + b // 3} {sum(r['progress'] >= first + b + 1 for r in rs) / len(rs):.0%}"
                         for b in range(3 * (game["max_ante"] - ante + 1)))
        print(f"{line:7s} n={len(rs)}  past: {past}; won {sum(r['won'] for r in rs) / len(rs):.0%}; "
              f"mean progress {sum(r['progress'] for r in rs) / len(rs):.2f}; the game's own shuffle: progress "
              f"{own['progress']:.2f}")
        print(f"        jokers at the end, most common: {Counter(j for r in rs for j in r['jokers']).most_common(8)}")
    if a.out:
        json.dump(rows, open(a.out, "w"), indent=1)
    print("exit 0", flush=True)


if __name__ == "__main__":
    main()
