"""Play fresh random seeds with the value bot (hand-set weights, Red Deck, White Stake, to ante 8) and diagnose every
loss step by step:
- the round it died in: could other plays and discards have won it, with the same cards to come (a beam search over
  the bot's own best plays and discards, from the round's first decision)? Would its own play have won without the
  boss's effect (same target)?
- the build against the targets at every blind: its typical best hand (ValueBot.power) times the round's hands, over
  the target; when that first fell short;
- the shops meanwhile: money held while the build was short, rerolls, empty joker slots, unused consumables,
  hand levels, xMult jokers.
Each loss gets causes; the report clusters them, with seeds to open in the run viewer.

    python3 -u scripts/analyze_losses.py [--games 100] [--rng 99] [--workers 6] >> logs/analyze_losses.log 2>&1

Writes runs/analysis/losses.json (per game) and runs/analysis/losses.txt (the clusters, then a story per loss)."""
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
from balatro.items import data, entries  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.shop import cost_of  # noqa: E402
from balatro.strategy import ValueBot  # noqa: E402

CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
OUT = ROOT / "runs" / "analysis"
BOSS_EFFECT = {b["name"]: b["effect"] for b in entries("boss")}
XMULT = {j["name"] for j in data("jokers.json") if "xmult" in (j.get("values") or {})}
BEAM, PLAYS, DISCARDS = 24, 3, 3
RANKS = {11: "J", 12: "Q", 13: "K", 14: "A"}


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def clone(run):
    """A copy of the run to try other moves on (the agent shared, nothing recorded)."""
    frames, log_ = run.frames, run.log
    run.frames = run.log = None
    try:
        return copy.deepcopy(run, {id(run.agent): run.agent})
    finally:
        run.frames, run.log = frames, log_


def card(c) -> str:
    rank = RANKS.get(c.rank, str(c.rank))
    extra = "".join(f"[{x}]" for x in (c.enhancement, c.edition, c.seal and c.seal + " Seal") if x)
    return f"{rank}{c.suit[0]}{extra}" + ("(down)" if c.face_down else "") + ("(debuffed)" if c.debuffed else "")


def joker(j) -> str:
    return j.name + (f" [{j.edition}]" if j.edition else "") + ("".join(f" [{s}]" for s in ("eternal", "perishable", "rental") if getattr(j, s, False)))


def item_name(o) -> str:
    it = getattr(o, "item", o)
    return (joker(it) if hasattr(it, "rarity") else getattr(it, "name", None) or (card(it) if hasattr(it, "rank") else str(it)))


class Watcher(ValueBot):
    """The value bot, noting at each round's first decision a copy of the run and the build's margin, and every
    decision it makes in a journal (for reading a run step by step)."""

    def __init__(self):
        super().__init__()
        self.snap, self.key, self.rounds, self.journal = None, None, [], []

    def round_action(self, run):
        key = (run.rounds_played, run.ante, run.blind.kind)
        if key != self.key:
            self.key = key
            self.snap = clone(run)
            typical = math.expm1(self.power(run, plain=True))
            name = run.blind.boss.name if run.blind.boss else run.blind.name
            self.rounds.append({"ante": run.ante, "blind": name,
                                "target": run.blind.chips, "typical": round(typical), "hands": run.hands_left,
                                "margin": round(typical * run.hands_left / max(1, run.blind.chips), 2),
                                "money": run.money, "jokers": len(run.jokers), "slots": run.joker_slots})
            boss = f" ({BOSS_EFFECT.get(name, '')})" if run.blind.boss else ""
            self.journal.append(f"\n## ROUND ante {run.ante} {name}{boss}: target {run.blind.chips:,}; {run.hands_left} hands, "
                                f"{run.discards_left} discards; typical best hand {typical:,.0f} (margin {self.rounds[-1]['margin']}); "
                                f"${run.money}; jokers {[joker(j) for j in run.jokers]}; consumables {[c.name for c in run.consumables]}; "
                                f"levels {({h: n for h, n in run.hand_levels.items() if n > 1})}")
        a = super().round_action(run)
        top = ranked_plays(run, top=10)[:3]
        alt = "; ".join(f"{label(run, idx)} = {s:,}" for s, idx, _ in top)
        did = f"{a[0]} {label(run, a[1])}" if a[0] in ("play", "discard") else str(a)
        self.journal.append(f"  score {run.round_score:,}/{run.blind.chips:,}, hands {run.hands_left}, discards {run.discards_left} | "
                            f"hand {' '.join(card(c) for c in run.hand)} | best plays: {alt} | -> {did}")
        return a

    def shop_action(self, run, shop):
        a = super().shop_action(run, shop)
        offers = [f"{item_name(o)} ${cost_of(run, o)}" for o in shop.cards + shop.packs + shop.vouchers]
        worths = ", ".join(f"{k}={v:+.2f}" for k, v in sorted(getattr(self, "worths", {}).items(), key=lambda kv: -kv[1])[:6])
        self.journal.append(f"  SHOP ante {run.ante} ${run.money} reroll ${shop.reroll_cost}: offers {offers}; jokers "
                            f"{[joker(j) for j in run.jokers]} | worths {worths} | -> {a}")
        return a

    def pack_action(self, run, pack):
        a = super().pack_action(run, pack)
        cards = [item_name(c) for c in pack.cards]
        worths = ", ".join(f"{k}={v:+.2f}" for k, v in sorted(getattr(self, "worths", {}).items(), key=lambda kv: -kv[1])[:6])
        self.journal.append(f"  PACK {pack.pack.name}: {cards} | worths {worths} | -> {a}")
        return a

    def skip_blind(self, run, blind, tag):
        a = super().skip_blind(run, blind, tag)
        self.journal.append(f"  SELECT ante {run.ante} {blind.name}: tag {getattr(tag, 'name', None)} -> {'SKIP' if a else 'play'}")
        return a


def finish(run, agent) -> bool:
    """Play the rest of the round with this agent, as Run.play_round does: did it win?"""
    run.agent = agent
    for _ in range(100):
        if run.round_score >= run.blind.chips:
            return True
        if run.hands_left <= 0 or not run.hand:
            return False
        a = run.ask(agent.round_action)
        if not run.hand:
            return False
        if a[0] == "discard" and run.discards_left > 0:
            run.discard(a[1])
        else:
            run.play_hand(a[1] if a[0] in ("play", "discard") and len(a) > 1 else [0])
    return False


def label(run, idx) -> str:
    return " ".join(f"{RANKS.get(c.rank, c.rank)}{c.suit[0]}" for c in (run.hand[i] for i in idx))


def search(snap, bot) -> dict:
    """Beam search from the round's first decision over the bot's best few plays and discards, with the cards to
    come as they will come: a winning line if one is found, else the best score reached."""
    best, frontier = snap.round_score, [(clone(snap), [])]
    for _ in range(12):
        children = []
        for run, path in frontier:
            if run.hands_left <= 0 or not run.hand:
                continue
            ranked = ranked_plays(run, top=10)
            options = [("play", list(idx)) for _, idx, _ in ranked[:PLAYS]]
            if run.discards_left > 0 and ranked:
                options += [("discard", list(d)) for _, d, _ in bot._ranked_discards(run, ranked[0][1])[:DISCARDS] if d]
            for kind, idx in options:
                child, step = clone(run), f"{kind} {label(run, idx)}"
                if kind == "play":
                    child.play_hand(idx)
                else:
                    child.discard(idx)
                best = max(best, child.round_score)
                if child.round_score >= child.blind.chips:
                    return {"won": True, "line": path + [step], "best": child.round_score}
                children.append((child, path + [step]))
        if not children:
            break

        def hope(r):
            rp = ranked_plays(r, top=5)
            return r.round_score + (rp[0][0] if rp else 0) * r.hands_left
        children.sort(key=lambda c: -hope(c[0]))
        frontier = children[:BEAM]
    return {"won": False, "best": best}


def without_boss(snap) -> bool:
    """The bot's own play of the round with the boss's effect off (same target, hands and discards restored,
    cards face up and undebuffed; a hand-size cut stays)."""
    run = clone(snap)
    boss = run.blind.boss
    if boss is None:
        return False
    boss.disabled = True
    run.hands_left = max(run.hands_left, max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers())))
    run.discards_left = max(run.discards_left, max(0, run.base_discards + sum(j.discards_bonus for j in run.active_jokers())))
    for c in run.hand + run.draw_pile:
        c.face_down = False
    run.refresh_debuffs()
    bot = ValueBot()
    bot.w = snap.agent.w
    return finish(run, bot)


def shops(frames) -> list[dict]:
    """Each shop visit: money in and out, rerolls, what was done."""
    out, cur = [], None
    for f in frames:
        k = f["kind"]
        if k == "shop":
            act =(f.get("act") or {}).get("do") if isinstance(f.get("act"), dict) else None
            if cur is None or cur.get("closed"):
                cur = {"ante": f["ante"], "money_in": f["money"], "rerolls": 0, "did": [], "closed": False}
                out.append(cur)
            if act == "reroll":
                cur["rerolls"] += 1
            if f.get("did"):
                cur["did"].append(f["did"])
            cur["money_out"] = f["money"]
            cur["jokers"] = len(f["jokers"])
            cur["slots"] = f.get("joker_slots")
        elif k in ("select", "skip", "blind") and cur is not None:
            cur["closed"] = True
    return out


def diagnose(seed: str) -> dict:
    bot = Watcher()
    run = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8, record=True)
    res = run.play()
    g = {"seed": seed, "won": res.won, "ante": res.ante, "progress": round(res.progress, 2), "rounds": bot.rounds}
    if res.won:
        return g
    end, last = run.frames[-1], bot.rounds[-1]
    snap = bot.snap
    t = time.time()
    found = search(snap, bot)
    g["search_seconds"] = round(time.time() - t, 1)
    g["died"] = {**last, "score": run.round_score, "share": round(run.round_score / max(1, last["target"]), 2),
                 "boss_effect": BOSS_EFFECT.get(last["blind"], "") if snap.blind.boss else "", "winnable": found["won"],
                 "line": found.get("line"), "search_best": found["best"],
                 "won_without_boss": without_boss(snap) if snap.blind.boss else None}
    behind = [r for r in bot.rounds if r["margin"] < 1.0]
    g["first_short"] = behind[0] if behind else None
    g["shops"] = shops(run.frames)
    g["end"] = {"jokers": [j["name"] for j in end["jokers"]], "slots": end["joker_slots"], "money": end["money"],
                "consumables": [c["name"] for c in end["consumables"]],
                "levels": {h: n for h, n in end["hand_levels"].items() if n > 1},
                "most_played": max(end.get("hand_plays", {"-": 0}).items(), key=lambda kv: kv[1])[0],
                "xmult": [j["name"] for j in end["jokers"] if j["name"] in XMULT]}
    g["causes"] = causes(g)
    end_line = (f"\n## END: lost at ante {g['ante']} on {last['blind']}: scored {run.round_score:,} of {last['target']:,}; "
                f"jokers {[joker(j) for j in run.jokers]}; ${run.money}; consumables {[c.name for c in run.consumables]}")
    (OUT / "games").mkdir(parents=True, exist_ok=True)
    (OUT / "games" / f"{seed}.txt").write_text(f"# {seed} (Red Deck, White Stake)" + "\n".join(bot.journal) + end_line + "\n")
    return g


def causes(g) -> list[str]:
    d, out = g["died"], []
    if d["winnable"]:
        out.append("misplayed the deciding round")
    elif d["won_without_boss"]:
        out.append("the boss's effect decided it")
    else:
        out.append("build too weak for the target")
    if d["share"] >= 0.9:
        out.append("near miss (90%+ of the target)")
    short = g["first_short"]
    if short:
        lead = g["ante"] - short["ante"]
        out.append(f"short of the targets {'from ante ' + str(short['ante']) if lead >= 2 else 'only near the end'}")
    rich = [s for s in g["shops"] if s.get("money_out", 0) >= 25 and s["rerolls"] == 0]
    if len(rich) >= 2:
        out.append("held $25+ through shops without rerolling")
    if any(s.get("slots") and s.get("jokers", 0) < s["slots"] for s in g["shops"][-3:]):
        out.append("empty joker slot in the last shops")
    if not g["end"]["xmult"] and g["ante"] >= 5:
        out.append("no xMult joker by ante 5+")
    lvl = g["end"]["levels"].get(g["end"]["most_played"], 1)
    if g["ante"] >= 5 and lvl <= 2:
        out.append("main hand barely levelled")
    if g["end"]["consumables"]:
        out.append("died holding consumables")
    if g["end"]["money"] >= 20:
        out.append("died with $20+")
    return out


def story(g) -> str:
    d = g["died"]
    lines = [f"=== {g['seed']}: lost at ante {g['ante']} on {d['blind']} ({d['boss_effect'] or 'no boss'}); causes: {'; '.join(g['causes'])}",
             f"  needed {d['target']:,}, scored {d['score']:,} ({100 * d['share']:.0f}%); typical hand {d['typical']:,} x {d['hands']} hands "
             f"= margin {d['margin']}; beam search {'WON: ' + ' | '.join(d['line']) if d['winnable'] else 'no win (best ' + format(d['search_best'], ',') + ')'}"
             + ("" if d["won_without_boss"] is None else f"; without the boss: {'won' if d['won_without_boss'] else 'lost'}"),
             f"  end: jokers {g['end']['jokers']} ({len(g['end']['jokers'])}/{g['end']['slots']}), ${g['end']['money']}, "
             f"consumables {g['end']['consumables']}, levels {g['end']['levels']}, most played {g['end']['most_played']}, xMult {g['end']['xmult']}",
             "  margins: " + ", ".join(f"a{r['ante']} {r['blind']} {r['margin']}" for r in g["rounds"]),
             "  shops: " + " / ".join(f"a{s['ante']} ${s['money_in']}->${s.get('money_out')} rr{s['rerolls']} {len(s['did'])} moves" for s in g["shops"])]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--rng", type=int, default=99)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    rng = random.Random(args.rng)
    seeds = ["".join(rng.choice(CHARS) for _ in range(8)) for _ in range(args.games)]
    log(f"analyze: {len(seeds)} seeds (set {args.rng}), Red Deck, White Stake, to ante 8; {args.workers} workers")
    games, t0 = [], time.time()
    with mp.get_context("fork").Pool(args.workers) as pool:
        for g in pool.imap_unordered(diagnose, seeds):
            games.append(g)
            if len(games) % 10 == 0 or len(games) == len(seeds):
                el = time.time() - t0
                log(f"{len(games)}/{len(seeds)} games, {sum(x['won'] for x in games)} won, ETA {(len(seeds) - len(games)) * el / len(games) / 60:.1f} min")
    lost = [g for g in games if not g["won"]]
    counts = Counter(c for g in lost for c in g["causes"])
    primary = Counter(g["causes"][0] for g in lost)
    report = [f"{len(games)} games, {len(games) - len(lost)} won ({100 * (len(games) - len(lost)) / len(games):.0f}%), "
              f"{len(lost)} lost; lost at ante {dict(sorted(Counter(g['ante'] for g in lost).items()))}",
              "", "Primary cause (the deciding round):"]
    for c, n in primary.most_common():
        ex = [g["seed"] for g in lost if g["causes"][0] == c][:6]
        report.append(f"  {n:3d}  {c}   e.g. {', '.join(ex)}")
    report += ["", "All causes (a loss can have several):"]
    for c, n in counts.most_common():
        ex = [g["seed"] for g in lost if c in g["causes"]][:6]
        report.append(f"  {n:3d}  {c}   e.g. {', '.join(ex)}")
    bosses = Counter(g["died"]["blind"] for g in lost)
    report += ["", "Where runs died: " + ", ".join(f"{b} {n}" for b, n in bosses.most_common())]
    report += ["", "Stories:"] + [story(g) for g in sorted(lost, key=lambda g: (g["ante"], g["seed"]))]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "losses.json").write_text(json.dumps(games, indent=1))
    (OUT / "losses.txt").write_text("\n".join(report) + "\n")
    log("\n".join(report[:30]))
    log(f"done in {(time.time() - t0) / 60:.1f} min; wrote runs/analysis/losses.json and losses.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
