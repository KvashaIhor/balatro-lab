"""Play or build at the bosses that end games (BACKLOG priority 5). Each boss round a baseline game lost, and as a
control a round of a game that beat the same boss at the same ante, is replayed from its seed with the same cards and
played twice: by the bot as it is, and by Search, the bot with a look ahead: before each play or discard, the bot's own
pick and the leading others (the top plays by score, the top discards it weighs) are each played out to the round's
end over ROLLOUTS redraws of the cards not yet seen (the bot finishing the round, chance from streams of their own:
nothing a player can't know), and the one that wins most is taken (a tie: the bot's). Lost rounds Search wins, less won
rounds it loses, say what the round's play leaves; few, and the games go in the build.

Usage:  python3 -u scripts/boss_rounds.py --eval i-base [--rounds 140] [--rollouts 8] [--workers 12] [--out NAME]
        python3 -u scripts/boss_rounds.py --eval i-base --probe     (one lost round: replay check and timings)
        python3 -u scripts/boss_rounds.py --eval i-base --out b1 --explain [--workers 2]   (b1's rescued rounds played
            with ROUND_SEARCH, every decision it weighed in runs/bossplay/b1/explain.jsonl)
Writes: runs/bossplay/<out>/rounds.jsonl (a round a line, as it finishes), runs/bossplay/<out>/report.txt
Log:    logs/boss_rounds.log (append with >>)
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VALUEBOT_WEIGHTS", "hand")

from balatro.bots import ranked_plays  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot, action_key  # noqa: E402

ROLLOUTS = 8
PLAYS = 3          # the top plays by score weighed besides the bot's pick
DISCARDS = 3       # the top discards the bot weighs


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def bosses(seed: str, antes: int = 8) -> list[str]:
    """Each ante's boss as the seed draws it (least used first, key "boss"; boss rerolls aside)."""
    run = Run(ValueBot(), game_seed=seed, deck="Red Deck", max_ante=antes)
    out = []
    for a in range(1, antes + 1):
        run.ante = a
        out.append(run.seedrng.boss(run))
    return out


class _Snap(Exception):
    pass


def snapshot(seed: str, ante: int):
    """The run as the value bot left it at the start of ante `ante`'s boss round (the blind chosen, nothing dealt)."""
    bot = ValueBot()
    bot.ROUND_SEARCH = False                            # the baseline games were played without it (i-base)
    run = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8)

    def play_round():
        if run.ante == ante and run.blind.kind == 2:
            del run.play_round                              # the copy plays its rounds as any run
            raise _Snap(copy.deepcopy(run))
        return Run.play_round(run)
    run.play_round = play_round
    try:
        run.play()
    except _Snap as s:
        return s.args[0]
    return None


def finish_round(t) -> bool:
    """play_round's loop from where the round stands: True if it is won (Mr. Bones too)."""
    for _ in range(500):
        if t.round_score >= t.blind.chips:
            return True
        if t.hands_left <= 0 or not t.hand:
            break
        action = t.ask(t.agent.round_action)
        if not t.hand:
            break
        if action[0] == "discard" and t.discards_left > 0:
            t.discard(action[1])
        else:
            t.play_hand(action[1] if action[0] in ("play", "discard") and len(action) > 1 else [0])
    return t.round_score >= t.blind.chips or any(j.on_fail(t) for j in t.each_joker())


class Search:
    """The bot, looking ahead before each play or discard (see the module's note). Everything else is the bot's."""

    def __init__(self, bot, rollouts: int = ROLLOUTS):
        self.bot, self.n = bot, rollouts
        self.stats = Counter()

    def round_action(self, run):
        own = self.bot.round_action(run)
        if own[0] not in ("play", "discard"):              # a free action (an order, a use, a sale): the bot's
            return own
        needed = run.blind.chips - run.round_score
        cands, seen = [own], {action_key(own)}
        plays = ranked_plays(run, need=needed, top=PLAYS)
        for _, idx, _ in plays:
            if action_key(("play", idx)) not in seen:
                cands.append(("play", list(idx)))
                seen.add(action_key(("play", idx)))
        if run.discards_left > 0:
            keep = plays[0][1] if plays else (own[1] if own[0] == "play" else [])
            for _, opt, _ in self.bot._ranked_discards(run, keep)[:DISCARDS]:
                if opt and action_key(("discard", opt)) not in seen:
                    cands.append(("discard", list(opt)))
                    seen.add(action_key(("discard", opt)))
        self.stats["decisions"] += 1
        if len(cands) == 1:
            return own
        scores = {}
        for c in cands:
            res = [self.rollout(run, c, i) for i in range(self.n)]
            scores[action_key(c)] = (sum(w for w, _ in res) / self.n, sum(s for _, s in res) / self.n)
            if c is own and scores[action_key(c)][0] == 1.0:   # the bot's pick always wins: nothing to gain
                self.stats["sure"] += 1
                return own
        best = max(cands, key=lambda c: (scores[action_key(c)][0], c is own, scores[action_key(c)][1]))
        if best is not own:
            self.stats["changed"] += 1
            self.stats[f"changed {own[0]}->{best[0]}"] += 1
        return best

    def rollout(self, run, action, i: int) -> tuple[bool, float]:
        """One play-out of `action` and the rest of the round by the bot, the unseen cards redrawn."""
        saved, run.agent = run.agent, self.bot
        try:
            t = copy.deepcopy(run)
        finally:
            run.agent = saved
        rng = random.Random(f"search:{run.seed}:{run.rounds_played}:{run.round_hands_played}:{run.discards_left}:"
                            f"{len(run.draw_pile)}:{i}")
        t.draw_pile = rng.sample(t.draw_pile, len(t.draw_pile))
        t.rng = {name: random.Random(f"{rng.random()}:{name}") for name in t.rng}
        if t.seedrng is not None:
            roll = random.Random(rng.random())
            t.seedrng.roll = lambda key, roll=roll: roll.random()
        if action[0] == "discard" and t.discards_left > 0:
            t.discard(action[1])
        else:
            t.play_hand(action[1])
        won = finish_round(t)
        return won, math.log(max(1.0, t.round_score) / max(1, t.blind.chips))


def play_line(snap, search: bool, rollouts: int) -> dict:
    t = copy.deepcopy(snap)
    agent = Search(t.agent, rollouts) if search else None
    if agent:
        t.agent = agent
    start = time.time()
    won = t.play_round()
    return {"won": bool(won), "share": round(t.round_score / t.blind.chips, 3), "seconds": round(time.time() - start, 1),
            **({"stats": dict(agent.stats)} if agent else {})}


def one(job) -> dict:
    seed, ante, kind, rollouts = job
    start = time.time()
    snap = snapshot(seed, ante)
    if snap is None:
        return {"seed": seed, "ante": ante, "kind": kind, "error": "no boss round at that ante"}
    out = {"seed": seed, "ante": ante, "kind": kind, "boss": snap.ante_boss.name,
           "jokers": [j.name for j in snap.jokers], "replay_seconds": round(time.time() - start, 1)}
    out["bot"] = play_line(snap, False, rollouts)
    out["search"] = play_line(snap, True, rollouts)
    return out


def explain_one(job) -> dict:
    """--explain: a round played again by the bot with ROUND_SEARCH on (balatro/search.py: face-down cards redrawn,
    the margin), each decision it weighed written down."""
    seed, ante, kind, share = job
    from balatro import bots
    bots.BASE_CARD_EFFECTS = False                      # i-base's code had it off: the same games to the same rounds
    snap = snapshot(seed, ante)
    if snap is None:
        return {"seed": seed, "ante": ante, "kind": kind, "error": "the replay never reached that boss round"}
    check = play_line(snap, False, 0)                   # the bot alone must end the round as in the baseline
    if abs(check["share"] - share) > 0.001:
        return {"seed": seed, "ante": ante, "kind": kind, "error": f"replay {check['share']} against {share}"}
    t = copy.deepcopy(snap)
    bot = t.agent
    bot.ROUND_SEARCH, bot.search_notes = True, []
    start = time.time()
    won = t.play_round()
    return {"seed": seed, "ante": ante, "kind": kind, "boss": snap.ante_boss.name, "won": bool(won),
            "share": round(t.round_score / t.blind.chips, 3), "bot_share": share,
            "seconds": round(time.time() - start, 1), "notes": bot.search_notes}


def explain(a) -> int:
    """The rounds of an earlier run's rounds.jsonl that its Search won and the bot lost, played with ROUND_SEARCH."""
    src = ROOT / "runs" / "bossplay" / a.out
    rows = [json.loads(x) for x in (src / "rounds.jsonl").read_text().splitlines()]
    jobs = [(r["seed"], r["ante"], r["kind"], r["bot"]["share"]) for r in rows
            if r.get("kind") == "lost" and r["search"]["won"]]
    log(f"explain: {len(jobs)} rounds of {src} (lost, won by its Search), {a.workers} workers -> {src / 'explain.jsonl'}")
    t0, n_won = time.time(), 0
    with mp.Pool(a.workers) as pool, open(src / "explain.jsonl", "w") as f:
        for i, r in enumerate(pool.imap_unordered(explain_one, jobs), 1):
            f.write(json.dumps(r) + "\n")
            f.flush()
            el = time.time() - t0
            if "error" in r:
                log(f"{i}/{len(jobs)} {r['seed']} ante {r['ante']}: skipped, {r['error']}")
                continue
            n_won += r["won"]
            ch = [x for x in r["notes"] if x["changed"]]
            log(f"{i}/{len(jobs)} ({el / 60:.1f} min, ETA {el / i * (len(jobs) - i) / 60:.1f} min) {r['seed']} ante "
                f"{r['ante']} {r['boss']}: {'won' if r['won'] else 'lost'} {r['share']}, {len(ch)} changed of "
                f"{len(r['notes'])} weighed; so far won {n_won}/{i}")
    log(f"explain done: ROUND_SEARCH won {n_won} of {len(jobs)}")
    return 0


def pick(eval_label: str, rounds: int) -> list[tuple[str, int, str]]:
    """The lost boss rounds (seed, ante), and a control for each: another game that met the same boss at that ante
    and beat it."""
    runs = json.loads((ROOT / "runs" / "value" / f"eval_{eval_label}.json").read_text())["runs"]
    lost = [(r["seed"], r["ante"]) for r in runs if not r["won"] and int(r["progress"]) % 3 == 2][:rounds]
    drawn = {r["seed"]: bosses(r["seed"]) for r in runs}
    rng = random.Random(1)
    used, jobs = set(), []
    for seed, ante in lost:
        boss = drawn[seed][ante - 1]
        jobs.append((seed, ante, "lost"))
        beat = [r["seed"] for r in runs if r["seed"] != seed and r["seed"] not in used
                and drawn[r["seed"]][ante - 1] == boss and (r["won"] or int(r["progress"]) >= 3 * ante)]
        if beat:
            s = rng.choice(sorted(beat))
            used.add(s)
            jobs.append((s, ante, "won"))
    return jobs


def report(rows: list[dict]) -> str:
    lines = []
    for kind in ("lost", "won"):
        rs = [r for r in rows if r.get("kind") == kind and "bot" in r]
        if not rs:
            continue
        bot = sum(r["bot"]["won"] for r in rs)
        srch = sum(r["search"]["won"] for r in rs)
        flips = Counter((r["bot"]["won"], r["search"]["won"]) for r in rs)
        lines.append(f"{kind} rounds {len(rs)}: the bot wins {bot}, Search wins {srch}  (bot lost & Search won "
                     f"{flips[(False, True)]}, bot won & Search lost {flips[(True, False)]})")
        by = Counter()
        for r in rs:
            by[(r["boss"], r["bot"]["won"], r["search"]["won"])] += 1
        for boss in sorted({r["boss"] for r in rs}, key=lambda b: -sum(1 for r in rs if r["boss"] == b)):
            n = sum(1 for r in rs if r["boss"] == boss)
            lines.append(f"    {boss:16s} {n:3d}: Search won where the bot lost {by[(boss, False, True)]}, "
                         f"lost where it won {by[(boss, True, False)]}")
    mism = [r for r in rows if r.get("kind") == "lost" and r.get("bot", {}).get("won")]
    lines.append(f"replay check: lost rounds the bot won on replay {len(mism)} (should be 0)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", required=True)
    ap.add_argument("--rounds", type=int, default=140)
    ap.add_argument("--rollouts", type=int, default=ROLLOUTS)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default=None)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--explain", action="store_true", help="the rounds --out's Search won, played with ROUND_SEARCH")
    a = ap.parse_args()
    if a.explain:
        return explain(a)
    if a.probe:
        seed, ante, _ = pick(a.eval, 1)[0]
        t0 = time.time()
        snap = snapshot(seed, ante)
        log(f"probe {seed} ante {ante} {snap.ante_boss.name}: replay {time.time() - t0:.1f} s")
        t0 = time.time()
        for _ in range(5):
            copy.deepcopy(snap)
        log(f"a deep copy of the run (bot and all): {(time.time() - t0) / 5 * 1000:.0f} ms")
        bot = play_line(snap, False, a.rollouts)
        log(f"the bot: {bot}")
        srch = play_line(snap, True, a.rollouts)
        log(f"Search ({a.rollouts} rollouts): {srch}")
        return 0
    out = ROOT / "runs" / "bossplay" / (a.out or a.eval)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(s, ante, kind, a.rollouts) for s, ante, kind in pick(a.eval, a.rounds)]
    log(f"boss rounds: {a.eval}, {sum(j[2] == 'lost' for j in jobs)} lost + {sum(j[2] == 'won' for j in jobs)} won, "
        f"{a.rollouts} rollouts, {a.workers} workers -> {out}")
    rows, t0 = [], time.time()
    with mp.Pool(a.workers) as pool, open(out / "rounds.jsonl", "w") as f:
        for i, r in enumerate(pool.imap_unordered(one, jobs), 1):
            rows.append(r)
            f.write(json.dumps(r) + "\n")
            f.flush()
            el = time.time() - t0
            log(f"{i}/{len(jobs)} ({el / 60:.1f} min, ETA {el / i * (len(jobs) - i) / 60:.1f} min) {r.get('kind')} "
                f"{r.get('seed')} ante {r.get('ante')} {r.get('boss')}: bot {r.get('bot', {}).get('won')}, "
                f"Search {r.get('search', {}).get('won')} ({r.get('search', {}).get('stats')})")
            if i % 20 == 0:
                log("so far:\n" + report(rows))
    text = report(rows)
    (out / "report.txt").write_text(text + "\n")
    log("done:\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
