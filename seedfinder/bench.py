"""Python speed of the seed -> observable checks (single core).

    python3 -u bench.py [--seconds 8]      # ~45 s total, log: logs/bench_python.log

Each check runs on fresh random 8-character seeds for about --seconds and reports seeds/second.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

from opening import BOSSES_ANTE1, DECK_ORDER, Run, opening
from rng import SEED_CHARS, GameRNG

HERE = Path(__file__).resolve().parent
LOG = HERE / "logs" / "bench_python.log"
T0 = time.time()


def log(fh, msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} +{time.time() - T0:6.1f}s  {msg}"
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def boss_only(seed):
    return BOSSES_ANTE1[GameRNG(seed).element_index("boss", 8)]


def voucher_only(seed):
    return Run(seed).voucher(1)


TARGET = frozenset(DECK_ORDER[i] for i in (0, 7, 14, 21, 28, 35, 42, 49))   # an arbitrary 8-card hand


def hand_filter(seed):
    """Early-exit hand check: draw the Fisher-Yates positions 52..45 one at a time and stop at the
    first card that is not in the target hand (what a search would do)."""
    lr = GameRNG(seed).seeded("nr1")
    deck = list(DECK_ORDER)
    for i in range(52, 44, -1):
        j = lr.random_n(i)
        deck[i - 1], deck[j - 1] = deck[j - 1], deck[i - 1]
        if deck[i - 1] not in TARGET:
            return False
    return True


def full_hand(seed):
    return Run(seed).hand(1)


def full_opening(seed):
    return opening(seed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=8.0)
    args = ap.parse_args()
    LOG.parent.mkdir(exist_ok=True)
    fh = open(LOG, "w")
    rnd = random.Random(12345)
    checks = [("boss (key 'boss', 1 draw)", boss_only), ("voucher (key 'Voucher1' + resamples)", voucher_only),
              ("first hand, early-exit filter", hand_filter), ("first hand, full 51-swap shuffle", full_hand),
              ("full opening (tags, boss, voucher, hand, shop, packs)", full_opening)]
    log(fh, f"bench.py start, python {sys.version.split()[0]}, {args.seconds:.0f}s per check, "
            f"ETA {args.seconds * len(checks):.0f}s")
    results = {}
    for name, fn in checks:
        n, t = 0, time.perf_counter()
        deadline = t + args.seconds
        next_report = t + 2
        while True:
            for _ in range(200):
                fn("".join(rnd.choice(SEED_CHARS) for _ in range(8)))
            n += 200
            now = time.perf_counter()
            if now >= next_report:
                log(fh, f"  {name}: {n} seeds, {n / (now - t):,.0f} seeds/s, ETA {max(0, deadline - now):.0f}s")
                next_report = now + 2
            if now >= deadline:
                break
        rate = n / (time.perf_counter() - t)
        results[name] = rate
        log(fh, f"RESULT {name}: {rate:,.0f} seeds/s (single core, includes seed-string generation)")
    space = 35 ** 8
    for name, rate in results.items():
        log(fh, f"PROJECTION {name}: 35^8 seeds on 1 core = {space / rate / 86400 / 365:,.1f} years; "
                f"on 18 cores = {space / rate / 18 / 86400:,.0f} days")
    log(fh, f"done in {time.time() - T0:.1f}s, exit 0")


if __name__ == "__main__":
    main()
