"""Baseline bots. Evolved strategies come later; these exercise the engine and set the bar."""
from __future__ import annotations

import math
import random
from itertools import combinations

from .agent import Agent
from .cards import rank_chips
from .hands import evaluate, evaluate_cached
from .items import Consumable
from .jokers import JOKER_DATA, Joker
from .scoring import HandContext, hand_base, score_hand
from .shop import cost_of


class _NoLuck:
    """The random source for estimates: chances (Lucky cards, Bloodstone, ...) never trigger, ranged rolls
    (Misprint) give their middle value."""

    @staticmethod
    def random() -> float:
        return 0.999999

    @staticmethod
    def randint(a: int, b: int) -> int:
        return (a + b) // 2

    @staticmethod
    def uniform(a: float, b: float) -> float:
        return (a + b) / 2

    @staticmethod
    def choice(seq):
        return seq[0]


NO_LUCK = _NoLuck()


LUCK_EXPECTED = True    # estimates count a chance that scores by its expectation (a Lucky card's +20 Mult 1 in 5 as
                        # +4, Bloodstone's X1.5 1 in 2 as X1.25), not as never coming off; a win still has to be sure.
                        # A run's own `expect_luck`, when set, decides instead. 29 Oct: a Flush (296) was played over a
                        # Straight holding two Lucky cards (260, 780 on average) with 1,000 to go. Ante 8 beaten +0.8 ±
                        # 1.3 and -0.6 ± 1.4 points on the two sets, progress +0.04 and +0.13: level, kept as a fix


def expects_luck(run) -> bool:
    return getattr(run, "expect_luck", LUCK_EXPECTED)


def chancy(run, played) -> bool:
    """Could a chance change what these cards score (a Lucky card among them, Bloodstone)?"""
    return any(c.enhancement == "Lucky" for c in played) or any(j.name == "Bloodstone" for j in run.jokers)


def estimate(run, played, held, result=None, sure=False, rng=None) -> int:
    """What playing these cards would score now (chance effects don't trigger, nothing changed; with expects_luck,
    unless `sure`, those that score count as their expectation; with `rng`, they are rolled from it)."""
    result = result or evaluate(played, run.rules)
    boss = run.active_boss
    if boss is not None and not boss.allows(run, result, played):
        return 0
    ctx = HandContext(run, played, held, result, rng or NO_LUCK, estimating=True,
                      expecting=rng is None and not sure and expects_luck(run))
    money = run.money if boss is None else boss.money_when_scored(run, result, played)
    if money == run.money:
        return score_hand(ctx, run.hand_levels[result.name], boss).total
    saved, run.money = run.money, money              # The Ox, The Tooth: Bull and Bootstraps see what is left
    try:
        return score_hand(ctx, run.hand_levels[result.name], boss).total
    finally:
        run.money = saved


def surely_wins(run, total, idx, need) -> bool:
    """Does the play at these positions in hand, estimated at `total`, reach `need` with no chance coming off?"""
    played = [run.hand[i] for i in idx]
    if any(c.face_down for c in played):            # what a face-down card is isn't known: never a sure win (and
        return False                                # nothing here reads it)
    if total < need or not expects_luck(run):
        return total >= need
    if not chancy(run, played):
        return True
    held = [c for i, c in enumerate(run.hand) if i not in idx and not c.face_down]
    return estimate(run, played, held, sure=True) >= need


LUCK_SAMPLES = 200      # rolls of a play's luck when its chance of reaching a target is wanted (win_odds)


def win_odds(run, idx, need, samples: int = LUCK_SAMPLES) -> float:
    """The chance the play at these positions in hand reaches `need`: 1 or 0 with nothing left to chance (Lucky
    cards, Bloodstone, Misprint), else the share of `samples` rolls of its luck that get there (each play rolled from
    the same seed)."""
    played = [run.hand[i] for i in idx]
    held = [c for i, c in enumerate(run.hand) if i not in idx and not c.face_down]
    down = [k for k, i in enumerate(idx) if run.hand[i].face_down]
    if down:                                        # face-down cards: over what they could be (down_pool), never as
        pool = down_pool(run, run.hand)             # they are
        if len(pool) < len(down):
            return 0.0
        rng = random.Random(f"{getattr(run, 'seed', '')}|{run.rounds_played}|{run.hands_played}|odds-down")
        hits = 0
        for _ in range(FACE_DOWN_SAMPLES):
            seen = dict(zip(down, rng.sample(pool, len(down))))
            hits += estimate(run, [seen.get(k, c) for k, c in enumerate(played)], held, sure=True) >= need
        return hits / FACE_DOWN_SAMPLES
    if not (chancy(run, played) or any(j.name == "Misprint" for j in run.jokers)):
        return float(estimate(run, played, held, sure=True) >= need)
    rng = random.Random(f"{getattr(run, 'seed', '')}|{run.rounds_played}|{run.hands_played}|odds")
    return sum(estimate(run, played, held, rng=rng) >= need for _ in range(samples)) / samples


BASE_CARD_EFFECTS = True   # the cheap ranking counts the scoring cards' own enhancements and editions too: without
                           # them a Glass 3 alone never reached full scoring, so the bot couldn't see it as a play and
                           # used Justice on the 3 it then threw away, not on the J it would play (the user's
                           # 6AWQ2FCT, ante 9: J alone 53,130 against K's 41,349). A correctness fix: on


def base_value(run, played, result) -> float:
    """Hand level chips x mult plus the scoring cards' chips (a debuffed card's count for nothing), and with
    BASE_CARD_EFFECTS their enhancements' and editions' chips, Mult and X Mult: a cheap ranking before full scoring."""
    return base_at_level(result.name, run.hand_levels[result.name], played, result)


def base_at_level(name: str, level: int, played, result) -> float:
    """base_value with poker hand `name` at `level`."""
    chips, mult = hand_base(name, level)
    times = 1.0
    for i in result.scoring:
        c = played[i]
        if c.debuffed:
            continue
        chips += 50 if c.is_stone else rank_chips(c.rank) + c.bonus_chips
        if not BASE_CARD_EFFECTS:
            continue
        if c.enhancement == "Bonus":
            chips += 30
        elif c.enhancement == "Mult":
            mult += 4
        elif c.enhancement == "Glass":
            times *= 2
        if c.edition == "Foil":
            chips += 50
        elif c.edition == "Holographic":
            mult += 10
        elif c.edition == "Polychrome":
            times *= 1.5
    return chips * mult * times


KICKERS = True     # among plays ranked alike, those that keep Steel and Gold cards and Blue Seals in hand first


def held_kickers(played, result) -> int:
    """Cards played that don't score but would pay for staying in hand (Steel's X1.5, Gold's $3, a Blue Seal's
    Planet): a play padded with one of them (The Psychic, a kicker) loses that. 0 with KICKERS off."""
    if not KICKERS:
        return 0
    return sum(1 for i, c in enumerate(played) if i not in result.scoring
               and (c.enhancement in ("Steel", "Gold") or c.seal == "Blue"))


def best_play(run, max_size: int = 5, hand=None, top: int = 10, bonus=None, need=None) -> tuple[int, list[int]]:
    """The highest-scoring set of 1-5 cards in hand right now (or in `hand`). Every set is ranked by its
    poker hand cheaply; the best `top` overall and the best two of each size and of each poker hand get the
    full scoring with jokers (which can favour a smaller or different hand). Face-down cards are unknown,
    so they are only played when nothing else is left. With `bonus(played, result)` (what a play is worth
    beyond its score, in power: the log of the score) the best is by log score plus bonus; if some plays reach
    `need`, the best of them by bonus alone (what a winning hand scores beyond the blind is worth nothing), then
    score. Returns the chosen play's score and positions."""
    plays = ranked_plays(run, max_size, hand, top, bonus, need)
    if not plays:                                   # every card face down (The House): up to five, blind, score unknown
        hand = run.hand if hand is None else hand
        return -1, list(range(min(max_size, len(hand)))) or [0]
    return plays[0][0], plays[0][1]


FACE_DOWN_PLAYS = True   # plays with face-down cards in them weighed too, on what those cards could be: never played
FACE_DOWN_SAMPLES = 16   # before, so under The Mark (face cards face down: five of them hold a pair at least) the hand
                         # filled with them by the round's end (the user's catch and the review's m5, 29 Oct)


def down_pool(run, hand) -> list:
    """What a face-down card in `hand` can be, as a player knows it: one of the cards not seen (the draw pile and the
    face-down cards, face up, by uid: nothing of which is where); under The Mark, which draws exactly the face cards face
    down, one of those."""
    pool = sorted([c for c in run.draw_pile] + [_face_up(c) for c in hand if c.face_down], key=lambda c: c.uid)
    boss = run.active_boss
    if boss is not None and boss.name == "The Mark":
        faces = [c for c in pool if c.is_face(run.pareidolia)]
        pool = faces or pool
    return pool


def _face_up(c):
    from dataclasses import replace
    return replace(c, face_down=False)


def _down_plays(run, hand, known_plays, max_size, need, bonus) -> list:
    """The plays with face-down cards: all of them alone (up to max_size), and each of `known_plays` filled with them,
    each weighed over FACE_DOWN_SAMPLES draws of what they are (down_pool, the same draws for every play): (key, mean
    score, positions, poker hand of the first draw). Never a sure win (wins False): what they are isn't known."""
    down = [i for i, c in enumerate(hand) if c.face_down]
    pool = down_pool(run, hand)
    if not down or len(pool) < len(down):
        return []
    rng = random.Random(f"{getattr(run, 'seed', '')}|{run.rounds_played}|{run.round_hands_played}|{len(run.draw_pile)}|down")
    draws = [rng.sample(pool, len(down)) for _ in range(FACE_DOWN_SAMPLES)]
    sets = {tuple(down[:k]) for k in range(1, min(max_size, len(down)) + 1)}
    for idx in known_plays:
        room = max_size - len(idx)
        if room > 0:
            sets.add(tuple(sorted(tuple(idx) + tuple(down[:room]))))
    out = []
    for idx in sets:
        held = [c for i, c in enumerate(hand) if i not in idx and not c.face_down]
        totals, logs, extras, first = [], [], [], None
        for d in draws:
            seen = dict(zip(down, d))
            played = [seen.get(i, hand[i]) for i in idx]
            r = evaluate_cached(played, run.rules)
            first = first or r
            t = estimate(run, played, held, r)
            totals.append(t)
            logs.append(math.log1p(max(t, 0)))
            if bonus is not None:
                extras.append(bonus(played, r))
        total = int(sum(totals) / len(totals))
        if bonus is None:
            key = (total,) if need is None else (False, total)
        else:
            key = (False, sum(extras) / len(extras) + sum(logs) / len(logs), total)
        out.append((key, total, list(idx), first))
    return out


def ranked_plays(run, max_size: int = 5, hand=None, top: int = 10, bonus=None, need=None) -> list[tuple[int, list[int], object]]:
    """The plays best_play weighs, best first (as best_play ranks them): (score, positions, poker hand). Cards face
    down are not counted as held (Steel, Baron...): what they are, a player doesn't know (with all of them face down it
    used to weigh the hidden cards as they were, 27 Oct). With FACE_DOWN_PLAYS, in the hand dealt, plays with them in
    are weighed on what they could be (_down_plays)."""
    hand = run.hand if hand is None else hand
    rules = run.rules
    known = [i for i, c in enumerate(hand) if not c.face_down]
    ranked = []
    for size in range(1, min(max_size, len(known)) + 1):
        for idx in combinations(known, size):
            played = [hand[i] for i in idx]
            r = evaluate_cached(played, rules)
            ranked.append((base_value(run, played, r), idx, r, played))
    ranked.sort(key=lambda t: (-t[0], held_kickers(t[3], t[2])))      # a tie: the one keeping what pays held
    chosen, per_size, per_hand = {}, {}, {}
    for v, idx, r, played in ranked:
        n_size, n_hand = per_size.get(len(idx), 0), per_hand.get(r.name, 0)
        # (with a bonus, a Lucky card alone too: the play that rolls its $20 most once the round is won anyway, its
        # retriggers all on it; a lone 2 never ranked among the best two of its size: the user's 6AWQ2FCT, The Goad)
        lucky_alone = bonus is not None and len(idx) == 1 and played[0].enhancement == "Lucky"
        if len(chosen) < top or n_size < 2 or n_hand < 2 or lucky_alone:
            chosen[idx] = (r, played)
            per_size[len(idx)] = n_size + 1
            per_hand[r.name] = n_hand + 1
    out = []
    luck = expects_luck(run)
    for idx, (r, played) in chosen.items():
        held = [c for i, c in enumerate(hand) if i not in idx and not c.face_down]
        total = estimate(run, played, held, r)
        wins = (need is not None and total >= need
                and not (luck and chancy(run, played) and estimate(run, played, held, r, sure=True) < need))
        if bonus is None:
            key = (total,) if need is None else (wins, total)
        else:
            key = (wins, bonus(played, r) + (0.0 if wins else math.log1p(total)), total)
        out.append((key, total, list(idx), r))
    if FACE_DOWN_PLAYS and hand is run.hand and known and any(c.face_down for c in hand):
        out += _down_plays(run, hand, list(chosen)[:top], max_size, need, bonus)
    out.sort(key=lambda t: t[0], reverse=True)      # stable: of equal plays, the first weighed comes first
    return [(total, idx, r) for _, total, idx, r in out]


def multiplies(joker) -> bool:
    """Does this joker give xMult (so it should come after the +Mult jokers)?"""
    return any("xmult" in k or "x_mult" in k for k in (JOKER_DATA.get(joker.name, {}).get("values") or {}))  # growing ones too


def joker_order(jokers) -> list[int]:
    """+Chips and +Mult jokers first, xMult jokers last so they multiply everything, and Blueprint just left
    of the last xMult joker so it copies one. An edition counts too: an xMult joker that is Holographic (+10 Mult)
    leads the xMult ones, so the rest multiply its +10, and a + joker that is Polychrome (x1.5) ends the + ones."""
    def key(i):
        j = jokers[i]
        x = j.name not in ("Blueprint", "Brainstorm") and multiplies(j)
        return (x, j.edition != "Holographic" if x else j.edition == "Polychrome", i)
    order = sorted(range(len(jokers)), key=key)
    blueprints = [i for i in order if jokers[i].name == "Blueprint"]
    rest = [i for i in order if jokers[i].name != "Blueprint"]
    x = [k for k, i in enumerate(rest) if multiplies(jokers[i]) and jokers[i].copyable]
    at = x[-1] if x else len(rest)
    return rest[:at] + blueprints + rest[at:]


COPIERS = ("Blueprint", "Brainstorm")


def copy_fires(jokers) -> list[int]:
    """How many times each joker's effects go off in this order: once itself, once more for each copier whose copy
    reaches it (Blueprint copies the joker to its right, Brainstorm the leftmost; a copier on a copier passes on that
    one's target; one reached again copies nothing, as the engine's guard has it); a copier itself 0."""
    out = [0 if j.name in COPIERS else 1 for j in jokers]
    for k, j in enumerate(jokers):
        if j.name not in COPIERS:
            continue
        seen, t = {k}, k
        while t is not None and jokers[t].name in COPIERS:
            nxt = t + 1 if jokers[t].name == "Blueprint" else 0
            t = None if nxt >= len(jokers) or nxt in seen or not jokers[nxt].copyable else nxt
            if t is not None:
                seen.add(t)
        if t is not None:
            out[t] += 1
    return out


def copier_orders(jokers) -> list[list[int]]:
    """The orders worth trying when Blueprint (copies the joker to its right) or Brainstorm (copies the leftmost)
    is there, the usual one first. Only + before x matters (+Chips and +Mult jokers first, so the xMult ones
    multiply them; xMult jokers commute), so the choices are what goes leftmost for Brainstorm (the usual order's
    first, or any joker it can copy, which then acts before the + jokers) and what Blueprint copies: any joker it
    can, standing just left of it, or Brainstorm, which passes on the leftmost's (so a big xMult joker leftmost
    counts three times). A copy of an xMult joker goes last, with the xMult jokers; of a + joker, with the + ones.
    (It tried 14 orders for 7 jokers and never Blueprint on Brainstorm: a person found 2.35M a hand where its pick
    made 1.75M.)"""
    base = joker_order(jokers)
    copier = lambda i, name: jokers[i].name == name                                       # noqa: E731
    blue = next((i for i in base if copier(i, "Blueprint")), None)
    storm = next((i for i in base if copier(i, "Brainstorm")), None)
    if blue is None and storm is None:
        return [base]
    extra = [i for i in base if copier(i, "Blueprint") or copier(i, "Brainstorm")]
    extra = [i for i in extra if i not in (blue, storm)]                                # a second copier: last
    plain = [i for i in base if not (copier(i, "Blueprint") or copier(i, "Brainstorm"))]
    targets = [i for i in plain if jokers[i].copyable]
    x = lambda i: multiplies(jokers[i])                                                  # noqa: E731

    def place(row: list, c: int, target: int | None) -> list:
        """`c` into `row`: just left of `target`, or with the kind of joker it copies (`target` None: Brainstorm's
        copy of the leftmost)."""
        if target is not None:
            k = row.index(target)
            return row[:k] + [c] + row[k:]
        if row and x(row[0]):
            return row + [c]
        k = next((k for k, i in enumerate(row) if k and x(i)), len(row))
        return row[:k] + [c] + row[k:]

    out, seen = [base], {tuple(base)}
    for left in [None] + (targets if storm is not None else []):
        row = ([left] if left is not None else []) + [i for i in plain if i != left]
        if storm is not None:
            row = place(row, storm, None)
        for bt in ([None] if blue is None else [t for t in targets if t != left or storm is None]
                   + ([storm] if storm is not None else [])):
            order = row if blue is None else place(row, blue, bt)
            order = order + extra
            if tuple(order) not in seen:
                seen.add(tuple(order))
                out.append(order)
    return out


class GreedyBot(Agent):
    """Plays the best hand available and discards the rest when that won't get there in time. Buys any
    joker it can afford, uses Planet cards at once, picks jokers and Planets from packs, and keeps its
    jokers ordered +Mult first, xMult last."""

    def _reorder(self, run):
        order = joker_order(run.jokers)
        if not run.in_round:
            # what comes next is a blind's selection, when Ceremonial Dagger destroys the joker to its right:
            # rightmost, it has none (in a round the jokers go back to the order for scoring)
            order = ([i for i in order if run.jokers[i].name != "Ceremonial Dagger"]
                     + [i for i in order if run.jokers[i].name == "Ceremonial Dagger"])
        return ("order_jokers", order) if order != list(range(len(run.jokers))) else None

    def round_action(self, run):
        reorder = self._reorder(run)
        if reorder:
            return reorder
        planet = self._planet(run)
        if planet is not None:
            return ("use", planet, [])
        best, idx = best_play(run)
        needed = run.blind.chips - run.round_score
        if run.discards_left > 0 and best * run.hands_left < needed:
            keep = set(idx)
            junk = [i for i in range(len(run.hand)) if i not in keep][:5]
            if junk:
                return ("discard", junk)
        return ("play", idx)

    @staticmethod
    def _planet(run) -> int | None:
        return next((i for i, c in enumerate(run.consumables) if c.kind == "Planet"), None)

    def shop_action(self, run, shop):
        reorder = self._reorder(run)
        if reorder:
            return reorder
        planet = self._planet(run)
        if planet is not None:
            return ("use", planet, [])
        spend = run.money - run.debt_limit
        for i, offer in enumerate(shop.cards):
            if cost_of(run, offer) > spend:
                continue
            if isinstance(offer.item, Joker) and run.joker_room(offer.item):
                return ("buy", "card", i)
            if offer.kind == "Planet":
                return ("buy_use", i, [])
        for i, offer in enumerate(shop.packs):
            if offer.item.kind in ("Buffoon", "Celestial") and cost_of(run, offer) <= spend:
                if offer.item.kind == "Celestial" or run.joker_room():
                    return ("buy", "pack", i)
        return ("leave",)

    def pack_action(self, run, pack):
        for i, item in enumerate(pack.cards):
            if isinstance(item, Joker) and run.joker_room(item):
                return ("pick", i, [])
            if isinstance(item, Consumable) and item.kind == "Planet":
                return ("pick", i, [])
        return ("skip",)
