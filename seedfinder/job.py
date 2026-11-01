"""One seed search at a time, run in the background for the Lab's Seed Finder page.

Stage 1 is the C scanner (fastcheck search: first hand, then boss and voucher) over every seed;
stage 2 checks each candidate it reports against everything the player entered, in Python
(opening.py). Progress comes from the scanner's own log lines; this module also logs to
logs/seed_job.log.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path

from opening import BOSSES_ANTE1, TAGS, VOUCHERS, opening
from rng import RANDOM_SEED_CHARS, SEED_CHARS

HERE = Path(__file__).resolve().parent
SCAN_LOG = HERE / "logs" / "fastcheck_search.log"
JOB_LOG = HERE / "logs" / "seed_job.log"
TABLES = HERE / "tables"  # the precomputed seed table (table.c), when built
PROGRESS = re.compile(r"progress ([\d.e+]+) / ([\d.e+]+) seeds \(([\d.]+)%\), ([\d.]+) M seeds/s .*?ETA (\d+)s")


def table_info() -> dict:
    """How much of the precomputed table exists and what share of seeds it finds (table.c info)."""
    if not (TABLES / "t0.meta").exists():
        return {"built": False}
    out = subprocess.run([str(HERE / "table"), "info", str(TABLES)], capture_output=True, text=True, timeout=30).stdout
    m = re.search(r"all tables: expected success ([\d.]+)%", out)
    seg = re.findall(r"(\d+)/(\d+) segments", out)
    done, total = (sum(int(a) for a, _ in seg), sum(int(b) for _, b in seg)) if seg else (0, 0)
    return {"built": True, "success": float(m[1]) if m else 0.0, "segments": done, "segments_total": total}


def table_lookup(obs: dict, threads: int) -> list[str]:
    """Seeds the table finds for an opening: the hand, boss and both tags, and the voucher; when the voucher isn't
    given, each of the 16 an ante-1 shop can show (the base ones, VOUCHERS' even places) is tried in turn, about 2 s
    each (29 Oct: a search without it went straight to the 1h40m scan). [] if none or no table."""
    if not (TABLES / "t0.meta").exists() or not all(obs.get(k) for k in ("boss", "small_tag", "big_tag")):
        return []
    hand = ",".join(f"{c[1]}{c[0]}" for c in sorted(obs["hand"]))
    found = []
    for voucher in [obs["voucher"]] if obs.get("voucher") else VOUCHERS[::2]:
        cmd = [str(HERE / "table"), "lookup", str(TABLES), hand, str(BOSSES_ANTE1.index(obs["boss"])),
               str(VOUCHERS.index(voucher)), str(TAGS.index(obs["small_tag"])), str(TAGS.index(obs["big_tag"])),
               str(threads)]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600).stdout
        found += [line.split()[1] for line in out.splitlines() if line.startswith("FOUND ")]
    return found


def matches(o: dict, obs: dict) -> list[str]:
    """What in the observation this opening contradicts (empty: it fits)."""
    wrong = []
    if obs.get("hand") and set(o["first_hand"]) != set(obs["hand"]):
        wrong.append("hand")
    for key in ("boss", "voucher", "small_tag", "big_tag"):
        if obs.get(key) and o[key] != obs[key]:
            wrong.append(key)
    if obs.get("shop") and sorted(c["name"] for c in o["shop_cards"]) != sorted(obs["shop"]):
        wrong.append("shop")
    return wrong


class SeedSearch:
    def __init__(self, threads: int = 18):
        self.threads = threads
        self.lock = threading.RLock()  # start() reports status() while holding it
        self.proc: subprocess.Popen | None = None
        self.state = {"status": "idle"}

    def _log(self, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
        with open(JOB_LOG, "a") as fh:
            fh.write(line + "\n")

    def start(self, obs: dict) -> dict:
        """obs: hand (8 internal cards like 'SA'), and optionally boss, voucher, small_tag, big_tag, shop,
        no_o (seed made by the game, so no letter O)."""
        with self.lock:
            if self.state.get("status") == "running":
                raise RuntimeError("a search is already running")
            if len(set(obs.get("hand") or [])) != 8:
                raise ValueError("pick the 8 cards of the first hand")
            alpha = RANDOM_SEED_CHARS if obs.get("no_o", True) else SEED_CHARS
            b = len(alpha)
            hand_arg = ",".join(f"{c[1]}{c[0]}" for c in sorted(obs["hand"]))
            boss_arg = str(BOSSES_ANTE1.index(obs["boss"])) if obs.get("boss") else "-1"
            voucher_arg = str(VOUCHERS.index(obs["voucher"])) if obs.get("voucher") else "-1"
            SCAN_LOG.parent.mkdir(exist_ok=True)
            first, last = obs.get("chunks") or (0, b ** 3 - 1)  # chunks: a slice of the seed space, for tests
            cmd = [str(HERE / "fastcheck"), "search", str(SCAN_LOG), str(self.threads), str(8 * 3600), str(b),
                   str(first), str(last), hand_arg, boss_arg, voucher_arg]
            self.state = {"status": "running", "phase": "table", "obs": obs, "started": time.time(), "scanned": 0,
                          "total": float((last - first + 1) * b ** 5),
                          "percent": 0.0, "rate": 0.0, "eta": None, "stage1": [], "found": [], "rejected": []}
            self._log(f"start {obs}")
            threading.Thread(target=self._run, args=(obs, cmd), daemon=True).start()
            return self.status()

    def _run(self, obs: dict, cmd: list[str]) -> None:
        """The table first (about a second, when it is built and the opening is complete), then the full scan."""
        if obs.get("no_o", True) and not obs.get("chunks"):
            t0 = time.time()
            seeds = table_lookup(obs, self.threads)
            fits = [c for c in ({"seed": s, "opening": opening(s)} for s in seeds) if not matches(c["opening"], obs)]
            self._log(f"table lookup in {time.time() - t0:.1f}s: {seeds}, fitting {[c['seed'] for c in fits]}")
            if fits:
                with self.lock:
                    for c in fits:
                        c["wrong"] = []
                    self.state.update(status="done", phase="table", found=fits, percent=100.0, finished=time.time())
                return
        with self.lock:
            if self.state.get("status") != "running":
                return
            self.state["phase"] = "scan"
            self._log(f"scan: {' '.join(cmd)}")
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self._follow(self.proc, obs)

    def _follow(self, proc: subprocess.Popen, obs: dict) -> None:
        for line in proc.stdout:
            m = PROGRESS.search(line)
            if m:
                with self.lock:
                    self.state.update(scanned=float(m[1]), total=float(m[2]), percent=float(m[3]),
                                      rate=float(m[4]) * 1e6, eta=int(m[5]))
            elif " MATCH " in line:
                seed = line.split()[-1]
                o = opening(seed)
                wrong = matches(o, obs)
                with self.lock:
                    self.state["stage1"].append(seed)
                    (self.state["rejected"] if wrong else self.state["found"]).append({"seed": seed, "opening": o, "wrong": wrong})
                self._log(f"candidate {seed}: {'fits' if not wrong else 'differs in ' + ', '.join(wrong)}")
        code = proc.wait()
        with self.lock:
            if self.state.get("status") == "running":
                self.state["status"] = "done" if code == 0 else f"failed (exit {code})"
            self.state["finished"] = time.time()
        self._log(f"end: {self.state['status']}, {len(self.state['found'])} seed(s) fit: "
                  f"{[c['seed'] for c in self.state['found']]}")

    def stop(self) -> dict:
        with self.lock:
            if self.state.get("status") == "running":
                self.state["status"] = "stopped"
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        return self.status()

    def status(self) -> dict:
        with self.lock:
            s = dict(self.state)
        if "started" in s:
            s["elapsed"] = (s.get("finished") or time.time()) - s["started"]
        return s
