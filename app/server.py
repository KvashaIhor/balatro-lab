"""Balatro Lab: a local web app that plays a recorded run and shows it with the game's art.

Usage:  python3 app/server.py [--port 8643]     then open http://127.0.0.1:8643
Log:    logs/app.log
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from balatro.bots import GreedyBot  # noqa: E402
from balatro.interactive import Games, PlayError, ReplayError  # noqa: E402
from balatro.items import DECKS, entries  # noqa: E402
from balatro.jokers import CATALOG  # noqa: E402
from balatro.models import listing as model_list, make as make_model  # noqa: E402
from balatro.projection import project as project_seed  # noqa: E402
from balatro.run import Run  # noqa: E402

sys.path.insert(0, str(ROOT / "seedfinder"))
import opening as seed_opening  # noqa: E402
from job import SeedSearch, table_info  # noqa: E402

STAKES = [s["name"] for s in entries("stake")]
SEARCH = SeedSearch()
PLAY = Games()                                       # the Play tab's games (runs/played/)
SEED_CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"   # what the game draws a random seed from (no 0 or O)


def game_seed_of(text: str) -> str:
    """A Balatro seed as typed (any case), checked: 1-8 characters from 1-9 and A-Z."""
    seed = text.strip().upper()
    if not (1 <= len(seed) <= 8 and all(c in "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in seed)):
        raise ValueError("a seed is 1-8 characters from 1-9 and A-Z")
    return seed


def seed_projection(query: str) -> tuple[dict, int]:
    """/api/seed/projection?seed=...&deck=...&antes=4: what the seed's run shows ante by ante along one fixed path
    (balatro/projection.py), as (JSON, HTTP status)."""
    q = parse_qs(query)
    try:
        seed = game_seed_of((q.get("seed") or [""])[0])
        deck = (q.get("deck") or [""])[0] or "Red Deck"
        antes = max(1, min(8, int((q.get("antes") or [4])[0])))
    except ValueError as exc:
        return {"error": f"bad request: {exc}"}, 400
    if deck not in DECKS:
        return {"error": f"unknown deck {deck}"}, 400
    return project_seed(seed, deck, antes), 200


def table_builds(running_only: bool = False) -> list[int]:
    """Seed-table builds (seedfinder/table). A plan needs every core, so running ones pause while it runs (one
    that another job paused, such as an evolution run, is left to that job)."""
    out = subprocess.run(["pgrep", "-f", r"^\./table build"], capture_output=True, text=True).stdout
    pids = [int(pid) for pid in out.split()]
    if running_only:
        pids = [p for p in pids if not subprocess.run(["ps", "-o", "stat=", "-p", str(p)], capture_output=True,
                                                      text=True).stdout.strip().startswith("T")]
    return pids


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def pid_alive(pid) -> bool:
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


EVOLVE_DIR = ROOT / "runs" / "evolve"
ACTIVE_WEIGHTS = EVOLVE_DIR / "planner.json"   # what the value bot (and so the planner) plays with
RUN_ID = re.compile(r"^\d{8}-\d{6}$")


class Evolution:
    """Evolution runs of the value bot's weights (scripts/evolve_valuebot.py), each its own process and folder
    runs/evolve/<id>/ (config, status, a line per generation, the champion)."""

    def __init__(self):
        self.pids: dict[str, int] = {}           # runs started here, until they write their own status
        self.kinds: dict[str, str] = {}          # and what they evolve, until they write their config

    def summary(self, run_id: str) -> dict:
        d = EVOLVE_DIR / run_id
        status, config, champ = read_json(d / "status.json", {}), read_json(d / "config.json", {}), read_json(d / "champion.json")
        state = status.get("state")
        if state is None:
            state = "starting" if pid_alive(self.pids.get(run_id)) else "died"
        elif state == "running" and not pid_alive(status.get("pid")):
            state = "died"                       # killed before it could say so
        kind = {"neural": "network"}.get(config.get("kind"), config.get("kind")) or self.kinds.get(run_id, "weights")
        return {"id": run_id, "kind": kind, "state": state, "gen": status.get("gen", 0),
                "fitness": (config.get("config") or {}).get("fitness", "progress"),
                "generations": status.get("generations") or (config.get("config") or {}).get("generations"),
                "started": status.get("started"), "updated": status.get("updated"), "error": status.get("error"),
                "benchmark": champ["benchmark"] if champ else None, "champion_gen": champ["gen"] if champ else None,
                "baseline": (config.get("baseline") or {}).get("benchmark"),
                "active": (read_json(ACTIVE_WEIGHTS, {}) or {}).get("source") == run_id}

    def runs(self) -> list[dict]:
        ids = {p.name for p in EVOLVE_DIR.iterdir() if p.is_dir() and RUN_ID.match(p.name)} if EVOLVE_DIR.exists() else set()
        return [self.summary(i) for i in sorted(ids | set(self.pids), reverse=True)]

    def running(self) -> list[dict]:
        return [r for r in self.runs() if r["state"] in ("running", "starting")]

    def detail(self, run_id: str, since: int) -> dict:
        d = EVOLVE_DIR / run_id
        records = []
        try:
            for line in (d / "generations.jsonl").read_text().splitlines():
                rec = json.loads(line)
                if rec["gen"] > since:
                    records.append(rec)
        except (OSError, ValueError):
            pass                                 # none yet, or a line being written: it comes on the next poll
        summary = self.summary(run_id)
        if summary["kind"] == "network":
            for rec in records:
                rec["influence"] = network_influence(run_id, rec["gen"])
        out = {"summary": summary, "config": read_json(d / "config.json"), "champion": read_json(d / "champion.json"),
               "records": records}
        if summary["state"] in ("error", "died", "starting", "stopped"):
            try:
                out["log_tail"] = (ROOT / "logs" / f"evolve_{run_id}.log").read_text(errors="replace").splitlines()[-25:]
            except OSError:
                out["log_tail"] = []
        return out

    def start(self, body: dict) -> dict:
        if self.running():
            raise RuntimeError("an evolution run is already going")

        def num(key, default, lo, hi):
            return max(lo, min(hi, int(body.get(key) or default)))
        kind = body.get("kind") or "weights"
        if kind == "network":
            args = {"generations": num("generations", 150, 1, 2000), "pairs": num("pairs", 32, 4, 128),
                    "seeds": num("seeds", 24, 4, 200)}
            init = str(body.get("init") or "")
            if init:                                     # continue from that network run's champion
                if not RUN_ID.match(init) or not (EVOLVE_DIR / init / "champion.json").exists():
                    raise ValueError(f"no network champion in run {init}")
                args["init"] = init
            script = "evolve_neural.py"
        elif kind == "weights":
            args = {"generations": num("generations", 40, 1, 500), "population": num("population", 24, 8, 96),
                    "seeds": num("seeds", 24, 4, 200)}
            script = "evolve_valuebot.py"
        else:
            raise ValueError(f"unknown kind of run {kind}")
        run_id = time.strftime("%Y%m%d-%H%M%S")
        cmd = [sys.executable, "-u", str(ROOT / "scripts" / script), "--run-id", run_id]
        for k, v in args.items():
            cmd += [f"--{k}", str(v)]
        (ROOT / "logs").mkdir(exist_ok=True)
        # Launched through a process that exits at once, so the run is no child of this server: stopping or
        # restarting the server leaves it running. Its stderr goes to its log, so a crash it can't log shows.
        launcher = ("import subprocess, sys; p = subprocess.Popen(sys.argv[2:], stdout=subprocess.DEVNULL, "
                    "stderr=open(sys.argv[1], 'ab'), start_new_session=True); print(p.pid)")
        out = subprocess.run([sys.executable, "-c", launcher, str(ROOT / "logs" / f"evolve_{run_id}.log"), *cmd],
                             cwd=str(ROOT), capture_output=True, text=True, check=True)
        self.pids[run_id] = int(out.stdout)
        self.kinds[run_id] = kind
        log.info("evolution run %s started (pid %s): %s", run_id, out.stdout.strip(), " ".join(cmd))
        return {"id": run_id}

    def stop(self, run_id: str) -> dict:
        status = read_json(EVOLVE_DIR / run_id / "status.json", {})
        pid = status.get("pid") or self.pids.get(run_id)
        if not pid_alive(pid):
            raise RuntimeError("that run is not running")
        os.kill(pid, signal.SIGTERM)
        return {"ok": True}

    def use(self, run_id: str) -> dict:
        champ = read_json(EVOLVE_DIR / run_id / "champion.json")
        if not champ:
            raise RuntimeError("that run has no champion yet")
        EVOLVE_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVE_WEIGHTS.write_text(json.dumps({"genome": champ["genome"], "benchmark": champ["benchmark"],
                                              "source": run_id, "gen": champ["gen"], "network": champ.get("network")}))
        return self.active()

    @staticmethod
    def active() -> dict:
        a = read_json(ACTIVE_WEIGHTS)
        if not a:
            return {"source": "hand"}
        return {"source": a.get("source", "first evolution"), "gen": a.get("gen") or a.get("generation"),
                "benchmark": a.get("benchmark"), "network": bool(a.get("network"))}


EVOLUTION = Evolution()
_INFLUENCE: dict = {}
_TIMING_JOBS: dict[str, subprocess.Popen] = {}
TIMING_SEEDS = 16                 # games behind "Value by ante" (fewer leave the late antes to one game's build)


def network_timing(run_id: str) -> dict:
    """The champion's value of every card at each ante (scripts/timing.py, run in the background the first time;
    cached per champion generation, and redone if it was made from fewer games)."""
    champ = read_json(EVOLVE_DIR / run_id / "champion.json")
    if not champ or not champ.get("network"):
        return {"state": "none"}
    done = read_json(EVOLVE_DIR / run_id / f"timing_{champ['gen']}.json")
    if done and done.get("seeds", 0) >= TIMING_SEEDS:
        return {"state": "done", **done}
    job = _TIMING_JOBS.get(run_id)
    if job is None or job.poll() is not None:
        _TIMING_JOBS[run_id] = subprocess.Popen([sys.executable, "-u", str(ROOT / "scripts" / "timing.py"), run_id,
                                                 "--seeds", str(TIMING_SEEDS)],
                                                cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"state": "computing", "gen": champ["gen"]}


def item_texts() -> dict:
    """What each item the network corrects does, and what each input it reads means, for the Evolution tab's
    tooltips."""
    from balatro.items import data
    from balatro.neural import FACTS, SEALS
    items = {}
    for j in data("jokers.json"):
        items[f"joker|{j['name']}"] = f"{j['rarity']} joker, ${j['cost']}. {j['effect']}"
    for kind in ("tarot", "planet", "spectral"):
        for e in entries(kind):
            items[f"{kind}|{e['name']}"] = f"{e['type']}, ${e['cost']}. {e['effect']}"
    for p in data("shop.json")["booster_packs"]["packs"]:
        items[f"pack|{p['name']}"] = f"${p['cost']}: {p['contents']}; choose {p['cards_chosen']} of {p['cards_shown']}."
    for v in entries("voucher"):
        items[f"voucher|{v['name']}"] = f"${v['cost']}. {v['effect']}" + (f" Needs {v['requires']} first." if v.get("requires") else "")
    for kind in ("Tarot", "Planet", "Spectral"):
        items[f"keep|{kind}"] = (f"Holding a {kind} card in a consumable slot instead of using it at once. Perkeo makes a "
                                 f"Negative copy of a held consumable at each shop's end" + ("; with Observatory, each Planet "
                                 "held gives x1.5 Mult when its hand is played." if kind == "Planet" else "."))
    mods = data("modifiers.json")
    effect = {e["name"].replace(" Card", ""): e["effect"] for e in mods["enhancements"]}
    effect.update({e["name"]: e["effect"] for e in mods["editions"]})
    seal = {s["name"].replace(" Seal", ""): s["effect"] for s in mods["seals"]}
    vouchers = {v["name"]: v["effect"] for v in entries("voucher")}
    basics = {"ante / 16": "How far the run is: ante 1 is 0.06, ante 8 is 0.5.",
              "money / $50": "Money in hand, $50 = 1.", "joker slots filled": "Jokers owned out of the slots (1 = full).",
              "free joker slots / 5": "Empty joker slots.", "consumable slots filled": "Consumables held out of the slots.",
              "build power / 10": "How strong the build is: the average log of the best hand's score from the deck.",
              "deck size / 52": "Cards in the deck (52 = 1).", "hand size / 8": "Cards dealt per hand (8 = 1)."}
    facts = {}
    for f in FACTS:
        if f in basics:
            facts[f] = basics[f]
        elif f.startswith("share with a ") and f.endswith(" seal"):
            name = f[len("share with a "):-len(" seal")]
            facts[f] = f"Share of the deck's cards with a {name} Seal. {seal.get(name, '')}"
        elif f.startswith("share that is "):
            name = f[len("share that is "):]
            facts[f] = f"Share of the deck's cards that are {name}. {effect.get(name, '')}"
        elif f.startswith("share of ") and f.endswith(" cards"):
            name = f[len("share of "):-len(" cards")]
            facts[f] = f"Share of the deck's cards that are {name} cards. {effect.get(name, '')}"
        elif f.startswith("share of "):
            facts[f] = f"Share of the deck's cards that are {f[len('share of '):]} (Stone cards have no rank or suit)."
        elif f.endswith(" level"):
            facts[f] = f"The level of {f[:-len(' level')]} above 1 (each level adds chips and Mult when it's played)."
        elif f.startswith("has "):
            facts[f] = f"Whether {f[4:]} has been redeemed. {vouchers.get(f[4:], '')}"
    return {"items": items, "facts": facts}


def network_influence(run_id: str, gen: int) -> dict | None:
    """How strongly each input moves a network's corrections at generation `gen` (from its saved parameters):
    for a context fact, the size of the change in all 252 corrections per unit of that fact; for an owned joker or
    a held consumable, the change its embedding makes. Linearised at the middle of the hidden layer, so it is
    zero until the network learns to use the input."""
    key = (run_id, gen)
    if key not in _INFLUENCE:
        path = EVOLVE_DIR / run_id / "params" / f"{gen:04d}.npy"
        if not path.exists():
            return None
        import numpy as np
        from balatro.neural import N_FACTS, Network
        net = Network(np.load(path).astype(np.float64))
        reach = net.out[:, 1:] @ net.w1                      # corrections per unit of each input to the hidden layer
        facts = np.linalg.norm(reach[:, :N_FACTS], axis=0)
        jokers = np.linalg.norm(reach[:, N_FACTS:N_FACTS + net.embed.shape[1]] @ net.embed.T, axis=0)
        consumables = np.linalg.norm(reach[:, N_FACTS + net.embed.shape[1]:] @ net.cembed.T, axis=0)
        _INFLUENCE[key] = {"facts": np.round(facts, 4).tolist(), "jokers": np.round(jokers, 4).tolist(),
                           "consumables": np.round(consumables, 4).tolist()}
    return _INFLUENCE[key]


_SYNERGY_JOB: list = []


def synergy() -> dict:
    """What goes best and worst with each card in scoring (scripts/synergy.py, run in the background the first
    time; it doesn't depend on any run, so it is kept in runs/synergy.json)."""
    done = read_json(ROOT / "runs" / "synergy.json")
    if done:
        return {"state": "done", **done}
    if not _SYNERGY_JOB or _SYNERGY_JOB[0].poll() is not None:
        (ROOT / "logs").mkdir(exist_ok=True)
        _SYNERGY_JOB[:] = [subprocess.Popen([sys.executable, "-u", str(ROOT / "scripts" / "synergy.py")], cwd=str(ROOT),
                                            stdout=open(ROOT / "logs" / "synergy.log", "a"), stderr=subprocess.STDOUT)]
    return {"state": "computing"}


_TEXTS: dict = {}


def viewer_texts() -> dict:
    """What the run viewer's tooltips, Run Info and deck view say: every joker, consumable, voucher, pack and deck's
    effect, the card enhancements, editions and seals, and the poker hands (base chips and mult, per-level gains)."""
    if not _TEXTS:
        from balatro.items import data
        mods = data("modifiers.json")
        _TEXTS.update({
            "jokers": {j["name"]: {"effect": j["effect"], "rarity": j["rarity"]} for j in data("jokers.json")},
            "consumables": {e["name"]: {"effect": e["effect"], "kind": e["type"]} for k in ("tarot", "planet", "spectral")
                            for e in entries(k)},
            "vouchers": {v["name"]: v.get("description") or v["effect"] for v in entries("voucher")},   # the card's text
            "packs": {p["name"]: {"contents": p["contents"], "choose": p["cards_chosen"], "shown": p["cards_shown"]}
                      for p in data("shop.json")["booster_packs"]["packs"]},
            "decks": {d["name"]: d["effect"] for d in entries("deck")},
            "tags": {g["name"]: g["effect"] for g in entries("tag")},
            "enhancements": {e["name"].replace(" Card", ""): e["effect"] for e in mods["enhancements"]},
            "editions": {e["name"]: e["effect"] for e in mods["editions"]},
            "seals": {s["key"]: s["effect"] for s in mods["seals"]},
            "hands": [{k: h[k] for k in ("name", "chips", "mult", "level_chips", "level_mult", "secret", "definition")}
                      for h in data("hands.json")["hands"]],
        })
    return _TEXTS


SWEEP_PROGRESS = re.compile(r"^(\S+ \S+)  (\d+)/(\d+) games, (\d+) a minute, ETA (\d+) min")


def sweep() -> dict:
    """The behaviour modifiers' strength sweep (scripts/sweep_mods.py) for the Evolution tab: its plan
    (runs/sweeps/plan.json), its progress from its log, and each rule's result as it finishes (runs/sweeps/)."""
    out = ROOT / "runs" / "sweeps"
    plan = read_json(out / "plan.json")
    if not plan:
        return {"state": "none"}
    try:
        lines = (ROOT / "logs" / "sweep_mods.log").read_text().splitlines()
    except OSError:
        lines = []
    start = max((i for i, line in enumerate(lines) if "  sweep: " in line), default=len(lines))
    lines = lines[start:]
    prog = [m for m in map(SWEEP_PROGRESS.match, lines) if m]
    alive = subprocess.run(["pgrep", "-f", "scripts/sweep_mods.py"], capture_output=True, text=True).stdout.split()
    ended = next((line for line in reversed(lines) if "done in" in line or "failed" in line or "process exit" in line), "")
    state = "running" if alive else "done" if "done in" in ended else "stopped" if lines else "none"
    from balatro.modifiers import RULES as MOD_RULES
    partial = (read_json(out / "partial.json") or {}).get("rules", {}) if state == "running" else {}
    rules, first = [], True
    for r in plan["rules"]:
        res = read_json(out / f"{r}.json")
        status = "done" if res else "running" if state == "running" and (first or r in partial) else "waiting"
        if not res:
            first = False
        rules.append({"rule": r, "what": MOD_RULES.get(r, ""), "status": status, "result": res,
                      "partial": None if res else partial.get(r)})
    last = prog[-1] if prog else None
    return {"state": state, "plan": plan, "rules": rules,
            "games": int(last.group(2)) if last else 0, "total": int(last.group(3)) if last else None,
            "per_minute": int(last.group(4)) if last else None, "eta_min": int(last.group(5)) if last and alive else None,
            "updated": last.group(1) if last else None, "log_tail": lines[-6:]}


def gene_info() -> dict:
    """What each weight of the value bot is about, for the Evolution tab's "?" panels: an explanation and the
    cards it concerns (jokers of a group or rarity, a pack's sizes, a voucher), with their effects."""
    from balatro.items import data
    from balatro.strategy import GENES, GROWS, PAYS, RULES  # noqa: E402
    jokers = sorted(data("jokers.json"), key=lambda j: j["n"])

    def joker_items(pick, edition=None):
        return [{"kind": "Joker", "name": j["name"], "text": j["effect"], "rarity": j["rarity"], "edition": edition}
                for j in jokers if pick(j)]

    vouchers = {v["name"]: v for v in entries("voucher")}
    packs = data("shop.json")["booster_packs"]["packs"]
    power = ("Worth is in units of build power: the average log of the best hand's score over a few hands dealt from "
             "the deck, with the jokers, levels and cards the bot would have. +0.1 power is a build that scores about "
             "10% more.")
    info = {
        "money": {"text": "What each $1 spent costs. A purchase is made only when what it adds is worth more than "
                          "its price at this rate (plus the interest it loses). " + power, "example": "money"},
        "interest": {"text": "Each $5 held at the end of a round pays $1 of interest (up to $5 a round). A purchase "
                             "that takes money below a multiple of $5 loses that interest each round; this is the cost "
                             "of each $1 of interest lost. " + power, "example": "interest"},
        "grows": {"text": "A bonus for jokers that grow during a run (Mult or chips that build up), on top of what "
                          "they add to today's hands, which is all that build power can see.",
                  "items": joker_items(lambda j: j["name"] in GROWS)},
        "pays": {"text": "A bonus for jokers that make money, which build power doesn't see.",
                 "items": joker_items(lambda j: j["name"] in PAYS)},
        "rules": {"text": "A bonus for jokers that change the rules (hands, odds, slots, money limits) rather than "
                          "score directly.", "items": joker_items(lambda j: j["name"] in RULES)},
        "negative": {"text": "A bonus for a Negative joker: it takes no joker slot, so it never pushes another "
                             "joker out.", "items": joker_items(lambda j: j["name"] == "Joker", edition="Negative")},
        "sell_margin": {"text": "With every joker slot full, the bot sells its weakest joker for a new one only when "
                                "the new one is worth this much more (power and bonuses). Higher keeps what it has."},
        "keep": {"text": "The worth of buying a tarot or spectral card that can't be used in the shop (it needs cards "
                         "in hand), to use in the next round.", "price": 3, "price_of": "a tarot"},
        "card": {"text": "The worth of a playing card: bought in the shop (with Magic Trick or Illusion) or taken "
                         "from a Standard Pack.",
                 "items": [{"kind": "Playing card", "name": "Ace of Spades", "text": "a playing card added to the deck",
                            "card": {"rank": 14, "suit": "Spades", "enhancement": None, "edition": None, "seal": None,
                                     "bonus_chips": 0, "debuffed": False, "face_down": False, "label": "AS"}}],
                 "price": 1, "price_of": "a plain playing card"},
        "reroll": {"text": "The worth of a reroll before seeing what it brings. At 0 or below the bot never rerolls on "
                           "its own; the planner can still choose a reroll.", "price": 5, "price_of": "the first reroll"},
        "skip_safety": {"text": "The bot skips a Small or Big Blind for its tag only if a round of its typical best hand "
                                "(every hand of the round) beats the next blind's target by this much: skipping also skips "
                                "the shop before that blind. Higher is more careful."},
        "skip_shop": {"text": "What the shop after a blind is worth, counted against a tag along with the blind's reward, "
                              "a round of interest and a dollar for a hand left over: the price of skipping."},
    }
    from balatro.strategy import TAG_MONEY, TAG_PACK
    for t in data("tags.json")["tags"]:
        name = t["name"]
        extra = (f" It also brings about ${TAG_MONEY[name](type('R', (), {'money': 20, 'hands_played': 20, 'unused_discards': 5, 'skips': 0})())}"
                 f" (counted at the money weight)." if name in TAG_MONEY else f" Its {TAG_PACK[name]} is counted at that pack's weight and price."
                 if name in TAG_PACK else "")
        info[f"tag:{name}"] = {"text": f"{name}: {t['effect']} What it is worth, beyond money and packs, when the bot weighs "
                                       f"skipping a blind for it.{extra}"}
    for i, rarity in enumerate(("Common", "Uncommon", "Rare", "Legendary")):
        info[f"rarity:{i}"] = {"text": f"A bonus for every {rarity} joker, on top of what it adds to today's hands."
                               + (" Legendary jokers come only from The Soul." if rarity == "Legendary" else ""),
                               "items": joker_items(lambda j, r=rarity: j["rarity"] == r)}
    for kind in ("Buffoon", "Arcana", "Celestial", "Spectral", "Standard"):
        rows = [p for p in packs if p["kind"] == kind]
        info[f"pack:{kind}"] = {"text": f"The worth of opening a {kind} Pack, before seeing what's in it (Jumbo counts "
                                        f"1.3x, Mega 1.6x): {rows[0]['contents']}.",
                                "items": [{"kind": "Pack", "name": p["name"], "text": f"${p['cost']}: choose {p['cards_chosen']} "
                                           f"of {p['cards_shown']}"} for p in rows],
                                "sizes": [{"name": p["name"], "cost": p["cost"], "mult": {"Normal": 1.0, "Jumbo": 1.3, "Mega": 1.6}[p["size"]]}
                                          for p in rows]}
    for name, v in vouchers.items():
        req = f" Needs {v['requires']} first." if v.get("requires") else ""
        info[f"voucher:{name}"] = {"text": f"The worth of redeeming {name} (${v['cost']}).{req}", "price": v["cost"],
                                   "price_of": name,
                                   "items": [{"kind": "Voucher", "name": name, "text": v["effect"]}]
                                   + ([{"kind": "Voucher", "name": v["requires"], "text": vouchers[v["requires"]]["effect"]}]
                                      if v.get("requires") in vouchers else [])}
    from balatro.modifiers import RULES as MOD_RULES, TIMED
    by_name = {j["name"]: j for j in jokers}
    for rule, what in MOD_RULES.items():
        card = ([{"kind": "Joker", "name": rule, "text": by_name[rule]["effect"], "rarity": by_name[rule]["rarity"]}]
                if rule in by_name else [{"kind": "Playing card", "name": "Purple Seal",
                                          "text": "a card with a Purple Seal: discarded, it makes a Tarot",
                                          "card": {"rank": 7, "suit": "Spades", "seal": "Purple"}}])
        text = (f"{rule} acts on some hands only: {what}. The bot's measure of a build (its best hand over sample "
                f"hands, as a round starts) counts it on that share of hands, times this strength: 1 is that share, 0 "
                f"ignores it, 2 counts it on twice as many." if rule in TIMED else
                f"{rule} rewards this: {what}. Owning it, the bot adds what that is worth (measured on its build, or "
                f"the money at its money weight) to its plays, discards or purchases, times this strength: 1 is as "
                f"measured, 0 ignores it, 2 counts it double.")
        info[f"mod:{rule}"] = {"text": text, "items": card}
    from balatro.joker_classes import CLASSES, JOKER_CLASSES
    for c in CLASSES:
        facet, label = c.split(":")
        info[f"class:{c}"] = {"text": f"A bonus for jokers Jev labels \"{label.replace('_', ' ')}\" on {facet} "
                                      "(scripts/classify_jokers.py), times how sure Jev is of it. Listed: the jokers "
                                      "it gives that label at least half its weight.",
                              "items": joker_items(lambda j, c=c: JOKER_CLASSES.get(j["name"], {}).get(c, 0.0) >= 0.5)}
    missing = [g["name"] for g in GENES if g["name"] not in info]
    if missing:
        log.warning("no Evolution-tab explanation for %s", missing)
    return info


class PlanJob:
    """One seed plan at a time, run as its own process group (python3 -m balatro.planner), since the search
    forks a process per line it keeps. Progress and the result come back through files."""

    # Planner settings per effort: quick stops at 30 s; thorough searches every decision to the run's end.
    EFFORT = {"quick": ["--beam", "6", "--horizon", "3", "--time", "30"],
              "thorough": ["--beam", "12", "--horizon", "3", "--time", "0"]}

    def __init__(self):
        self.proc = None
        self.args: dict = {}
        self.started = 0.0
        self.finished = None
        self.out = ROOT / "runs" / "plan.json"
        self.prog = ROOT / "runs" / "plan_progress.json"

    def start(self, seed: str, deck: str, max_ante: int, effort: str = "quick") -> dict:
        if self.proc and self.proc.poll() is None:
            raise RuntimeError("a plan is already being made")
        if effort not in self.EFFORT:
            raise ValueError(f"unknown search effort {effort}")
        seed = game_seed_of(seed)
        if deck not in DECKS:
            raise ValueError(f"unknown deck {deck}")
        self.out.parent.mkdir(exist_ok=True)
        for f in (self.out, self.prog):
            f.unlink(missing_ok=True)
        self.args = {"seed": seed, "deck": deck, "max_ante": max_ante, "effort": effort}
        log_fh = open(ROOT / "logs" / "plan.log", "a")
        # A plan needs every core: running table builds and evolution runs (each a process group: the run and
        # its workers) pause while it runs.
        paused = {"pids": table_builds(running_only=True),
                  "groups": [read_json(EVOLVE_DIR / r["id"] / "status.json", {}).get("pid") for r in EVOLUTION.running()]}
        paused["groups"] = [g for g in paused["groups"] if pid_alive(g)]
        for pid in paused["pids"]:
            os.kill(pid, signal.SIGSTOP)
        for group in paused["groups"]:
            os.killpg(group, signal.SIGSTOP)
        if paused["pids"] or paused["groups"]:
            log_fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} paused while planning: table build {paused['pids']}, "
                         f"evolution runs {paused['groups']}\n")
            log_fh.flush()
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "balatro.planner", seed, "--deck", deck, "--max-ante", str(max_ante),
                 *self.EFFORT[effort], "--json", str(self.out), "--progress", str(self.prog)],
                cwd=str(ROOT), stdout=log_fh, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError:
            self._resume(paused, log_fh)
            raise
        self.started, self.finished = time.time(), None
        threading.Thread(target=self._wait, args=(self.proc, paused, log_fh), daemon=True).start()
        return self.status()

    def _wait(self, proc, paused, log_fh) -> None:
        proc.wait()
        try:                                       # whatever of the search outlived the planner (a stop)
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        self._resume(paused, log_fh)

    @staticmethod
    def _resume(paused, log_fh) -> None:
        for pid in paused["pids"]:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        for group in paused["groups"]:
            try:
                os.killpg(group, signal.SIGCONT)
            except (ProcessLookupError, PermissionError):
                pass
        if paused["pids"] or paused["groups"]:
            log_fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} resumed: table build {paused['pids']}, "
                         f"evolution runs {paused['groups']}\n")
        log_fh.close()

    def stop(self) -> dict:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
        return self.status()

    def status(self) -> dict:
        if not self.proc:
            return {"status": "idle"}
        code = self.proc.poll()
        if code is not None and self.finished is None:
            self.finished = time.time()
        st = {"status": "running" if code is None else "done" if code == 0 and self.out.exists() else
              "stopped" if code in (-15, 143) else f"failed (exit {code})", **self.args,
              "elapsed": (self.finished or time.time()) - self.started}
        try:
            st["progress"] = json.loads(self.prog.read_text())
        except (OSError, ValueError):
            pass
        return st

    def result(self) -> dict | None:
        try:
            return json.loads(self.out.read_text())
        except (OSError, ValueError):
            return None


PLAN = PlanJob()
# Example seeds whose openings the game must confirm (seedfinder/REPORT.md section 8).
TEST_SEEDS = ["4Z7TWAWF", "1PSV32J4", "8MTHQKH1", "XVXR3J1P"]

STATIC = Path(__file__).resolve().parent / "static"
LOG_PATH = ROOT / "logs" / "app.log"
BOTS = {"greedy": GreedyBot}
log = logging.getLogger("balatro-lab")


def manifest() -> dict:
    path = STATIC / "img" / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")      # pages and scripts revalidate, so edits show up
        super().end_headers()

    def log_message(self, fmt, *args):
        if not any(p in (args[0] if args else "") for p in ("/api/seed/status", "/api/plan/status")):  # polled
            log.info("%s %s", self.address_string(), fmt % args)

    def _play(self, path: str, q: dict, body: dict):
        """The Play tab (play.html): new games, their state, actions, rewinds and branches (balatro/interactive.py)."""
        what = path.removeprefix("/api/play/")
        num = lambda k: int(q[k][0]) if q.get(k) and q[k][0] != "" else None   # noqa: E731
        try:
            if what == "games":
                return self._send_json({"games": PLAY.listing()})
            if what == "state":                        # ?cursor=<steps taken> to look back along the line; ?from=<frames held>
                return self._send_json(PLAY.state((q.get("id") or [""])[0], (q.get("hint") or ["1"])[0] != "0",
                                                  frames_from=num("from"), cursor=num("cursor")))
            if what == "hint":                         # the bot's view, once a worker has it (?id, ?cursor)
                return self._send_json(PLAY.hint((q.get("id") or [""])[0], num("cursor")))
            if what == "new":
                deck, stake = body.get("deck") or "Red Deck", body.get("stake") or "White Stake"
                if deck not in DECKS or stake not in STAKES:
                    return self._send_json({"error": f"unknown deck or stake: {deck}, {stake}"}, 400)
                return self._send_json(PLAY.new(body.get("seed"), deck, stake, int(body.get("max_ante") or 8)))
            if what == "act":
                return self._send_json(PLAY.act(str(body.get("id", "")), body.get("action"), body.get("cursor")))
            if what == "rewind":
                return self._send_json(PLAY.rewind(str(body.get("id", "")), body.get("step")))
            if what == "branch":
                return self._send_json(PLAY.switch(str(body.get("id", "")), body.get("branch")))
            if what == "endless":
                return self._send_json(PLAY.endless(str(body.get("id", ""))))
            if what == "preview":
                return self._send_json(PLAY.preview(str(body.get("id", "")), body.get("cards") or [], body.get("cursor")))
        except (PlayError, TypeError, ValueError) as exc:
            return self._send_json({"error": str(exc)}, 400)
        except ReplayError as exc:
            return self._send_json({"error": f"this game no longer replays: {exc}"}, 409)
        return self._send_json({"error": "unknown endpoint"}, 404)

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/meta":
            return self._send_json({"jokers": sorted(CATALOG), "bots": sorted(BOTS), "models": model_list(),
                                    "decks": sorted(DECKS), "stakes": STAKES,
                                    "bosses": {b["name"]: b.get("short", b["effect"]) for b in entries("boss")}, "art": manifest(),
                                    "texts": viewer_texts()})
        if url.path == "/api/run":
            q = parse_qs(url.query)
            try:
                seed = game_seed_of((q.get("seed") or [""])[0] or "".join(random.choice(SEED_CHARS) for _ in range(8)))
                max_ante = max(1, min(16, int((q.get("max_ante") or [8])[0])))
                names = [n for n in (q.get("jokers") or [""])[0].split(",") if n]
                model = (q.get("model") or q.get("bot") or ["greedy"])[0]   # any of balatro.models.listing()
                agent = make_model(model)
                deck = (q.get("deck") or [""])[0] or None
                stake = (q.get("stake") or ["White Stake"])[0]
            except (ValueError, KeyError) as exc:
                return self._send_json({"error": f"bad request: {exc}"}, 400)
            unknown = [n for n in names if n not in CATALOG]
            if unknown or len(names) > 5:
                return self._send_json({"error": f"up to 5 jokers from the catalog; unknown: {unknown}"}, 400)
            if (deck is not None and deck not in DECKS) or stake not in STAKES:
                return self._send_json({"error": f"unknown deck or stake: {deck}, {stake}"}, 400)
            run = Run(agent, game_seed=seed, max_ante=max_ante, record=True, deck=deck, stake=stake)
            run.jokers = [CATALOG[n]() for n in names]
            try:
                result = run.play()
            except RuntimeError as exc:                  # an outside player that can't answer (balatro/jev.py: JevError)
                if type(exc).__name__ != "JevError":
                    raise
                return self._send_json({"error": str(exc)}, 502)
            return self._send_json({"seed": seed, "jokers": names, "model": model, "result": {
                "won": result.won, "ante": result.ante, "blinds_beaten": result.blinds_beaten,
                "progress": result.progress, "best_hand": result.best_hand, "money": result.money},
                "frames": result.frames})
        if url.path == "/api/seed/meta":
            o = seed_opening
            return self._send_json({
                "bosses": o.BOSSES_ANTE1, "vouchers": o.BASE_VOUCHERS,
                "tags": [t for t in o.TAGS if t not in o.TAGS_MIN_ANTE_2],
                "shop": sorted(set(o.COMMON_JOKERS + o.UNCOMMON_JOKERS + o.RARE_JOKERS + o.TAROTS + o.PLANETS)),
                "test_seeds": TEST_SEEDS, "art": manifest()})
        if url.path == "/api/seed/opening":
            seed = (parse_qs(url.query).get("seed") or [""])[0].strip().upper()
            try:
                return self._send_json(seed_opening.opening(seed))
            except Exception as exc:  # noqa: BLE001
                return self._send_json({"error": f"bad seed {seed!r}: {exc}"}, 400)
        if url.path == "/api/seed/projection":
            return self._send_json(*seed_projection(url.query))
        if url.path == "/api/seed/status":
            return self._send_json(SEARCH.status())
        if url.path == "/api/seed/table":
            return self._send_json(table_info())
        if url.path == "/api/plan/status":
            return self._send_json(PLAN.status())
        if url.path in ("/api/plan/result", "/api/plan/frames"):
            res = PLAN.result()
            if res is None:
                return self._send_json({"error": "no plan yet"}, 404)
            if url.path.endswith("frames"):
                return self._send_json({"frames": res["frames"], "deck": res["deck"], "seed": res["seed"]})
            return self._send_json({k: v for k, v in res.items() if k != "frames"})
        if url.path == "/api/evolve/runs":
            return self._send_json({"runs": EVOLUTION.runs(), "active": EVOLUTION.active()})
        if url.path == "/api/evolve/genes":
            return self._send_json(gene_info())
        if url.path == "/api/evolve/items":
            return self._send_json(item_texts())
        if url.path == "/api/evolve/synergy":
            return self._send_json(synergy())
        if url.path == "/api/evolve/sweep":
            return self._send_json(sweep())
        m = re.match(r"^/api/evolve/runs/([\w-]+)/timing$", url.path)
        if m and RUN_ID.match(m.group(1)):
            return self._send_json(network_timing(m.group(1)))
        m = re.match(r"^/api/evolve/runs/([\w-]+)$", url.path)
        if m and RUN_ID.match(m.group(1)):
            since = (parse_qs(url.query).get("since") or ["0"])[0]
            return self._send_json(EVOLUTION.detail(m.group(1), int(since) if since.isdigit() else 0))
        if url.path.startswith("/api/play/"):
            return self._play(url.path, parse_qs(url.query), {})
        if url.path.startswith("/api/"):
            return self._send_json({"error": "unknown endpoint"}, 404)
        return super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if url.path == "/api/seed/search":
            try:
                return self._send_json(SEARCH.start(body))
            except (ValueError, RuntimeError) as exc:
                return self._send_json({"error": str(exc)}, 400)
        if url.path == "/api/seed/stop":
            return self._send_json(SEARCH.stop())
        if url.path == "/api/plan":
            try:
                return self._send_json(PLAN.start(str(body.get("seed", "")), body.get("deck") or "Red Deck",
                                                  max(1, min(32, int(body.get("max_ante") or 12))),
                                                  str(body.get("effort") or "quick")))
            except (ValueError, RuntimeError) as exc:
                return self._send_json({"error": str(exc)}, 400)
        if url.path == "/api/plan/stop":
            return self._send_json(PLAN.stop())
        if url.path == "/api/evolve/runs":
            try:
                return self._send_json(EVOLUTION.start(body))
            except (ValueError, RuntimeError) as exc:
                return self._send_json({"error": str(exc)}, 409)
        m = re.match(r"^/api/evolve/runs/([\w-]+)/(stop|use)$", url.path)
        if m and RUN_ID.match(m.group(1)):
            try:
                return self._send_json(EVOLUTION.stop(m.group(1)) if m.group(2) == "stop" else EVOLUTION.use(m.group(1)))
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 409)
        if url.path.startswith("/api/play/"):
            return self._play(url.path, {}, body)
        return self._send_json({"error": "unknown endpoint"}, 404)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Balatro Lab web app.")
    parser.add_argument("--port", type=int, default=8643)
    args = parser.parse_args()
    LOG_PATH.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s",
                        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
    busy = subprocess.run(["pgrep", "-f", "balatro.planner|evolve_valuebot|evolve_neural|bench_planner|sweep_mods"],
                          capture_output=True, text=True).stdout
    if not busy.strip():                           # left paused if an earlier server died mid-plan
        for pid in table_builds():
            os.kill(pid, signal.SIGCONT)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    log.info("Balatro Lab running at http://127.0.0.1:%d (log: %s)", args.port, LOG_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
