"""How many bits each opening observable carries, and how many seeds survive typical inputs.

    python3 -u info.py [N]     # default N=40000 random seeds, ~15 s, log: logs/info.log

Entropies are measured on N random seeds with the full opening model (plug-in estimate; for the
first hand, whose 7.5e8 values cannot be sampled, the exact uniform value log2(C(52,8)) is used and
the sample is only checked for repeats).  Expected surviving seeds for an observation set =
seed space x 2^-(bits), i.e. the count for a typical (not unusually common) observation.
"""
from __future__ import annotations

import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

from opening import opening
from rng import RANDOM_SEED_CHARS, SEED_CHARS

HERE = Path(__file__).resolve().parent
LOG = HERE / "logs" / "info.log"
T0 = time.time()


def entropy(counter: Counter) -> float:
    n = sum(counter.values())
    return -sum(c / n * math.log2(c / n) for c in counter.values())


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
    fh = open(LOG, "w")

    def log(msg):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} +{time.time() - T0:6.1f}s  {msg}"
        print(line, flush=True)
        fh.write(line + "\n")
        fh.flush()

    log(f"info.py start: {n} random seeds, ETA ~{n / 3000:.0f}s")
    rnd = random.Random(99)
    obs = {k: Counter() for k in ("boss", "voucher", "small_tag", "big_tag", "tags", "shop_cards",
                                  "shop_cards_set", "pack2", "hand")}
    for i in range(1, n + 1):
        o = opening("".join(rnd.choice(SEED_CHARS) for _ in range(8)))
        obs["boss"][o["boss"]] += 1
        obs["voucher"][o["voucher"]] += 1
        obs["small_tag"][o["small_tag"]] += 1
        obs["big_tag"][o["big_tag"]] += 1
        obs["tags"][(o["small_tag"], o["big_tag"])] += 1
        cards = tuple((c["name"], c.get("edition")) for c in o["shop_cards"])
        obs["shop_cards"][cards] += 1
        obs["shop_cards_set"][tuple(sorted(c["name"] for c in o["shop_cards"]))] += 1
        obs["pack2"][o["packs"][1]] += 1
        obs["hand"][tuple(o["first_hand"])] += 1
        if i % 10000 == 0:
            el = time.time() - T0
            log(f"  {i}/{n} seeds, {i / el:.0f}/s, ETA {(n - i) / (i / el):.0f}s")
    bits = {}
    for k in ("boss", "voucher", "small_tag", "big_tag", "tags", "pack2"):
        bits[k] = entropy(obs[k])
        log(f"BITS {k:14s} {bits[k]:6.2f}  ({len(obs[k])} distinct values seen)")
    # Shop cards have hundreds of values: the plug-in estimate on N samples is biased low; report it
    # and a model-based figure (type, rarity, identity, edition independent).
    log(f"BITS shop cards (ordered, with edition) plug-in {entropy(obs['shop_cards']):.2f} "
        f"({len(obs['shop_cards'])} distinct in {n}); unordered names {entropy(obs['shop_cards_set']):.2f}")
    one = Counter()
    for (a, b), c in obs["shop_cards"].items():
        one[a] += c
        one[b] += c
    bits["shop_cards"] = 2 * entropy(one)
    log(f"BITS shop cards model: 2 x {entropy(one):.2f} (one slot) = {bits['shop_cards']:.2f}")
    bits["hand"] = math.log2(math.comb(52, 8))
    log(f"BITS first hand = log2(C(52,8)) = {bits['hand']:.2f}; sample repeats: "
        f"{sum(c - 1 for c in obs['hand'].values())} (expect ~{n * (n - 1) / 2 / math.comb(52, 8):.2f})")
    for name, alpha in (("all 8-char seeds (35^8)", SEED_CHARS), ("game-generated (34^8, no O)", RANDOM_SEED_CHARS)):
        space = len(alpha) ** 8
        log(f"SPACE {name}: {space:.4g} = {math.log2(space):.2f} bits")
        combos = [
            ("tags + boss (blind-select screen only)", ["tags", "boss"]),
            ("tags + boss + voucher + shop cards + pack (no hand)", ["tags", "boss", "voucher", "shop_cards", "pack2"]),
            ("first hand", ["hand"]),
            ("first hand + boss", ["hand", "boss"]),
            ("first hand + boss + voucher", ["hand", "boss", "voucher"]),
            ("first hand + boss + tags", ["hand", "boss", "tags"]),
            ("first hand + boss + voucher + tags", ["hand", "boss", "voucher", "tags"]),
            ("first hand + boss + voucher + tags + shop cards", ["hand", "boss", "voucher", "tags", "shop_cards"]),
        ]
        for label, keys in combos:
            b = sum(bits[k] for k in keys)
            exp_other = (space - 1) * 2 ** -b
            log(f"  SURVIVORS {label:55s} {b:6.2f} bits -> the true seed + ~{exp_other:,.3g} others; "
                f"P(unique) ~ {math.exp(-exp_other):.3f}")
    log(f"done in {time.time() - T0:.1f}s, exit 0")


if __name__ == "__main__":
    main()
