"""Cross-check the C fast path (fastcheck.c) against the Python reference (rng.py/opening.py).

    python3 -u crosscheck.py [N]      # default N=20000 random seeds, ~15 s, log: logs/crosscheck.log

Compares hashed seed (bit exact), ante-1 boss, voucher, both tags and the 8 first-hand cards.
"""
from __future__ import annotations

import random
import subprocess
import sys
import time
from pathlib import Path

from opening import BOSSES_ANTE1, DECK_ORDER, TAGS, VOUCHERS, Run
from rng import SEED_CHARS

HERE = Path(__file__).resolve().parent
LOG = HERE / "logs" / "crosscheck.log"
T0 = time.time()


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    fh = open(LOG, "w")

    def log(msg):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} +{time.time() - T0:6.1f}s  {msg}"
        print(line, flush=True)
        fh.write(line + "\n")
        fh.flush()

    rnd = random.Random(7)
    seeds = ["".join(rnd.choice(SEED_CHARS) for _ in range(8)) for _ in range(n)]
    seeds += ["7LB2WVPK", "11153DRU", "ALEEBOOO", "99K6IUBD"]
    log(f"crosscheck start: {len(seeds)} seeds, ETA ~{len(seeds) / 1500:.0f}s")
    bad, batch = 0, 2000
    for b in range(0, len(seeds), batch):
        chunk = seeds[b:b + batch]
        out = subprocess.run([str(HERE / "fastcheck"), "dump", *chunk], capture_output=True, text=True,
                             check=True).stdout.splitlines()
        for s, line in zip(chunk, out):
            r = Run(s)
            boss, v = BOSSES_ANTE1.index(r.boss_ante1()), VOUCHERS.index(r.voucher(1))
            t = (TAGS.index(r.tag(1)), TAGS.index(r.tag(1)))
            hand = ",".join(r.rng.shuffle("nr1", DECK_ORDER)[-8:][::-1])
            want = f"{s} {r.rng.hashed_seed!r} boss={boss} voucher={v} tags={t[0]},{t[1]} hand={hand}"
            f = line.split()
            got = f"{f[0]} {float(f[1])!r} {' '.join(f[2:])}"
            if got != want:
                bad += 1
                if bad <= 10:
                    log(f"MISMATCH\n  C : {got}\n  Py: {want}")
        done = min(b + batch, len(seeds))
        el = time.time() - T0
        log(f"  {done}/{len(seeds)} seeds, {done / el:.0f}/s, ETA {(len(seeds) - done) / (done / el):.0f}s, mismatches {bad}")
    log(f"RESULT {len(seeds) - bad}/{len(seeds)} seeds identical (hashed seed, boss, voucher, 2 tags, 8-card hand); exit 0")


if __name__ == "__main__":
    main()
