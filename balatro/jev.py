"""Jev (TypeSafe's System One model) as a Balatro player.

At each decision the value bot lists the moves it weighs, and Jev, reading the whole position, picks one:
- in a round, the value bot's best plays (with what each scores, and whether it beats the blind) and its best
  discards (with what the best play after the cards they would draw scores), plus the bot's own choice;
- in the shop and packs, the value bot's best options (with prices and effects), plus its own choice.
Using consumables, the joker order, skipping blinds and boss rerolls stay the value bot's. With `shop_only`
("Jev shops") Jev decides only in the shop and packs and the value bot plays the rounds; with `ties` ("Jev breaks
near-ties") it decides only between the shop and pack options the value bot rates within that margin of its best. Every move comes from the
game, so every answer is a legal move. Answers are cached by question (runs/jev/cache.sqlite): replaying a seed asks
nothing new and costs nothing. TYPESAFE_API_KEY comes from the environment, else from the .env file JEV_ENV names
(by default the moviescoring-ml project's).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

import requests

from .bots import ranked_plays
from .cards import Card
from .items import Consumable, data, info
from .jokers import Joker, joker_now
from .modifiers import income, play_bonus
from .shop import cost_of
from .strategy import SUIT_SYMBOL, ValueBot, Weights, action_key

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
PRICE_IN, PRICE_OUT = 0.042 / 1e6, 0.0          # dollars per token (the moviescoring-ml project's price)
ENV_FILE = Path(os.environ.get("JEV_ENV", Path.home() / "Projects" / "moviescoring-ml" / ".env"))
CACHE = Path(__file__).resolve().parent.parent / "runs" / "jev" / "cache.sqlite"
INSTRUCTIONS = ("You are playing Balatro and want to beat ante 8's boss blind to win the run. Rules that matter: a blind "
                "is beaten when the chips scored reach its target, and the run is lost if the hands run out first. A "
                "discard costs nothing but one of the round's discards, and discards left at the end of a round are "
                "simply lost, so discarding toward a stronger hand is usually better than playing a weak one while "
                "hands are short. Money left between blinds earns $1 interest per $5 held. " + (
                "How runs are won: a hand scores chips x mult, and blind targets grow two to three times each ante, so the "
                "build has to keep multiplying its score. Jokers that add Chips or Mult carry the first antes; only jokers "
                "that multiply Mult (xMult) or keep growing reach ante 8. Strong runs build around one poker hand: play it, "
                "level it with its Planet cards, and take jokers that reward it. The five joker slots are the main "
                "resource: fill them early with whatever scores, then replace the weakest with better ones. Interest ($1 "
                "per $5, up to $5 a round at $25) pays over many rounds, but a build that falls behind the targets loses "
                "the run, so spend when the build's typical hand is short of what the coming blinds need. Pass on packs "
                "and jokers that do nothing for this build. ") + "Which of these moves is best now?")
RANK = {11: "J", 12: "Q", 13: "K", 14: "A"}


class JevError(RuntimeError):
    """Jev can't answer: no key, no credits, or no answer after retries."""


def api_key() -> str:
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    try:
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("TYPESAFE_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    raise JevError(f"no TYPESAFE_API_KEY in the environment or in {ENV_FILE}")


class Client:
    """Asks Jev which of some moves is best; counts what it costs; remembers every answer."""

    def __init__(self):
        self.session, self.key, self.db = requests.Session(), None, None
        self.usage = Counter()

    def _cache(self):
        if self.db is None:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(CACHE, timeout=30)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS answers (question TEXT PRIMARY KEY, probabilities TEXT)")
        return self.db

    def choose(self, state: str, options: list[str], instructions: str = INSTRUCTIONS) -> list[float]:
        """Jev's probability that each option is the best move (or, with other `instructions`, the best answer)."""
        question = hashlib.sha1(json.dumps([MODEL, instructions, state, options]).encode()).hexdigest()
        row = self._cache().execute("SELECT probabilities FROM answers WHERE question = ?", (question,)).fetchone()
        if row:
            self.usage["cached"] += 1
            return json.loads(row[0])
        self.key = self.key or api_key()
        body = {"state": state, "model": MODEL,
                "questions": {"move": {"type": "score", "criteria": options, "instructions": instructions}}}
        for attempt in range(6):
            try:
                r = self.session.post(API, headers={"Authorization": f"Bearer {self.key}"}, json=body, timeout=60)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                try:
                    detail = r.json().get("detail")
                    detail = detail.get("message", detail) if isinstance(detail, dict) else detail
                except ValueError:
                    detail = r.text[:200]
                raise JevError(f"Jev refused ({r.status_code}): {detail}")
            j = r.json()
            p = j["answers"]["move"]["probabilities"]
            probs = [float(p.get(str(i), 0.0)) for i in range(len(options))]
            self.usage["calls"] += 1
            self.usage["input_tokens"] += j["usage"]["input_tokens"]
            self.usage["output_tokens"] += j["usage"].get("output_tokens", 0)
            db = self._cache()
            db.execute("INSERT OR REPLACE INTO answers VALUES (?, ?)", (question, json.dumps(probs)))
            db.commit()
            return probs
        raise JevError("Jev gave no answer after 6 tries")

    def cost(self) -> float:
        return self.usage["input_tokens"] * PRICE_IN + self.usage["output_tokens"] * PRICE_OUT


# ---- the position, in words -------------------------------------------------------------------------

def _effects() -> dict:
    jokers = {j["name"]: j["effect"] for j in data("jokers.json")}
    mods = data("modifiers.json")
    extras = {e["name"].replace(" Card", ""): e["effect"] for e in mods["enhancements"]}
    extras.update({e["name"]: e["effect"] for e in mods["editions"]})
    extras.update({s["key"]: s["effect"] for s in mods["seals"]})
    return {"jokers": jokers, "extras": extras}


EFFECTS = _effects()


def card_text(c: Card) -> str:
    if c.face_down:
        return "a face-down card"
    name = "Stone card" if c.is_stone else f"{RANK.get(c.rank, c.rank)}{SUIT_SYMBOL[c.suit]}"
    extras = [x for x in (c.enhancement if not c.is_stone else None, c.edition, c.seal and f"{c.seal} Seal",
                          c.bonus_chips and f"+{c.bonus_chips} Chips") if x]
    return name + (f" ({', '.join(extras)})" if extras else "") + (" [debuffed]" if c.debuffed else "")


def cards_text(cards) -> str:
    return " ".join(card_text(c) for c in cards)


def joker_text(run, j) -> str:
    """A joker, its edition and stickers, what it does, and what it has built up or aims at now."""
    tags = [x for x in (j.edition, j.eternal and "Eternal", j.perishable and "Perishable", j.rental and "Rental",
                        (j.perished or j.disabled) and "debuffed") if x]
    now = joker_now(j)
    return (f"{j.name}" + (f" ({', '.join(tags)})" if tags else "") + f": {_sentence(EFFECTS['jokers'].get(j.name, ''))}"
            + (f" Now: {now}." if now else ""))


def consumable_text(c) -> str:
    try:
        effect = info(c.kind.lower(), c.name)["effect"]
    except (KeyError, StopIteration):
        effect = ""
    return f"{c.name} ({c.kind}{', ' + c.edition if getattr(c, 'edition', None) else ''}): {_sentence(effect)}"


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text.endswith((".", "!", "?")) else text + "."


def position(run) -> str:
    """The run as it stands: ante, blind, money, jokers, consumables, vouchers, levels, hand and deck."""
    lines = [f"Balatro run on the {run.deck_name or 'standard deck'}, {run.stake}. "
             f"Ante {run.ante}; beating ante 8's boss blind wins. Money: ${run.money}."]
    b = run.blind
    if b is not None and run.in_round:
        boss = b.boss
        what = f"{boss.name} (boss: {info('boss', boss.name)['effect']})" if boss else b.name
        lines.append(f"Blind: {what}. Score {b.chips:,} chips to beat it: {run.round_score:,} scored so far, "
                     f"{run.hands_left} hands and {run.discards_left} discards left.")
    lines.append(f"Jokers ({len(run.jokers)} of {run.joker_slots} slots, left to right):"
                 + ("".join(f"\n  {k + 1}. {joker_text(run, j)}" for k, j in enumerate(run.jokers)) or " none."))
    lines.append(f"Consumables ({len(run.consumables)} of {run.consumable_slots}):"
                 + ("".join(f"\n  {consumable_text(c)}" for c in run.consumables) or " none."))
    if run.vouchers:
        lines.append(f"Vouchers: {', '.join(run.vouchers)}.")
    levels = {h: n for h, n in run.hand_levels.items() if n > 1}
    if levels:
        lines.append("Poker hand levels above 1: " + ", ".join(f"{h} {n}" for h, n in levels.items()) + ".")
    if run.hand:
        lines.append(f"Hand: {cards_text(run.hand)}.")
    lines.append(f"Deck: {len(run.draw_pile)} cards left to draw of {len(run.deck)}.")
    return "\n".join(lines)


class JevBot(ValueBot):
    """Jev chooses among the moves the hand-set value bot weighs (see the module docstring)."""

    PLAYS, DISCARDS, OPTIONS = 6, 3, 8

    def __init__(self, shop_only: bool = False, ties: float | None = None):
        super().__init__()
        self.w, self.net = Weights(), None                 # the hand-set value bot underneath, not the planner's
        self.ties = ties          # a margin in power: Jev decides only between the shop and pack options the value bot
        self.shop_only = shop_only or ties is not None     # rates within it of its best (it plays the rounds itself)
        self.jev = Client()
        self.history, self.moves = [], []                  # blinds beaten (target, score, hands); purchases and sales
        self._blind, self._start, self._shop = None, None, None

    def _ask(self, run, moves: list[tuple], texts: list[str], own: tuple, where: str = "") -> tuple:
        """Jev's pick of `moves` (described by `texts`); the value bot's own choice is `own`."""
        if len(moves) < 2:
            return moves[0] if moves else own
        state = "\n".join([position(run), *self._context(run)] + ([where] if where else []))
        probs = self.jev.choose(state, texts)
        k = max(range(len(moves)), key=lambda i: probs[i])
        pick = moves[k]
        self.jev.usage["decisions"] += 1
        self.jev.usage["agreed"] += action_key(pick) == action_key(own)
        if pick[0] in ("buy", "buy_use", "sell_joker", "pick", "reroll"):
            self.moves.append(f"ante {run.ante}: {re.split(r'[.:] | [(]pick', texts[k])[0]}")
        return pick

    # ---- what Jev reads besides the position -------------------------------------------------------
    def _typical(self, run, delta: float = 0.0) -> float:
        """The build's typical best hand from a fresh hand (ValueBot.power, back in chips), after `delta` power."""
        return math.expm1(self.power(run) + delta)

    def _context(self, run) -> list[str]:
        lines = [f"Build strength: the best hand from {run.hand_size} fresh cards, before any discard, scores about "
                 f"{self._typical(run):,.0f} chips on average with these jokers and hand levels.", self._blinds_ahead(run)]
        played = [(h, n) for h, n in run.hand_plays.most_common(3) if n]
        if played:
            lines.append("Hands played this run: " + ", ".join(f"{h} x{n} (level {run.hand_levels[h]})" for h, n in played) + ".")
        suits = Counter(c.suit for c in run.deck if not c.is_stone)
        special = Counter(x for c in run.deck for x in (c.enhancement, c.seal and f"{c.seal} Seal", c.edition) if x)
        lines.append(f"Deck of {len(run.deck)}: " + ", ".join(f"{n} {SUIT_SYMBOL[s]}" for s, n in suits.items())
                     + ("; " + ", ".join(f"{n} {x}" for x, n in special.most_common()) if special else "") + ".")
        if self.history:
            lines.append("Blinds beaten (target: scored, hands used): " + "; ".join(self.history[-6:]) + ".")
        if self.moves:
            lines.append("Recent purchases and sales: " + "; ".join(self.moves[-8:]) + ".")
        return lines

    def _blinds_ahead(self, run) -> str:
        """This ante's blinds still to beat, and the boss targets of the antes after it."""
        b = run.blind
        boss_unknown = b is not None and b.kind == 2 and not run.in_round      # after a boss: the next ante, boss not drawn yet
        first = 0 if b is None or boss_unknown else b.kind + (0 if run.in_round else 1)
        parts = []
        for kind in range(first, 3):
            if kind == 2 and boss_unknown:
                parts.append(f"Boss Blind about {int(run.ante_table[run.ante] * 2 * run.blind_scale):,} (boss not known yet)")
                continue
            bl = run.make_blind(kind)
            parts.append(f"{bl.boss.name} {bl.chips:,} (boss: {info('boss', bl.boss.name)['effect']})" if bl.boss
                         else f"{bl.name} {bl.chips:,}")
        later = [f"ante {a}: {int(run.ante_table[a] * 2 * run.blind_scale):,}" for a in range(run.ante + 1, 9) if a in run.ante_table]
        return ((f"Still to beat in ante {run.ante}: " + "; ".join(parts) + ". ") if parts else "") + (
            "Boss targets ahead: " + ", ".join(later) + "." if later else "")

    def _note_round(self, run) -> None:
        if run.blind is not self._blind:
            self._blind, self._start = run.blind, (run.hands_left, run.discards_left)

    def _note_shop(self, run) -> None:
        b = run.blind
        if run.shops_seen == self._shop or b is None:
            return
        self._shop = run.shops_seen
        hands = f", {self._start[0] - run.hands_left} hands" if self._start and self._blind is b else ""
        self.history.append(f"ante {run.ante - 1 if b.kind == 2 else run.ante} {b.boss.name if b.boss else b.name} "
                            f"{b.chips:,}: {run.round_score:,}{hands}")

    def _with_it(self, run, joker) -> str:
        now = self._typical(run)
        after = self._typical(run, self.joker_worth(run, joker, self.power(run)) - self.bonus(joker, run) - income(self, run, joker))
        return f" On today's hands it would take the typical best hand from {now:,.0f} to {after:,.0f} chips."

    # ---- rounds -----------------------------------------------------------------------------------
    def round_action(self, run):
        self._note_round(run)
        if self.shop_only:
            return super().round_action(run)
        order = self._play_order(run)
        if order:
            return ("order_jokers", order)
        use = self._use(run)
        if use:
            return use
        own = super().round_action(run)
        needed = run.blind.chips - run.round_score
        mods = self._measure(run)
        bonus = (lambda played, r: play_bonus(self, mods, played, r)) if mods else None
        plays, seen = [], set()                          # one play per set of scoring cards (spare cards aside)
        for total, idx, r in ranked_plays(run, bonus=bonus, need=needed if mods else None):
            scoring = (r.name, frozenset(idx[k] for k in r.scoring))
            if scoring not in seen and len(plays) < self.PLAYS:
                seen.add(scoring)
                plays.append((total, idx, r))
        moves, texts = [], []
        for total, idx, r in plays:
            moves.append(("play", idx))
            after = needed - total
            texts.append(f"Play {cards_text(run.hand[i] for i in idx)} ({r.name}): scores about {total:,}, "
                         + ("which beats the blind." if after <= 0 else
                            f"leaving {after:,} to score with {run.hands_left - 1} hands left."))
        if run.discards_left > 0 and plays:
            for value, opt, _ in self._ranked_discards(run, plays[0][1], mods)[:self.DISCARDS]:
                moves.append(("discard", opt))
                texts.append(f"Discard {cards_text(run.hand[i] for i in opt)}: with the cards that would be drawn, "
                             f"the best play then scores about {max(value, 0):,}.")
        if own[0] in ("play", "discard") and action_key(own) not in {action_key(m) for m in moves}:
            moves.append(own)
            texts.append(f"{'Play' if own[0] == 'play' else 'Discard'} {cards_text(run.hand[i] for i in own[1])}"
                         + (" (only for what a joker or seal pays for discarding them)." if own[0] == "discard" else "."))
        return self._ask(run, moves, texts, own)

    # ---- shop and packs ---------------------------------------------------------------------------
    def _top(self, own) -> list[tuple]:
        """The value bot's most promising options of this decision (self.worths), its own choice among them; with
        `ties`, only those within that margin of the best."""
        ranked = [k for k, _ in sorted(self.worths.items(), key=lambda kv: -kv[1])][:self.OPTIONS]
        if self.ties is not None:
            best = max(self.worths.values())
            ranked = [k for k in ranked if self.worths[k] >= best - self.ties]
        keys = ranked if action_key(own) in ranked else ranked[:-1] + [action_key(own)]
        return [tuple(list(x) if isinstance(x, tuple) else x for x in k) for k in keys]

    def shop_action(self, run, shop):
        self._note_shop(run)
        own = super().shop_action(run, shop)
        if own[0] in ("order_jokers", "use") or len(self.worths) < 2:
            return own
        moves = self._top(own)
        if ("leave",) not in moves and self.ties is None:
            moves.append(("leave",))
        texts = [self._shop_text(run, shop, m) for m in moves]
        where = "In the shop between blinds. Offers: " + "; ".join(
            f"{o.name} (${cost_of(run, o)})" for o in shop.cards + shop.packs + shop.vouchers) + "."
        return self._ask(run, moves, texts, own, where)

    def _shop_text(self, run, shop, m) -> str:
        if m[0] == "leave":
            return f"Leave the shop and keep the ${run.money} (interest pays $1 per $5 held at a round's end, up to ${run.interest_cap} a round)."
        if m[0] == "reroll":
            return f"Reroll the shop's cards for ${shop.reroll_cost}."
        if m[0] == "sell_joker":
            j = run.jokers[m[1]]
            base = self.power(run)
            without = self._typical(run, -(self.owned_worth(run, m[1], base) - self.bonus(j, run) - income(self, run, j)))
            return (f"Sell the joker {j.name} for ${run.sell_value(j)}" + ("." if run.joker_room() else " to make room for a new one.")
                    + " " + joker_text(run, j).split(": ", 1)[-1]
                    + f" Without it the typical best hand would score about {without:,.0f} (now {self._typical(run):,.0f}).")
        where, i = (m[1], m[2]) if m[0] == "buy" else ("card", m[1])
        o = {"card": shop.cards, "pack": shop.packs, "voucher": shop.vouchers}[where][i]
        price = f"${cost_of(run, o)}"
        if where == "voucher":
            return f"Buy the voucher {o.name} for {price}: {info('voucher', o.name)['effect']}"
        if where == "pack":
            p = o.item
            return f"Buy the {p.name} for {price} (pick {p.chosen} of {p.shown}: {self._contents(p)})."
        item = o.item
        if isinstance(item, Joker):
            return f"Buy the joker {item.name} for {price}. " + joker_text(run, item).split(": ", 1)[-1] + self._with_it(run, item)
        if isinstance(item, Consumable):
            return (f"Buy {item.name} ({item.kind}) for {price} and " + ("use it now. " if m[0] == "buy_use" else "keep it. ")
                    + consumable_text(item).split(": ", 1)[-1] + self._planet_effect(run, item))
        return f"Buy the playing card {card_text(item)} for {price} (added to the deck)."

    def _planet_effect(self, run, planet) -> str:
        if getattr(planet, "kind", None) != "Planet":
            return ""
        delta = self.planet_worth(run, planet)
        return "" if delta is None else f" It would take the typical best hand from {self._typical(run):,.0f} to {self._typical(run, delta):,.0f} chips."

    @staticmethod
    def _contents(pack) -> str:
        return next((p["contents"] for p in data("shop.json")["booster_packs"]["packs"] if p["name"] == pack.name), pack.kind)

    def pack_action(self, run, pack):
        own = super().pack_action(run, pack)
        if len(self.worths) < 2:
            return own
        moves = self._top(own)
        texts = []
        for m in moves:
            if m[0] == "skip":
                texts.append("Skip the rest of this pack.")
                continue
            if m[0] == "sell_joker":                        # slots full: room made first for a joker from the pack
                texts.append(self._shop_text(run, None, m))
                continue
            item = pack.cards[m[1]]
            on = f" on {cards_text(run.hand[t] for t in m[2])}" if len(m) > 2 and m[2] else ""
            if isinstance(item, Joker):
                texts.append(f"Take the joker {item.name}. " + joker_text(run, item).split(": ", 1)[-1] + self._with_it(run, item))
            elif isinstance(item, Consumable):
                texts.append(f"Take and use {item.name} ({item.kind}){on}. " + consumable_text(item).split(": ", 1)[-1]
                             + self._planet_effect(run, item))
            else:
                texts.append(f"Take the playing card {card_text(item)} (added to the deck).")
        where = f"Opening a {pack.pack.name}: " + ", ".join(getattr(x, "name", None) or card_text(x) for x in pack.cards) + "."
        return self._ask(run, moves, texts, own, where)
