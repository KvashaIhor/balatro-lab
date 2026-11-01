"""Which of the bot's decisions cost games: the user's fork test (scripts/fork_test.py) over many games at once.

    python3 -u scripts/mine_decisions.py trace runs/mine/<name> --seeds 300 --rng 4242
    python3 -u scripts/mine_decisions.py fork runs/mine/<name> --per-loss 2 --wins 100 --shuffles 6
    python3 -u scripts/mine_decisions.py report runs/mine/<name>
    python3 -u scripts/mine_decisions.py sales runs/mine/<name> --wins 50 --shuffles 4
    python3 -u scripts/mine_decisions.py sales-report runs/mine/<name>

sales (the close calls' blind spot: the shop keeps one sale per buy, so which joker to sell never shows as a runner-up):
each sale that made room for a buy or a pack pick (the last in each lost game, some from won games) forked into every
joker sold for the same item and none of it; rows in <name>/sales/forks.jsonl.

trace: plays fresh seeds (never set 90210 or 777: what is found here is measured there) with the value bot, recording
every decision as fork_test replays it, and at each shop and pack decision the options the bot weighed (its worths).
fork: picks shop and pack decisions where the runner-up was close (from lost games, and some from won ones as a
check), and plays each game on from there twice per reshuffle: the bot's own choice and the runner-up (with the buy a
sale makes room for), the bot playing the rest. Same reshuffle for both lines (fork_test's), shops staying the game's.
Rows land in forks.jsonl as they finish. report: per kind of decision, how much the runner-up gains over the choice
(blinds passed, ante 8 beaten), paired by reshuffle; then the single decisions that cost the most."""
import argparse
import json
import math
import os
import random
import sys
import time
from collections import defaultdict
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("VALUEBOT_WEIGHTS", "hand")
from balatro.cards import Card  # noqa: E402
from balatro.interactive import describe, plain  # noqa: E402
from balatro.jokers import Joker  # noqa: E402
from balatro.models import make  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import action_key  # noqa: E402
from fork_test import handoff  # noqa: E402

CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"   # (eval_value.py's)
MODEL = "value"
SEARCH = os.environ.get("MINE_SEARCH") == "1"  # the bot's ROUND_SEARCH (on by default since 31 Oct) off unless asked:
                                              # ~4x the time a game, and these forks weigh shop and pack choices, every
                                              # line played on alike (m1 was traced without it)


def make_bot():
    bot = make(MODEL)
    bot.ROUND_SEARCH = SEARCH
    return bot
GAP = 0.5                                     # the runner-up within this much of the choice (in power): a close call


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def kind_of(item) -> str:
    return "Joker" if isinstance(item, Joker) else "Card" if isinstance(item, Card) else getattr(item, "kind", "?")


def tag(run, kind, args, a) -> str:
    """What an action is about, for grouping: 'buy Joker', 'buy Planet', 'pick Tarot', 'sell Joker', 'leave'..."""
    name = a[0]
    if name in ("leave", "reroll", "skip"):
        return name
    if name in ("sell_joker", "sell_consumable"):
        return "sell " + ("Joker" if name == "sell_joker" else "consumable")
    if kind == "shop" and name in ("buy", "buy_use"):
        where, i = (a[1], a[2]) if name == "buy" else ("card", a[1])
        if where != "card":
            return f"buy {where}"
        return ("buy+use " if name == "buy_use" else "buy ") + kind_of(args[0].cards[i].item)
    if kind == "pack" and name == "pick":
        return "pick " + kind_of(args[0].cards[a[1]])
    return name


def options(bot, run, kind, args, chosen):
    """The options the bot weighed at this call, best first: [{action, then, worth, text, tag}]; None when it decided
    without weighing (a reorder, a use) or weighed one thing only."""
    worths = getattr(bot, "worths", None)
    if not worths or len(worths) < 2:
        return None
    acts = getattr(bot, "_acts", {}) if kind == "shop" else {}
    out = []
    for key, worth in sorted(worths.items(), key=lambda kv: -kv[1]):
        act, then = acts.get(key, (key, None))
        act = plain(act)
        out.append({"action": act, "then": plain(then) if then else None, "worth": round(worth, 4),
                    "text": describe(run, kind, args, act) + (f" then {describe(run, kind, args, plain(then))}"
                                                               if then else ""),
                    "tag": tag(run, kind, args, act) + (f" > {tag(run, kind, args, plain(then))}" if then else ""),
                    "chosen": action_key(act) == action_key(chosen)})
    return out if any(o["chosen"] for o in out) else None


def traced(bot):
    """`bot` recording its decisions as fork_test's steps, and at shop and pack calls the options it weighed."""
    steps, decisions = [], []
    for name, kind in (("skip_blind", "select"), ("reroll_boss", "boss"), ("round_action", "round"),
                       ("shop_action", "shop"), ("pack_action", "pack")):
        own = getattr(bot, name)

        def answer(run, *args, own=own, kind=kind):
            bot.worths = None
            a = own(run, *args)
            if kind == "select":
                step = ["skip" if a else "select"]
            elif kind == "boss":
                step = ["reroll" if a else "keep"]
            else:
                step = plain(a)
            if kind in ("shop", "pack"):
                opts = options(bot, run, kind, args, step)
                if opts:
                    decisions.append({"at": len(steps), "kind": kind, "ante": run.ante, "money": run.money,
                                      "jokers": [j.name for j in run.jokers], "options": opts[:4]})
            steps.append({"kind": kind, "action": step})
            return a
        setattr(bot, name, answer)
    return bot, steps, decisions


def trace_one(seed):
    t = time.time()
    bot, steps, decisions = traced(make_bot())
    res = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8).play()
    return {"seed": seed, "won": res.won, "ante": res.ante, "progress": res.progress, "seconds": time.time() - t,
            "steps": steps, "decisions": decisions}


def fork_one(job):
    """One line of one decision on one reshuffle: the game replayed to it, the line's actions, the bot on its own."""
    seed, head, line, k = job
    rng = random.Random(f"fork:{k}")

    def reshuffle(run):
        run.rng["luck"] = random.Random(f"fork:{k}:luck")
        run.seedrng.shuffle = lambda run_, deck: rng.sample(list(deck), len(deck))

    bot = handoff(make_bot(), head + line, reshuffle)
    t = time.time()
    r = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8).play()
    return {"progress": r.progress, "won": r.won, "ante": r.ante, "seconds": time.time() - t}


def cmd_trace(a):
    os.makedirs(a.dir, exist_ok=True)
    rng = random.Random(a.rng)
    seeds = ["".join(rng.choice(CHARS) for _ in range(8)) for _ in range(a.seeds)]
    path = os.path.join(a.dir, "games.jsonl")
    log(f"trace: {a.seeds} seeds (Random({a.rng})), bot {MODEL}, {a.workers} workers -> {path}")
    t0, won, n = time.time(), 0, 0
    with open(path, "w") as f, Pool(a.workers) as pool:
        for g in pool.imap_unordered(trace_one, seeds):
            n += 1
            won += g["won"]
            f.write(json.dumps(g) + "\n")
            f.flush()
            el = time.time() - t0
            log(f"{n}/{a.seeds} {g['seed']} won {g['won']} ante {g['ante']} decisions weighed {len(g['decisions'])} "
                f"{g['seconds']:.0f}s; beat ante 8 so far {won}/{n} ({won / n:.1%}); ETA {el / n * (a.seeds - n) / 60:.1f} min")
    log(f"trace done: beat ante 8 in {won}/{n}; exit 0")


def pick_decisions(games, per_loss, wins, seed=1):
    """Close calls (the runner-up within GAP of the choice): `per_loss` from each lost game, `wins` in all from won
    games, at random (seeded)."""
    rng = random.Random(seed)
    picked, won_pool = [], []
    for g in games:
        close = []
        for d in g["decisions"]:
            if d["ante"] > 8:                         # (the shop after ante 8's boss: the run ends there)
                continue
            opts = d["options"]
            chosen = next(o for o in opts if o["chosen"])
            other = next((o for o in opts if not o["chosen"]), None)
            if other is None or chosen["worth"] - other["worth"] > GAP:
                continue
            close.append({"seed": g["seed"], "game_won": g["won"], "game_ante": g["ante"], **d,
                          "chosen": chosen, "other": other, "gap": round(chosen["worth"] - other["worth"], 4)})
        if g["won"]:
            won_pool += close
        else:
            picked += rng.sample(close, min(per_loss, len(close)))
    return picked + rng.sample(won_pool, min(wins, len(won_pool)))


def cmd_fork(a):
    games = {g["seed"]: g for g in map(json.loads, open(os.path.join(a.dir, "games.jsonl")))}
    chosen = pick_decisions(games.values(), a.per_loss, a.wins)
    jobs, meta = [], []
    for n, d in enumerate(chosen):
        head = games[d["seed"]]["steps"][:d["at"]]
        for which in ("chosen", "other"):
            o = d[which]
            line = [{"kind": d["kind"], "action": o["action"]}]
            if o["then"]:
                line.append({"kind": d["kind"], "action": o["then"]})
            for k in range(1, a.shuffles + 1):
                jobs.append((d["seed"], head, line, k))
                meta.append((n, which, k))
    path = os.path.join(a.dir, "forks.jsonl")
    json.dump(chosen, open(os.path.join(a.dir, "decisions.json"), "w"), indent=1)
    log(f"fork: {len(chosen)} decisions ({sum(not d['game_won'] for d in chosen)} from lost games), 2 lines x "
        f"{a.shuffles} reshuffles = {len(jobs)} games, {a.workers} workers -> {path}")
    t0, done = time.time(), defaultdict(dict)
    order = list(range(len(jobs)))
    random.Random(2).shuffle(order)              # (mixed, so the running tally is a fair sample throughout)
    tally = defaultdict(list)
    with open(path, "w") as f, Pool(a.workers) as pool:
        for finished, (i, r) in enumerate(zip(order, pool.imap(fork_one, [jobs[i] for i in order], chunksize=1)), 1):
            n, which, k = meta[i]
            f.write(json.dumps({"decision": n, "line": which, "k": k, **r}) + "\n")
            f.flush()
            done[(n, k)][which] = r
            el = time.time() - t0
            log(f"{finished}/{len(jobs)} decision {n} {which} k={k} progress {r['progress']:.2f} won {r['won']} "
                f"{r['seconds']:.0f}s; ETA {el / finished * (len(jobs) - finished) / 60:.1f} min")
            if len(done[(n, k)]) == 2:                # a pair complete: the running tally (pairs, not decisions)
                pair = done[(n, k)]
                tally["progress"].append(pair["other"]["progress"] - pair["chosen"]["progress"])
                tally["won"].append(pair["other"]["won"] - pair["chosen"]["won"])
                if len(tally["progress"]) % 20 == 0:
                    mp, sp = mean_se(tally["progress"])
                    mw, sw = mean_se(tally["won"])
                    log(f"{len(tally['progress'])} pairs: the runner-up against the choice so far: blinds {mp:+.2f} ± "
                        f"{sp:.2f}, ante 8 beaten {100 * mw:+.1f} ± {100 * sw:.1f} points")
    log("fork done; exit 0")


def mean_se(xs):
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return m, 0.0
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1) / len(xs))


def cmd_report(a):
    decisions = json.load(open(os.path.join(a.dir, "decisions.json")))
    lines = defaultdict(dict)
    for row in map(json.loads, open(os.path.join(a.dir, "forks.jsonl"))):
        lines[(row["decision"], row["k"])][row["line"]] = row
    per = defaultdict(lambda: {"progress": [], "won": []})
    for (n, k), pair in lines.items():
        if len(pair) == 2:
            per[n]["progress"].append(pair["other"]["progress"] - pair["chosen"]["progress"])
            per[n]["won"].append(pair["other"]["won"] - pair["chosen"]["won"])
    rows = []
    for n, d in enumerate(decisions):
        if per[n]["progress"]:
            rows.append({**d, "n": n, "dp": sum(per[n]["progress"]) / len(per[n]["progress"]),
                         "dw": sum(per[n]["won"]) / len(per[n]["won"]), "pairs": len(per[n]["progress"])})
    print(f"{len(rows)} decisions forked ({sum(r['pairs'] for r in rows)} pairs). The runner-up against the bot's "
          f"choice, per decision averaged over its reshuffles, then over decisions (± standard error over decisions):")

    def table(title, key):
        groups = defaultdict(list)
        for r in rows:
            groups[key(r)].append(r)
        print(f"\n{title}")
        print(f"  {'':52s} {'n':>4s} {'blinds passed':>16s} {'ante 8 beaten (points)':>24s}")
        for g, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            mp, sp = mean_se([r["dp"] for r in rs])
            mw, sw = mean_se([r["dw"] for r in rs])
            print(f"  {g[:52]:52s} {len(rs):4d} {mp:+8.2f} ± {sp:5.2f} {100 * mw:+12.1f} ± {100 * sw:5.1f}")

    table("All, by the game's result:", lambda r: "lost games" if not r["game_won"] else "won games")
    table("By the choice and the runner-up (lost games):",
          lambda r: f"{r['chosen']['tag']}  vs  {r['other']['tag']}" if not r["game_won"] else "(won games)")
    table("By ante (lost games):", lambda r: f"ante {r['ante']}" if not r["game_won"] else "(won games)")
    print("\nThe decisions where the runner-up did best (lost games):")
    for r in sorted((r for r in rows if not r["game_won"]), key=lambda r: (-r["dw"], -r["dp"]))[:a.top]:
        print(f"  {r['seed']} step {r['at']} ante {r['ante']} ${r['money']}: chose \"{r['chosen']['text']}\" "
              f"({r['chosen']['worth']:+.3f}) over \"{r['other']['text']}\" ({r['other']['worth']:+.3f}): runner-up "
              f"ante 8 {100 * r['dw']:+.0f} points, blinds {r['dp']:+.2f} over {r['pairs']}; jokers {r['jokers']}")
    print("\nAnd where the bot's choice did best (lost games):")
    for r in sorted((r for r in rows if not r["game_won"]), key=lambda r: (r["dw"], r["dp"]))[:a.top]:
        print(f"  {r['seed']} step {r['at']} ante {r['ante']} ${r['money']}: chose \"{r['chosen']['text']}\" over "
              f"\"{r['other']['text']}\": runner-up ante 8 {100 * r['dw']:+.0f} points, blinds {r['dp']:+.2f}")


def sale_events(games, wins, seed=1):
    """Each sale that made room for a buy or a pack pick (the step after it), the last at ante 8 or before in each lost
    game, and `wins` of them from won games (at random, seeded): {seed, game_won, at, kind, ante, jokers, sold, then}."""
    rng = random.Random(seed)
    lost, won_pool = [], []
    for g in games:
        steps, known = g["steps"], {d["at"]: d for d in g["decisions"]}
        events = []
        for s, step in enumerate(steps[:-1]):
            a, nxt = step["action"], steps[s + 1]
            if (a and a[0] == "sell_joker" and s in known and known[s]["ante"] <= 8 and nxt["kind"] == step["kind"]
                    and nxt["action"] and nxt["action"][0] in ("buy", "pick")):
                d = known[s]
                events.append({"seed": g["seed"], "game_won": g["won"], "game_ante": g["ante"], "at": s,
                               "kind": step["kind"], "ante": d["ante"], "money": d["money"], "jokers": d["jokers"],
                               "sold": a[1], "then": nxt["action"]})
        if not events:
            continue
        if g["won"]:
            won_pool += events
        else:
            lost.append(max(events, key=lambda e: (e["ante"], e["at"])))
    return lost + rng.sample(won_pool, min(wins, len(won_pool)))


def cmd_sales(a):
    """Fork each sale event: the bot's sale, every other joker sold for the same buy or pick, and none of it (leave
    the shop, skip the pack)."""
    games = {g["seed"]: g for g in map(json.loads, open(os.path.join(a.dir, "games.jsonl")))}
    events = sale_events(games.values(), a.wins)
    jobs, meta = [], []
    for n, e in enumerate(events):
        head = games[e["seed"]]["steps"][:e["at"]]
        lines = {f"sell {j}": [["sell_joker", j], e["then"]] for j in range(len(e["jokers"]))}
        lines["keep all"] = [["leave"] if e["kind"] == "shop" else ["skip"]]
        e["lines"] = {name: (e["jokers"][int(name.split()[1])] if name != "keep all" else "keep all") for name in lines}
        for name, acts in lines.items():
            for k in range(1, a.shuffles + 1):
                jobs.append((e["seed"], head, [{"kind": e["kind"], "action": x} for x in acts], k))
                meta.append((n, name, k))
    out = os.path.join(a.dir, "sales")
    os.makedirs(out, exist_ok=True)
    json.dump(events, open(os.path.join(out, "events.json"), "w"), indent=1)
    path = os.path.join(out, "forks.jsonl")
    log(f"sales: {len(events)} sale events ({sum(not e['game_won'] for e in events)} from lost games), "
        f"{len(jobs)} games ({a.shuffles} reshuffles a line), {a.workers} workers -> {path}")
    order = list(range(len(jobs)))
    random.Random(2).shuffle(order)
    t0 = time.time()
    with open(path, "w") as f, Pool(a.workers) as pool:
        for finished, (i, r) in enumerate(zip(order, pool.imap(fork_one, [jobs[i] for i in order], chunksize=1)), 1):
            n, name, k = meta[i]
            f.write(json.dumps({"event": n, "line": name, "k": k, **r}) + "\n")
            f.flush()
            el = time.time() - t0
            if finished % 25 == 0 or finished == len(jobs):
                log(f"{finished}/{len(jobs)} games ({el / 60:.1f} min, ETA {el / finished * (len(jobs) - finished) / 60:.1f} min)")
    log("sales done; exit 0")


def cmd_sales_report(a):
    """Per sale event, each line against the bot's own sale (paired by reshuffle); then by the joker the bot sold:
    how its sale did against selling another (the mean of the other lines), and the events where it cost most."""
    out = os.path.join(a.dir, "sales")
    events = json.load(open(os.path.join(out, "events.json")))
    rows = defaultdict(dict)
    for row in map(json.loads, open(os.path.join(out, "forks.jsonl"))):
        rows[(row["event"], row["k"])][row["line"]] = row
    per = []
    for n, e in enumerate(events):
        own = f"sell {e['sold']}"
        diffs = defaultdict(lambda: {"progress": [], "won": []})
        for (m, k), lines in rows.items():
            if m != n or own not in lines:
                continue
            for name, r in lines.items():
                if name != own:
                    diffs[name]["progress"].append(r["progress"] - lines[own]["progress"])
                    diffs[name]["won"].append(r["won"] - lines[own]["won"])
        if not diffs:
            continue
        best = max(diffs, key=lambda x: (sum(diffs[x]["won"]) / len(diffs[x]["won"]),
                                         sum(diffs[x]["progress"]) / len(diffs[x]["progress"])))
        others = [x for x in diffs if x != "keep all"]
        per.append({**e, "n": n, "own": e["jokers"][e["sold"]],
                    "others_dp": sum(sum(diffs[x]["progress"]) / len(diffs[x]["progress"]) for x in others) / max(1, len(others)),
                    "others_dw": sum(sum(diffs[x]["won"]) / len(diffs[x]["won"]) for x in others) / max(1, len(others)),
                    "best": best, "best_name": e["lines"][best],
                    "best_dp": sum(diffs[best]["progress"]) / len(diffs[best]["progress"]),
                    "best_dw": sum(diffs[best]["won"]) / len(diffs[best]["won"])})
    print(f"{len(per)} sale events forked. Another sale against the bot's (the mean over the other jokers it could have "
          f"sold; ± standard error over events):")
    for title, sel in (("lost games", lambda r: not r["game_won"]), ("won games", lambda r: r["game_won"])):
        rs = [r for r in per if sel(r)]
        mp, sp = mean_se([r["others_dp"] for r in rs])
        mw, sw = mean_se([r["others_dw"] for r in rs])
        print(f"  {title:12s} {len(rs):4d} events: blinds {mp:+.2f} ± {sp:.2f}, ante 8 beaten {100 * mw:+.1f} ± {100 * sw:.1f} points")
    print("\nBy the joker the bot sold (all events): selling another instead")
    groups = defaultdict(list)
    for r in per:
        groups[r["own"]].append(r)
    for name, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        mp, sp = mean_se([r["others_dp"] for r in rs])
        mw, sw = mean_se([r["others_dw"] for r in rs])
        print(f"  {name[:28]:28s} {len(rs):4d}  blinds {mp:+.2f} ± {sp:.2f}  ante 8 {100 * mw:+.1f} ± {100 * sw:.1f}")
    print("\nThe events where another line did best (lost games; the best of several lines is picked, so expect a bias up):")
    for r in sorted((r for r in per if not r["game_won"]), key=lambda r: (-r["best_dw"], -r["best_dp"]))[:a.top]:
        print(f"  {r['seed']} step {r['at']} ante {r['ante']} ${r['money']}: sold {r['own']} for {r['then']}; "
              f"{r['best_name']} instead: ante 8 {100 * r['best_dw']:+.0f} points, blinds {r['best_dp']:+.2f}; "
              f"jokers {r['jokers']}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trace")
    t.add_argument("dir")
    t.add_argument("--seeds", type=int, default=300)
    t.add_argument("--rng", type=int, default=4242)
    t.add_argument("--workers", type=int, default=16)
    f = sub.add_parser("fork")
    f.add_argument("dir")
    f.add_argument("--per-loss", type=int, default=2)
    f.add_argument("--wins", type=int, default=100)
    f.add_argument("--shuffles", type=int, default=6)
    f.add_argument("--workers", type=int, default=16)
    r = sub.add_parser("report")
    r.add_argument("dir")
    r.add_argument("--top", type=int, default=15)
    s = sub.add_parser("sales")
    s.add_argument("dir")
    s.add_argument("--wins", type=int, default=50)
    s.add_argument("--shuffles", type=int, default=4)
    s.add_argument("--workers", type=int, default=16)
    sr = sub.add_parser("sales-report")
    sr.add_argument("dir")
    sr.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    {"trace": cmd_trace, "fork": cmd_fork, "report": cmd_report, "sales": cmd_sales,
     "sales-report": cmd_sales_report}[a.cmd](a)


if __name__ == "__main__":
    main()
