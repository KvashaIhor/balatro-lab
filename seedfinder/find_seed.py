"""Find the seed of a White Stake, Red Deck run from what the player saw at its start.

Real use (full scan of all 8-character seeds, ~4 h on 18 cores; ~3.2 h with --no-o):
    python3 -u find_seed.py --hand "AS KH 10D 2C 9S 4H 7D QC" --boss "The Club" \
        --voucher "Hone" --tags "Charm Tag, Double Tag" --shop "Blueprint, The Fool" --no-o

Demo (picks a secret seed, then searches a slice of the seed space around it, ~1 min):
    python3 -u find_seed.py --demo

Stage 1 (C, fastcheck search): first hand (+ boss + voucher if given) over the seed space.
Stage 2 (Python, opening.py): every stage-1 candidate is checked against all observations.
Log: logs/find_seed.log (driver) and logs/fastcheck_search.log (C progress with ETA).
"""
from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from opening import BOSSES_ANTE1, VOUCHERS, card_label, opening, parse_card
from rng import RANDOM_SEED_CHARS, SEED_CHARS

HERE = Path(__file__).resolve().parent
LOG = HERE / "logs" / "find_seed.log"
CLOG = HERE / "logs" / "fastcheck_search.log"
T0 = time.time()
_fh = None


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} +{time.time() - T0:6.1f}s  {msg}"
    print(line, flush=True)
    _fh.write(line + "\n")
    _fh.flush()


def chunk_of(seed: str, alpha: str) -> int:
    b = len(alpha)
    return alpha.index(seed[7]) * b * b + alpha.index(seed[6]) * b + alpha.index(seed[5])


def matches(o: dict, obs: dict) -> bool:
    if obs.get("hand") and set(o["first_hand"]) != obs["hand"]:
        return False
    if obs.get("boss") and o["boss"] != obs["boss"]:
        return False
    if obs.get("voucher") and o["voucher"] != obs["voucher"]:
        return False
    if obs.get("tags") and [o["small_tag"], o["big_tag"]] != obs["tags"]:
        return False
    if obs.get("shop") and sorted(c["name"] for c in o["shop_cards"]) != sorted(obs["shop"]):
        return False
    return True


def main():
    global _fh
    ap = argparse.ArgumentParser()
    ap.add_argument("--hand", help="8 cards, e.g. 'AS KH 10D 2C 9S 4H 7D QC'")
    ap.add_argument("--boss")
    ap.add_argument("--voucher")
    ap.add_argument("--tags", help="'Small Tag, Big Tag'")
    ap.add_argument("--shop", help="the 2 shop cards, comma separated")
    ap.add_argument("--no-o", action="store_true", help="only seeds without the letter O (game-generated)")
    ap.add_argument("--threads", type=int, default=18)
    ap.add_argument("--max-seconds", type=float, default=6 * 3600)
    ap.add_argument("--chunks", help="FIRST:LAST chunk range (default: all)")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()
    LOG.parent.mkdir(exist_ok=True)
    _fh = open(LOG, "w")
    alpha = RANDOM_SEED_CHARS if args.no_o or args.demo else SEED_CHARS
    b = len(alpha)
    nchunks = b ** 3

    if args.demo:
        rnd = random.Random(int(time.time()))
        secret = "".join(rnd.choice(RANDOM_SEED_CHARS) for _ in range(8))
        o = opening(secret)
        obs = {"hand": set(o["first_hand"]), "boss": o["boss"], "voucher": o["voucher"],
               "tags": [o["small_tag"], o["big_tag"]], "shop": [c["name"] for c in o["shop_cards"]]}
        c = chunk_of(secret, alpha)
        first, last = max(0, c - 60), min(nchunks - 1, c + 59)
        log(f"DEMO secret seed {secret} (chunk {c}); the player would report:")
        log(f"  hand {' '.join(card_label(x) for x in o['first_hand'])}; boss {o['boss']}; voucher {o['voucher']}; "
            f"tags {obs['tags']}; shop {obs['shop']}")
    else:
        obs = {}
        if args.hand:
            cards = [parse_card(x) for x in re.split(r"[\s,]+", args.hand.strip()) if x]
            if len(set(cards)) != 8:
                sys.exit("--hand needs 8 distinct cards")
            obs["hand"] = set(cards)
        if args.boss:
            obs["boss"] = args.boss
        if args.voucher:
            obs["voucher"] = args.voucher
        if args.tags:
            obs["tags"] = [t.strip() for t in args.tags.split(",")]
        if args.shop:
            obs["shop"] = [t.strip() for t in args.shop.split(",")]
        if "hand" not in obs:
            sys.exit("the first hand is required: without it a search cannot be narrowed enough")
        first, last = (map(int, args.chunks.split(":")) if args.chunks else (0, nchunks - 1))

    seeds_to_scan = (last - first + 1) * b ** 5
    log(f"stage 1: fastcheck over chunks {first}..{last} = {seeds_to_scan:.3g} seeds, alphabet {b}, "
        f"{args.threads} threads; expected ~160 M seeds/s -> ETA ~{seeds_to_scan / 1.6e8:.0f}s; "
        f"watch: tail -f {CLOG}")
    hand_arg = ",".join(f"{x[1]}{x[0]}" for x in sorted(obs["hand"]))
    boss_arg = str(BOSSES_ANTE1.index(obs["boss"])) if obs.get("boss") else "-1"
    v_arg = str(VOUCHERS.index(obs["voucher"])) if obs.get("voucher") else "-1"
    cmd = [str(HERE / "fastcheck"), "search", str(CLOG), str(args.threads), str(args.max_seconds), str(b),
           str(first), str(last), hand_arg, boss_arg, v_arg]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"fastcheck FAILED with exit code {proc.returncode}: {proc.stderr[-2000:]}")
        sys.exit(1)
    out = proc.stdout.splitlines()
    log("stage 1 done: " + out[-1].split("s  ", 1)[-1])
    cands = [line.split()[-1] for line in out if " MATCH " in line]
    log(f"stage 1 candidates (hand{' + boss' if obs.get('boss') else ''}"
        f"{' + voucher' if obs.get('voucher') else ''}): {len(cands)} {cands[:20]}")
    final = [s for s in cands if matches(opening(s), obs)]
    log(f"stage 2 (all observations in Python): {len(final)} seed(s): {final}")
    if args.demo:
        log(f"DEMO {'SUCCESS' if final == [secret] else 'FAILURE'}: secret {secret}, found {final}")
    log(f"done in {time.time() - T0:.1f}s, exit 0")


if __name__ == "__main__":
    main()
