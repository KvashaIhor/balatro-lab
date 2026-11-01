"""What goes best and worst with each card in scoring: the lists the Evolution tab shows when you hover a card.

Usage:  python3 -u scripts/synergy.py [--hands 40] [--workers N]
Writes: runs/synergy.json (the app runs this the first time the tab asks, logging to logs/synergy.log)

For two things A and B (two jokers, or a joker and a deck feature: 8 Steel cards, 13 more Hearts, 3 levels of
Flush, ...) the synergy is how much more a build scores with both than the two add alone, in build power (the
value bot's measure: the mean log of the best hand's score over hands dealt from a standard deck):

    power(A and B) - power(A) - power(B) + power(neither)

Positive: they combine (Mime with Baron, Pareidolia with Scary Face). Negative: they get in each other's way
(two +Mult jokers, whose Mult only adds up; jokers that want different poker hands). Being in log score, two
effects that simply multiply count as 0. Only scoring shows: money, growth over a run and rule changes don't.
Hands are scored as a round starts (all hands and discards left). A few jokers combine with nearly
any joker (Swashbuckler, Abstract Joker) or clash with any (Joker Stencil); they would top or end every list,
so they are left out of the others' lists and say so on their own. A tarot, planet or spectral that makes a
deck feature (The Chariot: Steel cards; Jupiter: Flush levels) shares that feature's list. About a minute.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from balatro.items import entries  # noqa: E402
from balatro.jokers import CATALOG  # noqa: E402
from balatro.neural import EDITIONS, ENHANCEMENTS, HANDS, JOKERS, SEALS, SUITS  # noqa: E402
from balatro.run import Run  # noqa: E402
from balatro.strategy import ValueBot, joker_order  # noqa: E402

OUT = ROOT / "runs" / "synergy.json"
TOP = 5
NOTABLE = 0.01                     # power: hands scoring about 1% more or less
GENERIC = 0.05                     # a joker whose typical synergy with other jokers is this far from 0
EVERY = slice(0, 48, 6)            # the 8 deck cards a deck feature is put on
ENHANCE_TAROT = {"The Magician": "Lucky", "The Empress": "Mult", "The Hierophant": "Bonus", "The Lovers": "Wild",
                 "The Chariot": "Steel", "Justice": "Glass", "The Devil": "Gold", "The Tower": "Stone"}
SUIT_TAROT = {"The Star": "Diamonds", "The Moon": "Clubs", "The Sun": "Hearts", "The World": "Spades"}
SEAL_SPECTRAL = {"Talisman": "Gold", "Deja Vu": "Red", "Trance": "Blue", "Medium": "Purple"}


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def _set(attr, value):
    def apply(run):
        for c in run.deck[EVERY]:
            setattr(c, attr, value)
    return apply


def _suit(suit):
    def apply(run):
        for i in [i for i, c in enumerate(run.deck) if c.suit != suit][::3][:13]:
            run.deck[i].suit = suit
    return apply


def _levels(hand):
    def apply(run):
        run.hand_levels[hand] += 3
    return apply


# Deck features, named as the Evolution tab names the network's inputs.
FEATURES = ([(f"share of {e} cards", f"+8 {e} cards", _set("enhancement", e)) for e in ENHANCEMENTS]
            + [(f"share with a {s} seal", f"+8 cards with a {s} Seal", _set("seal", s)) for s in SEALS]
            + [(f"share that is {e}", f"+8 {e} cards", _set("edition", e)) for e in EDITIONS]
            + [(f"share of {s}", f"+13 {s}", _suit(s)) for s in SUITS]
            + [(f"{h} level", f"{h} +3 levels", _levels(h)) for h in HANDS])


class Scorer(ValueBot):
    HANDS = 40


BOT: Scorer = None
RUNS: dict = {}                    # None: the plain deck; else a feature's name
ALONE: dict = {}                   # (deck, joker or None) -> power


def power(deck, names) -> float:
    run = RUNS[deck]
    made = [CATALOG[n]() for n in names]
    run.jokers = [made[i] for i in joker_order(made)]
    try:
        return BOT.power(run)
    except Exception:  # noqa: BLE001 - a joker that can't score without a real round: no synergy to show
        return math.nan
    finally:
        run.jokers = []


def row(a: int):
    """Joker a with every later joker, and with every deck feature."""
    ja, base = JOKERS[a], ALONE[(None, None)]
    jokers = [power(None, [ja, jb]) - ALONE[(None, ja)] - ALONE[(None, jb)] + base for jb in JOKERS[a + 1:]]
    features = [power(f, [ja]) - ALONE[(None, ja)] - ALONE[(f, None)] + base for f, _, _ in FEATURES]
    return a, jokers, features


def ranked(pairs):
    """The TOP best and worst of (kind, name, label, synergy), leaving out what is about none."""
    pairs = sorted((p for p in pairs if not math.isnan(p[3])), key=lambda p: -p[3])
    up = [[k, n, lab, round(v, 3)] for k, n, lab, v in pairs[:TOP] if v >= NOTABLE]
    down = [[k, n, lab, round(v, 3)] for k, n, lab, v in reversed(pairs[-TOP:]) if v <= -NOTABLE]
    return {"up": up, "down": down}


def main() -> int:
    global BOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=40)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    t0 = time.time()
    Scorer.HANDS = args.hands
    BOT = Scorer()
    log(f"synergy: {len(JOKERS)} jokers x ({len(JOKERS)} jokers + {len(FEATURES)} deck features), "
        f"{args.hands} hands each, {args.workers} workers")
    RUNS[None] = Run(BOT, game_seed="SYNERGY", deck=None)
    for f, _, apply in FEATURES:
        RUNS[f] = Run(BOT, game_seed="SYNERGY", deck=None)
        apply(RUNS[f])
    for deck in RUNS:
        ALONE[(deck, None)] = power(deck, [])
    for j in JOKERS:
        ALONE[(None, j)] = power(None, [j])
    log(f"each alone: {time.time() - t0:.1f}s")

    n = len(JOKERS)
    jj = [[math.nan] * n for _ in range(n)]
    jf = [None] * n
    done = 0
    # Workers fork with the runs and the powers alone already made; long rows (early jokers) go first.
    with mp.get_context("fork").Pool(args.workers) as pool:
        for a, jokers, features in pool.imap_unordered(row, range(n)):
            for k, s in enumerate(jokers, start=a + 1):
                jj[a][k] = jj[k][a] = s
            jf[a] = features
            done += 1
            if done % 10 == 0 or done == n:
                el = time.time() - t0
                log(f"{done}/{n} jokers, {el:.0f}s, about {el / done * (n - done):.0f}s left")

    cards = {}
    flabel = {f: label for f, label, _ in FEATURES}
    typical = [statistics.median(s for s in jj[b] if not math.isnan(s)) for b in range(n)]
    generic = {b for b in range(n) if abs(typical[b]) >= GENERIC}
    log("with any joker: " + ", ".join(f"{JOKERS[b]} {typical[b]:+.2f}" for b in sorted(generic)))
    for a, ja in enumerate(JOKERS):
        cards[f"joker|{ja}"] = ranked([("joker", jb, jb, jj[a][b]) for b, jb in enumerate(JOKERS) if b != a and b not in generic]
                                      + [("fact", f, label, jf[a][k]) for k, (f, label, _) in enumerate(FEATURES)])
        if a in generic:
            cards[f"joker|{ja}"]["any"] = round(typical[a], 3)
    for k, (f, label, _) in enumerate(FEATURES):
        cards[f"fact|{f}"] = {**ranked([("joker", ja, ja, jf[a][k]) for a, ja in enumerate(JOKERS)]), "via": label}
    made = ({("tarot", t): f"share of {e} cards" for t, e in ENHANCE_TAROT.items()}
            | {("tarot", t): f"share of {s}" for t, s in SUIT_TAROT.items()}
            | {("spectral", s): f"share with a {seal} seal" for s, seal in SEAL_SPECTRAL.items()}
            | {("planet", p["name"]): f"{p['hand']} level" for p in entries("planet")})
    for (kind, name), f in made.items():
        cards[f"{kind}|{name}"] = {**cards[f"fact|{f}"], "via": flabel[f]}
    OUT.parent.mkdir(exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"hands": args.hands, "seconds": round(time.time() - t0, 1),
                               "made": time.strftime("%Y-%m-%d %H:%M:%S"), "cards": cards}))
    tmp.replace(OUT)
    log(f"wrote {OUT.relative_to(ROOT)}: {len(cards)} cards in {time.time() - t0:.0f}s; exit 0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        log("failed:\n" + traceback.format_exc() + "exit 1")
        raise SystemExit(1)
