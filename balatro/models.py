"""The players a run can be watched with: the baseline bots, the value bot with its hand-set weights, the
weights the planner plays with, and every evolved champion in runs/evolve (weights, or weights with a
network). `listing()` says what there is; `make(id)` builds a fresh agent for one run."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .bots import GreedyBot
from .modifiers import RULES
from .strategy import EVOLVED, SmartBot, ValueBot, Weights, weights_of

EVOLVE_DIR = EVOLVED.parent
RUN_ID = re.compile(r"^\d{8}-\d{6}$")
# The behaviour modifiers the value bot had before the 22 added on 26 Oct 2026, for comparing with and without
FIRST_RULES = ("Space Joker", "Ride the Bus", "Runner", "Square Joker", "Spare Trousers", "Obelisk", "To Do List",
               "Green Joker", "Ramen", "Castle", "Mail-In Rebate", "Hit the Road", "Yorick", "Trading Card",
               "Faceless Joker", "Burnt Joker", "Delayed Gratification", "Purple Seal", "Hologram", "Satellite")


def _hand_set(only=None, bot: dict | None = None, **weights):
    """The value bot with the hand-set weights (not the planner's) and no network; `only`: the behaviour
    modifiers it plays to (the others at strength 0), all of them by default; `weights`: weights set otherwise;
    `bot`: the bot's own settings set otherwise (spare_money...)."""
    def make():
        agent = ValueBot()
        agent.w, agent.net = Weights(), None
        for r in RULES:
            if only is not None and r not in only:
                agent.w.mods[r] = 0.0
        for k, v in weights.items():
            setattr(agent.w, k, v)
        for k, v in (bot or {}).items():
            setattr(agent, k, v)
        return agent
    return make


def _jev(shop_only: bool, ties: bool = False):
    """TypeSafe's Jev choosing among the value bot's moves (balatro/jev.py; needs TYPESAFE_API_KEY); with `ties`,
    only between its near-equal shop and pack options (the margin from JEV_TIES, in power; 0.1 by default)."""
    def make():
        from .jev import JevBot
        return JevBot(shop_only, float(os.environ.get("JEV_TIES", 0.1)) if ties else None)
    return make


# "Value bot, latest": what is on in the plain value bot, plus what is written but not shown worse (the run viewer's
# default and the Play tab's advisor, interactive.opinion). INCOME_STRENGTH, DISCARD_INCOME and DISCOUNT_FIRST were the
# hint's own (the user's asks, 28 Oct; INCOME_STRENGTH 0.5 and DISCOUNT_FIRST measured level).
LATEST_SWITCHES = {"LAST_HAND_ODDS": True, "GROWTH_HORIZON": 12, "ODDS_CALIBRATED": True, "EDITION_TAGS_MEASURED": True,
                   "MILK_LIKELY": True, "BEHIND_DIG": True, "ODDS_BY_ANTE": True, "NEGATIVE_LASTS": True,
                   "INCOME_STRENGTH": 0.5, "DISCARD_INCOME": True, "DISCOUNT_FIRST": True,
                   "ROLLOUT_ODDS": True, "SURVIVAL": True, "SCALING": True, "SKIP_SHOP_MEASURED": True}

BASIC = {
    "greedy": ("Greedy bot", "plays the highest-scoring hand it sees and buys what it can afford", GreedyBot),
    "smart": ("Smart bot", "the greedy bot, plus discarding towards better hands and using its consumables", SmartBot),
    "value": (f"Value bot (best so far), hand-set weights, all {len(RULES)} rules",
              "weighs every purchase by how much stronger the build gets and plays to its jokers with every behaviour "
              "modifier; holds its interest reserve and spends freely beyond it. Honest since 27 Oct afternoon: face-down "
              "cards are unknown to it and it tries random effects on streams of its own (it had seen both, worth 4.4 "
              "points); cards that make cards (The Fool, Emperor) and Tarots kept for a later hand are worth what they "
              "do; it holds only what is worth copying for Perkeo, and counts Double Tags held when it skips. Since 28 "
              "Oct: Tarots kept counted at twice their measured worth, jokers that pay as hands are played (Reserved "
              "Parking...) and Mime's doubling of held Gold cards counted, money spent in the run's last shop, and its "
              "build-strength cache no longer stale (Blue Joker, growing jokers), and in the shop its build measured "
              "with the draw pile a round starts with; with its consumable slots full it sells the weakest for a "
              "clearly better one; money and interest worth a quarter more than their tuned weights (it spent too "
              "freely); a paid discard (Mail-In Rebate's rank) made when the round is won anyway; Ride the Bus and Obelisk "
              "valued from what they have built. Since 29 Oct: Lucky cards and Bloodstone counted at their average in a "
              "hand's estimate, a win still counted only when sure, and a Tarot not used on the hand held when that "
              "costs the round; its sample hands paired across hand sizes (Paint Brush and Palette weighed on the "
              "same hands); lasting things (income, growth, Tarots kept) counted over the rounds the run is likely to "
              "last, not to its last boss (in runs to 16 it had beaten ante 8 13 points less often). Since 30 Oct: a free "
              "joker from a pack worth at least its resale and sold before the next round's first hand if it hurts the "
              "build, Constellation and Hologram counting the Planets and cards the shops offer (owning one changes what "
              "it buys), a Celestial pack counting Constellation's growth, a joker's lost hand counted (Troubadour), "
              "and money a joker earns far past the interest reserve priced as spending there is. Beat ante 8 in "
              "about 63% and 68% of "
              "480 fresh seeds each of two sets (Red Deck, White Stake)", _hand_set()),
    "value-latest": ("Value bot, latest: survival and ante-8 odds (being measured)",
                     "the value bot with what is written but not yet shown worse switched on, the run viewer's default "
                     "and the Play tab's advisor (30 Oct): the round's last hand played for its odds of reaching the "
                     "target rather than its average (not measured yet), growing jokers counted over 12 rounds rather "
                     "than 6 (+4.0 points on one set, level on the other), a blind's odds read by what the bot's play "
                     "beats (a bare deck's 2% against ante 1's boss was half), a skip paying for its risk, Foil, "
                     "Holographic and Polychrome Tags worth their edition, what Cloud 9, Golden Joker and the other "
                     "payers bring counted at half, what discard payers bring counted, and a discount voucher bought "
                     "before what it makes cheaper (the user's asks for the hint, level where measured), and the "
                     "structural steps (being measured): a blind's odds read by playing it out on copies of the run, and "
                     "a shop's leading options worth what they add to the odds of beating the next blind and ante 8's "
                     "boss (the build projected there, with its money and free slots). Everything "
                     "measured in, and the level correctness fixes turned on 30 Oct (vouchers by what they bring, the "
                     "behind-the-boss gamble, milking a won round, The Mouth's odds, Riff-Raff...), is in the plain value "
                     "bot too. Not the build plan",
                     _hand_set(bot=LATEST_SWITCHES)),
    "value-plan": ("Value bot with the build plan (new, being measured)",
                   "the value bot that builds toward a strategy (29 Oct, docs/superpowers/specs): it picks the one its "
                   "steering adds most to (held Steel cards and Kings with Baron, Mime, Red Seals; or a Flush in one suit, "
                   "with that suit's Tarot on off-suit cards and The Hanged Man cutting them), with DNA as a tool copying "
                   "the strategy's key card (a Steel Red Seal King, the best card of the suit); values buys, sells, packs, "
                   "rerolls and Tarot targets by what they add to it beyond today (missing pieces at the shop's odds, "
                   "never the seed's future), keeps held cards out of discards and pays to play them. Step 1 (held and "
                   "DNA) level in runs to 8; step 2 being measured tonight; about twice as slow", _hand_set(bot={"PLAN": True})),
    "value-plan-x3": ("Value bot with the build plan, pulled three times harder",
                      "the same with the plan's worth tripled (PLAN_WEIGHT 3): it reaches for engine pieces sooner. Not "
                      "measured; for trying out", _hand_set(bot={"PLAN": True, "PLAN_WEIGHT": 3.0})),
    "value-27oct": ("Value bot, as on 27 Oct evening",
                    "the value bot before the 28 Oct changes (Tarots kept at their measured worth, nothing for jokers "
                    "that pay as hands are played or for Mime's Gold cards, money held in the last shop, the stale "
                    "cache, money at its tuned weights): beat ante 8 in 49.2% and 50.4% of the same seeds (it now "
                    "counts Lucky cards at their average too, a level change of 29 Oct)",
                    _hand_set(bot={"KEEP_TRUST": 1.0, "HAND_INCOME": False, "MIME_HELD": False, "END_MONEY": False,
                                   "POWER_EXACT": False, "POWER_PILE": False, "CONSUMABLE_SWAP": False,
                                   "MONEY_SCALE": 1.0, "PAID_WON": False, "GROWN_FROM_NOW": False,
                                   "USE_GUARD": False})),
    "value-before-money": ("Value bot, before the money settings",
                           "the same before the morning of 27 Oct: $1 beyond the interest reserve at a quarter of $1 "
                           "within it, interest at 0.05, no weight on a reroll: beat ante 8 in 44.2% and 45.0% of the "
                           "same seeds (measured while bots could still see face-down cards and random outcomes: a few "
                           "points high)", _hand_set(interest=0.05, reroll=0.0, bot={"spare_money": 0.25})),
    "value-flat-bonuses": ("Value bot, with the old flat money/rules bonuses",
                           "the value bot with its former fixed bonus for jokers that pay (+0.3) or change the rules "
                           "(+0.25), which kept Credit Card, Egg and Delayed Gratification over scoring jokers: beat "
                           "ante 8 in 21.0% of the same seeds", _hand_set(pays=0.3, rules=0.25)),
    "value-first-rules": (f"Value bot, hand-set weights, first {len(FIRST_RULES)} rules",
                          "the same without the 22 behaviour modifiers added on 26 Oct (Supernova, Business Card, Rough "
                          "Gem, Acrobat...): beat ante 8 in 12.1% of the same seeds", _hand_set(FIRST_RULES)),
    "jev": ("Jev (TypeSafe AI) plays", "TypeSafe's Jev model picks every play, discard, purchase and pack card from the "
            "moves the value bot weighs, reading the whole position; answers are cached, so a replayed seed is free. "
            "About a cent and a minute a run", _jev(False)),
    "jev-shop": ("Jev shops, value bot plays", "Jev picks only purchases and pack cards; the value bot plays the rounds",
                 _jev(True)),
    "jev-ties": ("Jev breaks the value bot's near-ties", "the value bot plays; in the shop and packs, Jev chooses only "
                 "between the options the value bot rates about equal (within 0.1 power, hands scoring about 10%)",
                 _jev(True, ties=True)),
}
NEEDS_NETWORK = {"jev", "jev-shop", "jev-ties"}               # models that call an outside service as they play


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def _saved(model_id: str) -> tuple[Path, dict] | None:
    """The file behind an evolved model id: "active" (the planner's), "saved:<name>" or "evolve:<run id>"."""
    if model_id == "active":
        path = EVOLVED
    elif model_id.startswith("saved:") and re.fullmatch(r"[\w.-]+", model_id[6:]) and model_id != "saved:planner":
        path = EVOLVE_DIR / f"{model_id[6:]}.json"
    elif model_id.startswith("evolve:") and RUN_ID.match(model_id[7:]):
        path = EVOLVE_DIR / model_id[7:] / "champion.json"
    else:
        return None
    saved = _read(path)
    return (path, saved) if saved and saved.get("genome") else None


def _detail(saved: dict) -> str:
    bench = saved.get("benchmark") or saved.get("fitness")
    gen = saved.get("gen") or saved.get("generation")
    wins = saved.get("fitness_kind") == "wins"               # evolved for beating ante 8: its benchmark is a percentage
    parts = ["weights and a network" if saved.get("network") else "weights", gen and f"generation {gen}",
             bench is not None and (f"beat ante 8 in {bench:.1f}% of its benchmark seeds" if wins else f"benchmark {bench:.2f}")]
    return ", ".join(p for p in parts if p)


def listing() -> list[dict]:
    """[{id, name, detail, benchmark}], basic bots first, then the planner's weights, saved champions and
    each evolution run's champion (newest first; a run still going says so, its champion can still change)."""
    out = [{"id": k, "name": name, "detail": detail, "benchmark": None} for k, (name, detail, _) in BASIC.items()]
    active = _read(EVOLVED)
    if active and active.get("genome"):
        out.append({"id": "active", "name": "Value bot, the planner's weights",
                    "detail": f"from {active.get('source', 'a saved run')}: {_detail(active)}", "benchmark": active.get("benchmark")})
    if EVOLVE_DIR.exists():
        for path in sorted(EVOLVE_DIR.glob("*.json")):
            saved = _read(path)
            if path != EVOLVED and saved and saved.get("genome"):
                out.append({"id": f"saved:{path.stem}", "name": f"Value bot, {path.stem}", "detail": _detail(saved),
                            "benchmark": saved.get("benchmark") or saved.get("fitness")})
        for d in sorted((p for p in EVOLVE_DIR.iterdir() if p.is_dir() and RUN_ID.match(p.name)), reverse=True):
            saved = _read(d / "champion.json")
            if not (saved and saved.get("genome")):
                continue
            status = _read(d / "status.json") or {}
            going = status.get("state") == "running" and _alive(status.get("pid"))
            out.append({"id": f"evolve:{d.name}", "name": f"Evolved {'network' if saved.get('network') else 'weights'} {d.name}",
                        "detail": _detail(saved) + (" (still evolving: the champion so far)" if going else ""),
                        "benchmark": saved.get("benchmark")})
    return out


def spec(model_id: str) -> dict:
    """What `model_id` is right now, read once: {"id"} for a basic bot, plus "genome" and "network" for an
    evolved one (a champion still evolving can change later; a spec doesn't). KeyError if there is no such model."""
    if model_id in BASIC:
        return {"id": model_id}
    found = _saved(model_id)
    if not found:
        raise KeyError(f"unknown model {model_id!r}")
    _, saved = found
    return {"id": model_id, "genome": saved["genome"], "network": saved.get("network")}


def build(s: dict):
    """A fresh agent from a spec."""
    if s["id"] in BASIC:
        return BASIC[s["id"]][2]()
    bot = ValueBot()
    bot.w = weights_of(s["genome"])               # this bot's own weights and network: the class keeps the planner's
    if s.get("network"):
        from .neural import Network
        bot.net = Network(s["network"]["params"])
    else:
        bot.net = None
    return bot


def make(model_id: str):
    """A fresh agent for `model_id`; KeyError if there is no such model."""
    return build(spec(model_id))


def name_of(model_id: str) -> str:
    return next((m["name"] for m in listing() if m["id"] == model_id), model_id)
