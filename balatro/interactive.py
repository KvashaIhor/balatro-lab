"""Games a person plays in the Lab's Play tab, recorded for analysis.

A game is a seed, deck and stake plus the actions taken so far. The run is replayed from its start by a scripted
player (Scripted) that answers each decision from the recorded actions and stops (NeedInput) at the first one it has
no action for: that is where the person is. Every replay of the same actions is the same run (a game seed fixes the
cards; the engine's other random streams are seeded too). Rewinding to a step starts a new branch with the actions
before it, so every line tried is kept; a game switches between its branches.

At each decision the value bot (hand-set weights) says what it would do, on a copy of the run: the Play tab's hint,
and, kept with each action, the breakdown of where the person and the bot part ways. Games are saved to
runs/played/<id>.json, with a journal per branch in the format scripts/analyze_losses.py writes (<id>.txt).
"""
from __future__ import annotations

import concurrent.futures
import copy
import json
import multiprocessing
import random
import threading
import time
from pathlib import Path

from .agent import Agent
from .bots import estimate, ranked_plays
from .cards import Card
from .hands import evaluate
from .items import Consumable, entries, info
from .jokers import Joker
from .run import FREE_ACTIONS, Run, hand_key
from .shop import cost_of
from .strategy import action_key

DIR = Path(__file__).resolve().parent.parent / "runs" / "played"
SEED_CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
FREE = ("use", "sell_joker", "sell_consumable", "order_jokers", "order_hand", "sort_hand")
ASIDE = ("order_hand", "sort_hand")       # arranging the hand: not a choice to hold against the bot's
REORDER = ("order_jokers", "order_hand", "sort_hand")   # left out of the bot's plan as the hint words it
PLAN_STEPS = 4                            # free steps the hint follows the bot through, to the action they lead to
# The Play tab's advisor is "Value bot, latest" (models.LATEST_SWITCHES, the user's ask 30 Oct: the same bot as the run
# viewer's default). Its hint-only switches moved there; their history:
# Switches on for the hint only, ahead of their measurement (asked 28 Oct, C5X6MXUN): what Cloud 9, Golden Joker,
# Rocket, To the Moon and Egg pay, and what Mail-In Rebate and the other discard payers bring, counted; the hint bot
# sold Cloud 9 ($4 a round) for Wily Joker. The measured bot (run viewer) is unchanged. Measured 28 Oct 22:52: at 1.0
# the bot lost 3.3 points (progress -0.62 +- 0.15), at 0.5 level: 0.5 here. GROWN_FROM_NOW, a plain fix (the hint sold
# a Ride the Bus at +24 for a Runner at 0), on here while it is measured.
# DISCOUNT_FIRST the same (the user's point: Liquidation before the packs it makes cheaper).
# DISCOUNT_FIRST measured level (29 Oct), kept here: for a person it is pure order. Lucky cards and Bloodstone by
# their expectation (the hint passed over a pair with a Lucky card) and the Tarot guard (the hint used Strength on a
# straight's 9s) were on here first; both measured level and are on for every bot since 29 Oct.
ADVISOR = "value-latest"
RANKS = {11: "J", 12: "Q", 13: "K", 14: "A"}
BOSS_EFFECT = {b["name"]: b["effect"] for b in entries("boss")}


class NeedInput(Exception):
    """The replay reached a decision with no recorded action: `kind` (select, boss, round, shop, pack) and the
    arguments the run asked it with (the blind and tag, the boss, the shop, the open pack)."""

    def __init__(self, kind: str, args: tuple):
        super().__init__(kind)
        self.kind, self.args = kind, args


class ReplayError(RuntimeError):
    """The recorded actions don't fit the run (a decision of another kind came up): the engine changed."""


class PlayError(ValueError):
    """An action the run can't take now, with the reason for the person."""


def to_action(a) -> tuple:
    return tuple(a)


class Scripted(Agent):
    """Answers each decision from `steps` ({"kind", "action"}); NeedInput at the first one without. `watch(i, kind,
    run, args, step)` sees every answered decision before its action is taken (the journal)."""

    def __init__(self, steps: list, watch=None):
        self.steps, self.i, self.watch = steps, 0, watch
        self.marks: list[int] = []        # frames recorded before each answered decision

    def _next(self, kind: str, run, *args):
        if self.i >= len(self.steps):
            raise NeedInput(kind, args)
        step = self.steps[self.i]
        if step["kind"] != kind:
            raise ReplayError(f"step {self.i}: recorded a {step['kind']} decision, but the run asks for a {kind} one")
        if self.watch:
            self.watch(self.i, kind, run, args, step)
        self.marks.append(len(run.frames or []))
        self.i += 1
        return step["action"]

    def skip_blind(self, run, blind, tag) -> bool:
        return self._next("select", run, blind, tag)[0] == "skip"

    def reroll_boss(self, run, boss) -> bool:
        return self._next("boss", run, boss)[0] == "reroll"

    def round_action(self, run) -> tuple:
        return to_action(self._next("round", run))

    def shop_action(self, run, shop) -> tuple:
        return to_action(self._next("shop", run, shop))

    def pack_action(self, run, pack) -> tuple:
        return to_action(self._next("pack", run, pack))


class Position:
    """Where a replay stopped: the run as it stands, the decision it waits for (None once the run is over) and the
    run's result then."""

    def __init__(self, run: Run, need: NeedInput | None, result, agent: Scripted):
        self.run, self.need, self.result, self.agent = run, need, result, agent
        self.frames_at = len(run.frames or [])

    @property
    def kind(self) -> str | None:
        return self.need.kind if self.need else None


def replay(spec: dict, steps: list, watch=None) -> Position:
    """Play the game's recorded actions from the start, up to the first decision with none."""
    agent = Scripted(steps, watch)
    run = Run(agent, game_seed=spec["seed"], deck=spec["deck"], stake=spec["stake"], max_ante=spec["max_ante"],
              record=True)
    run.hand_sort = spec.get("hand_sort")     # games saved before sort modes keep the dealt order their steps assume
    run.draw_after_win = spec.get("draw_after_win", True)   # and those saved before the round's end drew no card
    try:
        result = run.play()
    except NeedInput as need:
        return Position(run, need, None, agent)
    if agent.i < len(steps):
        raise ReplayError(f"the run ended after {agent.i} of {len(steps)} recorded steps")
    return Position(run, None, result, agent)


# ---- words for cards and actions ---------------------------------------------------------------------------

SUIT_SIGNS = {"Spades": "♠", "Hearts": "♥", "Clubs": "♣", "Diamonds": "♦"}   # (the user: easier to read than S H C D)


def card_text(c: Card) -> str:
    if c.face_down:                                  # what it is isn't shown (the log and hints named it: "K♦[down]")
        return "?(down)" + ("(debuffed)" if c.debuffed else "")
    rank = RANKS.get(c.rank, str(c.rank))
    extra = "".join(f"[{x}]" for x in (c.enhancement, c.edition, c.seal and c.seal + " Seal") if x)
    suit = SUIT_SIGNS.get(c.suit, c.suit[:1])
    return f"{rank}{suit}{extra}" + ("(down)" if c.face_down else "") + ("(debuffed)" if c.debuffed else "")


def joker_text(j) -> str:
    return j.name + (f" [{j.edition}]" if j.edition else "") + "".join(
        f" [{s}]" for s in ("eternal", "perishable", "rental") if getattr(j, s, False))


def item_text(item) -> str:
    if isinstance(item, Joker):
        return joker_text(item)
    if isinstance(item, Card):
        return card_text(item)
    return getattr(item, "name", None) or str(item)


def _cards(run, idx) -> str:
    return " ".join(card_text(run.hand[i]) for i in idx if 0 <= i < len(run.hand))


def describe(run, kind: str, args: tuple, a) -> str:
    """An action in words, as the run stands before it."""
    a = list(a)
    name = a[0] if a else ""
    if kind == "select":
        blind, tag = args
        return f"Skip the {blind.name} for the {tag.name}" if name == "skip" and tag else f"Play the {blind.name}"
    if kind == "boss":
        return "Reroll the boss ($10)" if name == "reroll" else f"Keep {args[0].name}"
    if name == "play":
        return f"Play {_cards(run, a[1])}"
    if name == "discard":
        return f"Discard {_cards(run, a[1])}"
    if name == "use":
        c = run.consumables[a[1]] if 0 <= a[1] < len(run.consumables) else None
        on = _cards(run, a[2] if len(a) > 2 else [])
        return f"Use {c.name if c else '?'}" + (f" on {on}" if on else "")
    if name == "sell_joker":
        j = run.jokers[a[1]] if 0 <= a[1] < len(run.jokers) else None
        return f"Sell {j.name} (${run.sell_value(j)})" if j else "Sell a joker"
    if name == "sell_consumable":
        c = run.consumables[a[1]] if 0 <= a[1] < len(run.consumables) else None
        return f"Sell {c.name} (${run.sell_value(c)})" if c else "Sell a consumable"
    if name == "order_jokers":
        return "Order jokers: " + ", ".join(run.jokers[i].name for i in a[1] if 0 <= i < len(run.jokers))
    if name == "order_hand":
        return "Rearrange the hand"
    if name == "sort_hand":
        return f"Sort the hand by {a[1]}"
    if kind == "shop":
        shop = args[0]
        if name in ("buy", "buy_use"):
            where, i = (a[1], a[2]) if name == "buy" else ("card", a[1])
            offers = {"card": shop.cards, "pack": shop.packs, "voucher": shop.vouchers}.get(where, [])
            if not 0 <= i < len(offers):
                return "Buy ?"
            o = offers[i]
            verb = "Buy and use" if name == "buy_use" else "Buy"
            return f"{verb} {item_text(o.item) if where == 'card' else o.name} (${cost_of(run, o)})"
        if name == "reroll":
            return f"Reroll (${shop.reroll_cost})"
        return "Leave the shop"
    if kind == "pack":
        pack = args[0]
        if name == "pick" and 0 <= a[1] < len(pack.cards):
            on = _cards(run, a[2] if len(a) > 2 else [])
            return f"Take {item_text(pack.cards[a[1]])}" + (f" on {on}" if on else "")
        return f"Skip the {pack.pack.name}"
    return str(a)


def plain(a) -> list:
    """An action as JSON: a list, with card positions as a list."""
    return [list(x) if isinstance(x, (list, tuple)) else x for x in a]


# ---- what the person sees ----------------------------------------------------------------------------------

def frame_now(run) -> dict:
    """The run as the viewer's frames show it (Run.frame), without recording it."""
    saved = run.frames
    run.frames = []
    try:
        run.frame("now")
        f = run.frames[0]
    finally:
        run.frames = saved
    f["deck_cards"] = run.deck_cards()
    return f


def view(pos: Position) -> dict:
    """The state at the decision, for the Play tab: a viewer frame (as the run records them, so the run viewer's board
    draws it unchanged) plus, under "controls", what this decision offers: what each consumable sells for and takes,
    and which offers and pack cards can be had."""
    run, need = pos.run, pos.need
    f = frame_now(run)
    f["max_ante"] = run.max_ante
    f["debt_limit"] = run.debt_limit
    f["spend"] = run.money - run.debt_limit
    f["in_round"] = run.in_round
    f["hand_sort"] = run.hand_sort
    controls: dict = {"consumables": [{"sell": run.sell_value(c), "min_targets": getattr(c, "min_targets", 0),
                                       "max_targets": getattr(c, "max_targets", 0), "usable": c.can_use(run, [])}
                                      for c in run.consumables]}
    f["controls"] = controls
    if need is None:
        return f
    k = need.kind
    if k == "select":
        blind, tag = need.args
        f["select"] = {"kind": blind.kind, "tag": tag.name if tag else None,
                       "tags": [t.name if t else None for t in run.ante_tags]}
    elif k == "boss":
        f["boss"] = {"name": need.args[0].name, "effect": BOSS_EFFECT.get(need.args[0].name, "")}
    elif k == "shop":
        shop = need.args[0]
        f["shop"] = shop.to_dict()
        offers = {}
        for where, items in (("cards", shop.cards), ("packs", shop.packs), ("vouchers", shop.vouchers)):
            offers[where] = []
            for o in items:
                item = o.item
                c = {"affordable": run.money - cost_of(run, o) >= run.debt_limit,
                     "room": (run.joker_room(item) if isinstance(item, Joker)
                              else run.consumable_room(item) if isinstance(item, Consumable) else True)}
                if isinstance(item, Consumable):
                    c.update(consumable=True, usable=item.can_use(run, []))
                offers[where].append(c)
        controls["offers"] = offers
    elif k == "pack":
        state = need.args[0]
        f["pack"] = state.to_dict(run)
        cards = []
        for x in state.cards:
            if isinstance(x, Consumable):
                cards.append({"min_targets": getattr(x, "min_targets", 0), "max_targets": getattr(x, "max_targets", 0),
                              "usable": x.can_use(run, [])})
            elif isinstance(x, Joker):
                cards.append({"joker": True, "room": run.joker_room(x)})
            else:
                cards.append({"card": True})
        controls["pack"] = cards
    return f


def events(pos: Position, since: int) -> list[str]:
    """What happened between the last decision and this one, in words (from the frames recorded meanwhile)."""
    out = []
    for f in (pos.run.frames or [])[since:pos.frames_at]:
        k = f["kind"]
        if k == "play":
            out.append(f"{f['hand_name']} (level {f['level']}): {f['chips']:,} x {f['mult']:,} = {f['total']:,}"
                       + (f", ${f['earned']}" if f.get("earned") else ""))
        elif k == "discard":
            out.append("Discarded " + " ".join(c["label"] for c in f.get("discarded", [])))
        elif k == "blind":
            b = f["blind"]
            out.append(f"{b['name']}: score at least {b['chips']:,}")
        elif k == "cash_out":
            out.append(f"Cashed out ${f['earned']}" + (" (" + ", ".join(f"{n} ${v}" for n, v in f.get("parts", [])) + ")" if f.get("parts") else ""))
        elif k in ("shop", "pack") and f.get("did"):
            out.append(f["did"])
        elif k == "use":
            out.append(f"Used {f['used']}")
        elif k == "sell":
            out.append(f"Sold {f['item']['name']} for ${f['value']}")
        elif k == "skip":
            out.append(f"Skipped the {f['blind']['name']}" + (f" for the {f['tag']}" if f.get("tag") else ""))
        elif k == "boss_reroll":
            out.append(f"Boss rerolled: {f['boss']}")
        elif k == "saved":
            out.append("Saved by Mr. Bones")
        elif k == "end":
            out.append("Run won!" if f.get("won") else "Game over")
    return out


def play_steps(run, idx) -> list[dict] | None:
    """What a play's score is made of, as the bot estimates it (for the Play tab's breakdown): each step of its scoring
    (the hand's base, each card, each joker), with the chips and mult after it. None for a play with face-down cards
    (what they are isn't shown)."""
    from .bots import NO_LUCK, expects_luck
    from .scoring import HandContext, score_hand
    played = [run.hand[i] for i in idx if 0 <= i < len(run.hand)]
    if not played or any(c.face_down for c in played):
        return None
    held = [c for i, c in enumerate(run.hand) if i not in idx and not c.face_down]
    result = evaluate(played, run.rules)
    boss = run.active_boss
    if boss is not None and not boss.allows(run, result, played):
        return [{"text": f"{boss.name}: {result.name} scores nothing here", "chips": 0, "mult": 0}]
    ctx = HandContext(run, played, held, result, NO_LUCK, estimating=True, expecting=expects_luck(run))
    score = score_hand(ctx, run.hand_levels[result.name], boss)
    out = []
    words = {"+chips": "+{:g} chips", "+mult": "+{:g} Mult", "xmult": "×{:g} Mult", "$": "+${:g}",
             "balance": "chips and Mult balanced ({:g})"}
    names = {c.label(): card_text(c) for c in played + held}       # cards with their suit signs
    for (src, kind, amount), (chips, mult) in zip(score.log, score.trail):
        src = names.get(src, src)
        if kind.startswith("level"):
            text = f"{src}, {kind}: the hand's base"
        else:
            text = f"{src}: " + words.get(kind, kind + " {:g}").format(amount)
        out.append({"text": text, "chips": round(float(chips), 2), "mult": round(float(mult), 2)})
    return out


def worth_parts(bot, run, kind, args, key, base) -> list[dict]:
    """What a shop or pack option's worth is made of (for the Play tab's breakdown): before its price and the price;
    for a joker bought or picked, what it adds to the build, its bonus, what it pays and destroys, and the rest
    (the build plan and other adjustments)."""
    p = (getattr(bot, "worth_parts", None) or {}).get(tuple(key))
    if not p:
        return []
    item = None
    try:
        if key[0] in ("buy", "buy_use") and (key[1] == "card" or key[0] == "buy_use"):
            item = args[0].cards[key[2] if key[0] == "buy" else key[1]].item
        elif key[0] == "pick":
            item = args[0].cards[key[1]]
    except (IndexError, AttributeError, TypeError):
        item = None
    what = ("what using it does, tried on copies of the run" if isinstance(item, Consumable)
            else "the pack: what such a pack usually holds" if key[0] == "buy" and key[1] == "pack"
            else "the voucher: its weight, and what it measures" if key[0] == "buy" and key[1] == "voucher"
            else "a sale to afford a buy: what the buy adds, less what the sale loses"
            if key[0] in ("sell_joker", "sell_consumable") and p.get("cost")
            else "a sale: what the build loses, what it frees" if key[0] in ("sell_joker", "sell_consumable")
            else "worth before the price")
    if "kept" in p:                                          # a joker sold for being worth less kept than sold
        j = run.jokers[key[1]] if key[0] == "sell_joker" and 0 <= key[1] < len(run.jokers) else None
        out = [{"text": f"sold: ${run.sell_value(j) if j else '?'} at money's weight", "worth": round(p["sale"], 4)},
               {"text": "given up: its worth kept (below 0: it costs the build more than it adds)",
                "worth": round(-p["kept"], 4)}]
        if isinstance(j, Joker):
            names = {"build": "adds to the build's typical score", "bonus": "bonus (rarity, edition, kind, growth)",
                     "income": "what it pays", "destroys": "what it destroys"}
            parts = bot.joker_parts(run, j, base)
            out += [{"text": f"  of its worth kept: {names[k]}", "worth": round(v, 4)}
                    for k, v in parts.items() if abs(v) > 5e-5]
            rest = p["kept"] - sum(parts.values())
            if abs(rest) > 5e-5:
                out.append({"text": "  of its worth kept: other (its place in the lineup, build plan, adjustments)",
                            "worth": round(rest, 4)})
        return out + _survival_row(p)
    out = [{"text": what, "worth": round(p["gross"], 4)}]
    if p.get("cost"):
        out.append({"text": f"the price (${p['cost']}: money's worth, interest lost)", "worth": round(-p["price"], 4)})
    if isinstance(item, Joker):
        parts = bot.joker_parts(run, item, base)
        names = {"build": "adds to the build's typical score", "bonus": "bonus (rarity, edition, kind, growth)",
                 "income": "what it pays", "destroys": "what it destroys"}
        rows = [{"text": f"  of it: {names[k]}", "worth": round(v, 4)} for k, v in parts.items() if abs(v) > 5e-5]
        rest = p["gross"] - sum(parts.values())
        if abs(rest) > 5e-5:
            rows.append({"text": "  of it: other (resale floor, build plan, adjustments)", "worth": round(rest, 4)})
        out[1:1] = rows
    return out + _survival_row(p)


def _survival_row(p: dict) -> list[dict]:
    """SURVIVAL's and SCALING's parts of an option's worth: what it adds to the odds of beating the next blind, and
    ante 8's boss, at a lost run's cost."""
    out = []
    if p.get("survival"):
        out.append({"text": "survival: what it adds to the odds of beating the next blind (played out), at a lost run's cost",
                    "worth": round(p["survival"], 4)})
    if p.get("ante 8"):
        out.append({"text": "ante 8: what it adds to the odds of beating ante 8's boss (the build projected there, money "
                            "and free slots, fitted on the bot's own games), at a lost run's cost",
                    "worth": round(p["ante 8"], 4)})
    return out


def opinion(pos: Position, follow=None) -> dict:
    """What the value bot (hand-set weights) would do here, chosen on a copy of the run: its action in words and as
    JSON, its best options' worths (shop and packs), and the best plays it sees (rounds). A free action is often the
    first half of a plan (sell a joker, to buy the one it makes room for): with `follow(steps)`, the run replayed with
    these steps taken, the bot is asked again after each free one, and `plan` holds the steps to the action they lead
    to, `plan_text` them in a line (reorders left out)."""
    run, need = pos.run, pos.need
    frames = run.frames
    run.frames = None
    try:
        twin, args = copy.deepcopy((run, need.args))
    finally:
        run.frames = frames
    from .models import make                             # (models imports the bots: here, not at the top)
    bot = make(ADVISOR)
    bot.worths = {}
    k = need.kind
    out: dict = {}
    if k == "select":
        skip = bot.skip_blind(twin, *args)
        a = ["skip" if skip else "select"]
        try:                                                 # both choices and their parts (the Play tab's breakdown)
            sp = bot.skip_parts(twin, *args)
            blind, tag = args[0], args[1] if len(args) > 1 else None
            rows = [{"text": f"Play the {blind.name}", "worth": round(sp["play"], 5), "dollars": None,
                     "parts": [{"text": t, "worth": round(v, 4)} for t, v in sp["play_parts"]]}]
            if tag is not None:
                rows.append({"text": f"Skip it for the {tag.name}", "worth": round(sp["skip"], 5), "dollars": None,
                             "parts": [{"text": t, "worth": round(v, 4)} for t, v in sp["skip_parts"]]
                             + [{"text": sp["safety"], "worth": None}]})
            out["worths"] = sorted(rows, key=lambda r: -r["worth"])
        except Exception:                                    # a breakdown never breaks the hint
            pass
    elif k == "boss":
        a = ["keep"]
    elif k == "round":
        a = plain(bot.round_action(twin))
        out["plays"] = [{"cards": [int(i) for i in idx], "text": _cards(twin, idx), "hand": r.name, "score": int(s),
                         "steps": play_steps(twin, idx)}
                        for s, idx, r in ranked_plays(twin, top=10)[:3]]
    elif k == "shop":
        a = plain(bot.shop_action(twin, args[0]))
    else:
        a = plain(bot.pack_action(twin, args[0]))
    out["action"] = a
    out["text"] = describe(run, k, need.args, a)
    worths = getattr(bot, "worths", None) or {}
    dollar = bot.w.money                                     # what a dollar is worth to it: worths in dollars too
    if k in ("shop", "pack") and worths:
        base = bot.scoring_power(twin)
        out["worths"] = [{"text": describe(run, k, need.args, list(key)), "worth": round(v, 5),
                          "dollars": round(v / dollar, 2) if dollar else None,
                          "parts": worth_parts(bot, twin, k, args, key, base)}
                         for key, v in sorted(worths.items(), key=lambda kv: -kv[1])[:8]]
    if action_key(a) in worths:
        out["worth"] = round(worths[action_key(a)], 5)
    if k == "shop" and a[0] == "buy_use" and worths and max(worths, key=worths.get) == ("reroll",):
        # bought ahead of the reroll that would throw it away (CARDS_BEFORE_REROLL): the move is both, not a choice
        # between them (the user's 6AWQ2FCT, 30 Oct: "it still pushes for reroll though")
        out["plan_text"] = f"{out['text']} → {describe(run, k, need.args, ['reroll'])}"
        out["both"] = True
    if follow and a[0] in FREE:
        out["plan"] = plan(out, k, follow)
        if len(out["plan"]) > 1:
            out["plan_text"] = " → ".join(p["text"] for p in out["plan"] if not p["aside"]) or out["text"]
            for w in out.get("worths", []):                # the worth it weighed was the whole plan's
                if w["text"] == out["text"]:
                    w["text"] = out["plan_text"]
    return out


def plan(first: dict, kind: str, follow) -> list[dict]:
    """The bot's free steps from `first` on (selling to make room, using a card, reordering), each chosen on the run
    after the ones before it, up to the action they lead to (or PLAN_STEPS of them): text, action, worth, and
    whether it is only a reorder (`aside`)."""
    out, taken, op = [], [], first
    while True:
        a = op["action"]
        out.append({"text": op["text"], "action": a, "worth": op.get("worth"), "aside": a[0] in REORDER})
        if a[0] not in FREE or len(out) > PLAN_STEPS:
            return out
        taken.append({"kind": kind, "action": a})
        try:
            pos = follow(taken)
        except (ReplayError, ValueError, IndexError):         # (the bot chose it on a copy, so it should be taken)
            return out
        if pos.kind != kind:
            return out
        op = opinion(pos)


def _opinion_job(spec: dict, steps: list) -> dict | None:
    """The bot's view after these steps of a game (`spec`: the game without its branches), in a worker process."""
    pos = replay(spec, steps)
    return opinion(pos, lambda more: replay(spec, steps + more)) if pos.need is not None else None


# ---- checking an action before it is taken -------------------------------------------------------------------

def _indexes(x, n: int, most: int, least: int = 0) -> list[int]:
    if not isinstance(x, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in x):
        raise PlayError("card positions must be a list of numbers")
    if len(set(x)) != len(x) or not all(0 <= i < n for i in x):
        raise PlayError("pick each card once, from your hand")
    if not least <= len(x) <= most:
        raise PlayError(f"pick {least}-{most} cards" if least != most else f"pick {most} cards")
    return x


def _slot(x, n: int, what: str) -> int:
    if not isinstance(x, int) or isinstance(x, bool) or not 0 <= x < n:
        raise PlayError(f"no such {what}")
    return x


def _usable(run, item, targets) -> None:
    cards = run.cards_at(targets)
    if not item.can_use(run, cards):
        lo, hi = getattr(item, "min_targets", 0), getattr(item, "max_targets", 0)
        need = "no cards" if hi == 0 else f"{lo}-{hi} cards" if lo != hi else f"{hi} card{'s' if hi > 1 else ''}"
        raise PlayError(f"{item.name} can't be used like that (it takes {need} from your hand)")


def check(pos: Position, action: list, free_so_far: int) -> None:
    """Raise PlayError unless the run can take `action` at this decision."""
    need, run = pos.need, pos.run
    if need is None:
        raise PlayError("the run is over")
    if not isinstance(action, list) or not action or not isinstance(action[0], str):
        raise PlayError("an action is a list starting with its name")
    k, name = need.kind, action[0]
    if k == "select":
        if name not in ("select", "skip") or len(action) != 1:
            raise PlayError("play the blind or skip it")
        if name == "skip" and need.args[1] is None:
            raise PlayError("this blind has no tag to skip for")
        return
    if k == "boss":
        if name not in ("reroll", "keep") or len(action) != 1:
            raise PlayError("reroll the boss or keep it")
        return
    if name in FREE:
        if free_so_far >= FREE_ACTIONS - 1:
            raise PlayError("too many uses, sales and reorders in one decision")
        if name == "use":
            i = _slot(action[1] if len(action) > 1 else None, len(run.consumables), "consumable")
            targets = _indexes(action[2] if len(action) > 2 else [], len(run.hand), 5)
            _usable(run, run.consumables[i], targets)
        elif name == "sell_joker":
            i = _slot(action[1] if len(action) > 1 else None, len(run.jokers), "joker")
            if run.jokers[i].eternal:
                raise PlayError(f"{run.jokers[i].name} is Eternal: it can't be sold")
        elif name == "sell_consumable":
            _slot(action[1] if len(action) > 1 else None, len(run.consumables), "consumable")
        elif name == "sort_hand":
            if len(action) != 2 or action[1] not in ("rank", "suit"):
                raise PlayError("sort the hand by rank or by suit")
        else:
            items = run.jokers if name == "order_jokers" else run.hand
            perm = action[1] if len(action) > 1 else None
            if not isinstance(perm, list) or sorted(perm) != list(range(len(items))):
                raise PlayError("a new order lists every position once")
        return
    if k == "round":
        if name not in ("play", "discard") or len(action) != 2:
            raise PlayError("play or discard some cards (or use, sell, reorder)")
        _indexes(action[1], len(run.hand), 5, 1)
        if name == "discard" and run.discards_left <= 0:
            raise PlayError("no discards left")
        return
    if k == "shop":
        shop = need.args[0]
        if name == "leave":
            return
        if name == "reroll":
            if run.money - shop.reroll_cost < run.debt_limit:
                raise PlayError(f"a reroll costs ${shop.reroll_cost}")
            return
        if name not in ("buy", "buy_use"):
            raise PlayError("buy, reroll or leave (or use, sell, reorder)")
        if name == "buy":
            where = action[1] if len(action) > 1 else None
            offers = {"card": shop.cards, "pack": shop.packs, "voucher": shop.vouchers}.get(where)
            if offers is None:
                raise PlayError("buy a card, a pack or a voucher")
            i = _slot(action[2] if len(action) > 2 else None, len(offers), "offer")
            use, targets = False, []
        else:
            offers = shop.cards
            i = _slot(action[1] if len(action) > 1 else None, len(offers), "offer")
            use, targets = True, _indexes(action[2] if len(action) > 2 else [], len(run.hand), 5)
        o = offers[i]
        cost = cost_of(run, o)
        if run.money - cost < run.debt_limit:
            raise PlayError(f"{o.name} costs ${cost}; you have ${run.money}")
        item = o.item
        if isinstance(item, Joker) and not run.joker_room(item):
            raise PlayError("no room for another joker: sell one first")
        if isinstance(item, Consumable):
            if use:
                _usable(run, item, targets)
            elif not run.consumable_room(item):
                raise PlayError("no room for another consumable: use or sell one first")
        elif use:
            raise PlayError(f"{o.name} isn't something to use")
        return
    if k == "pack":
        state = need.args[0]
        if name == "skip":
            return
        if name != "pick":
            raise PlayError("take a card or skip the pack (or use, sell, reorder)")
        i = _slot(action[1] if len(action) > 1 else None, len(state.cards), "card in the pack")
        targets = _indexes(action[2] if len(action) > 2 else [], len(run.hand), 5)
        item = state.cards[i]
        if isinstance(item, Joker):
            if not run.joker_room(item):
                raise PlayError("no room for another joker: sell one first")
        elif isinstance(item, Consumable):
            _usable(run, item, targets)
        return
    raise PlayError(f"unknown decision {k}")


# ---- saved games ------------------------------------------------------------------------------------------------

class Games:
    """The Play tab's games: each a seed, deck and stake with its branches of recorded actions, saved under `root`.
    One lock for all: the server answers on threads, and a replay takes the run's state for itself."""

    def __init__(self, root: Path = DIR):
        self.root = root
        self.lock = threading.RLock()
        self.games: dict[str, dict] = {}
        self.positions: dict[tuple, Position] = {}       # (game, branch, steps) -> the replay there
        self.opinions: dict[tuple, dict] = {}            # (game, branch, steps) -> the bot's view there
        self.pending: dict[tuple, concurrent.futures.Future] = {}   # the same, being worked out (prefetch)
        self.pool: concurrent.futures.ProcessPoolExecutor | None = None

    # -- storage
    def _path(self, gid: str, ext: str) -> Path:
        if not gid or any(c not in "0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in gid):
            raise PlayError("no such game")
        return self.root / f"{gid}.{ext}"

    def load(self, gid: str) -> dict:
        if gid not in self.games:
            path = self._path(gid, "json")
            if not path.exists():
                raise PlayError("no such game")
            self.games[gid] = json.loads(path.read_text())
        return self.games[gid]

    def save(self, game: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        game["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = self._path(game["id"], "json.tmp")
        tmp.write_text(json.dumps(game, indent=1))
        tmp.replace(self._path(game["id"], "json"))
        journals = [self.journal(game, b) for b in game["branches"]]
        self._path(game["id"], "txt").write_text("\n\n".join(journals) + "\n")

    def listing(self) -> list[dict]:
        out = []
        if self.root.exists():
            for p in sorted(self.root.glob("*.json"), reverse=True):
                try:
                    g = json.loads(p.read_text())
                except ValueError:
                    continue
                cur = next((b for b in g["branches"] if b["id"] == g["current"]), g["branches"][0])
                out.append({"id": g["id"], "seed": g["seed"], "deck": g["deck"], "stake": g["stake"],
                            "updated": g.get("updated"), "branches": len(g["branches"]), "steps": len(cur["steps"]),
                            "result": cur.get("result")})
        return out

    # -- positions
    def _branch(self, game: dict, bid: int | None = None) -> dict:
        bid = game["current"] if bid is None else bid
        b = next((b for b in game["branches"] if b["id"] == bid), None)
        if b is None:
            raise PlayError("no such branch")
        return b

    def position(self, game: dict, branch: dict, n: int | None = None) -> Position:
        """The run after the branch's first `n` steps (all of them by default): a branch only ever grows at its end,
        so its first n steps, and the replay of them, never change."""
        n = len(branch["steps"]) if n is None else n
        key = (game["id"], branch["id"], n)
        if key not in self.positions:
            if len(self.positions) > 64:
                self.positions.clear()
            self.positions[key] = replay(game, branch["steps"][:n])
        return self.positions[key]

    def bot_view(self, game: dict, branch: dict, pos: Position, n: int | None = None) -> dict | None:
        """The bot's view of a position: known, worked out by a worker (prefetch; waited for), or worked out here."""
        if pos.need is None:
            return None
        key = (game["id"], branch["id"], len(branch["steps"]) if n is None else n)
        if key not in self.opinions:
            if len(self.opinions) > 512:
                self.opinions.clear()
            job = self.pending.pop(key, None)
            if job is not None:
                self.opinions[key] = job.result()
            else:
                done = branch["steps"][:key[2]]
                self.opinions[key] = opinion(pos, lambda more: replay(game, done + more))
        return self.opinions[key]

    HINT_WORKERS = 2

    def prefetch(self, game: dict, branch: dict, n: int) -> None:
        """Have a worker process work out the bot's view after the branch's first n steps, unless it is known or on
        its way: a shop's takes seconds, and a thread here would hold up the server's others (one interpreter)."""
        key = (game["id"], branch["id"], n)
        if key in self.opinions or key in self.pending:
            return
        if self.pool is None:
            self.pool = concurrent.futures.ProcessPoolExecutor(self.HINT_WORKERS, mp_context=multiprocessing.get_context("spawn"))
        spec = {k: v for k, v in game.items() if k != "branches"}
        steps = [{"kind": s["kind"], "action": s["action"]} for s in branch["steps"][:n]]
        self.pending[key] = self.pool.submit(_opinion_job, spec, steps)

    def hint(self, gid: str, cursor: int | None = None) -> dict:
        """The bot's view at the cursor, for the page to show once it is ready: waited for outside the lock, so the
        page's other requests go on meanwhile."""
        with self.lock:
            game = self.load(gid)
            branch = self._branch(game)
            n = _cursor(branch, cursor)
            key = (gid, branch["id"], n)
            if key not in self.opinions:
                pos = self.position(game, branch, n)
                if pos.need is None:
                    return {"bot": None, "cursor": n}
                self.prefetch(game, branch, n)
            job = self.pending.get(key)
        if job is not None:
            job.result()
        with self.lock:
            return {"bot": self.bot_view(game, branch, self.position(game, branch, n), n), "cursor": n}

    # -- what the page asks
    def new(self, seed: str | None, deck: str | None, stake: str, max_ante: int = 8) -> dict:
        with self.lock:
            seed = (seed or "").strip().upper() or "".join(random.choice(SEED_CHARS) for _ in range(8))
            if not 1 <= len(seed) <= 8 or any(c not in SEED_CHARS for c in seed):
                raise PlayError("a seed is 1-8 characters from 1-9 and A-Z")
            gid = f"{time.strftime('%Y%m%d-%H%M%S')}-{seed}"
            game = {"id": gid, "seed": seed, "deck": deck or "Red Deck", "stake": stake or "White Stake",
                    "max_ante": max(1, min(16, int(max_ante))), "hand_sort": "rank", "draw_after_win": False,
                    "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "current": 0, "branches": [{"id": 0, "parent": None, "from_step": 0, "steps": [], "result": None}]}
            Run(Agent(), game_seed=seed, deck=game["deck"], stake=game["stake"])     # a bad deck or stake fails here
            self.games[gid] = game
            self.save(game)
            return self.state(gid)

    def state(self, gid: str, hint: bool = True, frames_from: int | None = None, cursor: int | None = None) -> dict:
        """Where the game's current branch stands after its first `cursor` steps (the cursor: all of them by default;
        going back along the line keeps the steps after it). With it, the run's recorded frames (the run viewer's,
        which the Play tab animates): all of them, or with `frames_from` only those from there on (after an action, from
        the decision it answered: a replay records the same frames up to there)."""
        with self.lock:
            game = self.load(gid)
            branch = self._branch(game)
            steps = branch["steps"]
            n = _cursor(branch, cursor)
            pos = self.position(game, branch, n)
            since = pos.agent.marks[-1] if pos.agent.marks else 0
            start = 0 if frames_from is None else max(0, min(frames_from, pos.frames_at))
            out = {"id": gid, "seed": game["seed"], "deck": game["deck"], "stake": game["stake"],
                   "max_ante": game["max_ante"], "branch": branch["id"], "decision": pos.kind, "step": n, "cursor": n,
                   "view": view(pos), "events": events(pos, since),
                   "frames": (pos.run.frames or [])[start:pos.frames_at], "frames_from": start,
                   "timeline": [{"i": i, "kind": s["kind"], "text": s.get("text", ""), "ante": s.get("ante"),
                                 "bot": None if aside(s) else (s.get("bot") or {}).get("plan_text")
                                 or (s.get("bot") or {}).get("text"),
                                 "agree": None if aside(s) else s.get("agree"), "aside": aside(s)}
                                for i, s in enumerate(steps)],
                   "branches": [{"id": b["id"], "parent": b["parent"], "from_step": b["from_step"], "steps": len(b["steps"]),
                                 "result": b.get("result")} for b in game["branches"]],
                   "result": None}
            if pos.need is None and pos.result is not None:
                out["result"] = result_of(pos.result)
                if n == len(steps):
                    branch["result"] = out["result"]
            if pos.need is not None:                         # its bot view on the way, for the hint and the step's record
                self.prefetch(game, branch, n)
            if hint and (game["id"], branch["id"], n) in self.opinions:
                out["bot"] = self.opinions[(game["id"], branch["id"], n)]
            elif hint and pos.need is not None:
                out["bot_pending"] = True                    # the page asks /api/play/hint for it
            return out

    def act(self, gid: str, action: list, cursor: int | None = None) -> dict:
        """Take `action` at the cursor (the branch's end by default). Where the line already goes on that way (the
        recorded next step), the cursor just moves on; any other action there starts a new branch, the steps before
        the cursor plus this one, and switches to it (the old line is kept). At the end it adds to the branch."""
        with self.lock:
            game = self.load(gid)
            branch = self._branch(game)
            steps = branch["steps"]
            n = _cursor(branch, cursor)
            pos = self.position(game, branch, n)
            free = 0
            for s in reversed(steps[:n]):
                if s["action"][0] not in FREE or s["kind"] != pos.kind:
                    break
                free += 1
            if (isinstance(action, list) and len(action) == 2 and action[0] == "sort_hand" and not game.get("hand_sort")
                    and action[1] in ("rank", "suit")):        # a game from before sort modes: a one-off reorder
                hand = pos.run.hand
                action = ["order_hand", sorted(range(len(hand)), key=lambda i: hand_key(action[1])(hand[i]))]
            check(pos, action, free)
            if n < len(steps) and steps[n]["kind"] == pos.kind and plain(steps[n]["action"]) == plain(action):
                return self.state(gid, frames_from=pos.frames_at, cursor=n + 1)   # the line goes this way: on along it
            # sorting the hand isn't held against the bot's choice (and costs no opinion)
            bot = None if action[0] in ASIDE else self.bot_view(game, branch, pos, n)
            step = {"kind": pos.kind, "action": action, "text": describe(pos.run, pos.kind, pos.need.args, action),
                    "ante": pos.run.ante, "bot": bot,
                    "agree": None if action[0] in ASIDE else bool(bot) and plain(bot["action"]) == plain(action)}
            before = json.dumps(view(pos), sort_keys=True, default=str)
            after = replay(game, steps[:n] + [step])
            if after.kind == pos.kind and json.dumps(view(after), sort_keys=True, default=str) == before:
                raise PlayError("that changed nothing (the game didn't take it)")
            if n < len(steps):                                   # another way from here: a new branch
                target = {"id": max(b["id"] for b in game["branches"]) + 1, "parent": branch["id"], "from_step": n,
                          "steps": copy.deepcopy(steps[:n]) + [step], "result": None}
                game["branches"].append(target)
                game["current"] = target["id"]
            else:
                target = branch
                steps.append(step)
            self.positions[(gid, target["id"], len(target["steps"]))] = after
            target["result"] = result_of(after.result) if after.need is None else None
            self.save(game)
            return self.state(gid, frames_from=pos.frames_at)

    def rewind(self, gid: str, step: int) -> dict:
        """Start a new branch with the current branch's first `step` actions (the decision `step` comes up again)."""
        with self.lock:
            game = self.load(gid)
            branch = self._branch(game)
            if not isinstance(step, int) or not 0 <= step <= len(branch["steps"]):
                raise PlayError("no such step")
            if step == len(branch["steps"]):
                return self.state(gid)
            new = {"id": max(b["id"] for b in game["branches"]) + 1, "parent": branch["id"], "from_step": step,
                   "steps": copy.deepcopy(branch["steps"][:step]), "result": None}
            game["branches"].append(new)
            game["current"] = new["id"]
            self.save(game)
            return self.state(gid)

    ENDLESS_ANTE = 39    # the last ante the game's blind tables give a target for

    def endless(self, gid: str) -> dict:
        """Play on past the run's last ante, as the game's Endless mode does after a win: the run goes on to ante 39.
        Only the end moves, so every recorded step replays as before."""
        with self.lock:
            game = self.load(gid)
            game["max_ante"] = max(game["max_ante"], self.ENDLESS_ANTE)
            for b in game["branches"]:
                b["result"] = None                           # (a branch that stopped at the old limit now goes on)
            for cache in (self.positions, self.opinions, self.pending):
                for key in [k for k in cache if k[0] == gid]:
                    del cache[key]                           # replays (and bot views) made with the old limit
            self.save(game)
            return self.state(gid)

    def switch(self, gid: str, bid: int) -> dict:
        with self.lock:
            game = self.load(gid)
            self._branch(game, bid)
            game["current"] = bid
            self.save(game)
            return self.state(gid)

    def preview(self, gid: str, cards: list, cursor: int | None = None) -> dict:
        """The poker hand these cards make and what the bot's estimate says they score (no luck), for the sidebar."""
        with self.lock:
            game = self.load(gid)
            branch = self._branch(game)
            pos = self.position(game, branch, _cursor(branch, cursor))
            run = pos.run
            if pos.kind != "round" or not cards:
                return {"hand": None}
            idx = _indexes(cards, len(run.hand), 5, 1)
            played = [run.hand[i] for i in idx]
            held = [c for i, c in enumerate(run.hand) if i not in idx]
            result = evaluate(played, run.rules)
            return {"hand": result.name, "level": run.hand_levels[result.name],
                    "estimate": estimate(run, played, held, result), "reason": why_not(run, played, result)}


    # -- the journal
    def journal(self, game: dict, branch: dict) -> str:
        """The branch decision by decision, as scripts/analyze_losses.py writes a run, with the bot's choice (and
        its worths) beside each of the person's."""
        lines = [f"# {game['id']}: {game['seed']} ({game['deck']}, {game['stake']}), branch {branch['id']}"
                 + (f" from branch {branch['parent']} at step {branch['from_step']}" if branch["parent"] is not None else "")]
        state = {"round": None}

        def watch(i, kind, run, args, step):
            bot = step.get("bot") or {}
            mark = "  <-- differs" if step.get("agree") is False and not aside(step) else ""
            botline = f" | bot -> {bot.get('plan_text') or bot.get('text', '?')}" if bot else ""
            if kind == "round":
                key = (run.rounds_played, run.ante, run.blind.kind)
                if key != state["round"]:
                    state["round"] = key
                    b = run.blind
                    name = b.boss.name if b.boss else b.name
                    effect = f" ({BOSS_EFFECT.get(name, '')})" if b.boss else ""
                    lines.append(f"\n## ROUND ante {run.ante} {name}{effect}: target {b.chips:,}; {run.hands_left} hands, "
                                 f"{run.discards_left} discards; ${run.money}; jokers {[joker_text(j) for j in run.jokers]}; "
                                 f"consumables {[c.name for c in run.consumables]}; levels {({h: n for h, n in run.hand_levels.items() if n > 1})}")
                plays = "; ".join(f"{p['text']} = {p['score']:,}" for p in bot.get("plays", []))
                lines.append(f"  [{i}] score {run.round_score:,}/{run.blind.chips:,}, hands {run.hands_left}, discards "
                             f"{run.discards_left} | hand {' '.join(card_text(c) for c in run.hand)} | best plays: {plays} | "
                             f"you -> {step.get('text')}{botline}{mark}")
            elif kind == "shop":
                shop = args[0]
                offers = [f"{item_text(o.item) if o.kind not in ('Pack', 'Voucher') else o.name} ${cost_of(run, o)}"
                          for o in shop.cards + shop.packs + shop.vouchers]
                worths = ", ".join(f"{w['text']}={w['worth']:+.2f}" for w in bot.get("worths", [])[:6])
                lines.append(f"  [{i}] SHOP ante {run.ante} ${run.money} reroll ${shop.reroll_cost}: offers {offers}; jokers "
                             f"{[joker_text(j) for j in run.jokers]} | you -> {step.get('text')}{botline} | worths {worths}{mark}")
            elif kind == "pack":
                pack = args[0]
                worths = ", ".join(f"{w['text']}={w['worth']:+.2f}" for w in bot.get("worths", [])[:6])
                lines.append(f"  [{i}] PACK {pack.pack.name}: {[item_text(c) for c in pack.cards]} | you -> {step.get('text')}"
                             f"{botline} | worths {worths}{mark}")
            elif kind == "select":
                blind, tag = args
                lines.append(f"  [{i}] SELECT ante {run.ante} {blind.name}: tag {tag.name if tag else None} | you -> "
                             f"{step.get('text')}{botline}{mark}")
            else:
                lines.append(f"  [{i}] BOSS {args[0].name} | you -> {step.get('text')}{botline}{mark}")

        try:
            pos = replay(game, branch["steps"], watch)
        except ReplayError as exc:
            return "\n".join(lines + [f"\n## REPLAY ERROR: {exc}"])
        run = pos.run
        compared = [s for s in branch["steps"] if not aside(s)]
        agree = sum(bool(s.get("agree")) for s in compared)
        tail = (f"\n## END: {'won' if pos.result.won else 'lost'} at ante {pos.result.ante}, progress {pos.result.progress:.2f}"
                if pos.result else f"\n## NOW: waiting for a {pos.kind} decision at ante {run.ante}")
        lines.append(tail + f"; jokers {[joker_text(j) for j in run.jokers]}; ${run.money}; the bot would have chosen the "
                     f"same in {agree} of {len(compared)} decisions (sorting the hand not counted)")
        return "\n".join(lines)


def result_of(res) -> dict:
    return {"won": res.won, "ante": res.ante, "blinds_beaten": res.blinds_beaten, "progress": round(res.progress, 2),
            "best_hand": res.best_hand, "money": res.money}


def why_not(run, played, result) -> str | None:
    """Why these cards would score nothing (or nothing from their cards), in words for the Play tab: the boss's rule,
    or every scoring card debuffed. None when they score as usual."""
    boss = run.active_boss
    if boss is not None and not boss.allows(run, result, played):
        if boss.name == "The Mouth":
            return f"The Mouth: only {next(iter(run.round_hand_types))} scores this round"
        if boss.name == "The Eye":
            return f"The Eye: {result.name} already played this round"
        if boss.name == "The Psychic":
            return "The Psychic: must play 5 cards"
        return f"{boss.name}: {BOSS_EFFECT.get(boss.name, 'this hand scores nothing')}"
    scoring = [played[i] for i in result.scoring]
    if scoring and all(c.debuffed for c in scoring):
        return f"{boss.name + ': ' if boss else ''}every scoring card is debuffed"
    return None



def aside(step: dict) -> bool:
    """A step that only arranges the hand (sorting it): no comparison with the bot (older games recorded one)."""
    return step["action"][0] in ASIDE


def _cursor(branch: dict, cursor) -> int:
    """A cursor along the branch: how many of its steps are taken (all of them when None)."""
    n = len(branch["steps"])
    if cursor is None:
        return n
    if not isinstance(cursor, int) or isinstance(cursor, bool) or not 0 <= cursor <= n:
        raise PlayError("no such step")
    return cursor
