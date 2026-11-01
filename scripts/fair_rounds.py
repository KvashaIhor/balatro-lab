"""The deciding rounds of the losses in runs/analysis/losses.json played again, fairly: could a player who knows which
cards are left in the deck (the game's deck view) but not their order have won them? analyze_losses.search finds its
lines with the cards to come as they will come, so its count of misplayed rounds is only what was there to find.

Each loss is replayed to its deciding round (the value bot is deterministic) and the round played again on the real
cards by a policy that decides each step without that knowledge: the bot's own move and its best few plays and
discards, each tried in WORLDS shuffles of the unseen cards (the draw pile, and the face-down cards in hand, which
could be any of them; the luck streams reseeded) and finished there by the bot; the move that wins in most of them,
then the best mean share of the target, is made (the bot's own on a tie). The same worlds for every move.

    python3 -u scripts/fair_rounds.py [--worlds 32] [--workers 16] [--only SEED,SEED] >> logs/fair_rounds.log 2>&1

Writes runs/analysis/fair_rounds.json."""
import argparse
import json
import math
import multiprocessing as mp
import random
import sys
import time

import analyze_losses as al
from analyze_losses import OUT, clone, finish, label, log
from balatro.bots import ranked_plays
from balatro.run import Run
from balatro.strategy import ValueBot

PLAYS, DISCARDS = 3, 3


def world(run, salt: str):
    """A copy of the run with what a player can't see dealt again: the draw pile and the face-down cards in hand
    shuffled together (face-down ones keep their places in hand), the luck streams reseeded."""
    w = clone(run)
    down = [i for i, c in enumerate(w.hand) if c.face_down]
    pool = w.draw_pile + [w.hand[i] for i in down]
    rng = random.Random(salt)
    rng.shuffle(pool)
    for i in down:
        w.hand[i] = pool.pop()
        w.hand[i].face_down = True
    for c in pool:
        c.face_down = False
    w.draw_pile = pool
    for name, stream in w.rng.items():
        stream.seed(f"{salt}|{name}")
    w.seedrng = None
    w.refresh_debuffs()
    return w


def act(run, move) -> None:
    kind, idx = move
    if kind == "discard" and run.discards_left > 0:
        run.discard(idx)
    else:
        run.play_hand(idx)


def moves(run, bot, own) -> list[tuple[str, list[int]]]:
    """The bot's own move first, then its best few plays and discards (as analyze_losses.search tries them)."""
    out = [own]
    ranked = ranked_plays(run, top=10)
    out += [("play", list(idx)) for _, idx, _ in ranked[:PLAYS]]
    if run.discards_left > 0 and ranked:
        out += [("discard", list(d)) for _, d, _ in bot._ranked_discards(run, ranked[0][1])[:DISCARDS] if d]
    seen, unique = set(), []
    for kind, idx in out:
        key = (kind, tuple(sorted(idx)))
        if key not in seen:
            seen.add(key)
            unique.append((kind, sorted(idx)))
    return unique


def outcome(run) -> tuple[bool, float]:
    won = run.round_score >= run.blind.chips
    return won, min(1.0, run.round_score / max(1, run.blind.chips))


def fair_play(snap, w, worlds: int, seed: str) -> dict:
    """The round played on the real cards, each step chosen over `worlds` shuffles of what's unseen."""
    run = clone(snap)
    bot = ValueBot()
    bot.w = w
    run.agent = bot
    steps, n = [], 0
    for n in range(40):
        if run.round_score >= run.blind.chips or run.hands_left <= 0 or not run.hand:
            break
        a = run.ask(bot.round_action)                     # free moves (Planets, Tarots, joker order) as the bot makes them
        if not run.hand:
            break
        own = (a[0], list(a[1])) if a[0] in ("play", "discard") and len(a) > 1 else ("play", [0])
        if own[0] == "discard" and run.discards_left <= 0:
            own = ("play", own[1])
        options = moves(run, bot, own)
        tried = []
        if len(options) > 1:
            shuffles = [world(run, f"{seed}|{n}|{k}") for k in range(worlds)]
            for move in options:
                wins, share = 0, 0.0
                for s in shuffles:
                    t = clone(s)
                    act(t, move)
                    finish(t, bot)
                    won, sh = outcome(t)
                    wins += won
                    share += math.log1p(sh) / worlds
                tried.append((wins, share, move))
            best = max(tried, key=lambda t: (t[0], t[1]))    # max keeps the first of equals: the bot's own
            move = best[2]
        else:
            move = own
        steps.append({"move": f"{move[0]} {label(run, move[1])}", "own": move == own,
                      "tried": [(f"{m[0]} {label(run, m[1])}", wins, round(sh, 3)) for wins, sh, m in tried]})
        act(run, move)
    won, share = outcome(run)
    if not won:
        won = any(j.on_fail(run) for j in run.each_joker())
    first = steps[0]["tried"] if steps else []
    return {"won": won, "score": run.round_score, "share": round(share, 3), "steps": steps,
            # the round's odds from its start in the shuffles: the bot's own way (its move, then its play), the best move
            "bot_odds": first[0][1] / worlds if first else None, "fair_odds": max(t[1] for t in first) / worlds if first else None}


def replay(g: dict, worlds: int) -> dict:
    t0 = time.time()
    seed, died = g["seed"], g["died"]
    watcher = al.Watcher()
    run = Run(watcher, game_seed=seed, deck="Red Deck", max_ante=8, record=False)
    res = run.play()
    snap = watcher.snap
    same = (not res.won and res.ante == g["ante"] and run.round_score == died["score"])
    again = clone(snap)
    bot = ValueBot()
    bot.w = snap.agent.w
    again.agent = bot
    finish(again, bot)                                     # the bot alone on the snapshot: should lose as it did
    out = {"seed": seed, "ante": g["ante"], "blind": died["blind"], "target": died["target"], "bot_score": died["score"],
           "hindsight_won": died["winnable"], "replayed": same, "bot_again": again.round_score}
    if same:
        out.update(fair_play(snap, snap.agent.w, worlds, seed))
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=32)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    games = [g for g in json.loads((OUT / "losses.json").read_text()) if not g["won"]]
    if args.only:
        keep = set(args.only.split(","))
        games = [g for g in games if g["seed"] in keep]
    log(f"fair rounds: {len(games)} deciding rounds lost ({sum(g['died']['winnable'] for g in games)} won by the "
        f"hindsight search), {args.worlds} shuffles a move, {args.workers} workers")
    done, t0 = [], time.time()
    with mp.get_context("fork").Pool(args.workers) as pool:
        for r in pool.imap_unordered(replay_args, [(g, args.worlds) for g in games]):
            done.append(r)
            ok = [x for x in done if x["replayed"]]
            el = time.time() - t0
            log(f"{len(done)}/{len(games)} {r['seed']} ante {r['ante']} {r['blind']}: "
                + (f"fair {'WON' if r['won'] else 'lost'} ({r['score']:,} of {r['target']:,}, bot {r['bot_score']:,}), "
                   f"hindsight {'won' if r['hindsight_won'] else 'lost'}, {sum(not s['own'] for s in r['steps'])} of "
                   f"{len(r['steps'])} moves not the bot's, odds at the start: bot {fmt(r['bot_odds'])}, fair "
                   f"{fmt(r['fair_odds'])}" if r["replayed"] else "REPLAY DIFFERS, skipped")
                + f"; {r['seconds']}s | so far fair won {sum(x['won'] for x in ok)} of {len(ok)} "
                f"(of the hindsight wins {sum(x['won'] for x in ok if x['hindsight_won'])}/"
                f"{sum(x['hindsight_won'] for x in ok)}); ETA {(len(games) - len(done)) * el / len(done) / 60:.1f} min")
    ok = [x for x in done if x["replayed"]]
    hs = [x for x in ok if x["hindsight_won"]]
    log(f"done in {(time.time() - t0) / 60:.1f} min: fair play won {sum(x['won'] for x in ok)} of {len(ok)} deciding "
        f"rounds lost by the bot; {sum(x['won'] for x in hs)} of the {len(hs)} the hindsight search won, "
        f"{sum(x['won'] for x in ok if not x['hindsight_won'])} of the other {len(ok) - len(hs)}; "
        f"{len(done) - len(ok)} didn't replay; bot alone again lost {sum(x['bot_again'] == x['bot_score'] for x in ok)} "
        f"of {len(ok)} as before")
    odds = [x for x in ok if x["bot_odds"] is not None]
    if odds:
        log(f"odds at the round's start in the shuffles (mean over {len(odds)}): the bot's own way "
            f"{sum(x['bot_odds'] for x in odds) / len(odds):.2f}, the best first move {sum(x['fair_odds'] for x in odds) / len(odds):.2f}; "
            f"rounds the bot was favoured in (odds 0.5+) {sum(x['bot_odds'] >= 0.5 for x in odds)}, hopeless for it (0) "
            f"{sum(x['bot_odds'] == 0 for x in odds)}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fair_rounds.json").write_text(json.dumps(sorted(done, key=lambda x: x["seed"]), indent=1))
    log("wrote runs/analysis/fair_rounds.json")
    return 0


def replay_args(a):
    return replay(*a)


def fmt(x) -> str:
    return "-" if x is None else f"{x:.2f}"


if __name__ == "__main__":
    sys.exit(main())
