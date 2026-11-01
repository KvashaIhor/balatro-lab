"""Strategies that play a whole run: SmartBot (a greedy base) and the value bot built on it.

They choose hands, discards, purchases, pack picks and consumable use. The Seed Planner searches over their
decisions; what it doesn't search, they play.
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
import os
import random
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path

from .bots import (COPIERS, GreedyBot, base_at_level, base_value, best_play, copier_orders, estimate, held_kickers,
                   joker_order, ranked_plays, surely_wins, win_odds)
from .cards import Card, rank_chips
from .hands import evaluate_cached
from . import pool
from .items import BOSSES, CONSUMABLES, Consumable, data, entries
from .modifiers import (COPIED_ON_DISCARD, INCOME, OFF as MOD_OFF, RULES as MOD_RULES, TOLL_BOSSES, Measure, card_bonus,
                        discard_bonus, discard_fires, discard_options,
                        gold_money, held_triggers, income, lucky_each, planet_bonus, play_bonus, reroll_bonus, round_dollars, rounds_left, sell_bonus, skip_bonus, strength,
                        final_round, shops_left, spend_cost, timed)
from .joker_classes import CLASSES, JOKER_CLASSES
from .scoring import hand_base
from .jokers import CATALOG, Joker
from .engines import ENGINES, SHOPS_AN_ANTE, cards_seen, joker_chance, pack_cards_seen, shops_ahead
from .shop import PACK_WEIGHTS, PACKS, cost_of

SUIT_SYMBOL = {"Spades": "♠", "Hearts": "♥", "Clubs": "♣", "Diamonds": "♦"}
# The Wheel of Fortune is left out: its roll isn't modelled exactly, so a plan using it could part ways
# with the game.
NO_TARGET_TAROTS = {"The Hermit", "Temperance", "The Emperor", "The High Priestess", "Judgement", "The Fool"}
ENHANCING = {"The Empress": "Mult", "The Hierophant": "Bonus", "The Magician": "Lucky", "The Lovers": "Wild",
             "Justice": "Glass", "The Devil": "Gold", "The Chariot": "Steel"}
SUIT_TAROT = {"The Star": "Diamonds", "The Moon": "Clubs", "The Sun": "Hearts", "The World": "Spades"}
XMULT_HAND = {"The Duo": ("Pair", 2), "The Trio": ("Three of a Kind", 3), "The Family": ("Four of a Kind", 4),
              "The Order": ("Straight", 3), "The Tribe": ("Flush", 2)}   # xMult when the played cards hold that hand


def _top_sum(values: list, k: int, m: int) -> float:
    """The expected sum of the best `m` of `k` drawn without repeats from `values` (sorted best first): each value
    counts by the chance it is drawn with fewer than `m` better ones."""
    n = len(values)
    k = min(k, n)
    if k <= 0 or m <= 0:
        return 0.0
    total = math.comb(n, k)
    return sum(v * sum(math.comb(i, j) * math.comb(n - i - 1, k - 1 - j) for j in range(min(m, i + 1))) / total
               for i, v in enumerate(values))


def _reaches(cards, hand: str, rules) -> bool:
    """Do these cards hold `hand` (as a poker hand some five of them make)? Counted by ranks and suits: Pair,
    Three and Four of a Kind; Flush (Wild cards fit any suit, Smeared Joker joins the colours, Four Fingers needs
    four); Straight (five ranks in a row, four with Four Fingers, the Ace low or high; Shortcut not counted)."""
    plain = [c for c in cards if not c.is_stone]
    if hand in ("Pair", "Three of a Kind", "Four of a Kind"):
        need = {"Pair": 2, "Three of a Kind": 3, "Four of a Kind": 4}[hand]
        return max(Counter(c.rank for c in plain).values(), default=0) >= need
    need = 4 if rules.four_fingers else 5
    if hand == "Flush":
        wild = sum(c.enhancement == "Wild" for c in plain)
        counts = Counter(c.suit for c in plain if c.enhancement != "Wild")
        if rules.smeared:
            counts = Counter({"red": counts["Hearts"] + counts["Diamonds"], "black": counts["Spades"] + counts["Clubs"]})
        return max(counts.values(), default=0) + wild >= need
    if hand == "Straight":
        ranks = {c.rank for c in plain} | ({1} if any(c.rank == 14 for c in plain) else set())
        return any(all(r + k in ranks for k in range(need)) for r in range(1, 15))
    return False
ARCANA_PRIORITY = ["Judgement", "The Hermit", "The Emperor", "Temperance", "The Empress", "The Hierophant", "The Lovers",
                   "The Magician", "Justice", "Strength", "The Devil", "The High Priestess",
                   "The Star", "The Moon", "The Sun", "The World", "The Chariot", "The Hanged Man", "The Fool"]
# Spectral cards whose cost can outweigh them (other jokers destroyed, hand size, money): kept unless the
# search finds that using one pays.
SITUATIONAL = {"Ankh", "Hex", "Ectoplasm", "Wraith", "Ouija", "Immolate", "Sigil"}
SEALING = {"Talisman", "Deja Vu", "Trance", "Medium"}


def held_value(c: Card) -> bool:
    """Does this card pay for staying in hand? Gold ($3 if held as the round ends), Steel (x1.5 Mult while
    held), Blue Seal (a Planet if held as the round ends)."""
    return c.enhancement in ("Gold", "Steel") or c.seal == "Blue"


def card_worth(c: Card) -> float:
    """A rough worth of a card for Death to copy: its chips, plus what its enhancement, seal and edition add."""
    return ((50 if c.is_stone else min(c.rank, 11)) + 10 * (c.enhancement not in (None, "Stone"))
            + 10 * (c.seal is not None) + 10 * (c.edition is not None))


LOOKS = ("rank", "suit", "enhancement", "edition", "seal", "bonus_chips")


def _looks(c: Card) -> tuple:
    """Everything about a card that a consumable can change."""
    return tuple(getattr(c, a) for a in LOOKS)


def _joker_state(j) -> tuple:
    """A joker's own values (what it has grown to, its edition...): what changes about it in place."""
    return tuple(sorted((k, v) for k, v in vars(j).items() if isinstance(v, (int, float, str, bool, type(None)))))


def _base_at(levels, played, result) -> float:
    """bots.base_value at the given levels (ValueBot._candidates: the run's own, or those a level change is measured
    from)."""
    return base_at_level(result.name, levels[result.name], played, result)


def _base_at_level_1(played, result) -> float:
    """bots.base_value with the poker hand at level 1: chips x mult plus the scoring cards' chips (a debuffed card's
    count for nothing; with bots.BASE_CARD_EFFECTS their enhancements and editions too: a Glass card alone was never
    scored in power's sample hands either), a ranking no level changes (ValueBot._candidates)."""
    return base_at_level(result.name, 1, played, result)


def _as_scored(c: Card) -> Card:
    """The card as estimates should score it: a Lucky card as a Mult card, its expected +4 Mult (1 in 5 for +20;
    estimates never roll chances, so a Lucky card would otherwise count for nothing)."""
    if c.enhancement != "Lucky":
        return c
    stand_in = copy.copy(c)
    stand_in.enhancement = "Mult"
    return stand_in


def _outcome(run) -> tuple:
    """What an effect tried on a copy of the run left (jokers, deck, consumables, money, levels, sizes), to tell
    the ways a random one turned out apart; equal for the same outcome."""
    deck = sorted((c.rank, c.suit, c.enhancement or "", c.edition or "", c.seal or "", c.bonus_chips) for c in run.deck)
    return (tuple((j.name, j.edition or "") for j in run.jokers), tuple(deck), tuple(c.name for c in run.consumables),
            run.money, tuple(run.hand_levels.values()), run.base_hand_size, run.joker_slots, run.consumable_slots,
            tuple(t.name for t in run.tags))


def card_text(c: Card) -> str:
    if c.is_stone:
        return "Stone"
    return f"{ {11: 'J', 12: 'Q', 13: 'K', 14: 'A'}.get(c.rank, c.rank) }{SUIT_SYMBOL[c.suit]}"


class SmartBot(GreedyBot):
    """GreedyBot plus discards towards better hands (looking at the cards the deck will deal), and Tarot cards
    used."""

    # A discard is made when the best play after it scores this much more than the best play now: discards
    # left at the end of a round are lost, and a bigger hand wins the blind in fewer hands ($1 for each left).
    DISCARD_GAIN = 1.2
    DEAD_PLAYS = True  # with no discards left and nothing that scores, the play is chosen as a discard would be: it
                       # used to play whatever came first, throwing away the draws toward a hand The Eye still allows
    DRAWS = 6        # possible draws a discard is scored on (_discard)
    RERANK = 3       # the leading discards weighed again on RERANK_DRAWS other draws, which rank them: on 6 draws alone
    RERANK_DRAWS = 24  # 13% of 261 discard picks were 0.1 or more worse than a 32-draw pick (both pairs and a Flush draw
                       # thrown; a made Full House broken; the replay review's M2, 29 Oct)
    PEEK = False     # sees the deck order instead (the Seed Planner, whose seed is known)

    # ---- rounds -----------------------------------------------------------------------------------
    def round_action(self, run):
        """The round's next move, chosen with the jokers in their order for scoring; then the order that move wants
        (reordering is free): the scoring one for a play, for a discard the one where copiers repeat most of what
        it pays (Blueprint and Brainstorm on Burnt Joker for the round's first: its level up three times). Face-down
        cards are unknown to it, except with PEEK (the Seed Planner knows the seed, so what they are)."""
        self._live = run                                    # the run being played (the build plan's, not a copy's)
        sale = self._leaf_sale(run) if getattr(self, "VERDANT_SALE", False) else None
        if sale is not None:                                # Verdant Leaf lifted by a joker sold
            return ("sell_joker", sale)
        sale = self._dead_sale(run) if hasattr(self, "_dead_sale") else None
        if sale is not None:                                # a joker worth less kept than sold, before the first hand
            return ("sell_joker", sale)
        boss = run.active_boss                              # Amber Acorn: the jokers face down and shuffled. Those its
        known = boss.known(run) if boss is not None and boss.name == "Amber Acorn" and getattr(boss, "shuffled", False) \
            else None                                       # hands have shown (their effects their own: the user) are
        hidden = known is not None and len(known) < len(run.jokers)   # where they are; the rest in the order last
        down = [c for c in run.hand if c.face_down] if self.PEEK else []    # seen; none moved till all are known
        for c in down:
            c.face_down = False
        try:
            saved = run.jokers
            if hidden:
                order = None
                rest = iter([j for j in boss.before if any(j is x for x in saved) and id(j) not in known]
                            + [j for j in saved if not any(j is x for x in boss.before) and id(j) not in known])
                run.jokers = [j if id(j) in known else next(rest) for j in saved]
            else:
                order = self._play_order(run)
                if order:
                    run.jokers = [saved[i] for i in order]
            try:
                action = self._round_choice(run)
            finally:
                run.jokers = saved
        finally:
            for c in down:
                c.face_down = True
        if hidden:
            return action
        if action[0] == "discard":
            want = self._discard_plan(run)[0]
        elif action[0] == "play":
            dna, want = self._first_hand_plan(run, action[1])   # a one-card first hand for DNA: copiers on DNA
            want = want if dna else order
        else:
            want = None
        return ("order_jokers", want) if want else action

    def _discard_plan(self, run) -> tuple[list[int] | None, dict | None]:
        """For a discard: the joker order to put them in (None: as they are), and how many times each one's
        effects go off in it (None: as they are). Only the value bot weighs what discards pay."""
        return None, None

    def _first_hand_plan(self, run, idx) -> tuple[bool, list[int] | None]:
        """For a play: whether it wants the jokers in an order of its own rather than the scoring one, and that
        order (None: as they are). Only the value bot plays for DNA."""
        return False, None

    def _dna_play(self, run, needed: float, mods) -> list[int] | None:
        """A card to play alone as the round's first hand, for DNA. Only the value bot weighs it."""
        return None

    def _padded(self, run, idx, mods) -> list[int]:
        """The play with dead cards added, to draw more (the value bot does, with no discards left)."""
        return idx

    def _round_choice(self, run):
        use = self._use(run)
        if use:
            return use
        needed = run.blind.chips - run.round_score
        mods = self._measure(run)
        dna = self._dna_play(run, needed, mods)
        if dna:
            return ("play", dna)
        if mods:                                            # what the jokers make of each play, beyond its score
            best, idx = best_play(run, bonus=lambda played, r: play_bonus(self, mods, played, r), need=needed)
        else:
            best, idx = best_play(run, need=needed)
        plan = self._hand_type_plan(run, needed, mods) if not surely_wins(run, best, idx, needed) else None
        if plan:
            best, idx = plan
        wins = surely_wins(run, best, idx, needed)          # (best by expected luck with bots.LUCK_EXPECTED)
        if not wins and run.hands_left == 1 and self.LAST_HAND_ODDS:
            best, idx = self._likeliest(run, best, idx, needed, mods)
        if run.discards_left == 0 and best <= 0 and run.hands_left > 1 and self.DEAD_PLAYS:
            ranked = self._ranked_discards(run, idx, mods, everything=True)   # nothing scores (The Eye, The Mouth):
                                                            # the play is a discard
            if ranked:                                      # in all but name, the cards that build toward a hand kept
                return ("play", ranked[0][1])
        if run.discards_left == 0:
            return ("play", self._padded(run, idx, mods))
        if wins and getattr(self, "MILK_WON", False) and mods:   # a sure win kept in hand: a spare hand for what pays
            milk = self._milk_play(run, idx, mods, best, needed)
            if milk:
                return ("play", milk)
        if not wins and getattr(self, "MILK_LIKELY", False) and mods and self._likely_after_milk(run, best, needed):
            milk = self._milk_play(run, idx, mods, best, needed, likely=True)   # not sure in hand, but surely won with
            if milk:                                                             # the hands left: a spare one for pay
                return ("play", milk)
        if wins:                                            # this hand wins: discard first only what a joker pays for
            disc = self._paid_discard(run, idx, mods) if mods else None
            return ("discard", disc) if disc else ("play", idx)
        if getattr(self, "BEHIND_DIG", False) and run.discards_left > 0:   # below what each hand left must average:
            dig = self._dig(run, idx, best, needed)                         # the discard likeliest to get there
            if dig:
                return ("discard", dig)
        after, disc, extra = self._discard(run, idx, mods)
        if disc and self._worth_discarding(run, best, after, needed, extra):
            return ("discard", disc)
        return ("play", idx)

    BEHIND_STRICT = False   # behind (this hand every hand short of what is needed), a discard needs the usual 1.2x
                            # (DISCARD_GAIN) like any other, not any gain at all: builds whose later hands outscore this
                            # one (Card Sharp, Misprint, Verdant Leaf before the sale) burnt every discard before the first
                            # play. The review agent's round lab (31 Oct, runs/agent-review-20261031): +1.40 ± 0.68 round
                            # wins per contested round, flips +25 / -4. Off until measured
    BEHIND_DIG = False   # a hand below what each hand left must average (needed / hands left), discards left and no joker
                         # paying for them kept: the discard likeliest to make the next hand reach that average, not the
                         # one best on average (a loss ends the run). The user's CCU44VLE (30 Oct): ante 7's Big Blind,
                         # 52,500 in 5 hands; a Pair of 7s for 9,333 was played where a discard reached 10,500 one time
                         # in 5, and the round ended with its 3 discards unused. Off until measured
    DIG_DRAWS = 48
    DIG_KEEPERS = ("Banner", "Delayed Gratification", "Green Joker", "Ramen")   # jokers that pay for discards kept

    def _dig(self, run, idx, best, needed) -> list[int] | None:
        """BEHIND_DIG's discard, or None: the hand's best play (`best`, at `idx`) short of needed / hands left, the
        discard among _discard_options whose next hand reaches that in the most of DIG_DRAWS draws (a tie: the better
        mean log score), if any does."""
        target = needed / max(1, run.hands_left)
        if best >= target or any(j.name in self.DIG_KEEPERS for j in run.active_jokers()):
            return None
        hand = run.hand
        rng = random.Random(f"{run.seed}|{run.rounds_played}|{run.round_hands_played}|{run.discards_left}|dig")
        pool = self._unseen(run)
        draws = [rng.sample(pool, min(len(run.draw_pile), run.hand_size)) for _ in range(self.DIG_DRAWS)]
        boss = run.active_boss
        best_opt, best_key = None, (0.0, 0.0)
        run.discards_left -= 1
        try:
            for opt in self._discard_options(run, idx):
                kept = [c for i, c in enumerate(hand) if i not in opt]
                n = run.hand_size - len(kept)
                if boss:
                    n = boss.draw_count(run, n, "discard")
                scores = [best_play(run, hand=kept + (d[:n] if n > 0 else []))[0] for d in draws]
                key = (sum(s >= target for s in scores) / len(scores),
                       sum(math.log1p(max(s, 0)) for s in scores) / len(scores))
                if key[0] > 0 and key > best_key:
                    best_opt, best_key = list(opt), key
        finally:
            run.discards_left += 1
        return best_opt

    LAST_HAND_ODDS = False   # on the round's last hand with no play sure to win, the play likeliest to reach the target
                             # (win_odds: its Lucky cards, Bloodstone, Misprint rolled), not the best on average: a sure
                             # Flush of 296 never makes 500, a pair of Kings with a Lucky one (180 on average) does 1 in 5.
                             # Off until measured

    def _likeliest(self, run, best, idx, needed, mods) -> tuple[int, list[int]]:
        """The round's last hand, no play sure to win: of the plays weighed, the one likeliest to reach what the blind
        still needs; the chosen one unless another is likelier."""
        if best < 0:                                        # (every card face down: nothing to weigh)
            return best, idx
        bonus = (lambda played, r: play_bonus(self, mods, played, r)) if mods else None
        odds = win_odds(run, idx, needed)
        for total, other, _ in ranked_plays(run, bonus=bonus, need=needed):
            p = win_odds(run, other, needed)
            if p > odds:
                best, idx, odds = total, other, p
        return best, idx

    def _measure(self, run):
        """A Measure for the behaviour modifiers (modifiers.py); they measure with the value bot's power, so this
        bot has none."""
        return None

    def _hand_type_plan(self, run, needed: float, mods) -> tuple[int, list[int]] | None:
        """Under The Mouth (only the round's first poker hand scores) or The Eye (no poker hand scores twice), the
        play whose round adds up best, when no play wins now: of each poker hand's best play, its score plus, for
        each hand left after it, the best a later hand typically makes of a poker hand still allowed (The Mouth:
        the same; The Eye: each other one once), capped at what the blind still needs; the higher score now on a
        tie. A later hand is the cards kept plus a refill, DRAWS of them (the same draws for every play). None when
        the poker hand doesn't matter. (On 100 seeds, 6 of 80 runs lost died on The Mouth and 6 on The Eye: one
        opened The Mouth with a Straight it never made again over a Pair of level 4.)"""
        boss = run.active_boss
        if (boss is None or boss.name not in ("The Mouth", "The Eye") or run.hands_left <= 1
                or (boss.name == "The Mouth" and run.round_hands_played)):
            return None
        bonus = (lambda played, r: play_bonus(self, mods, played, r)) if mods else None
        firsts: dict[str, tuple[int, list[int]]] = {}
        for total, idx, r in ranked_plays(run, bonus=bonus, need=needed):
            if total > 0 and r.name not in firsts:
                firsts[r.name] = (total, idx)
        if len(firsts) < 2:
            return None
        pile = sorted(run.draw_pile, key=lambda c: c.uid)      # its cards, not the order they lie in (m6)
        rng = random.Random(f"{run.seed}|{run.rounds_played}|{run.round_hands_played}|{len(pile)}|plan")
        odds = self.MOUTH_ODDS and boss.name == "The Mouth"
        draws = [rng.sample(pile, min(len(pile), run.hand_size)) for _ in range(self.RERANK_DRAWS if odds else self.DRAWS)]
        later = run.hands_left - 1
        best_key, choice = None, None
        for name, (now, idx) in firsts.items():
            rest = max(0, needed - now)
            kept = [c for i, c in enumerate(run.hand) if i not in idx]
            n = boss.draw_count(run, len(idx), "play")
            typical: Counter = Counter()
            made = []                                         # (MOUTH_ODDS) what a later hand scores of `name`, 0: not made
            for d in draws:
                tops: dict[str, int] = {}
                for total, _, r in ranked_plays(run, hand=kept + d[:n]):
                    tops.setdefault(r.name, total)            # best first
                for t, total in tops.items():
                    typical[t] += min(max(total, 0), rest) / len(draws)
                made.append(max(tops.get(name, 0), 0))
            if odds:                                          # the chance enough later hands make it to cover the rest
                key = (self._mouth_odds(made, rest, later), now)
                if best_key is None or key > best_key:
                    best_key, choice = key, (now, idx)
                continue
            if boss.name == "The Mouth":
                after = later * typical[name]
            else:
                after = sum(sorted((v for t, v in typical.items() if t != name), reverse=True)[:later])
            key = (min(now + after, needed), now)
            if best_key is None or key > best_key:
                best_key, choice = key, (now, idx)
        return choice

    MOUTH_ODDS = False   # The Mouth's opening type chosen by the chance the round reaches its target with it (a later
                         # hand makes it with the share of draws that do, scoring what those do: enough of them, of the
                         # hands left), not by its capped mean: the user (29 Oct, 6X7SCM12): play for the odds when
                         # behind. Off until measured

    @staticmethod
    def _mouth_odds(made: list, rest: float, later: int) -> float:
        """The chance `later` hands, each scoring like one of `made` (0: the poker hand not made), cover `rest`: with p the
        share made and s their mean score, at least ceil(rest / s) of them made (binomial)."""
        if rest <= 0:
            return 1.0
        hits = [m for m in made if m > 0]
        if not hits or later < 1:
            return 0.0
        p, s = len(hits) / len(made), sum(hits) / len(hits)
        k = math.ceil(rest / s)
        if k > later:
            return 0.0
        return sum(math.comb(later, i) * p ** i * (1 - p) ** (later - i) for i in range(k, later + 1))

    PAID_WON = True    # a paid discard made when the hand kept still wins with a discard fewer doesn't count Banner's
                       # chips lost (this round's score only): C5X6MXUN (28 Oct), ante 3's Big Blind won 5,610 to 3,000,
                       # and the bot wouldn't throw Mail-In Rebate's 9 for $5 (+0.10) for Banner's 30 chips (-0.20).
                       # A fix, level, adopted 28 Oct: +0.2 +- 0.2 and -0.6 +- 0.4 points

    def _paid_discard(self, run, keep_idx, mods) -> list[int] | None:
        """With the winning hand kept, the cards a joker (or a Purple Seal) pays to see discarded, if worth $1."""
        hand = run.hand
        sets = discard_options(run) + [{i for i, c in enumerate(hand) if c.seal == "Purple"}]
        fires = self._discard_plan(run)[1]                  # copies as they will stand for the discard
        won = self.PAID_WON and self._wins_after_discard(run, keep_idx)
        best, choice = PAID_DISCARD, None
        for s in sets:
            cards = sorted(i for i in s if i not in keep_idx and not hand[i].face_down and not held_value(hand[i]))[:5]
            if cards:
                v = discard_bonus(self, mods, [hand[i] for i in cards], fires, won)
                if v > best:
                    best, choice = v, cards
        return choice

    @staticmethod
    def _wins_after_discard(run, keep_idx) -> bool:
        """Does the hand kept still win the round with one discard fewer left (Banner's chips, Mystic Summit)?"""
        hand = run.hand
        played = [hand[i] for i in keep_idx]
        held = [c for i, c in enumerate(hand) if i not in keep_idx and not c.face_down]
        run.discards_left -= 1
        try:
            return estimate(run, played, held, evaluate_cached(played, run.rules)) >= run.blind.chips - run.round_score
        finally:
            run.discards_left += 1

    def _play_order(self, run) -> list[int] | None:
        """The joker order for the hand about to be played, if it isn't the present one: the usual order, or
        with Blueprint (copies the joker to its right) or Brainstorm (copies the leftmost), each placement of
        them that copies another joker, whichever scores this hand best (the present order wins ties)."""
        jokers = run.jokers
        orders = copier_orders(jokers)
        if len(orders) == 1:
            return orders[0] if orders[0] != list(range(len(jokers))) else None
        candidates = [list(range(len(jokers)))] + orders
        saved, best, choice = jokers, -1, None
        try:
            for cand in candidates:
                run.jokers = [saved[i] for i in cand]
                score = best_play(run)[0]
                if score > best:
                    best, choice = score, cand
        finally:
            run.jokers = saved
        return choice if choice != list(range(len(saved))) else None

    def _worth_discarding(self, run, now: float, after: float, needed: float, extra: float = 0.0) -> bool:
        """Discard when the next hand plus what the jokers make of the discard (`extra`, in power: Delayed
        Gratification's lost $2s, Green Joker's lost Mult, Mail-In Rebate's $5s...) beats playing now: if it wins
        the blind, or is 1.2x better. And whatever the next draw, when playing now is lost anyway:
        - nothing scores (The Mouth, The Eye): a hand played would be wasted;
        - the last hand can't win: a discard is the only chance (with more than one left, the next may find it);
        - playing like this every hand wouldn't get there: any better hand is worth a discard, and what a joker
          pays for keeping discards doesn't count against losing the round.
        On 480 seeds, 32 of the 72 runs lost in antes 1-4 died playing a hand like that with discards left."""
        if now <= 0:
            return True
        if run.hands_left <= 1 and now < needed:
            return after >= needed or run.discards_left > 1 or after > now
        gain = math.log1p(max(after, 0)) - math.log1p(max(now, 0))
        if now * run.hands_left < needed:
            if self.BEHIND_STRICT:
                return gain + extra >= math.log(self.DISCARD_GAIN)
            return gain > 0
        gain += extra
        if gain <= 0:
            return False
        if after >= needed:
            return True
        return gain >= math.log(self.DISCARD_GAIN)

    def _discard_options(self, run, keep_idx) -> set[tuple[int, ...]]:
        """Up to 5 cards to throw away: what the best play doesn't use, or whatever doesn't build towards a
        flush, a straight, more of a kind or high cards. Face-down cards go first (unknown, they could be any card left:
        one drawn is as good and seen), then Purple Seal cards (each discard of one makes a Tarot), then the lowest;
        cards that pay for being held (held_value) are never thrown away."""
        hand = run.hand
        seen = [i for i, c in enumerate(hand) if not c.face_down]

        def order(i) -> tuple:
            c = hand[i]
            return (0, False, 0) if c.face_down else (1, c.seal != "Purple", c.rank)

        def toss(keep) -> tuple[int, ...]:
            rest = sorted((i for i in range(len(hand)) if i not in keep and (hand[i].face_down or not held_value(hand[i]))),
                          key=order)
            return tuple(sorted(rest[:5]))
        options = {toss(set(keep_idx))}
        for suit in SUIT_SYMBOL:
            same = {i for i in seen if hand[i].has_suit(suit, run.smeared)}
            if len(same) >= 3:
                options.add(toss(same))
        ranks: dict[int, list[int]] = {}
        for i in seen:
            if not hand[i].is_stone:
                ranks.setdefault(hand[i].rank, []).append(i)
        for low in range(1, 11):                            # five ranks in a row; 1 is the Ace below the 2
            have = [ranks[r][0] for r in (14 if r == 1 else r for r in range(low, low + 5)) if r in ranks]
            if len(have) >= 3:
                options.add(toss(set(have)))
        kinds = {i for idx in ranks.values() if len(idx) >= 2 for i in idx}
        if kinds:
            options.add(toss(kinds))
        options.add(toss(set(sorted(seen, key=lambda i: -hand[i].rank)[:3])))
        options.discard(())
        return options

    @staticmethod
    def _unseen(run) -> list:
        """The cards a discard can draw, as a player knows them: the draw pile, and with cards face down in hand, those
        too (any of them could be where the face-down ones are), face up, in an order that tells nothing of the pile's
        (by uid: sampled from the pile as it lay, shuffling only its order changed 16% of discards; the review's m6)."""
        down = [c for c in run.hand if c.face_down]
        return sorted(run.draw_pile + [replace(c, face_down=False) for c in down], key=lambda c: c.uid)

    def _discard(self, run, keep_idx, mods=None) -> tuple[float, list[int] | None, float]:
        """The best of a few discards: what the best play scores after it, the discard, and what the jokers make
        of it (`mods`: modifiers.discard_bonus; with them, the discards only a joker wants are tried too). Each is
        dealt DRAWS possible draws from the cards left in the pile (a player knows which cards are left, not their
        order; the same draws for every discard) and scored in full, jokers and all, with one discard fewer left
        (Banner, Mystic Summit): the score of the typical draw (the mean log score). With PEEK, the one draw it
        would really get (the Seed Planner, whose seed is known and so its deck order)."""
        ranked = self._ranked_discards(run, keep_idx, mods)
        return (ranked[0][0], ranked[0][1], ranked[0][2]) if ranked else (-1.0, None, 0.0)

    def _ranked_discards(self, run, keep_idx, mods=None, everything: bool = False) -> list[tuple[float, list[int], float]]:
        """The discards _discard weighs, best first: (the best play's score after it, the discard, what the jokers
        make of it). With `everything`, every one is weighed again on RERANK_DRAWS draws, not only the leading few: a
        dead play's worth (The Mouth: only Two Pair scores) hangs on a rare draw, which 6 draws can't rank (6X7SCM12
        kept J 7 10, 119 on 1000 draws, over J J and a Glass Ace, 1,036: the user's catch, 29 Oct)."""
        hand, pile, boss = run.hand, run.draw_pile, run.active_boss
        options = self._discard_options(run, keep_idx)
        if mods:                                            # what a joker pays for: only cards seen
            options |= {tuple(sorted(i for i in s if not hand[i].face_down and not held_value(hand[i]))[:5])
                        for s in discard_options(run)} - {()}
        holds = getattr(self, "_holds", lambda run: None)(run)
        if holds:                                           # the build plan's held cards stay (spec 4.5); a face-down
            options = {o for o in options                   # card isn't known, so it isn't one
                       if not any(not hand[i].face_down and holds(hand[i]) for i in o)} or options
        fires = self._discard_plan(run)[1] if mods else None   # copies as they will stand for the discard
        extras = {opt: discard_bonus(self, mods, [hand[i] for i in opt if not hand[i].face_down], fires) if mods else 0.0
                  for opt in options}
        if self.PEEK:
            draws = [pile[::-1]]                            # pile.pop() deals from the end
        else:
            rng = random.Random(f"{run.seed}|{run.rounds_played}|{run.round_hands_played}|{run.discards_left}|{len(pile)}")
            pool = self._unseen(run)
            draws = [rng.sample(pool, min(len(pile), run.hand_size)) for _ in range(self.DRAWS)]

        def typical(opt, draws) -> float:
            """The mean log score of the best play after discarding `opt`, over these draws."""
            kept = [c for i, c in enumerate(hand) if i not in opt]
            n = run.hand_size - len(kept)
            if boss:
                n = boss.draw_count(run, n, "discard")
            scores = [best_play(run, hand=kept + (d[:n] if n > 0 else []))[0] for d in draws]
            return sum(math.log1p(max(s, 0)) for s in scores) / len(scores)
        out = []
        run.discards_left -= 1
        try:
            for opt in options:
                key = typical(opt, draws)
                out.append((key + extras[opt], math.expm1(key), list(opt), extras[opt]))
            out.sort(key=lambda t: t[0], reverse=True)      # stable: of equal discards, the first weighed comes first
            if not self.PEEK and out:
                # The best of a few noisy estimates is too hopeful (it is best partly by fitting those draws), and on
                # 6 draws often not the best: the leading RERANK are weighed again on RERANK_DRAWS other draws, shared,
                # and those scores rank them and say what the discard is worth.
                fresh = [rng.sample(pool, min(len(pile), run.hand_size)) for _ in range(self.RERANK_DRAWS)]
                top = []
                for _, _, opt, extra in (out if everything else out[:self.RERANK]):
                    key = typical(tuple(opt), fresh)
                    top.append((key + extra, math.expm1(key), opt, extra))
                top.sort(key=lambda t: t[0], reverse=True)
                out[:len(top)] = top
        finally:
            run.discards_left += 1
        return [(value, opt, extra) for _, value, opt, extra in out]

    # ---- consumables ------------------------------------------------------------------------------
    def _use(self, run):
        for i, c in enumerate(run.consumables):
            if c.kind == "Planet":
                return ("use", i, [])
            if c.kind != "Tarot":
                continue
            targets = self._targets(run, c, run.hand)
            if targets is not None and c.can_use(run, run.cards_at(targets)):
                return ("use", i, targets)
        return None

    @staticmethod
    def _targets(run, c, hand) -> list[int] | None:
        """Hand positions to use this Tarot on, or None to keep it. Never a face-down card (what it is isn't known)."""
        if c.name in NO_TARGET_TAROTS:
            return []
        if not hand:
            return None
        n = c.max_targets
        by_value = sorted((i for i in range(len(hand)) if not hand[i].face_down), key=lambda i: -hand[i].rank)
        if c.name in ENHANCING:
            fresh = [i for i in by_value if hand[i].enhancement is None and not hand[i].is_stone]
            return fresh[:n] or None
        if c.name == "Strength":
            return [i for i in by_value if hand[i].rank < 14][:n] or None
        if c.name in SUIT_TAROT:
            suit = SUIT_TAROT[c.name]
            have = sum(hand[i].suit == suit for i in by_value)
            off = [i for i in by_value if hand[i].suit != suit]
            return off[:n] if have >= 3 and off else None
        if c.name == "The Hanged Man":
            return by_value[::-1][:n] or None
        return None

    # ---- consumables: the ways to use one -------------------------------------------------------------
    def _uses(self, run, c, hand) -> list[tuple[list[int], str]]:
        """Ways to use consumable `c` now: (hand positions, label). Cards that act on cards get a few target
        choices (high or low cards, face cards); the search picks."""
        name = c.name
        if c.max_targets == 0:
            return [([], f"Use {name}")] if c.can_use(run, []) else []
        if not hand:
            return []
        seen = [i for i in range(len(hand)) if not hand[i].face_down]      # what a face-down card is isn't known
        rank = lambda i: 0 if hand[i].is_stone else hand[i].rank
        high = sorted(seen, key=lambda i: -rank(i))
        faces = [i for i in high if hand[i].is_face()]
        plain = lambda i: hand[i].enhancement is None and hand[i].seal is None and hand[i].edition is None
        n = c.max_targets
        if name in ENHANCING:
            fresh = [i for i in high if hand[i].enhancement is None and not hand[i].is_stone]
            sets = [fresh[:n], fresh[::-1][:n]]
        elif name in SEALING:                    # the highest card, the lowest plain one (a Purple Seal's: thrown) and
            free = [i for i in high if hand[i].seal is None and not hand[i].is_stone]   # one held for what it pays
            low = [i for i in free[::-1] if plain(i)]                                    # (Blue, Red: it stays in hand)
            sets = [free[:1], low[:1], [i for i in free if held_value(hand[i])][:1]]
            if name == "Medium":                 # of equal worths the first is taken: a Purple Seal on a card thrown
                sets = sets[1:2] + sets[:1] + sets[2:]
        elif name == "Aura":
            sets = [[i for i in high if hand[i].edition is None][:1]]
        elif name == "Strength":
            sets = [[i for i in high if hand[i].rank < 14][:n], [i for i in high if hand[i].rank in (11, 12)][:n]]
        elif name in SUIT_TAROT:
            sets = [self._targets(run, c, hand) or []]
        elif name == "The Hanged Man":                   # destroys: only plain cards, never one enhanced or sealed
            sets = [[i for i in high[::-1] if plain(i)][:n], [i for i in faces if plain(i)][:n]]
        elif name == "Death":   # the left card becomes the right one, enhancement, seal and edition too: copy the
            # best card onto a plain worse one
            pairs = [(card_worth(hand[j]) - card_worth(hand[i]), i, j) for i in seen for j in seen
                     if i < j and plain(i) and card_worth(hand[j]) > card_worth(hand[i])]
            sets = [list(max(pairs)[1:])] if pairs else []
        elif name == "Cryptid":
            sets = [high[:1], faces[:1]]
        else:
            sets = [self._targets(run, c, hand) or []]
        if getattr(self, "PLAN", False):                 # the build plan's preferred targets (Kings for The Chariot)
            pref = [i for i in high if self._prefers(run, name, hand[i])][:n]
            if pref:
                sets.append(pref)
        out = []
        for t in sets:
            t = sorted(set(t))
            if t and len(t) >= c.min_targets and t not in [o[0] for o in out] and c.can_use(run, run.cards_at(t)):
                out.append((t, f"Use {name} on {' '.join(card_text(hand[i]) for i in t)}"))
        return out

    # ---- packs ------------------------------------------------------------------------------------
    def pack_action(self, run, pack):
        for i, item in enumerate(pack.cards):
            if isinstance(item, Joker) and run.joker_room(item):
                return ("pick", i, [])
        planets = [(i, it) for i, it in enumerate(pack.cards) if isinstance(it, Consumable) and it.kind == "Planet"]
        if planets:
            most = run.most_played_hand()
            pick = next((i for i, it in planets if getattr(it, "hand", None) == most), planets[0][0])
            return ("pick", pick, [])
        tarots = [(ARCANA_PRIORITY.index(it.name), i, it) for i, it in enumerate(pack.cards)
                  if isinstance(it, Consumable) and it.kind == "Tarot" and it.name in ARCANA_PRIORITY]
        for _, i, it in sorted(tarots):
            targets = self._targets(run, it, run.hand)
            if targets is not None and it.can_use(run, run.cards_at(targets)):
                return ("pick", i, targets)
        return ("skip",)


# ---- the value bot ------------------------------------------------------------------------------------

UNFED = {"Ceremonial Dagger"}     # grows only on what it destroys, and the bot keeps it rightmost (best_order), with
                                  # nothing to its right: it never grows
DESTROYS = {"Madness": 2}         # jokers it destroys in an ante: Madness a random other one each Small and Big Blind
# Jokers that grow only on cards of one kind: the grows weight counts in proportion to the deck's cards of that kind,
# all of it from FED_FULL of them (Lucky Cat with no Lucky card never grows; it was worth +0.45 all the same).
FED_BY = {"Lucky Cat": lambda c: c.enhancement == "Lucky", "Glass Joker": lambda c: c.enhancement == "Glass",
          "Vampire": lambda c: c.enhancement is not None}
FED_FULL = 8
# A growing joker is worth what it is expected to grow to: the build's power with it at its value halfway through the
# next GROWTH_HORIZON rounds (fewer near ante 8's boss), against as it is (ValueBot.growth_worth), where it used to
# get the flat grows weight whether or not the bot's play fed it (on 100 seeds the bot sold Sly Joker, The Trio or
# Even Steven for a Runner, Spare Trousers or Ride the Bus that stayed at 0, in some 15 of 73 losses). Each grows by
# GROWTH's step on its attribute, at a rate (ValueBot._growth_rate) from how the build plays (the best play of
# power's sample hands) or from what this run has done per round so far (rerolls, packs skipped, cards added...).
GROWTH_HORIZON = 6
GROWTH = {"Runner": ("value", 15), "Square Joker": ("value", 4), "Wee Joker": ("chips", 8), "Spare Trousers": ("mult", 2),
          "Green Joker": ("value", 1), "Ride the Bus": ("value", 1), "Obelisk": ("xmult", 0.2), "Castle": ("chips", 3),
          "Yorick": ("xmult", 1), "Hologram": ("xmult", 0.25), "Red Card": ("mult", 3), "Flash Card": ("mult", 2),
          "Campfire": ("xmult", 0.25), "Constellation": ("xmult", 0.1), "Madness": ("xmult", 0.5),
          # and those that wear away: worth what they will be (Seltzer: the share of the next rounds it lasts)
          "Ice Cream": ("chips", -5), "Popcorn": ("mult", -4), "Ramen": ("xmult", -0.01), "Seltzer": ("hands", -1),
          "Turtle Bean": ("hand_size_bonus", -1)}    # (it was valued as if its +5 hand size lasted: the review's m9)


# Rerolls a shop the value bot makes at each ante (its own play: 48 fresh seeds, runs to 16, 30 Oct; past the last
# ante measured, that one's rate). Few early, many late: a run's own rate so far undercounts what Reroll Surplus saves
# (EURSXV11 at ante 4, no reroll yet: the voucher measured 0, the user's "it still doesnt see vouchers worth?").
REROLLS_A_SHOP: dict[int, float] = {1: 0.03, 2: 0.25, 3: 0.61, 4: 1.06, 5: 1.53, 6: 2.0, 7: 2.4, 8: 2.73, 9: 2.62,
                                    10: 2.84}   # (antes 11-12: 5 shops, too few)


def rerolls_ahead(run, rounds: float) -> float:
    """The bot's own rerolls a shop (REROLLS_A_SHOP), as a mean over the antes the run is likely to last from here
    (`rounds` of them, three a round's shop an ante: rounds_left)."""
    if not REROLLS_A_SHOP:
        return 0.0
    last = max(REROLLS_A_SHOP)
    antes = range(run.ante, run.ante + max(1, round(rounds / 3)))
    return sum(REROLLS_A_SHOP.get(min(a, last), 0.0) for a in antes) / len(antes)


OFFERED_PACK = {"Planet": "Celestial", "Playing card": "Standard"}


def offered(run, kind: str) -> float:
    """Cards of `kind` (Planet, Playing card) a round's shop offers: its card slots at that kind's share of the shop's
    weights, and its two pack slots at the picks of the packs that deal it (Planets about 0.9 at the start: 2 x 1/7 +
    2 x 0.31). The rate a joker fed by them (Constellation, Hologram) can count on, where the run has taken few so far
    because none was worth more than it adds without the joker (EURSXV11, 29 Oct: Constellation was projected never to
    grow, and sold; the user: owning it changes what the bot does)."""
    weights = run.shop_weights()
    cards = run.shop_card_slots * weights.get(kind, 0) / max(1e-9, sum(weights.values()))
    total = sum(PACK_WEIGHTS)
    packs = 2 * sum(w * p.chosen for p, w in zip(PACKS.values(), PACK_WEIGHTS) if p.kind == OFFERED_PACK[kind]) / total
    return cards + packs


def planets_offered(run) -> float:
    return offered(run, "Planet")


def _joker_groups() -> tuple[set, set, set]:
    """Jokers whose worth doesn't show in the hands they score today: those that grow, those that pay, and
    those that change the rules (from their effect text in data/jokers.json). A joker whose payout grows (Rocket, Egg)
    isn't one that grows: income counts its money. PAYS_FROM in the environment names a labels file
    (scripts/classify_jokers.py) whose money facet says which pay instead of the words (an experiment)."""
    rows = data("jokers.json")
    grows = {j["name"] for j in rows if re.search(r"\bgains?\b|\bgrows?\b|permanently|increases? by|upgrade", j["effect"], re.I)
             and j["name"] not in INCOME and j["name"] not in UNFED}
    pays = {j["name"] for j in rows if re.search(r"\$|\bearn|money|sell value", j["effect"], re.I)}
    if os.environ.get("PAYS_FROM"):
        labels = json.loads(Path(os.environ["PAYS_FROM"]).read_text())["jokers"]
        pays = {n for n, facets in labels.items() if facets["money"]["label"] in ("every_round", "on_event", "sell")}
    rules = {j["name"] for j in rows if j["wiki_activation_type"] == "N/A (Passive)"}
    return grows, pays, rules


GROWS, PAYS, RULES = _joker_groups()
RARITY = {"Common": 0, "Uncommon": 1, "Rare": 2, "Legendary": 3}
PACK_SIZE = {"Normal": 1.0, "Jumbo": 1.3, "Mega": 1.6}
PAID_DISCARD = 0.02            # a discard made only for what a joker pays must be worth this (about $1)
SPARE_MONEY = 0.1             # what $1 beyond the reserve costs, against $1 within it (ValueBot.price): with interest
                              # 0.1 and reroll 0.05, 0.1 beat ante 8 in 53.8% and 53.3% of two 480-seed sets, 0.25 in 44.2%
                              # and 45.0% (27 Oct): hold the interest reserve, spend freely beyond it
UPGRADE_SHARE = 0.5           # of what a voucher's upgrade would add, counted in the voucher: about the chance
                              # the upgrade shows up in a later shop
UPGRADES = {e["requires"]: e for e in entries("voucher") if e.get("requires")}   # Blank -> Antimatter, ...
SECRET_HANDS = {h["name"] for h in data("hands.json")["hands"] if h["secret"]}
# A voucher's worth: what ValueBot.voucher_worth measures of it in the run as it stands (hands, discards, hand size),
# plus this weight (all of it for the ones not measured; Hieroglyph and Petroglyph: the ante they give back).
DISCOUNTS = ("Clearance Sale", "Liquidation")   # vouchers that cut the shop's prices from the moment they are bought
MEASURED_VOUCHERS = ("Overstock", "Overstock Plus", "Reroll Surplus", "Reroll Glut")   # (VOUCHERS_MEASURED)
VOUCHER_WORTH = {"Overstock": 0.4, "Overstock Plus": 0.4, "Clearance Sale": 0.3, "Liquidation": 0.3, "Hone": 0.15,
                 "Glow Up": 0.15, "Reroll Surplus": 0.1, "Reroll Glut": 0.1, "Crystal Ball": 0.2, "Omen Globe": 0.1,
                 "Telescope": 0.25, "Observatory": 0.6, "Grabber": 0.0, "Nacho Tong": 0.0, "Wasteful": 0.0,
                 "Recyclomancy": 0.0, "Tarot Merchant": 0.1, "Tarot Tycoon": 0.1, "Planet Merchant": 0.15,
                 "Planet Tycoon": 0.15, "Seed Money": 0.25, "Money Tree": 0.25, "Blank": 0.0, "Antimatter": 0.8,
                 "Magic Trick": 0.05, "Illusion": 0.1, "Hieroglyph": 0.1, "Petroglyph": 0.1, "Director's Cut": 0.0,
                 "Retcon": 0.0, "Paint Brush": 0.0, "Palette": 0.0}
# Vouchers the bot can't make use of yet, worth nothing whatever their weight: it never rerolls a boss, and Blank
# does nothing (its worth is the share of Antimatter it opens).
UNUSED_VOUCHERS = {"Director's Cut", "Retcon", "Blank"}
HANDS_FROM = {"Grabber": 1, "Nacho Tong": 1, "Hieroglyph": -1}       # hands per round a voucher adds
DISCARDS_FROM = {"Wasteful": 1, "Recyclomancy": 1, "Petroglyph": -1}  # discards per round
HAND_SIZE_FROM = {"Paint Brush": 1, "Palette": 1}                     # cards in hand
DISCARD_AS_HANDS = 0.5   # a discard counts as half a hand in a round's capacity (hands + discards)
VOUCHER_ANTES = 4        # antes left from which a voucher is worth all of it; fewer, that share (Money Tree at ante 8)
CAPACITY_WEIGHT = 3.6    # on the log of the change in capacity: Grabber 0.6 at 4 hands and 3 discards, the weight it
                         # had. The log alone (0.17) left it unbought, 24.8% against 28.1% on 480 seeds: a blind is
                         # beaten by a round's total, and a hand left over pays $1.


# Skipping a Small or Big Blind for its tag (ValueBot.skip_blind). A tag is worth the money it brings (TAG_MONEY, at
# the money weight), the pack it opens (that pack's weight and price) and, for what money can't say, TAG_WORTH (power,
# per tag: a weight evolution tunes).
TAG_MONEY = {"Investment Tag": lambda run: 25, "Economy Tag": lambda run: min(40, max(0, run.money)),
             "Handy Tag": lambda run: run.hands_played, "Garbage Tag": lambda run: run.unused_discards,
             "Speed Tag": lambda run: 5 * (run.skips + 1), "Coupon Tag": lambda run: 12, "D6 Tag": lambda run: 4,
             "Uncommon Tag": lambda run: 6, "Rare Tag": lambda run: 8, "Foil Tag": lambda run: 5,
             "Holographic Tag": lambda run: 5, "Polychrome Tag": lambda run: 5, "Negative Tag": lambda run: 5}
JOKER_MAKERS = ("The Soul", "Judgement", "Wraith")   # consumables that make a joker, which needs a slot
EDITION_OF_TAG = {"Foil Tag": "Foil", "Holographic Tag": "Holographic", "Polychrome Tag": "Polychrome"}
SLOT_TAGS = ("Uncommon Tag", "Rare Tag", "Foil Tag", "Holographic Tag", "Polychrome Tag")   # a joker in the next
                                                                                            # shop, which needs a slot
TAG_PACK = {"Standard Tag": "Mega Standard Pack", "Charm Tag": "Mega Arcana Pack", "Meteor Tag": "Mega Celestial Pack",
            "Buffoon Tag": "Mega Buffoon Pack", "Ethereal Tag": "Spectral Pack"}
# How much of the score a build typically makes a boss's effect leaves (rough figures; a boss's chip multiple is in
# its target already, and what it debuffs is counted from the deck: suits, face cards, Verdant Leaf's everything).
# The Needle's one hand is counted as the hands. For the bot's odds against a boss (ValueBot.boss_odds).
BOSS_STRAIN = {"The Flint": 0.5, "The Eye": 0.6, "The Mouth": 0.75, "The Psychic": 0.85, "The Manacle": 0.85,
               "The Arm": 0.85, "The Pillar": 0.85, "The Hook": 0.85, "The House": 0.85, "The Wheel": 0.85,
               "The Mark": 0.85, "The Fish": 0.85, "The Serpent": 0.9, "Crimson Heart": 0.75, "Cerulean Bell": 0.9,
               "Amber Acorn": 0.85, "The Water": 0.9}
AVERAGE_STRAIN = 0.85     # a boss drawn at random, for what rerolling one is worth
# The chance a blind is beaten at a margin m (a round of the build's typical hand against the target, as boss_margin and
# the skip check read it), fitted on 200 games of the value bot's own play (30 Oct, runs/value/odds_calibration.json:
# 1,446 bosses, 2,393 Small and Big Blinds): m^k / (m^k + c^k), even at c. The old m^4 / (1 + m^4) was even at 1, where
# bosses are beaten 9 times in 10: a bare deck's 0.38 against ante 1's boss read 2%, beaten about half the time
# (ODDS_CALIBRATED; the user's CCU44VLE skip question).
ODDS_FIT = {"boss": (2.932, 0.416), "blind": (4.039, 0.383)}
# ODDS_BY_ANTE: the same slopes, the curve's centre fitted by ante (antes 1-3, 4-5, 6 on): late rounds are harder at a
# margin, a Big Blind at antes 6-8 beaten 86% of the time at 0.75-1.0, at antes 1-3 96% (the user's CCU44VLE: a skip
# into ante 7's Big Blind read at 95%, lost).
ODDS_CENTRE = {"boss": (0.273, 0.324, 0.517), "blind": (0.330, 0.342, 0.483)}
# ROLLOUT_ODDS: a blind's odds by playing it out (ValueBot.blind_outlook). The bot plays better than the rollouts'
# GreedyBot: the log of a rollout's score over the target is moved by c and its spread scaled by s (c, s), and the
# z-score that gives is blended with the margin (ROLLOUT_BLEND: constant, z, log margin, boss), all fitted on 3,637
# blinds the bot then played (30 Oct, runs/value/odds_rollout.json, logs/fit_rollout.log). Cross-validated log-loss
# 0.0466 against the margin curve's 0.0541, and 0.269 against 0.317 on the rounds the curve reads at 60-97%.
ROLLOUT_FIT = (0.344, 1.200)
ROLLOUT_BLEND = (1.993, 0.931, 1.378, -0.828)
OPEN_TARGET = 10 ** 15    # a rollout's blind is left open, so the round plays every hand and its whole score is seen
# SCALING: the chance the bot beats ante 8's boss, read in a shop (ValueBot.scaling_odds): a logistic with a constant for
# each ante 1-8 and, for antes 1-3, 4-5 and 6-8, slopes on the projected log margin over ante 8's boss, the log of 1 +
# money and the joker slots free. Fitted on 6,757 shops of 360 games of the value bot (30 Oct, seeds from
# Random(2468), runs/value/scaling_probe.json, logs/fit_scaling.log; 5-fold by game): log-loss 0.5370 against 0.5795
# for the ante alone and 0.5460 for the margin unprojected. The free slots added nothing (0.5371) and read as a cost
# (weak builds have empty slots, a correlation that would pay for filling them with anything): left out.
SCALING_FIT = ((1.577, 1.113, 0.798, -0.152, -0.733, -0.666, -1.006, -1.18),
               ((0.211, 0.166, 0.0), (0.824, 0.65, 0.0), (1.568, 0.605, 0.0)))


class RolloutPolicy(GreedyBot):
    """GreedyBot's play for a blind's rollouts, against the real `target` while the copy's blind is left open."""

    def __init__(self, target: int):
        self.target = target

    def round_action(self, run):
        open_, run.blind.chips = run.blind.chips, self.target
        try:
            return super().round_action(run)
        finally:
            run.blind.chips = open_
DEATH = 2.0               # what losing the run costs, in power, where a boss's odds are weighed (Boss Tag, rerolls)
TAG_WORTH = {"Uncommon Tag": 0.25, "Rare Tag": 0.45, "Foil Tag": 0.15, "Holographic Tag": 0.25, "Polychrome Tag": 0.4,
             "Negative Tag": 0.5, "Top-up Tag": 0.12, "Orbital Tag": 0.0, "Juggle Tag": 0.03, "Double Tag": 0.15,
             "Boss Tag": 0.03, "Voucher Tag": 0.1, "Investment Tag": 0.0, "Economy Tag": 0.0, "Handy Tag": 0.0,
             "Garbage Tag": 0.0, "Speed Tag": 0.0, "Coupon Tag": 0.05, "D6 Tag": 0.0, "Standard Tag": 0.0,
             "Charm Tag": 0.0, "Meteor Tag": 0.0, "Buffoon Tag": 0.0, "Ethereal Tag": 0.0}


def action_key(action) -> tuple:
    """An action as a dict key (target lists become tuples)."""
    return tuple(tuple(x) if isinstance(x, list) else x for x in action)


@dataclass
class Weights:
    """What the value bot trades off, in units of `ValueBot.power` (the mean log of the best hand's score).
    Set by hand to start with; evolution tunes them."""
    money: float = 0.02            # per $ spent
    interest: float = 0.1          # per $ of interest a purchase costs each round (0.05 until 27 Oct; see SPARE_MONEY)
    grows: float = 0.45            # a joker that grows
    # A joker that makes money, or changes the rules: off since 26 Oct. Their flat bonuses kept Credit Card, Egg and
    # Delayed Gratification over scoring jokers; at 0 the bot beat ante 8 in 27.3% of 480 seeds against 21.0%.
    pays: float = 0.0
    rules: float = 0.0
    rarity: tuple = (0.0, 0.05, 0.15, 0.6)
    negative: float = 0.4          # a Negative joker takes no slot
    sell_margin: float = 0.1       # replace a joker only for one worth this much more
    keep: float = 0.1              # a tarot or spectral bought to use later
    card: float = 0.02             # a playing card bought or taken
    reroll: float = 0.05           # a reroll, before seeing what it brings (0 until 27 Oct; see SPARE_MONEY)
    skip_safety: float = 1.25      # skip a blind only if a round of the typical hand beats the next target by this
    skip_shop: float = 0.25        # what the shop after a blind is worth (skipping the blind skips it)
    packs: dict = field(default_factory=lambda: {"Buffoon": 0.3, "Arcana": 0.25, "Celestial": 0.2, "Spectral": 0.35,
                                                 "Standard": 0.05})
    vouchers: dict = field(default_factory=lambda: dict(VOUCHER_WORTH))
    joker: dict = field(default_factory=dict)  # per joker, on top of the rest
    mods: dict = field(default_factory=lambda: {**dict.fromkeys(MOD_RULES, 1.0), **MOD_OFF})   # modifiers' strengths, per rule
    tags: dict = field(default_factory=lambda: dict(TAG_WORTH))                 # a tag's worth beyond money and packs
    classes: dict = field(default_factory=lambda: dict.fromkeys(CLASSES, 0.0))  # per joker class (joker_classes.py)


# Weights as a flat genome, for evolution (scripts/evolve_valuebot.py); the evolved best is loaded when present.
SCALARS = ["money", "interest", "grows", "pays", "rules", "negative", "sell_margin", "keep", "card", "reroll", "skip_safety",
           "skip_shop"]
# The planner's weights: an evolution run's champion, chosen in the Evolution tab ("Use these weights").
EVOLVED = Path(__file__).resolve().parent.parent / "runs" / "evolve" / "planner.json"


def genome_of(w: Weights) -> dict:
    g = {k: getattr(w, k) for k in SCALARS}
    g.update({f"rarity:{i}": v for i, v in enumerate(w.rarity)})
    g.update({f"pack:{k}": v for k, v in w.packs.items()})
    g.update({f"voucher:{k}": v for k, v in w.vouchers.items()})
    g.update({f"mod:{r}": w.mods.get(r, MOD_OFF.get(r, 1.0)) for r in MOD_RULES})
    g.update({f"tag:{t}": w.tags.get(t, 0.0) for t in TAG_WORTH})
    g.update({f"class:{c}": w.classes.get(c, 0.0) for c in CLASSES})
    return g


def weights_of(g: dict) -> Weights:
    w = Weights()
    g = {**genome_of(w), **g}
    for k in SCALARS:
        setattr(w, k, g[k])
    w.rarity = tuple(g[f"rarity:{i}"] for i in range(len(w.rarity)))
    w.packs = {k: g[f"pack:{k}"] for k in w.packs}
    w.vouchers = {k: g[f"voucher:{k}"] for k in w.vouchers}
    w.mods = {r: g.get(f"mod:{r}", MOD_OFF.get(r, 1.0)) for r in MOD_RULES}   # (a rule added since: its default)
    w.tags = {t: g[f"tag:{t}"] for t in TAG_WORTH}
    w.classes = {c: g[f"class:{c}"] for c in CLASSES}
    return w


def _genes() -> list[dict]:
    """Each weight's label, section and range (evolution keeps it in range; the Evolution tab draws it on it)."""
    w = Weights()
    out = [{"name": "money", "label": "Worth of $1 spent", "section": "Money", "low": 0.0, "high": 0.06},
           {"name": "interest", "label": "Worth of $1 of interest each round", "section": "Money", "low": 0.0, "high": 0.15}]
    jokers = [("grows", "Joker that grows"), ("pays", "Joker that makes money"), ("rules", "Joker that changes the rules"),
              ("rarity:0", "Common joker"), ("rarity:1", "Uncommon joker"), ("rarity:2", "Rare joker"),
              ("rarity:3", "Legendary joker"), ("negative", "Negative joker (no slot)")]
    out += [{"name": n, "label": lb, "section": "Jokers", "low": -0.5, "high": 1.5} for n, lb in jokers]
    out.append({"name": "sell_margin", "label": "Margin to replace a joker", "section": "Jokers", "low": 0.0, "high": 1.0})
    out += [{"name": "keep", "label": "Tarot or spectral kept for later", "section": "Shop", "low": -0.5, "high": 1.0},
            {"name": "card", "label": "Playing card", "section": "Shop", "low": -0.5, "high": 1.0},
            {"name": "reroll", "label": "Reroll (before seeing it)", "section": "Shop", "low": -0.5, "high": 1.0}]
    out += [{"name": f"pack:{k}", "label": f"{k} Pack", "section": "Packs", "low": -0.5, "high": 1.5} for k in w.packs]
    out += [{"name": f"voucher:{k}", "label": k, "section": "Vouchers", "low": -0.5, "high": 1.5} for k in w.vouchers]
    out += [{"name": f"mod:{r}", "label": f"{r}: {what}", "section": "Modifiers", "low": 0.0, "high": 3.0}
            for r, what in MOD_RULES.items()]
    out += [{"name": "skip_safety", "label": "Skip only if a round beats the next blind by", "section": "Skipping", "low": 1.0, "high": 4.0},
            {"name": "skip_shop", "label": "Shop visit given up by skipping", "section": "Skipping", "low": 0.0, "high": 1.0}]
    out += [{"name": f"tag:{t}", "label": t, "section": "Skipping", "low": -0.5, "high": 1.5} for t in TAG_WORTH]
    out += [{"name": f"class:{c}", "label": "Jev class " + c.replace(":", ": ").replace("_", " "), "section": "Joker classes",
             "low": -0.5, "high": 0.5} for c in CLASSES]
    return out


GENES = _genes()


def load_planner() -> tuple[Weights, object]:
    """The planner's weights and network (runs/evolve/planner.json), or the hand-set weights and no network.
    VALUEBOT_WEIGHTS in the environment picks others: "hand" for the hand-set ones, or a path to a saved champion."""
    choice = os.environ.get("VALUEBOT_WEIGHTS", "")
    if choice == "hand":
        return Weights(), None
    try:
        saved = json.loads(Path(choice or EVOLVED).read_text())
    except (OSError, ValueError):
        return Weights(), None
    net = None
    if saved.get("network"):
        from .neural import Network
        net = Network(saved["network"]["params"])
    return weights_of(saved.get("genome") or {}), net


def load_weights() -> Weights:
    return load_planner()[0]


class ValueBot(SmartBot):
    """SmartBot that weighs what it buys, takes and uses. A joker, planet, tarot or spectral is worth the rise
    in the build's power (the best hand over a few sample hands from the deck, scored with the jokers, levels
    and cards it would have; tarots and spectrals are tried on a copy of the run) plus `Weights` for what
    today's hands don't show; money, and the interest it would have earned, is the price. It sells a weak
    joker for a much better one (to make room, or to raise the last few dollars) and, with Perkeo, keeps a
    consumable for Perkeo to copy."""
    MOUTH_ODDS = True    # (on 30 Oct for the value bot: a correctness fix, level; SmartBot keeps the capped mean)
    ROUND_SEARCH = True       # a play or discard in a boss round in doubt checked by playing the round out (search.py):
                              # the boss-round test won 52 of 140 lost boss rounds this way (30 Oct). Adopted 31 Oct:
                              # j-search +4.4 ± 1.3 points against j-base (70.2%), j777-search +2.3 ± 1.2 (72.5%); ~4x
                              # the time a game (146 s against 35 s on a loaded machine)
    SEARCH_BOSS_ONLY = True   # only in boss rounds (83% of lost games end at one; the search costs ~10-60 s a round)
    SEARCH_ROLLOUTS = 6       # play-outs an option, the same redraws for each
    SEARCH_CONFIRM = 12       # more play-outs for the bot's pick and the leading other before switching
    SEARCH_MARGIN = 2         # the other must win this many more of the 18 (6 + 12): b1's 3 won rounds lost came
                              # from switching on 6 alone
    SEARCH_PLAYS = 3          # the top plays by score weighed besides the bot's pick
    SEARCH_DISCARDS = 3       # the top discards it weighs

    LAST_DISCARD_ODDS = True  # the round's last hand, a discard left, no sure win: a discard when one of the leading few
                              # reaches the target in more of LAST_DRAWS draws than the play does (win_odds). It played a
                              # hand that couldn't win unless the typical draw beat it (_worth_discarding's last-hand rule):
                              # 22 such plays in the review agent's lab, all in lost rounds (31 Oct). A fix: on
    LAST_DRAWS = 48

    def _round_choice(self, run):
        action = super()._round_choice(run)
        if self.LAST_DISCARD_ODDS and action[0] == "play" and run.hands_left == 1 and run.discards_left >= 1:
            disc = self._last_discard(run, list(action[1]))
            if disc:
                return ("discard", disc)
        return action

    def _last_discard(self, run, idx) -> list[int] | None:
        """LAST_DISCARD_ODDS's discard, or None: of the top 4 discards weighed, the one whose next hand reaches what is
        needed in the most of LAST_DRAWS draws from the unseen cards, if that beats the play's own odds."""
        needed = run.blind.chips - run.round_score
        hand = run.hand
        if not run.draw_pile or any(hand[i].face_down for i in idx):
            return None
        played = [hand[i] for i in idx]
        now = estimate(run, played, [c for i, c in enumerate(hand) if i not in idx], evaluate_cached(played, run.rules))
        if surely_wins(run, now, idx, needed):
            return None
        best_p, pick = win_odds(run, idx, needed), None
        ranked = self._ranked_discards(run, idx, self._measure(run))[:4]
        if not ranked:
            return None
        rng = random.Random(f"{run.seed}|{run.rounds_played}|{run.discards_left}|lastodds")
        pool = self._unseen(run)
        k = min(len(run.draw_pile), run.hand_size)
        draws = [rng.sample(pool, k) for _ in range(self.LAST_DRAWS)]
        boss = run.active_boss
        run.discards_left -= 1
        try:
            for _, opt, _ in ranked:
                kept = [c for i, c in enumerate(hand) if i not in opt]
                n = run.hand_size - len(kept)
                if boss:
                    n = boss.draw_count(run, n, "discard")
                p = sum(best_play(run, hand=kept + (d[:n] if n > 0 else []), need=needed)[0] >= needed
                        for d in draws) / len(draws)
                if p > best_p:
                    best_p, pick = p, list(opt)
        finally:
            run.discards_left += 1
        return pick

    def round_action(self, run):
        action = super().round_action(run)
        if (self.ROUND_SEARCH and action[0] in ("play", "discard") and not self.__dict__.get("_in_search")
                and run.blind is not None and (run.blind.kind == 2 or not self.SEARCH_BOSS_ONLY)):
            from .search import choose
            action = choose(self, run, action)
        return action

    w, net = load_planner()           # net: a balatro.neural.Network correcting worths in context, or None
    HANDS = 12                        # sample hands for power: on 480 fresh seeds 12 played +0.86 progress
                                      # better than 3 (which missed too much), and 24 no better than 12
    CARD_HANDS = 8                    # hands a card a consumable re-ranks, destroys or adds is tried in (deck_change_worth)
    BOSS_AWARE = PACK_SWAPS = FEED = SMALL = True   # the 27 Oct fixes, one switch each (for measuring)
    USE_GUARD = True                  # in a round, a Tarot (Strength, a suit Tarot...) isn't used on the hand when that
                                      # lowers its best play (_use used one at once, whatever: Strength made a 9-8-7-6
                                      # straight's 9s 10s, C5X6MXUN 28 Oct). Alone: -1.7 +- 0.9 and -0.2 +- 1.0 points
                                      # (29 Oct): it also held back Tarots when the round was won either way
    GUARD_AT_RISK = True              # with USE_GUARD, only when the use costs the round: the hand's best play won the
                                      # round and no longer does, or played every hand left it got there and no longer
                                      # does (the straight above won it). The two: -0.2 +- 0.7 and +0.8 +- 0.7 points,
                                      # progress +0.05 and +0.09 +- 0.04 (29 Oct): level, kept as a fix
    DISCOUNT_FIRST = False            # a discount voucher the bot would buy here is bought before the cards, packs or
                                      # rerolls it would buy (_shop_action), so they cost less. Off until measured
    GROWN_FROM_NOW = True             # Ride the Bus and Obelisk projected from what they have built (_grown_value): the
                                      # steady state alone threw it away, so a Bus at +24 counted as heading for +6 and
                                      # was sold for a Runner at 0 (C5X6MXUN, 28 Oct). A fix, level, adopted 28 Oct:
                                      # +0.0 +- 0.5 and +0.6 +- 0.5 points (progress +0.04, +0.08 +- 0.04)
    spare_money = SPARE_MONEY         # what $1 beyond the interest reserve costs, against $1 within it (price)
    PLANET_TRUST = 1.0                # a level's worth (planet_worth, Celestial packs) times this: a level stays
                                      # for good and grows with the build, which today's sample hands understate
    STALE_ROUNDS = 3                  # a consumable held this many rounds without a use is sold in the shop (0: never):
                                      # The Tower and suit Tarots sat in 37 of 40 held at death. Even on 480 seeds
                                      # (53.5% against 53.8%): holding them wasn't what lost those runs; kept as sense
    REROLL_VOUCHERS = False           # Director's Cut and Retcon worth the boss rerolls they give (boss_reroll_worth):
                                      # off, 52.7% against 53.8% (27 Oct)
    LEGENDS = True                    # Chicot and Perkeo worth what they do (legend_worth), not only the legendary
                                      # bonus: it sold both by ante 4 on ALEEB and lost at ante 8's boss; with this it
                                      # keeps them and wins. (No game of the 480 seeds meets them: even there.)
    LEGEND_ANTES = 4                  # antes ahead counted for them (fewer near the end)
    DECK_TRUST = 1.0                  # what changes to the deck's cards are worth (deck_change_worth) times this: a
                                      # deck shaped on purpose may pay more than today's sample hands show, but 1.5
                                      # and 2 measured worse (52.5%, 50.8% against 53.8%, 27 Oct)
    CELESTIAL_MEASURED = False        # a Celestial pack worth the Planets it likely shows (celestial_worth), not
                                      # the flat pack weight: even (43.5% against 44.2%), and trusting levels 2-3x
                                      # worse (41.9%, 41.2%): off. Low main-hand levels aren't what loses runs
    ROUND_DISCARDS = 2                # discards weighed over the round (_worth_discarding): 0 never, 1 always, 2 only
                                      # when a discard costs every hand after it (Banner, Green Joker). 1 measured
                                      # worse (41.2% beat ante 8 against 43.3%), 2 even (43.1%) and kept (27 Oct)
    REACH_TRUST = 0.0                 # xMult jokers that need a poker hand, counted where a discard reaches it
                                      # (_reach_bonus): this share of it. Off until measured
    REACH_CARDS = 3                   # the cards one discard brings, for that
    EXTRA = 0                         # cards added to each of power's sample hands when the round has discards (what
                                      # a discard brings), meant to show what builds that discard into Flushes or
                                      # Straights really make. Off: with 3, 29.8% beat ante 8 on 480 seeds against
                                      # 39.6% without (27 Oct): it skews every comparison more than it helps those
    TARGET = None                     # an approach: a poker hand the shop builds toward from TARGET_ANTE on, everything
    TARGET_ANTE = 1                   # out of a round valued as if it had TARGET_LEVELS more levels (the build it is
    TARGET_LEVELS = 3                 # to become; play, discards and safety see the levels as they are). None: none
    POWER_PAIRED = True               # power's sample positions drawn once for PAIRED_CEILING cards, a smaller hand the
    PAIRED_CEILING = 20               # first n of each: options that change the hand size (Paint Brush, Palette, Juggler,
                                      # Turtle Bean) meet the same hands. The voucher check (29 Oct): Paint Brush read
                                      # -0.42 to +0.96 over 12 salts on n and n+1 different hands. Measured 29 Oct (queue
                                      # 20): +1.7 +- 2.1 and -1.5 +- 2.3 points, progress +0.19 and -0.21 +- 0.20: level,
                                      # a fix, adopted
    HORIZON_CAP = False       # lasting things counted to ante 8, or 4 antes ahead once past ante 4 (modifiers.last_ante),
                              # not to the run's last boss: in runs to 16 the bot beat ante 8 in 37.5% of 96 seeds
                              # against 51% in the same runs ending at 8 (29 Oct). A run to 8 plays as before. A control
                              # (the user: don't make it play only to ante 8); off
    SURVIVAL_HORIZON = True   # lasting things counted over the rounds the run is likely to last (survival_rounds), not
                              # half of those to its last boss: a strong build prepares for the late antes, a weak one
                              # for the next boss (the user's point, 29 Oct: prepare for the hardest antes from the
                              # start). Queue 22 (29 Oct): runs to 16 +8.1 +- 1.9 points (49.4% against 41.2%), 38.5%
                              # reach ante 10 against 29.6%; runs to 8 -0.2 +- 1.3 and -1.9 +- 1.3: a fix, adopted
    SURVIVAL_GROWTH = 1.6     # how much a build grows an ante: median margins over a random boss at the shops fell 2.43
                              # to 0.94 over antes 3-7 while the targets grew 17.5x (24 games, 29 Oct)
    SURVIVAL_SCALE = 1.4      # the margin times this in the odds curve: at 0.94 the curve said 44%, 74% got through;
                              # scaled, antes 5-8 fit within a few points (96%, 94%, 74%, 75% passed)
    SURVIVAL_EARLY = 2.4      # the margin a build has by ante 3 (the median): before that it isn't formed yet (a fresh
                              # build reads 0.64 at ante 1, and every run passes antes 1 and 2)
    SURVIVAL_DISCOUNT = 0.85  # a round an ante ahead, against one now (money and growth now compound sooner)

    def survival_rounds(self, run) -> float:
        """The rounds a lasting payment is counted for under SURVIVAL_HORIZON: each ante from this one to the run's last,
        its 3 rounds times the chance the run gets there, discounted SURVIVAL_DISCOUNT an ante. Antes 1 and 2 are passed
        97% of the time. From ante 3 on (from now, or from ante 3 at SURVIVAL_EARLY before it), the build's margin over
        a random boss (boss_margin) grows SURVIVAL_GROWTH an ante against each ante's real target (which jumps 2x at 9,
        5x at 10, 13x at 11), and the boss odds' curve (m^4 / (1 + m^4)) on SURVIVAL_SCALE times it gives the chance of
        getting past. A build far ahead counts into the late antes; one barely keeping up counts the next few; none
        counts much past ante 10 without growing far faster than builds do. Remembered per build."""
        key = (run.seed, run.ante, run.max_ante, run.rounds_played, run.shops_seen, tuple(j.name for j in run.jokers),
               tuple(run.hand_levels.values()), len(run.deck))
        memo = self.__dict__.setdefault("_survival", {})
        if key not in memo:
            if len(memo) > 256:
                memo.clear()
            base = lambda a: run.ante_table[min(max(a, 0), max(run.ante_table))] * run.blind_scale   # noqa: E731
            a0 = max(run.ante, 3)
            margin = self.boss_margin(run, None) if run.ante >= 3 else self.SURVIVAL_EARLY
            total, reach = 0.0, 1.0
            for k, a in enumerate(range(run.ante, run.max_ante + 1)):
                total += 3 * reach * self.SURVIVAL_DISCOUNT ** k
                if a <= 2:
                    reach *= 0.97
                else:
                    m = (self.SURVIVAL_SCALE * margin * self.SURVIVAL_GROWTH ** (a - a0) * base(a0) / base(a)) ** 4
                    reach *= m / (1 + m)
            memo[key] = total
        return memo[key]
    PLAN = False              # the build plan (docs/superpowers/specs/2026-10-29-build-planning-layer-design.md): the
                              # engines the run can most likely complete (engines.py), every decision valued and steered
                              # toward them. Off until measured
    PLAN_HELD = True          # each engine, when PLAN is on (a step's measurement turns the others off)
    PLAN_DNA = True
    PLAN_FLUSH = True         # (step 2, 29 Oct evening: Flush ahead of levels, and DNA a tool of whichever is main)
    PLAN_SYNERGY = True       # a missing group's joker counts only for what the plan's projection adds to it, beyond
                              # what it adds today (its own worth comes either way: a strong joker is bought anyway).
                              # Without it Flush's 11 jokers (0.6 over 2 antes against held's 0.25, Onyx Agate +7 Mult
                              # a Club) won the choice over Baron, Mime and 3 Steel Red Seal Kings: likely, not a plan.
                              # A plain Joker as the yardstick did the same (Onyx Agate beats it by 0.4 power alone)
    PLAN_WEIGHT = 1.0         # plan worth times this
    PLAN_HORIZON = 2          # antes the plan projects ahead
    PLAN_MIN = 0.0            # a plan only when its main engine scores above this (power): engine scores over 2 antes
                              # run ~0.02-0.03 (plan review, 29 Oct); step 4's sweeps set it
    PLAN_SWITCH = 0.25        # the main engine changes only for one scoring this share more than it
    PLAN_MARGIN = 0.02        # and this much more (power), and is dropped only below PLAN_MIN less this: scores run
                              # 0.005-0.07, and on the share alone the plan flipped flush/held 6 times a game (29 Oct)
    PLAN_HANDS = 12           # power's sample hands for a plan's value, and deck_change_worth's (8 otherwise). 36 and 24
    PLAN_CARD_HANDS = 8       # made a game 7x slower (70 s against 10 s on 16 seeds, 29 Oct: the card-by-card measure
                              # on 36 hands, and the candidates' cache thrashing); at 12 and 8 the plan shares the bot's
                              # own samples and caches (spec section 7's fallback)
    PLAN_KEEP = 0.8           # a Tarot kept for an engine's target: its use there, times this (the target may not come)
    PLAN_HOLD = 0.05          # playing a card the plan holds: this a hand left after this one (its held effect lost)
    SAMPLE_SALT = ""                  # added to the sample hands' seed: the same bot on other hands (a control for luck)
    POWER_EXACT = True                # power's cache also keyed on what power reads that changes under the same key: the
                                      # draw pile's size (Blue Joker), the jokers' own values (Green Joker, Ride the Bus,
                                      # Ice Cream...), in a round the hands and discards played and left. RZ364T64 (28 Oct):
                                      # a power stored in the shop after the Big Blind (a few cards left in the pile) was
                                      # used at the boss's start (a full pile), Mercury looked worth less, neither of two
                                      # was used and the bot threw a pair of Kings and lost the round a fresh bot wins.
                                      # Level, adopted 28 Oct: -0.4 +- 1.3 and +2.1 +- 1.4 points on the two sets (128
                                      # and 125 of 480 games change), no slower (34.5 s a game against 33.9)
    _key = None

    def _measure(self, run):
        """A Measure for the behaviour modifiers (modifiers.py) when a joker in play has a rule, a Purple Seal,
        Gold card, Blue Seal or (LUCKY_MONEY) Lucky card is in hand, or the boss takes money for a play; None otherwise
        (nothing to add, nothing to measure); and when the build plan holds cards in hand (play_bonus counts playing
        them)."""
        boss = run.active_boss
        holds = self._holds(run)
        paying = ("Gold", "Lucky") if self.LUCKY_MONEY else ("Gold",)
        if (any(j.name in MOD_RULES for j in run.active_jokers())
                or any(not c.face_down and (c.seal in ("Purple", "Blue") or c.enhancement in paying) for c in run.hand)
                or (boss is not None and boss.name in TOLL_BOSSES and run.money > 0)
                or (holds is not None and any(not c.face_down and holds(c) for c in run.hand))):
            return Measure(self, run)
        return None

    def _discard_plan(self, run) -> tuple[list[int] | None, dict | None]:
        """For a discard: the order (of those copier_orders weighs) where Blueprint and Brainstorm repeat most of
        what it pays (COPIED_ON_DISCARD: Burnt Joker's level on the round's first discard, Mail-In Rebate's and
        Faceless Joker's money), as indices into the present order (None: the present one does as well), and how
        many times each joker's effects go off there. The scoring order comes back before the next play."""
        paid = [j for j in run.jokers if j.name in COPIED_ON_DISCARD and (j.name != "Burnt Joker" or run.discards_used == 0)]
        return self._copy_plan(run, paid)

    DISCARD_EDGE = 0.01  # the chance of beating the blind a discard must add: one used now isn't there later

    def _worth_discarding(self, run, now: float, after: float, needed: float, extra: float = 0.0) -> bool:
        """Weighed over the round, not the next hand only: the chance of beating the blind (boss_odds' curve on the
        round's total against what it needs) if this hand is played now and the hands after it make the build's
        typical hand, against if the discard comes first: the hand after it, and every hand after that marked down
        by what the discard costs each of them (Banner's chips, Green Joker's Mult: `extra`'s losses). What a joker
        pays for the discard counts on top (money, levels), at DEATH per whole chance. When the round is lost either
        way, the old rule: whatever scores more. (It used to discard on any gain when this hand every turn fell
        short, which broke a made 47k three of a kind at The Wall and burnt Banner's discards: 4 of 62 losses
        read.)"""
        if now <= 0 or run.hands_left <= 1 or not self.ROUND_DISCARDS:
            return super()._worth_discarding(run, now, after, needed, extra)
        per_hand = self._discard_per_hand(run)
        if self.ROUND_DISCARDS == 2 and per_hand >= 0:
            return super()._worth_discarding(run, now, after, needed, extra)
        later = (run.hands_left - 1) * math.expm1(self.power(run, plain=True))
        odds = lambda total: (lambda m: m / (1 + m))((max(total, 0.0) / max(1.0, needed)) ** 4)   # noqa: E731
        play = odds(now + later)
        disc = odds(after + later * math.exp(per_hand))
        if max(play, disc) < 0.1 or min(play, disc) > 0.98:     # lost or won either way: the old rule (a bigger
            return super()._worth_discarding(run, now, after, needed, extra)   # hand wins in fewer hands, $1 each)
        return DEATH * disc + (extra - per_hand) > DEATH * (play + self.DISCARD_EDGE)

    def _discard_per_hand(self, run) -> float:
        """What a discard costs each hand after it, in power (0 or less): Banner's 30 chips and Mystic Summit's
        Mult on the discards left, Green Joker's Mult for good."""
        names = {j.name for j in run.active_jokers()}
        if not names & {"Banner", "Mystic Summit", "Green Joker"}:
            return 0.0
        measure = Measure(self, run)
        loss = measure.discards(-1) if names & {"Banner", "Mystic Summit"} else 0.0
        loss += sum(measure.joker(j, "value", max(0, j.value - 1)) for j in run.active_jokers() if j.name == "Green Joker")
        return min(0.0, loss)

    def _first_hand_plan(self, run, idx) -> tuple[bool, list[int] | None]:
        """A first hand of one card with DNA (which adds a copy of it to the deck, once more for each copy of DNA):
        (True, the order where copiers repeat DNA most; None: as they stand). Else (False, None)."""
        dna = [j for j in run.jokers if j.name == "DNA"]
        if run.round_hands_played or len(idx) != 1 or not dna:
            return False, None
        return True, self._copy_plan(run, dna)[0]

    def _padded(self, run, idx, mods) -> list[int]:
        """No discards left and hands to come: dead cards added to the play, up to five, so more are drawn next
        time (it used to play a lone High Card hand after hand, holding the same dead cards): the lowest that leave
        its poker hand, its score and what the jokers make of it as they are, never one that pays for being held."""
        if not self.SMALL or run.discards_left or run.hands_left <= 1 or len(idx) >= 5:
            return idx
        hand = run.hand
        if any(hand[i].face_down for i in idx):            # a play with face-down cards: what they are isn't known
            return idx

        def worth(sub):
            played = [hand[i] for i in sub]
            r = evaluate_cached(played, run.rules)
            score = estimate(run, played, [c for i, c in enumerate(hand) if i not in sub and not c.face_down], r)
            return r.name, score, play_bonus(self, mods, played, r) if mods else 0.0
        name, score, bonus = worth(idx)
        out = list(idx)
        for i in sorted((i for i in range(len(hand)) if i not in idx and not hand[i].face_down and not held_value(hand[i])),
                        key=lambda i: hand[i].rank):
            if len(out) >= 5:
                break
            trial = sorted(out + [i])
            n2, s2, b2 = worth(trial)
            if n2 == name and s2 >= score and b2 >= bonus - 1e-9:
                out = trial
        return out

    DNA_SAFETY = 1.5     # the hands after a DNA play must typically make this many times what the blind still needs

    def _dna_play(self, run, needed: float, mods) -> list[int] | None:
        """The round's first hand with DNA: one card played alone, so a copy of it joins the deck for good (one
        more for each copy of DNA, the copiers set on it), when the hands left after it typically beat the blind
        with room to spare (DNA_SAFETY) and the copy is worth something: the card whose copy adds most. Not under
        The Mouth (the round would be High Card from then on)."""
        dna = [j for j in run.active_jokers() if j.name == "DNA"]
        boss = run.active_boss
        if (not dna or mods is None or run.round_hands_played or run.hands_left < 2
                or (boss is not None and boss.name == "The Mouth")):
            return None
        if (run.hands_left - 1) * math.expm1(self.power(run, plain=True)) < needed * self.DNA_SAFETY:
            return None
        times = self._copy_plan(run, dna)[1].get(id(dna[0]), 1)
        best, pick = 0.0, None
        for i, c in enumerate(run.hand):
            if not c.face_down:
                v = mods.card_added(c) * times
                if v > best:
                    best, pick = v, [i]
        return pick

    def _copy_plan(self, run, wanted: list) -> tuple[list[int] | None, dict]:
        """The order (of those copier_orders weighs) where Blueprint and Brainstorm repeat the `wanted` jokers'
        effects most, as indices into the present order (None: the present one does as well), and how many times
        each joker's effects go off there."""
        here = discard_fires(run)
        if not wanted or not any(j.name in COPIERS for j in run.jokers):
            return None, here
        best, pick = sum(here[id(j)] for j in wanted), None
        for order in copier_orders(run.jokers):
            fires = discard_fires(run, order)
            v = sum(fires[id(j)] for j in wanted)
            if v > best:
                best, pick, here = v, order, fires
        return pick, here

    # ---- how strong a build is --------------------------------------------------------------------
    def power(self, run, fresh: bool = False, plain: bool = False) -> float:
        """The mean log of the best score over a few hands from the deck (the same positions in the deck for
        every option of a decision), with no blind in effect; out of a round, as a round starts (all hands and
        discards left: out of a round both are 0, which Mystic Summit, Banner, Acrobat and Dusk would see).
        Jokers that act on some hands only count on their share of hands (modifiers.timed). `fresh`: measured
        anew, for a change the cache can't see (cards' chips, hands played). The sample hands hold EXTRA more cards
        when the round has discards (what a discard brings), which serves comparing builds; `plain`: hands of the
        hand size only, the score a hand typically makes, for setting it against a blind's target."""
        t = self.TARGET
        if t and not plain and not run.in_round and run.ante >= self.TARGET_ANTE and not self.__dict__.get("_projected"):
            run.hand_levels[t] += self.TARGET_LEVELS
            self._projected = True
            try:
                return self.power(run, fresh, plain)
            finally:
                run.hand_levels[t] -= self.TARGET_LEVELS
                self._projected = False
        deck = run.deck
        n = min(run.hand_size, len(deck))
        if n == 0:
            return 0.0
        discards = run.discards_left if run.in_round else run.base_discards + sum(j.discards_bonus for j in run.active_jokers())
        n = min(len(deck), n + (self.EXTRA if discards > 0 and not plain else 0))
        key = (run.seed, run.rounds_played, run.shops_seen, len(deck), n)
        if self.HANDS != type(self).HANDS:           # the plan's own sample hands: their own samples and cache
            key += (self.HANDS,)
        if self._key != key:
            samples = self.__dict__.setdefault("_samples", {})
            if self.POWER_PAIRED:
                top = min(len(deck), max(self.PAIRED_CEILING, n))
                pairs = key[:4] + ("paired", top) + key[5:]
                if pairs not in samples:
                    if len(samples) > 8:
                        samples.clear()
                    rng = random.Random(str(pairs) + self.SAMPLE_SALT)
                    samples[pairs] = [rng.sample(range(len(deck)), top) for _ in range(self.HANDS)]
                self._key, self._idx = key, [s[:n] for s in samples[pairs]]
            else:
                if key not in samples:
                    if len(samples) > 8:
                        samples.clear()
                    rng = random.Random(str(key) + self.SAMPLE_SALT)
                    samples[key] = [rng.sample(range(len(deck)), n) for _ in range(self.HANDS)]
                self._key, self._idx = key, samples[key]
        frozen = self.__dict__.get("_rank_at")
        state = (id(run), key, tuple(map(id, run.jokers)), tuple(run.hand_levels.values()), run.consumables_used.total(),
                 tuple(frozen.values()) if frozen else None,
                 tuple(map(id, run.consumables)), run.money)
        if self.POWER_EXACT:
            state += (len(run.draw_pile) if run.in_round or not self.POWER_PILE else None, tuple(_joker_state(j) for j in run.jokers),
                      (run.round_hands_played, run.discards_used, run.hands_left, run.discards_left) if run.in_round else None)
        cache = self.__dict__.setdefault("_powers", {})
        if state in cache and not fresh:
            return cache[state][0]
        if len(cache) > 256:
            cache.clear()
        hands = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
        with self._as_round_starts(run):
            seen: list = []
            base = p = self._mean_log(run, seen)
            for share, now, force in timed(self, run, hands, seen):
                passes = {}
                for on in (True, False):
                    if now is on:
                        passes[on] = base
                    else:
                        undo = force(on)
                        try:
                            passes[on] = self._mean_log(run)
                        finally:
                            undo()
                p += passes[False] + share * (passes[True] - passes[False]) - base
            if self.REACH_TRUST:
                p += self.REACH_TRUST * self._reach_bonus(run, seen)
        if not fresh:
            cache[state] = (p, run, tuple(run.jokers), tuple(run.consumables))   # held, so their ids stay unique
        return p

    POWER_PILE = True      # out of a round, power scores hands with the draw pile a round starts with (the deck less a
                           # hand), not whatever the last round left in it: Blue Joker (+2 chips a card left) was worth
                           # what the last round happened to leave (RZ364T64, 28 Oct: a few cards after the Big Blind).
                           # A fix, level, adopted 28 Oct: +0.6 +- 0.6 and -0.6 +- 0.6 points on the two sets

    @contextlib.contextmanager
    def _as_round_starts(self, run):
        """No blind in effect and, out of a round, every hand and discard left (and with POWER_PILE the draw pile a
        round starts with): how power scores hands."""
        blind, run.blind = run.blind, None
        left, pile = (run.hands_left, run.discards_left), run.draw_pile
        if not run.in_round:
            run.hands_left = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
            run.discards_left = max(0, run.base_discards + sum(j.discards_bonus for j in run.active_jokers()))
            if self.POWER_PILE:
                run.draw_pile = list(run.deck[run.hand_size:])
        try:
            yield
        finally:
            run.blind = blind
            run.hands_left, run.discards_left = left
            run.draw_pile = pile

    def _reach_bonus(self, run, seen) -> float:
        """xMult jokers that need a poker hand (The Duo, The Trio, The Family, The Order, The Tribe): power's sample
        hands count them only where the best play makes their hand already, but a discard toward it makes it more
        often. Each adds log(X) on the share of sample hands that hold its hand with REACH_CARDS more cards from the
        deck (one discard's worth), beyond the share whose best play has it (`seen`, power's own pass)."""
        js = [j for j in run.active_jokers() if j.name in XMULT_HAND]
        if not js or not seen or not self._idx:
            return 0.0
        deck, rules = run.deck, run.rules
        rng = random.Random(f"{self._key}:reach")
        hands = []
        for idx in self._idx:
            rest = [i for i in range(len(deck)) if i not in set(idx)]
            hands.append([deck[i] for i in idx] + [deck[i] for i in rng.sample(rest, min(len(rest), self.REACH_CARDS))])
        total = 0.0
        for j in js:
            hand, x = XMULT_HAND[j.name]
            plain = sum(1 for s in seen if s[2] is not None and hand in s[2][1].contains) / len(seen)
            reach = sum(1 for h in hands if _reaches(h, hand, rules)) / len(hands)
            total += max(0.0, reach - plain) * math.log(x)
        return total

    def _mean_log(self, run, seen: list | None = None) -> float:
        """The mean log of the best score over the sample hands, the run as it is (`seen`: each hand's poker hands
        noted, as _best_log)."""
        deck = run.deck
        return sum(self._best_log(run, [deck[i] for i in idx], seen) for idx in self._idx) / self.HANDS

    def _best_log(self, run, hand, seen: list | None = None) -> float:
        """The log of the best score these cards can make (`seen`: gets the poker hand of the best play, the set of
        those the cards can make, and the best play: its cards and poker hand)."""
        best, name, names, top = 0, None, set(), None
        for sub, r in self._candidates(run, hand):
            held = [c for i, c in enumerate(hand) if i not in sub][:max(0, run.hand_size - len(sub))]   # (EXTRA)
            played = [hand[i] for i in sub]
            score = estimate(run, played, held, r)
            names.add(r.name)
            if score > best:
                best, name, top = score, r.name, (played, r)
        if seen is not None:
            seen.append((name, names, top))
        return math.log1p(best)

    def deck_change_worth(self, run, trial) -> float:
        """What a trial's changes to the deck are worth, card by card (power's few sample hands rarely hold the one
        card a Tarot changes, so a whole-deck measure sees nothing):
        - a card changed (enhancement, edition, seal, chips, rank or suit): the change tried on every card of its
          rank in power's sample hands (each with the card's old look and its new one), shared out over that rank's
          cards in the deck: the same hands, and nothing else about them changes;
        - a card destroyed: each card of its rank in those hands against three that could have come instead;
        - a card added (or a Stone card): tried in CARD_HANDS shared hands, in place of one of their cards;
        plus what hands can't show: a Lucky card counts as its expected +4 Mult (estimates never roll chances), Gold
        cards and Gold Seals as money and Blue and Purple Seals as cards made, over the rounds left. Every option of
        a decision is tried on the same hands, so options are compared on equal terms."""
        before, after = {c.uid: c for c in run.deck}, {c.uid: c for c in trial.deck}
        changed = [(before[u], after[u]) for u in before.keys() & after.keys() if _looks(before[u]) != _looks(after[u])]
        gone = [before[u] for u in before.keys() - after.keys()]
        new = [after[u] for u in after.keys() - before.keys()]
        deck = run.deck
        n = min(run.hand_size, len(deck) - 1)
        if not (changed or gone or new) or n < 2:
            return 0.0
        self.power(run)                                      # its sample hands (self._idx) for this decision
        key = (run.seed, run.rounds_played, run.shops_seen, len(deck), n, tuple(run.hand_levels.values()), tuple(map(id, run.jokers)))
        if self.CARD_HANDS != type(self).CARD_HANDS:   # the plan's own count (PLAN_CARD_HANDS): its own hands
            key += (self.CARD_HANDS,)
        if self.__dict__.get("_card_key") != key:      # the hands, and their scores, for every option of this decision
            rng = random.Random(str(key[:5]) + ":cards")
            self._card_key, self._card_hands, self._card_best = key, [rng.sample(deck, n + 1) for _ in range(self.CARD_HANDS)], {}
        memo = self._card_best

        def best(cards) -> float:
            # by look, never by id(): the cards tried here are short-lived copies, and a later copy with another look
            # can get a dead one's id (which made the memo answer for the wrong card, and runs not repeat)
            k = tuple((c.debuffed, *_looks(c)) for c in cards)
            if k not in memo:
                memo[k] = self._best_log(run, cards)
            return memo[k]

        def hands_without(c):
            """Each shared hand, `c` not in it (the hand's spare card in its place), its last card the one to swap."""
            for h in self._card_hands:
                cards = [x for x in h[:n] if x is not c]
                yield cards + [h[n]] if len(cards) < n else cards

        def dressed(card, look, attrs):
            """`card` with `look`'s values of `attrs` (scored as estimates should)."""
            twin = copy.copy(card)
            for a in attrs:
                setattr(twin, a, getattr(look, a))
            return _as_scored(twin)

        def rank_hits(rank):
            """Each card of this rank in power's sample hands: (the hand, its position)."""
            for idx in self._idx:
                hand = [deck[i] for i in idx]
                for pos, c in enumerate(hand):
                    if c.rank == rank and not c.is_stone:
                        yield hand, pos

        total, share = 0.0, n / len(deck)
        with self._as_round_starts(run):
            for old, now in changed:
                economy = self._card_economy(run, now) - self._card_economy(run, old)
                if old.is_stone or now.is_stone:
                    d = sum(best(h[:-1] + [_as_scored(now)]) - best(h[:-1] + [_as_scored(old)]) for h in hands_without(old))
                    total += share * d / self.CARD_HANDS + economy
                    continue
                attrs = [a for a in LOOKS if getattr(old, a) != getattr(now, a)]
                same = sum(1 for c in deck if c.rank == old.rank and not c.is_stone)
                d = sum(self._best_log(run, h[:p] + [dressed(h[p], now, attrs)] + h[p + 1:])
                        - self._best_log(run, h[:p] + [dressed(h[p], old, attrs)] + h[p + 1:]) for h, p in rank_hits(old.rank))
                total += d / (len(self._idx) * max(1, same)) + economy
            for old in gone:
                if old.is_stone:
                    d = sum(best(h) - best(h[:-1] + [_as_scored(old)]) for h in hands_without(old))
                    total += share * d / self.CARD_HANDS - self._card_economy(run, old)
                    continue
                same = sum(1 for c in deck if c.rank == old.rank and not c.is_stone)
                rng = random.Random(f"{key[:5]}:gone:{old.uid}")
                d = 0.0
                for h, p in rank_hits(old.rank):          # the card it was, and three cards that could have come instead
                    was = best(h[:p] + [dressed(h[p], old, LOOKS)] + h[p + 1:])
                    spares = rng.sample([c for c in deck if c not in h and c is not old], 3)
                    d += sum(best(h[:p] + [x] + h[p + 1:]) for x in spares) / 3 - was
                total += d / (len(self._idx) * max(1, same)) - self._card_economy(run, old)
            for now in new:
                d = sum(best(h[:-1] + [_as_scored(now)]) - best(h) for h in hands_without(None))
                total += n / max(1, len(trial.deck)) * d / self.CARD_HANDS + self._card_economy(run, now)
        return total

    def card_add_worth(self, run, card) -> float:
        """What playing card `card` adds to the deck beyond a plain card's flat weight (w.card): deck_change_worth of the
        deck with it (its rank, suit, enhancement, seal and edition tried in shared hands; its money and cards made over
        the rounds left). Every card used to weigh the same, so a Standard pack's first card was taken over a Glass,
        Steel or sealed one (79 of 79 picks: the replay review's m1, 29 Oct)."""
        trial = self._trial(run)
        trial.add_cards([copy.deepcopy(card)])
        return self.DECK_TRUST * self.deck_change_worth(run, trial)

    def _card_economy(self, run, c) -> float:
        """What a card pays outside the hands it scores, in power: Gold ($3 each round it is held as the round
        ends), a Gold Seal ($3 as it scores), a Blue Seal (a Planet when held as a round ends), a Purple Seal (a
        Tarot when discarded), over the rounds left. With MIME_HELD, a held card's payments count once per trigger
        (Red Seal, each Mime)."""
        v = 0.0
        times = held_triggers(run, c) if self.MIME_HELD else 1
        held = c.enhancement in ("Gold", "Steel")    # kept in hand for what it pays there (held_value): seldom played
        if c.enhancement == "Gold":                  # or thrown, so a seal paid for either is worth next to nothing
            v += self.w.money * gold_money(run) * times
        if c.seal == "Gold" and not held:            # (Medium's Purple Seal went on a Gold Queen, worth as much as on
            v += self.w.money * gold_money(run)      # a plain 4: 6X7SCM12, the user's catch, 29 Oct)
        if c.enhancement == "Lucky" and self.LUCKY_MONEY:   # its $20 at 1 in 15 as it scores, as a Gold Seal's $3
            v += self.w.money * lucky_each(run)
        if c.seal == "Blue" or (c.seal == "Purple" and not held):
            v += (times if c.seal == "Blue" else 1) * self.w.keep * run.hand_size / max(1, len(run.deck)) * rounds_left(run)
        return v

    # ---- the build plan (spec docs/superpowers/specs/2026-10-29-build-planning-layer-design.md) ---------------------
    def _engines(self) -> dict:
        on = {"held": self.PLAN_HELD, "dna": self.PLAN_DNA, "flush": self.PLAN_FLUSH}
        return {k: e for k, e in ENGINES.items() if on.get(k)}

    def _joins(self, main: str, k: str, state) -> bool:
        """Does engine k join a plan whose main strategy is `main`? A tool when it is owned or the main strategy has a
        card for it to work on; a strategy when it fits the main one and the run has made progress toward it."""
        e = ENGINES[k]
        if e.kind == "tool":
            return main in e.fits and (e.owned(state) or ENGINES[main].key(state) is not None)
        return k in ENGINES[main].fits and e.progress(state) > 0

    def _plan_of(self, main: str, state, engines=None) -> tuple:
        """The plan with this main strategy: it, then the engines that join it (_joins)."""
        engines = self._engines() if engines is None else engines
        return (main,) + tuple(k for k in engines if k != main and self._joins(main, k, state))

    @contextlib.contextmanager
    def _plan_hands(self):
        """power on PLAN_HANDS sample hands and deck_change_worth on PLAN_CARD_HANDS (their own samples and caches: the
        keys hold the counts); the decision's own hands, and any count set on this bot, are back after."""
        key, idx = self._key, self.__dict__.get("_idx")
        own = {a: self.__dict__[a] for a in ("HANDS", "CARD_HANDS") if a in self.__dict__}
        self.HANDS, self.CARD_HANDS = self.PLAN_HANDS, self.PLAN_CARD_HANDS
        try:
            yield
        finally:
            for a in ("HANDS", "CARD_HANDS"):
                if a in own:
                    setattr(self, a, own[a])
                else:
                    del self.__dict__[a]
            self._key, self._idx = key, idx

    def _trial(self, run):
        """A copy of the run for the plan: the bot isn't copied, and the game seed's streams are never touched (the copy
        has none: the plan works from the odds, not the seed's future)."""
        saved = run.frames, run.log, run.seedrng
        run.frames = run.log = run.seedrng = None
        try:
            return copy.deepcopy(run, {id(self): self})
        finally:
            run.frames, run.log, run.seedrng = saved

    def _project(self, state, engines):
        """The plan's projection of `state` (spec 4.2): a trial with each engine's whole expected changes over the
        horizon, card changes first, then levels, then DNA's copies (of the main strategy's key card: the first
        strategy among `engines`); and the fractions left, [(fraction, apply_one)]."""
        trial = self._trial(state)
        shops = shops_ahead(state, self.PLAN_HORIZON)
        main = next((e for e in engines if e.kind == "strategy"), None)
        key = main.key if main is not None else None
        rest = []
        for stage in ("cards", "levels", "copies"):
            for e in engines:
                if e.stage == stage:
                    rest += e.project(state, trial, shops, key)
        return trial, rest

    def _value_of(self, run0, r, rest) -> float:
        """value(R) (spec 4.2): power on run0's deck with R's jokers, levels and hand size (PLAN_HANDS hands), plus the
        deck's changes from run0's deck to R's card by card (deck_change_worth on PLAN_CARD_HANDS hands, under those
        jokers and levels), plus each fraction left times one more such change's worth. run0's deck stays: options meet
        the same hands."""
        saved = run0.jokers, dict(run0.hand_levels), run0.base_hand_size
        run0.jokers = list(r.jokers)
        run0.hand_levels.update(r.hand_levels)
        run0.base_hand_size = r.base_hand_size
        try:
            with self._plan_hands():
                v = self.power(run0)
                v += self.DECK_TRUST * self.deck_change_worth(run0, r)
                for fraction, apply_one in rest:
                    v += fraction * self._one_change(run0, apply_one)
        finally:
            run0.jokers, run0.base_hand_size = saved[0], saved[2]
            run0.hand_levels.clear()
            run0.hand_levels.update(saved[1])
        return v

    def _one_change(self, run0, apply_one) -> float:
        """One more of a projected change (The Chariot on a King...), card by card on run0's deck under the jokers and
        levels run0 holds now (_value_of sets the projection's): deck_change_worth adds cards up one by one, so this is
        that card's own term. Remembered for the decision: every option's projection with these jokers shares it."""
        key = (self.__dict__.get("_decision"), apply_one, tuple(j.name for j in run0.jokers),
               tuple(run0.hand_levels.values()), run0.base_hand_size)
        memo = self.__dict__.setdefault("_plan_ones", {})
        if key not in memo:
            if len(memo) > 64:
                memo.clear()
            one = self._trial(run0)
            memo[key] = self.DECK_TRUST * self.deck_change_worth(run0, one) if apply_one(one) else 0.0
        return memo[key]

    def _place(self, trial, joker, keep=()) -> bool:
        """`joker` into the trial's row: a free slot, else in for the joker worth least outside `keep` (the plan's
        pieces), else the plan piece worth least (that choice remembered per row of jokers). False when no joker can
        go."""
        if trial.joker_room(joker):
            trial.jokers.append(joker)
            return True
        lineup = (tuple(j.name for j in trial.jokers), frozenset(keep), len(trial.deck), tuple(trial.hand_levels.values()))
        memo = self.__dict__.setdefault("_plan_places", {})
        if lineup not in memo:
            movable = [k for k, j in enumerate(trial.jokers) if not j.eternal and j.edition != "Negative"]
            pool_ = [k for k in movable if trial.jokers[k].name not in keep] or movable
            if len(memo) > 128:
                memo.clear()
            if pool_:
                base = self.power(trial)
                memo[lineup] = min(pool_, key=lambda k: self.owned_worth(trial, k, base))
            else:
                memo[lineup] = None
        if memo[lineup] is None:
            return False
        trial.jokers[memo[lineup]] = joker
        return True

    def _best_of(self, state, e, keep) -> str | None:
        """The joker of e's group (not owned, able to appear) that adds most to `state`, as a buy would place it;
        chosen once a shop (on the first state asked: an option's own change rarely changes which, and once one of
        the group is bought the group is owned and this isn't asked; Flush's 11 jokers tried for every option made a
        game 5x slower)."""
        key = (state.seed, state.rounds_played, state.shops_seen, state.in_round, e.name, frozenset(keep))
        memo = self.__dict__.setdefault("_plan_best", {})
        if key not in memo:
            gone, best, pick = pool.taken(state), None, None
            for n in e.required:
                cls = CATALOG.get(n)
                if cls is None or n in gone or not cls.can_spawn(state):
                    continue
                t = self._trial(state)
                if self._place(t, cls(), keep):
                    v = self.power(t)
                    if best is None or v > best:
                        best, pick = v, n
            if len(memo) > 64:
                memo.clear()
            memo[key] = pick
        return memo[key]

    def _plan_value(self, run0, state, plan: tuple, skip=frozenset()) -> float:
        """V(plan, state) (spec 4.2) on run0's sample hands: the plan's projection of `state` (the run, or a trial of it
        with a decision's change), plus, for each engine of the plan whose group is missing (not in `skip`), the chance
        one of its jokers comes times what the best of them adds to the projection (redone with it). Remembered within
        one plan_worth (its switch test and today's part ask for the same values)."""
        memo, mk = self.__dict__.get("_pv"), (id(state), plan, skip)
        if memo is not None and mk in memo:
            return memo[mk]
        engines = [ENGINES[k] for k in plan]
        r, rest = self._project(state, engines)
        base = v = self._value_of(run0, r, rest)
        keep = set().union(*(e.pieces() for e in engines)) if engines else set()
        shops = shops_ahead(state, self.PLAN_HORIZON)
        cards, buffoon = cards_seen(state, shops), pack_cards_seen("Buffoon", shops)
        today = None                                     # (PLAN_SYNERGY) the state as it is, no projection
        for e in engines:
            if e.required and e.name not in skip and not e.owned(state):
                p = joker_chance(state, e.required, cards, buffoon)
                best = self._best_of(state, e, keep) if p > 0 else None
                if best is not None:                     # bought only if it adds: a loss isn't a reason to expect it
                    g = self._trial(state)
                    self._place(g, CATALOG[best](), keep)
                    rg, rest_g = self._project(g, engines)
                    gain = self._value_of(run0, rg, rest_g) - base
                    if self.PLAN_SYNERGY:
                        if today is None:
                            today = self._value_of(run0, state, [])
                        gain -= self._value_of(run0, g, []) - today
                    v += p * max(0.0, gain)
        if memo is not None:
            memo[mk] = v
        return v

    def _is_live(self, run) -> bool:
        """Is `run` the run the bot is playing (set by its entry points: round, shop, pack, skip; in a test the first run
        it plans for), not a copy effect_worth or keep_worth made? Plans are made for the live run only."""
        return self.__dict__.setdefault("_live", run) is run

    def _current_plan(self, run) -> tuple:
        """The plan as it stands (chosen once per run state: _plan's memo); () with PLAN off or on a copy of the run."""
        return self._plan(run) if self.PLAN and self._is_live(run) else ()

    def _plan(self, run) -> tuple:
        """The plan for this decision (spec 4.3): its main engine first, then the engines that fit it with progress
        above 0; () when no engine scores above PLAN_MIN. The main engine changes only for one scoring PLAN_SWITCH more.
        Logged when it changes (plan_log, for the eval JSON). Only for the live run (_is_live): a copy gets none."""
        if not self._is_live(run):
            return ()
        key = (id(run), run.rounds_played, run.shops_seen, tuple(j.name for j in run.jokers), len(run.deck),
               tuple(run.hand_levels.values()), run.consumables_used.total())
        memo = self.__dict__.get("_plan_memo")
        if memo and memo[0] == key:
            return memo[1]
        self._decision = key                             # (the memos of what this decision measures: _best_of,
        engines = self._engines()                        # _one_change; set before the scores, which use them)
        none = self._plan_value(run, run, ())
        scores = {k: self._plan_value(run, run, (k,)) - none for k, e in engines.items() if e.kind == "strategy"}
        held = self.__dict__.get("_plan_main")
        main = held[1] if held and held[0] == id(run) else None
        best = max(scores, key=scores.get, default=None)
        if main not in scores or scores[main] < self.PLAN_MIN - self.PLAN_MARGIN:   # (no flicker on and off)
            main = best if best is not None and scores[best] > self.PLAN_MIN else None
        elif scores[best] > max(scores[main] * (1 + self.PLAN_SWITCH), scores[main] + self.PLAN_MARGIN):
            main = best
        plan = () if main is None else self._plan_of(main, run, engines)
        prev = memo[1] if memo and memo[0][0] == id(run) else None
        if plan != prev:
            self.__dict__.setdefault("plan_log", []).append(
                {"ante": run.ante, "round": run.rounds_played, "plan": list(plan),
                 "progress": {k: round(ENGINES[k].progress(run), 2) for k in engines},
                 "scores": {k: round(v, 3) for k, v in scores.items()}})
        self._plan_main = (id(run), main)
        self._plan_memo = (key, plan)
        self.__dict__.pop("_plan_bases", None)
        return plan

    def _plan_after(self, run, trial, plan, skip=frozenset()) -> tuple:
        """The plan as a decision leaves it (spec 4.4): with the engine a joker it adds would start. A tool joins a plan
        (it starts none alone); a strategy starts the plan when there is none, joins it when it fits the main one, and
        otherwise counts only as a switch: when with the joker it would score PLAN_SWITCH more than the main one."""
        engines = self._engines()
        started = [k for k, e in engines.items() if k not in plan and e.required and e.owned(trial) and not e.owned(run)]
        strategies = [k for k in started if engines[k].kind == "strategy"]
        if not started or (not plan and not strategies):
            return plan
        if not plan:
            return self._plan_of(strategies[0], trial, engines)
        main = plan[0]
        for k in strategies:
            if k not in ENGINES[main].fits:
                none = self._plan_value(run, trial, (), skip)
                theirs = self._plan_value(run, trial, (k,), skip) - none
                mine = self._plan_value(run, trial, (main,), skip) - none
                if theirs > self.PLAN_MIN and theirs > max(mine * (1 + self.PLAN_SWITCH), mine + self.PLAN_MARGIN):
                    return self._plan_of(k, trial, engines)
        return plan + tuple(k for k in started if self._joins(main, k, trial))

    def _plan_base(self, run, plan, skip) -> float:
        """V(plan, run) with these chance terms left out, remembered for the decision."""
        key = (self.__dict__.get("_plan_memo", (None,))[0], plan, tuple(sorted(skip)))
        memo = self.__dict__.setdefault("_plan_bases", {})
        if key not in memo:
            memo[key] = self._plan_value(run, run, plan, skip)
        return memo[key]

    def plan_worth(self, run, change, names=(), beyond_today: bool = True) -> float:
        """PLAN_WEIGHT times what a decision's change adds to the build plan (spec 4.4): `change(trial)` makes it on a
        copy of the run (False: it can't). With `beyond_today`, only beyond what it adds today, both measured the same
        way, for call sites whose today's worth is measured (its own effect counts once); without, the whole gain, for
        call sites whose today's worth is a flat weight (playing cards, packs, a Tarot kept). `names`: the jokers it adds
        or takes away; their engines' chance terms are left out on both sides (a piece bought is certain, one sold isn't
        counted as coming back). 0 with PLAN off."""
        if not self.PLAN:
            return 0.0
        plan = self._plan(run)
        trial = self._trial(run)
        if change(trial) is False:
            return 0.0
        skip = frozenset(k for k, e in ENGINES.items() if set(names) & set(e.required))
        self._pv = {}                                    # _plan_value's memo, for this trial's life only
        try:
            after = self._plan_after(run, trial, plan, skip)
            if not plan and not after:
                return 0.0
            gain = self._plan_value(run, trial, after, skip) - self._plan_base(run, plan, skip)
            if not beyond_today:
                return self.PLAN_WEIGHT * gain
            today = self._plan_value(run, trial, (), skip) - self._plan_base(run, (), skip)
            return self.PLAN_WEIGHT * (gain - today)
        finally:
            self._pv = None

    def _plan_pieces(self, plan) -> set:
        return set().union(*(ENGINES[k].pieces() for k in plan)) if plan else set()

    def _plan_adjust(self, run, key) -> float:
        """adjust's plan part: a joker owned (what selling it loses, the plan's part) or offered (what buying it adds:
        a plan piece, one that starts an engine, or any joker when the row is full and it would push one out), a pack
        (_plan_pack), Paint Brush and Palette under a held plan (a card more in hand). Memoised per decision."""
        kind, name = key[0], (key[1] if len(key) > 1 else None)
        if kind not in ("joker", "pack", "voucher"):
            return 0.0
        self._plan(run)                                  # this decision's plan first: the memo key below reads it
        memo = self.__dict__.setdefault("_plan_adj", {})
        mkey = (self.__dict__.get("_plan_memo", (None,))[0], key, tuple(id(j) for j in run.jokers), len(run.deck))
        if mkey in memo:
            return memo[mkey]
        v = 0.0
        if kind == "joker":
            plan = self._plan(run)
            pieces = self._plan_pieces(plan)
            owned = [k for k, j in enumerate(run.jokers) if j.name == name]
            if owned:                                    # selling one: only a plan piece's sale costs the plan
                k = owned[0]
                if name in pieces:
                    v = -self.plan_worth(run, lambda t: t.jokers.pop(k), names=(name,))
            else:                                        # buying one: a plan piece, one that starts an engine, or one
                starts = any(name in e.required for e in self._engines().values())   # that would push a piece out
                crowded = not run.joker_room() and all(j.name in pieces or j.eternal or j.edition == "Negative"
                                                       for j in run.jokers)
                cls = CATALOG.get(name)
                if cls is not None and (name in pieces or starts or crowded):
                    v = self.plan_worth(run, lambda t: self._place(t, cls(), pieces), names=(name,))
        elif kind == "pack":
            v = self._plan_pack(run, name)
        elif name in ("Paint Brush", "Palette") and "held" in self._plan(run):
            v = self.plan_worth(run, lambda t: setattr(t, "base_hand_size", t.base_hand_size + 1))
        if len(memo) > 256:
            memo.clear()
        memo[mkey] = v
        return v

    def _plan_card(self, run, card) -> float:
        """What adding playing card `card` to the deck adds under the plan beyond today (its own worth, card_add_worth,
        counts at the call sites)."""
        if not self.PLAN or not self._plan(run):
            return 0.0
        return self.plan_worth(run, lambda t: t.add_cards([copy.deepcopy(card)]))

    def _plan_pack(self, run, name) -> float:
        """What a pack may bring the plan (spec 4.5): each consumable of the plan's engines it can hold, at its chance in
        the pack, times what keeping it for its target adds; a Standard pack, under a held plan, a Steel King at the
        chance one of its cards is Steel (40% enhanced, 1 in 8 of them Steel), at half a Steel King's worth (most are
        another rank)."""
        plan = self._plan(run) if self.PLAN else ()
        p = PACKS.get(name)
        if not plan or p is None:
            return 0.0
        total = 0.0
        if p.kind in ("Arcana", "Spectral"):
            kind = "Tarot" if p.kind == "Arcana" else "Spectral"
            n = sum(1 for c in CONSUMABLES.values() if c.kind == kind)
            for e in (ENGINES[k] for k in plan):
                for cname in e.consumables:
                    if CONSUMABLES[cname].kind == kind:
                        saved, run.hand = run.hand, []       # the card it may bring, kept for a target in the deck
                        try:
                            total += min(1.0, p.shown / max(1, n)) * self._plan_keep(run, CONSUMABLES[cname](), full=True)
                        finally:
                            run.hand = saved
        elif p.kind == "Standard" and "held" in plan:
            steel = 1 - (1 - 0.4 / 8) ** p.shown
            total += steel * 0.5 * self._plan_card(run, Card(13, "Spades", enhancement="Steel"))
        return total

    def _plan_reroll(self, run) -> float:
        """What a reroll may bring the plan: for each engine of the plan whose group is missing, the chance its best
        joker is among a reroll's 2 cards, times what buying it adds."""
        if not self.PLAN:
            return 0.0
        plan = self._plan(run)
        memo = self.__dict__.get("_plan_rerolls")
        if memo and memo[0] == self._plan_memo[0]:      # once a shop state (rerolls weighed every decision)
            return memo[1]
        keep, total = self._plan_pieces(plan), 0.0
        for e in (ENGINES[k] for k in plan):
            if e.required and not e.owned(run):
                p = joker_chance(run, e.required, 2)
                best = self._best_of(run, e, keep) if p > 0 else None
                if best is not None:
                    total += p * self.plan_worth(run, lambda t, b=best: self._place(t, CATALOG[b](), keep), names=(best,))
        self._plan_rerolls = (self._plan_memo[0], total)
        return total

    def _holds(self, run):
        """A test for the cards the current plan holds in hand (a Steel card, a King with Baron), or None."""
        engines = [ENGINES[k] for k in self._current_plan(run)] if self.PLAN else []
        if not any(e.name == "held" for e in engines):
            return None
        return lambda c: any(e.holds(run, c) for e in engines)

    def _plan_wants(self, run, c) -> list:
        """The engines of the plan that want consumable `c`'s card changes."""
        return [ENGINES[k] for k in self._plan(run) if c.name in ENGINES[k].consumables]

    def _prefers(self, run, name, card) -> bool:
        """Is `card` a target the plan wants consumable `name` used on (Kings for The Chariot)? Chooses the plan if this
        state has none yet (_current_plan)."""
        return any(ENGINES[k].prefers(run, name, card) for k in self._current_plan(run))

    def _plan_use(self, run, c, targets) -> float:
        """What using `c` on hand positions `targets` adds to the plan (spec 4.4), measured on those targets."""
        if not self.PLAN or not self._plan_wants(run, c):
            return 0.0
        return self.plan_worth(run, lambda t: t.apply_consumable(copy.deepcopy(c), t.cards_at(targets)))

    def _plan_keep(self, run, c, full: bool = False) -> float:
        """What keeping Tarot or Spectral `c` for the plan's preferred target adds (spec 4.5): its use on such a card in
        the deck, times PLAN_KEEP; with `full` the whole of what that use adds (where today's worth is flat:
        consumable_choice's keep option, a pack), else only the plan's part beyond today (the shop's keep_worth measures
        today's). Nothing when the hand holds such a card (the use there is weighed now), or no engine of the plan
        wants `c`."""
        if not self.PLAN:
            return 0.0
        wants = self._plan_wants(run, c)
        if not wants:
            return 0.0
        prefers = lambda x: any(e.prefers(run, c.name, x) for e in wants)          # noqa: E731
        if any(not x.face_down and prefers(x) for x in run.hand):
            return 0.0
        held = {id(x) for x in run.hand}
        k = next((i for i, x in enumerate(run.deck) if prefers(x) and id(x) not in held), None)
        if k is None:
            return 0.0
        use = lambda t: t.apply_consumable(copy.deepcopy(c), [t.deck[k]])          # noqa: E731
        return self.PLAN_KEEP * self.plan_worth(run, use, beyond_today=not full)

    LEVEL1_CANDIDATES = False  # the sets ranked as if every poker hand were at level 1 (30 Oct, for the free Pluto): no
                               # level could change which are scored, but a levelled hand kept only its best set (its
                               # kickers matter with Raised Fist or Baron): 38 of the 61 games e-base changed, 11 won and
                               # 19 lost. Replaced by the ranking frozen at the levels a level change is measured from
                               # (_ranked_at): the sets of the position judged, the same on both sides of the change

    @contextlib.contextmanager
    def _ranked_at(self, levels):
        """Power's sets to score ranked at these levels (a copy is kept) while a level change is measured: both sides
        of the comparison score the same sets, so a level can only raise them (the free Pluto that read -0.025)."""
        saved = self.__dict__.get("_rank_at")
        self._rank_at = dict(levels)
        try:
            yield
        finally:
            self._rank_at = saved

    def _candidates(self, run, hand) -> list:
        """The sets of a sample hand worth scoring in full: the best three by poker hand alone, and the best of
        each poker hand. Ranked as if every poker hand were at level 1, so a level never changes which sets are
        scored and can only raise the best of them: ranked at their levels, a level of High Card put more High Card
        sets in the best three, pushing out the Pair that played its low kicker so Raised Fist read a higher card
        held, and a free Pluto measured -0.025 (CCU44VLE, the user, 30 Oct). Jokers don't change this ranking (hand
        rules do), so it is reused while jokers and levels are compared."""
        rules = run.rules
        key = (tuple((id(c), c.debuffed, *_looks(c)) for c in hand), rules)       # (a card changed in place is new)
        levels = self.__dict__.get("_rank_at") or run.hand_levels
        if not self.LEVEL1_CANDIDATES:
            key += (tuple(levels.values()),)
        cache = self.__dict__.setdefault("_cands", {})
        if key not in cache:
            if len(cache) > 4096:                   # (512 thrashed under the build plan's many trial hands)
                cache.clear()
            ranked = []
            for size in range(1, min(5, len(hand)) + 1):
                for sub in combinations(range(len(hand)), size):
                    played = [hand[i] for i in sub]
                    r = evaluate_cached(played, rules)
                    ranked.append((_base_at_level_1(played, r) if self.LEVEL1_CANDIDATES else _base_at(levels, played, r),
                                   sub, r))
            ranked.sort(key=lambda t: (-t[0], held_kickers([hand[i] for i in t[1]], t[2])))
            chosen, seen = [], set()
            for _, sub, r in ranked:
                if len(chosen) < 3 or r.name not in seen:
                    chosen.append((sub, r))
                    seen.add(r.name)
            cache[key] = (chosen, hand)                                     # the hand held, as above
        return cache[key][0]

    def planet_worth(self, run, planet, held=None) -> float | None:
        """A planet's worth, by levelling its hand in place (and setting aside `held`, the copy being used);
        None when a joker reacts to consumables being used, so only a full trial will do."""
        hand = getattr(planet, "hand", None)
        if hand is None or any(type(j).on_consumable_used is not Joker.on_consumable_used for j in run.jokers):
            return None
        return self.level_worth(run, hand, held)

    def level_worth(self, run, hand: str, held=None) -> float:
        """What a level of `hand` adds to the build: its power with the level, less without (setting aside `held`,
        a Planet being used), times PLANET_TRUST. Both with the sets ranked at the levels as they are (_ranked_at)."""
        with self._ranked_at(run.hand_levels):
            before = self.power(run)
            saved = run.consumables
            if held is not None:
                run.consumables = [x for x in saved if x is not held]
            run.hand_levels[hand] += 1
            try:
                return self.PLANET_TRUST * (self.power(run) - before)
            finally:
                run.hand_levels[hand] -= 1
                run.consumables = saved

    def celestial_worth(self, run, pack) -> float:
        """A Celestial pack's worth: the best `chosen` of the `shown` Planets it deals, drawn from those there are
        (the visible hands' Planets), each worth what a level of its hand adds (level_worth): the expected sum, from
        the order of the Planets' worths. With Telescope the most played hand's Planet is among them. Each Planet
        picked also grows Constellation (planet_growth_worth), which a level alone leaves out."""
        hands = [h for h in run.hand_levels if h not in SECRET_HANDS or run.hand_plays[h]]
        worth = {h: max(0.0, self.level_worth(run, h)) for h in hands}
        k, picks = pack.shown, pack.chosen
        grown = picks * self.planet_growth_worth(run)
        if run.has_voucher("Telescope") and run.most_played_hand() in worth:
            sure = worth.pop(run.most_played_hand())
            return grown + sure + (_top_sum(sorted(worth.values(), reverse=True), k - 1, picks - 1) if picks > 1 else 0.0)
        return grown + _top_sum(sorted(worth.values(), reverse=True), k, picks)

    def planet_growth_worth(self, run) -> float:
        """What one Planet used adds through the jokers it grows: the build's power with each Constellation X0.1 higher,
        against as it is (a single Planet is tried on a copy and counts it; a Celestial pack's levels didn't: EURSXV11)."""
        grow = [j for j in run.active_jokers() if j.name == "Constellation"]
        if not grow:
            return 0.0
        base = self.power(run)
        saved = run.jokers
        grown = []
        for j in saved:
            if any(j is g for g in grow):
                j = copy.copy(j)                     # a new object: power's cache can't answer for the old state
                j.xmult += 0.1
            grown.append(j)
        run.jokers = grown
        try:
            return self.power(run) - base
        finally:
            run.jokers = saved

    def bonus(self, j, run=None, growth: bool = True) -> float:
        """What a joker is worth beyond the hands it scores today. With `run`: a joker that grows is worth what it
        is expected to grow to (growth_worth), one fed only by some cards the grows weight in proportion to how many
        the deck has, and any other in GROWS nothing (Hit the Road starts again every round, Canio and Burglar
        don't grow on what the bot does); without one, all of the grows weight. `growth` False leaves the
        expected growth out (where it is the same on both sides of a comparison: an effect tried on a copy)."""
        w = self.w
        grows = w.grows * (j.name in GROWS)
        if run is not None and j.name in FED_BY:
            grows *= min(1.0, sum(map(FED_BY[j.name], run.deck)) / FED_FULL)
        elif run is not None:
            grows = self.growth_worth(run, j) if growth else 0.0
        if run is not None and growth and self.LEGENDS and j.name in ("Chicot", "Perkeo"):
            grows += self.legend_worth(run, j)
        if run is not None and growth and self.RIFF_MEASURED and j.name == "Riff-Raff":
            grows += self.riff_worth(run, j)
        if run is not None and growth and j.name == "Burnt Joker" and self.BURNT_MEASURED:
            grows += self.burnt_worth(run, j)
        if run is not None and (j.hands_bonus or j.discards_bonus or j.name == "Burglar"):
            grows += min(0.0, self.capacity_change(run, j))       # a hand it takes (Troubadour); not what it adds
        return (w.rarity[RARITY.get(j.rarity, 0)] + w.joker.get(j.name, 0.0) + grows
                + w.pays * (j.name in PAYS) + w.rules * (j.name in RULES)
                + w.negative * (j.edition == "Negative" and not (self.NEGATIVE_LASTS and run is not None))
                + sum(w.classes.get(c, 0.0) * p for c, p in JOKER_CLASSES.get(j.name, {}).items()))

    RIFF_MEASURED = True      # (on 30 Oct: a correctness fix, level on both sets) Riff-Raff worth the Common jokers it makes (riff_worth), not only its rarity's weight (it
                              # was 0.08: on ALEEB a free one was skipped with 4 slots empty; 29 Oct)
    RIFF_SAMPLE = 10          # Common jokers its worth is the mean over (every k-th by name: the same ones each time)

    def riff_worth(self, run, j) -> float:
        """What Riff-Raff's Common jokers bring: at the next blind it makes as many as there is room for (two at most),
        each worth what it adds to the build or its resale, whichever is more (one worth less is sold before the
        round's first hand, _dead_sale), as a mean over RIFF_SAMPLE Commons. Later blinds' jokers aren't counted:
        what those bring is mostly their resale, and counting money jokers pay made the bot worse (modifiers.OFF)."""
        owned = any(x is j for x in run.jokers)
        room = run.joker_slots - sum(x.edition != "Negative" for x in run.jokers) - (0 if owned or j.edition == "Negative" else 1)
        made = min(2, room)
        if made <= 0:
            return 0.0
        key = (id(run), run.shops_seen, run.rounds_played, tuple(map(id, run.jokers)), run.money)
        if self.__dict__.get("_riff", (None,))[0] != key:
            commons = sorted(n for n, c in CATALOG.items() if c.rarity == "Common" and n != "Riff-Raff")
            pick = commons[::max(1, len(commons) // self.RIFF_SAMPLE)][:self.RIFF_SAMPLE]
            saved = run.jokers
            if owned:
                run.jokers = [x for x in saved if x is not j]
            try:
                base = self.power(run)
                each = [max(self.joker_worth(run, CATALOG[n](), base), run.sell_value(CATALOG[n]()) * self.w.money)
                        for n in pick]
            finally:
                run.jokers = saved
            self._riff = (key, sum(each) / max(1, len(each)))
        return made * self._riff[1]

    BURNT_MEASURED = True     # (on 30 Oct, a clear fix: a switch only to measure it apart)
    BURNT_SHARE = 0.7         # the rounds whose first discard makes the main poker hand (a level each for Burnt Joker)

    def burnt_worth(self, run, j) -> float:
        """Burnt Joker: the first discard of each round levels up its poker hand. Worth the build's power with its most
        played hand (Pair before any) up by the levels it brings halfway through the growth horizon, one a round in
        BURNT_SHARE of them, as a growing joker counts what it grows to. In the shop it counted only its rarity
        (CCU44VLE, the user, 30 Oct: −0.30 at $8); owned, the round's discards already count the level they buy."""
        if any(x is j for x in run.jokers) and j.disabled:
            return 0.0
        hand = run.most_played_hand() or "Pair"
        horizon = min(self.GROWTH_HORIZON, max(1, 3 * self._antes_ahead(run, max(1, 9 - run.ante))))
        levels = self.BURNT_SHARE * horizon / 2
        whole, part = int(levels), levels - int(levels)
        gains = []
        with self._ranked_at(run.hand_levels):
            base = self.power(run)
            for k in (whole, whole + 1):
                run.hand_levels[hand] += k
                try:
                    gains.append(self.power(run) - base)
                finally:
                    run.hand_levels[hand] -= k
        return gains[0] * (1 - part) + gains[1] * part

    def capacity_change(self, run, j) -> float:
        """What joker j changes in a round's capacity (hands + DISCARD_AS_HANDS a discard), by the rule voucher_worth uses
        for Grabber, Wasteful and Hieroglyph: CAPACITY_WEIGHT on the log of the change. Only a loss counts (bonus): a
        Troubadour's -1 hand counted 0, so it was bought every time it was weighed (+0.85 of hand size, -0.66 missing;
        the third review's M1: 3 -> 7 wins on its 10 seeds); counting what Drunkard, Merry Andy and Burglar add too lost
        a win on 38 seeds (the bot uses 1.3-2.2 hands a round)."""
        def capacity(jokers) -> float:
            active = [x for x in jokers if not (x.disabled or x.perished)]
            hands = run.base_hands + sum(x.hands_bonus for x in active)
            discards = run.base_discards + sum(x.discards_bonus for x in active)
            if any(x.name == "Burglar" for x in active):          # +3 hands, no discards (at blind select)
                hands, discards = hands + 3, 0
            return max(1, hands) + DISCARD_AS_HANDS * max(0, discards)
        held = run.jokers
        with_j, without = (held, [x for x in held if x is not j]) if any(x is j for x in held) else (held + [j], held)
        return CAPACITY_WEIGHT * math.log(capacity(with_j) / capacity(without))

    def earned(self, run, j) -> float:
        """What joker j pays (modifiers.income), at the weight price puts on a dollar where it lands: the dollars that
        fill the purse up to the interest reserve at the money weight, those beyond it at spare_money of that, as
        spending there is charged. The bot shops its purse down to the reserve, so most of a long payer's dollars land
        past it. The third review's M2: Satellite +0.79 was bought over Constellation +0.34 at $129. EURSXV11 (the user,
        30 Oct): Rocket counted +1.46 over 19.5 rounds at the full weight, against −0.69 of Stencil's X1."""
        pay = income(self, run, j)
        if pay <= 0 or self.w.money <= 0:
            return pay
        return self.dollars_worth(run, pay / self.w.money)   # (strength included: what it is counted as paying)

    def dollars_worth(self, run, dollars: float) -> float:
        """What `dollars` coming in over the run are worth (a joker's pay, what a voucher saves): those that fill the
        purse up to the interest reserve at the money weight, the rest at spare_money of it, as price charges
        spending there."""
        gap = max(0.0, 5 * run.interest_cap + self.RESERVE_EXTRA - run.money)
        full = min(dollars, gap)
        return self.w.money * (full + self.spare_money * (dollars - full))

    def legend_worth(self, run, j) -> float:
        """What Chicot and Perkeo do that today's hands don't show. Chicot: every boss from now on without its effect
        (and back to 2x chips): the odds that adds to a boss drawn at random (boss_margin), for this ante's boss as
        it is, and for each ante after, at DEATH per whole chance. Perkeo: a Negative copy of a consumable held at
        the end of every shop: one per shop ahead (three an ante), each worth the main hand's level or a kept card,
        for on average half the antes counted."""
        antes = max(1, min(self.LEGEND_ANTES, round(self._antes_ahead(run, 9 - run.ante))))
        if j.name == "Chicot":
            odds = lambda m: self.margin_odds(m, run=run)                              # noqa: E731
            free = self.boss_margin(run, None) / AVERAGE_STRAIN                        # a boss with no effect, 2x
            later = DEATH * (antes - 1) * max(0.0, odds(free) - self.boss_odds(run, None))
            now = DEATH * max(0.0, odds(free) - self.boss_odds(run, run.ante_boss)) if run.ante_boss else 0.0
            return now + later
        main = run.most_played_hand()
        copy_worth = max(self.w.keep, self.level_worth(run, main)) if main else self.w.keep
        return 3 * antes * copy_worth / 2             # (copies come one a shop: on average half the time to count)

    def growth_worth(self, run, j) -> float:
        """A growing joker's worth beyond its present state: the build's power with it grown to its expected value
        halfway through the next rounds (GROWTH, _growth_rate), against as it is; Hiker's chips on the cards it
        scores as a Measure counts card chips. Measured with j where the bot keeps it (added if not owned)."""
        if j.name not in GROWTH and j.name != "Hiker":
            return 0.0
        saved = run.jokers
        lineup = saved if any(x is j for x in saved) else [(saved + [j])[i] for i in self.best_order(run, saved + [j])]
        run.jokers = lineup
        try:
            key = (id(run), run.rounds_played, run.shops_seen, run.in_round, len(run.deck), tuple(map(id, lineup)),
                   tuple(run.hand_levels.values()), id(j), getattr(j, GROWTH.get(j.name, ("value",))[0], None))
            cache = self.__dict__.setdefault("_growth", {})
            if key not in cache:
                if len(cache) > 256:
                    cache.clear()
                cache[key] = (self._grown_worth(run, j), lineup)     # the lineup held, so its ids stay unique
            return cache[key][0]
        finally:
            run.jokers = saved

    def _grown_worth(self, run, j) -> float:
        plays = self._sample_plays(run)
        horizon = min(self.GROWTH_HORIZON, max(1, 3 * self._antes_ahead(run, max(1, 9 - run.ante))))
        rounds = max(1, run.rounds_played)
        hands = run.hands_played / rounds if run.rounds_played else 3.0
        if j.name == "Hiker":                        # +5 chips for good on each card it scores
            scored = sum(len(r.scoring) for _, r in plays) / max(1, len(plays))
            return Measure(self, run).card_chips(5) * scored * hands * horizon / 2
        attr, step = GROWTH[j.name]
        now = getattr(j, attr)
        if step < 0 and not self.SMALL:
            return 0.0
        if j.name == "Seltzer":                      # retriggers every card while it lasts: that share of its worth
            lasts = min(1.0, now / max(1.0, hands * horizon))
            saved = run.jokers
            run.jokers = [x for x in saved if x is not j]
            try:
                without = self.power(run)
            finally:
                run.jokers = saved
            return -(1 - lasts) * max(0.0, self.power(run) - without)
        grown = self._grown_value(run, j, attr, now, step, plays, hands, rounds, horizon / 2, self.GROWN_FROM_NOW)
        if grown is not None and attr == "hand_size_bonus":   # (Turtle Bean: a hand holds a whole number of cards)
            grown = int(grown + 0.5)
        if grown is None or abs(grown - now) < 1e-9:
            return 0.0
        twin = copy.copy(j)                          # a new object: power's cache can't answer for the old state
        setattr(twin, attr, grown)
        base = self.power(run)
        saved = run.jokers
        run.jokers = [twin if x is j else x for x in saved]
        try:
            return self.power(run) - base
        finally:
            run.jokers = saved

    def _sample_plays(self, run) -> list:
        """The best play of each of power's sample hands as the build stands: (cards, poker hand) each."""
        self.power(run)                              # (its sample hands for this decision)
        seen: list = []
        with self._as_round_starts(run):
            self._mean_log(run, seen)
        return [s[2] for s in seen if s[2] is not None]

    @staticmethod
    def _grown_value(run, j, attr: str, now, step, plays, hands: float, rounds: int, ahead: float, from_now: bool = False) -> float | None:
        """The value `j`'s attribute is expected to have `ahead` rounds from now: `step` times the times it grows,
        from the share of power's sample hands whose best play grows it (`plays`: (cards, poker hand) each, `hands`
        played a round) or from this run's own rate per round of what feeds it. Ride the Bus and Obelisk start over
        when a hand breaks their run: they settle near the length of a run of hands that feed them (`from_now`: from
        what they have built, p^N of it kept over the N hands ahead, GROWN_FROM_NOW)."""
        n, k = j.name, max(1, len(plays))
        share = lambda f: sum(1 for cards, r in plays if f(cards, r)) / k       # noqa: E731
        per_round = lambda total: total / rounds                                # noqa: E731
        if n in ("Ride the Bus", "Obelisk"):
            if n == "Ride the Bus":
                p = share(lambda cards, r: not any(cards[i].is_face(run.pareidolia) for i in r.scoring))
            else:                                    # grows unless the hand becomes the most played outright
                hp = run.hand_plays
                p = share(lambda cards, r: any(v >= hp[r.name] + 1 for h, v in hp.items() if h != r.name))
            start = 0 if n == "Ride the Bus" else 1
            if from_now:                             # from what it has built: each hand it grows with p, else starts over
                N = hands * ahead
                kept = p ** N
                return start + kept * (now - start) + step * (p * (1 - kept) / (1 - p) if p < 1 else N)
            streak = min(p / (1 - p) if p < 1 else float("inf"), hands * ahead)
            return start + step * streak
        if n == "Runner":
            times = hands * share(lambda cards, r: "Straight" in r.contains)
        elif n == "Spare Trousers":
            times = hands * share(lambda cards, r: "Two Pair" in r.contains)
        elif n == "Square Joker":
            times = hands * share(lambda cards, r: len(cards) == 4)
        elif n == "Wee Joker":
            times = hands * sum(sum(cards[i].rank == 2 and not cards[i].is_stone for i in r.scoring) for cards, r in plays) / k
        elif n == "Green Joker":                     # +1 a hand, -1 a discard
            times = hands - per_round(run.discards_made)
        elif n == "Castle":                          # its suit, a quarter of the cards discarded
            times = per_round(run.cards_discarded) / 4
        elif n == "Yorick":
            times = per_round(run.cards_discarded) / 23
        elif n == "Hologram":                        # at least the cards the shops offer (Standard packs; as Constellation)
            times = max(per_round(run.cards_added), offered(run, "Playing card"))
        elif n == "Red Card":
            times = per_round(run.packs_skipped)
        elif n == "Flash Card":                      # at least the bot's own rerolls at the antes ahead (as Reroll
            times = max(per_round(run.rerolls_done), rerolls_ahead(run, rounds_left(run)))   # Surplus): it rerolls
            # few early, so a run's own rate read 0 at ante 3 (the user's 6AWQ2FCT, 30 Oct: "flash card here beats sly
            # given number of rerolls"; it grew to nothing and lost to every joker held)
        elif n == "Constellation":                   # at least the Planets the shops offer: owned, it makes each one
            times = max(per_round(run.consumables_used["Planet"]), planets_offered(run))   # worth buying (the user)
        elif n == "Campfire":                        # starts over after each boss: about half an ante's sales
            return now + step * per_round(run.cards_sold) * min(ahead, 1.5)
        elif n == "Madness":                         # each Small and Big Blind
            times = 2 / 3
        elif n == "Ice Cream":                       # -5 chips a hand
            times = hands
        elif n in ("Popcorn", "Turtle Bean"):        # -4 Mult a round; -1 hand size a round
            times = 1
        elif n == "Ramen":                           # X0.01 less a card discarded
            times = per_round(run.cards_discarded)
        else:
            return None
        return max(1 if attr == "xmult" else 0, now + step * times * ahead)

    def state_value(self, run) -> float:
        return self.power(run) + sum(self.bonus(j, run, growth=False) + income(self, run, j) for j in run.jokers)

    def best_order(self, run, jokers) -> list[int]:
        """The order the bot keeps `jokers` in: the usual one, or with Blueprint or Brainstorm wherever they add
        most to the build's power (each placement that copies another joker is tried)."""
        orders = copier_orders(jokers)
        if len(orders) == 1:
            return orders[0]
        saved, best, pick = run.jokers, None, orders[0]
        try:
            for o in orders:
                run.jokers = [jokers[i] for i in o]
                p = self.power(run)
                if best is None or p > best:
                    best, pick = p, o
        finally:
            run.jokers = saved
        return pick

    def _reorder(self, run):
        if run.in_round or not any(j.name in ("Blueprint", "Brainstorm") for j in run.jokers):
            return super()._reorder(run)
        order = self.best_order(run, run.jokers)       # out of a round: copiers where they copy the most
        order = ([i for i in order if run.jokers[i].name != "Ceremonial Dagger"]
                 + [i for i in order if run.jokers[i].name == "Ceremonial Dagger"])
        return ("order_jokers", order) if order != list(range(len(run.jokers))) else None

    def scoring_power(self, run) -> float:
        """power with the jokers in the order they will score in (best_order). Out of a round Ceremonial Dagger waits
        rightmost, where it destroys nothing, and goes back for the round; measured as it stood, beside a Dagger with
        Mult every offer read +0.22 and every joker held -0.22, and the shop churned (1R4CELJQ, the review's m2)."""
        order = self.best_order(run, run.jokers)
        if order == list(range(len(run.jokers))):
            return self.power(run)
        saved = run.jokers
        run.jokers = [saved[i] for i in order]
        try:
            return self.power(run)
        finally:
            run.jokers = saved

    def joker_parts(self, run, j, base: float) -> dict:
        """joker_worth's parts, for the Play tab's breakdown: what j adds to the build's typical score (power, where the bot
        keeps its jokers), its bonus (rarity, edition, the kind of joker, growth), what it pays, what it destroys."""
        saved = run.jokers
        jokers = saved + [j]
        run.jokers = [jokers[i] for i in self.best_order(run, jokers)]
        try:
            gain = self.power(run) - base
        finally:
            run.jokers = saved
        return {"build": gain, "bonus": self.bonus(j, run), "income": self.earned(run, j), "destroys": -self.havoc(run, j)}

    def joker_worth(self, run, j, base: float) -> float:
        """What joker j adds, placed where the bot keeps its jokers, and what it pays; `base` is power(run)."""
        saved = run.jokers
        jokers = saved + [j]
        run.jokers = [jokers[i] for i in self.best_order(run, jokers)]
        try:
            return self._lasting(run, j, self.power(run) - base + self.bonus(j, run) + self.earned(run, j) - self.havoc(run, j))
        finally:
            run.jokers = saved

    NEGATIVE_LASTS = False    # a Negative joker worth its worth times how much longer it stays than a joker that takes a
                              # slot (the rounds the run is likely to last against HOLD_ROUNDS), in place of the flat
                              # w.negative: it is never sold to make room (the user, 30 Oct). Off until measured
    HOLD_ROUNDS = 6.2         # rounds the value bot keeps a joker, on average (60 seeds, 30 Oct: 59% sold or destroyed,
                              # those after 4.5 rounds; the rest held 8.6 to the run's end)

    def _lasting(self, run, j, worth: float) -> float:
        """NEGATIVE_LASTS: a Negative joker's `worth` times the rounds the run is likely to last (rounds_left) over
        HOLD_ROUNDS, when that is more than one (a joker that takes a slot is replaced about then)."""
        if not self.NEGATIVE_LASTS or j.edition != "Negative" or worth <= 0:
            return worth
        return worth * max(1.0, rounds_left(run) / self.HOLD_ROUNDS)

    def owned_worth(self, run, k: int, base: float, havoc: bool = True) -> float:
        saved = run.jokers
        cost = self.havoc(run, saved[k]) if havoc else 0.0
        rest = saved[:k] + saved[k + 1:]
        run.jokers = [rest[i] for i in self.best_order(run, rest)]
        try:
            return self._lasting(run, saved[k], base - self.power(run) + self.bonus(saved[k], run)
                                 + self.earned(run, saved[k]) - cost)
        finally:
            run.jokers = saved

    def swap_worth(self, run, k: int, j, adj) -> float:
        """What selling joker k for joker j adds (SWAP_EXACT): the build's power with j in k's place less with the jokers
        as they are, both in the order the bot keeps them (best_order: a Ceremonial Dagger kept rightmost, or a copier
        not yet moved, would otherwise count on one side only; the review's m2), plus j's bonus, income and adjust less
        k's. Measured on the lineup the swap leaves, so what the two do to each other and to the rest (Baseball Card's
        X1.5 on Uncommon jokers) counts once."""
        saved = run.jokers
        old = saved[k]
        jokers = saved[:k] + saved[k + 1:] + [j]
        try:
            run.jokers = [saved[i] for i in self.best_order(run, saved)]
            ref = self.power(run)
            run.jokers = [jokers[i] for i in self.best_order(run, jokers)]
            gain = self.power(run) - ref
        finally:
            run.jokers = saved
        return (gain + self.bonus(j, run) + self.earned(run, j) - self.havoc(run, j) + adj(("joker", j.name))
                - self.bonus(old, run) - self.earned(run, old) + self.havoc(run, old) - adj(("joker", old.name)))

    VERDANT_SALE = True   # under Verdant Leaf (every card debuffed until a joker is sold in the round) the joker whose loss
                          # costs least is sold when the build without it, cards scoring, beats the build as it stands;
                          # it never sold in a round, so played the round debuffed (0.80 of ante-8 Verdant Leafs beaten
                          # against 0.96-0.97 for the other showdown bosses; on 20 seeds, 9 of 14 losses became wins and
                          # none of 6 wins was lost: the second replay review's M1, 29 Oct). A plain bug: on at once

    MILK_WON = True       # (on 30 Oct: a correctness fix, level) a round surely won with the winning cards in hand: spare hands spent first on plays of the other
                          # cards that pay more than the $1 of cash-out a hand used gives up (Business Card's face cards,
                          # growth from hands played, ...): the user's NNVPEGNB at The Club (29 Oct). Off until measured
    MILK_MARGIN = 1.1     # the win must beat what is needed by this much (a decaying joker can take a little off)
    MILK_BOSSES = {"The Hook", "The Mouth", "The Eye", "The Psychic", "The Tooth", "The Arm", "The Ox", "Cerulean Bell",
                   "Crimson Heart", "Verdant Leaf", "Amber Acorn", "The Serpent", "The Fish", "The House", "The Wheel",
                   "The Mark", "The Pillar"}   # bosses that touch held cards, hand types, money, jokers or what is seen

    LUCKY_MONEY = True        # (on 30 Oct: a correctness fix) a Lucky card's $20 at 1 in 15 counted each time it scores: in
                              # what a play pays (play_bonus: among plays that win anyway, and milking, the one that rolls
                              # it most, retriggers too), in the card's worth, and in Hanging Chad's (it retriggers the
                              # first scoring card twice: hand_pay). It was +4 Mult and never money: the user's 6AWQ2FCT,
                              # "im using chad to trigger lucky cards" (6 in the deck; selling Chad read +0.23)

    MILK_LIKELY = True        # milk a round not won in hand but all but sure to be: the best play kept, the hands after it
                              # and a spare one finish it at MILK_LIKELY_ODDS or better (_likely_after_milk). The user's
                              # CCU44VLE (30 Oct): a round cleared in about 1.5 hands, Business Card, hands to spare.
                              # On 30 Oct 15:00: +0.6 ± 0.9 and +1.2 ± 1.0 points, progress -0.04 and +0.01 (queue 43)
    MILK_LIKELY_ODDS = 0.95

    def _likely_after_milk(self, run, best, needed) -> bool:
        """A spare hand spent on pay leaves the round all but won: at least three hands left (the spare, the best play
        kept, one more to finish), and the build's typical hand over the hands after those two reaching what the best
        play leaves, at MILK_LIKELY_ODDS by margin_odds (a Small or Big Blind's curve; a boss's)."""
        if run.hands_left < 3 or best <= 0 or best >= needed:
            return False
        rest = needed - best
        typical = math.expm1(self.power(run, plain=True))
        m = typical * (run.hands_left - 2) / max(1.0, rest)
        return self.margin_odds(m, boss=run.active_boss is not None, run=run) >= self.MILK_LIKELY_ODDS

    def _milk_play(self, run, win_idx, mods, best, needed, likely: bool = False) -> list[int] | None:
        """A play of the cards the sure win doesn't use (face up) worth more beyond its score (play_bonus) than the $1 of
        cash-out a hand used gives up, the best of them; None without hands to spare (two or more left), room in the win
        (MILK_MARGIN; `likely`: no win in hand, _likely_after_milk said the round is all but won), a run that goes on
        after the round, or with a boss in MILK_BOSSES."""
        boss = run.active_boss
        if run.hands_left < 2 or (not likely and best < needed * self.MILK_MARGIN) or final_round(run) \
                or (boss is not None and boss.name in self.MILK_BOSSES):
            return None
        hand = run.hand
        rest = [i for i in range(len(hand)) if i not in win_idx and not hand[i].face_down]
        cost = self.w.money * 1                             # the hand not left over at cash-out
        best_v, pick = cost, None
        for size in range(1, min(5, len(rest)) + 1):
            for sub in combinations(rest, size):
                played = [hand[i] for i in sub]
                v = play_bonus(self, mods, played, evaluate_cached(played, run.rules))
                if v > best_v:
                    best_v, pick = v, list(sub)
        return pick

    GROWTH_HORIZON = GROWTH_HORIZON   # (a switch: BOT=GROWTH_HORIZON=18 counts a growing joker over the run, not 6
                                      # rounds: Constellation pays Joker Stencil's X1 back in some 5 Planets; EURSXV11)
    LASTING_HORIZON = True    # (on 30 Oct: a correctness fix, level) what growing jokers grow to, vouchers, Chicot and Perkeo, and boss rerolls counted over the
                              # antes the run is likely to last (rounds_left: survival-weighted), not to ante 8: in runs
                              # to 16 they stopped there (the second review's m4, the voucher audit's G1). Off until
                              # measured (it moves runs to 8 a little too)

    def _antes_ahead(self, run, old: float) -> float:
        """The antes ahead lasting things are counted over: with LASTING_HORIZON a third of rounds_left; else `old` (the
        count to ante 8 each place had)."""
        return rounds_left(run) / 3 if self.LASTING_HORIZON else old

    def _dead_sale(self, run) -> int | None:
        """Before a round's first hand, the joker the shop would sell (worth less kept than sold, by sell_margin), or
        None: a joker taken from a pack for its resale (one that costs Joker Stencil X1: EURSXV11, the user) is sold
        before it scores, not at the next shop. Once a round, as the shop counts it; not against a boss, whose debuffs
        the round's power would read as the jokers' (the review's n1: The Plant would make a face joker look dead)."""
        if not run.jokers or run.round_hands_played or run.discards_used or run.round_score or run.active_boss is not None:
            return None
        w = self.w
        key = (run.rounds_played, run.ante, tuple(map(id, run.jokers)))
        if self.__dict__.get("_dead", (None,))[0] == key:
            return None
        self._dead = (key,)
        base = self.scoring_power(run)
        adj = self.adjust(run, base)
        fire = sell_bonus(self, run) if self.FEED else 0.0
        for k, j in enumerate(run.jokers):
            if j.eternal:
                continue
            fed = fire if j.name != "Campfire" else 0.0
            if self.owned_worth(run, k, base) + adj(("joker", j.name)) + w.sell_margin < run.sell_value(j) * w.money + fed:
                return k
        return None

    def _leaf_sale(self, run) -> int | None:
        """The joker to sell to lift Verdant Leaf, or None: the one whose removal costs least of the round's power with
        no card debuffed, if that beats the power as it stands (every card debuffed). Where the run goes on (ante 8 of a
        run to 16), only when the round looks lost without it: the joker is gone for later too."""
        boss = run.active_boss
        if boss is None or boss.name != "Verdant Leaf" or getattr(boss, "disabled", False) or not run.jokers:
            return None
        keep = self.power(run, fresh=True)                   # as it stands: every card debuffed
        if not final_round(run):
            needed = run.blind.chips - run.round_score
            if math.expm1(keep) * max(1, run.hands_left) >= needed:
                return None
        seen, cards = set(), []                              # every card: the deck, the hand, the pile
        for c in run.deck + run.hand + run.draw_pile:
            if id(c) not in seen:
                seen.add(id(c))
                cards.append(c)
        flags = [c.debuffed for c in cards]
        saved = run.jokers
        cands = []
        try:
            for c in cards:
                c.debuffed = False
            lifted = self.power(run, fresh=True)
            for k, j in enumerate(saved):
                if j.eternal:
                    continue
                rest = saved[:k] + saved[k + 1:]
                run.jokers = [rest[i] for i in self.best_order(run, rest)]
                try:
                    cands.append((lifted - self.power(run, fresh=True), k))   # the round's power the sale costs
                finally:
                    run.jokers = saved
        finally:
            run.jokers = saved
            for c, f in zip(cards, flags):
                c.debuffed = f
        if not cands:
            return None
        cost, k = min(cands)
        return k if lifted - cost > keep else None

    def _best_swap(self, run, j, adj, sellable):
        """(worth, position) of the joker among positions `sellable` whose sale for j adds most (swap_worth); None if
        there is none."""
        return max(((self.swap_worth(run, k, j, adj), k) for k in sellable), default=None)

    def havoc(self, run, j) -> float:
        """What joker `j` (in run.jokers) costs in the jokers it destroys over the next ante (DESTROYS): each the
        average of what the others it may pick (not Eternal) are worth now, nothing for one worth less."""
        n = DESTROYS.get(j.name, 0)
        victims = [k for k, o in enumerate(run.jokers) if o is not j and not o.eternal]
        if not n or not victims:
            return 0.0
        base = self.power(run)
        worths = [max(0.0, self.owned_worth(run, k, base, havoc=False)) for k in victims]
        return min(n, len(victims)) * sum(worths) / len(worths)

    TRIALS = 8           # copies an effect is tried on, each with random streams of its own: its worth is the mean over
    HONEST_TRIALS = True  # how they turn out. Off: one copy with the run's own streams, which knew how a random effect
                          # would turn out (the joker Ectoplasm makes Negative, whether Wheel of Fortune hits; 27 Oct)
    PICK_TIES = True      # a pack pick worth as much as skipping (and not below 0) is taken: Jupiter, Earth and Saturn
                          # all measured 0 (no sample hand made their hands) and the pack was skipped, though a level
                          # never hurts (the user's XRTTE7VX, ante 1, 31 Oct). A fix: on
    RANDOM_TRIALS = 32    # an effect that drew on chance and turned out the same in all TRIALS copies is tried on this
                          # many: The Wheel of Fortune's 1 in 4 missed all 8 one time in ten and measured 0 (the user's
                          # XRTTE7VX at ante 1, 31 Oct: 0.0 against +0.19 on 200 copies). A fix: on

    def effect_worth(self, run, apply) -> float:
        """The worth of an effect, tried on copies of the run (the bot itself isn't copied): the build's power
        with everything but the deck changed (measured with the run's own cards, so on the same sample hands),
        the deck's changes card by card (deck_change_worth), each Tarot or Planet it makes worth one kept, and
        the money. Each copy's random streams are reseeded from what a player knows and the game seed's are set
        aside, so a random effect (Ectoplasm's joker, Sigil's suit, Judgement's joker...) turns out as it may, not as
        it will: the mean over the ways it turned out, each measured once."""
        frames, log = run.frames, run.log
        run.frames = run.log = None
        outcomes: dict = {}
        trials, k, drew = (self.TRIALS if self.HONEST_TRIALS else 1), 0, False
        try:
            while k < trials:
                trial = copy.deepcopy(run, {id(self): self})
                if self.HONEST_TRIALS:
                    for name, stream in trial.rng.items():
                        stream.seed(f"{run.seed}|{run.rounds_played}|{run.shops_seen}|{run.ante}|{name}|trial {k}")
                    trial.seedrng = None
                    states = [stream.getstate() for stream in trial.rng.values()]
                try:
                    apply(trial)
                except Exception:
                    return float("-inf")
                if self.HONEST_TRIALS and not drew:          # the effect drew on chance
                    drew = any(s.getstate() != st for s, st in zip(trial.rng.values(), states))
                key = _outcome(trial)
                outcomes[key] = (outcomes[key][0] + 1, outcomes[key][1]) if key in outcomes else (1, trial)
                k += 1
                if k == trials and drew and len(outcomes) == 1 and trials < self.RANDOM_TRIALS:
                    trials = self.RANDOM_TRIALS               # every copy came out alike: a chance that missed each time
        finally:
            run.frames, run.log = frames, log
        n = sum(times for times, _ in outcomes.values())
        return sum(times * self._trial_worth(run, trial) for times, trial in outcomes.values()) / n

    def _trial_worth(self, run, trial) -> float:
        """effect_worth for one copy, the effect applied."""
        cards, trial.deck = trial.deck, run.deck
        try:
            with self._ranked_at(run.hand_levels):           # (a level the effect adds can only raise the sets scored)
                rest = self.power(trial, fresh=True) - self.state_value(run)
        finally:
            trial.deck = cards
        rest += sum(self.bonus(j, trial, growth=False) + income(self, trial, j) for j in trial.jokers)   # its own deck: Lucky cards made
        made = Counter(c.name for c in trial.consumables) - Counter(c.name for c in run.consumables)
        if self.MADE_MEASURED:
            new = []
            for c in reversed(trial.consumables):
                if made[c.name] > 0:
                    made[c.name] -= 1
                    new.append(c)
            kept = sum(self.made_worth(trial, c) for c in new)
        else:
            kept = self.w.keep * sum(made.values())
        return (rest + self.DECK_TRUST * self.deck_change_worth(run, trial) + kept
                + self.w.money * (trial.money - run.money))

    MADE_MEASURED = True   # a consumable an effect makes is worth what it does (made_worth), not w.keep whatever it is:
                           # The Fool was worth the same copying the main hand's Planet as a useless one (27 Oct). On
                           # 480 seeds 47.3% against 49.4% (-2.1 ± 1.5 points, progress +0.08 ± 0.10): kept on the
                           # user's call, for the tactics a true worth makes possible (which card The Fool will copy)
    _made_depth = 0

    def made_worth(self, run, c) -> float:
        """What consumable `c`, just made by an effect, is worth (`run`: the copy it was made in): a Planet the level it
        adds (the bot uses one at once); a card that acts on no cards (The Hermit, Judgement, the Wheel...) what using
        it does, measured one deep (what that one makes counts w.keep); either at least what it sells for. One used on
        cards in hand counts w.keep: what it will do waits on a hand."""
        sale = self.w.money * run.sell_value(c)
        if c.kind == "Planet":
            v = self.planet_worth(run, c, held=c)
            return self.w.keep if v is None else max(sale, v)
        if c.max_targets == 0 and self._made_depth == 0 and c.can_use(run, []):
            k = next(i for i, x in enumerate(run.consumables) if x is c)
            self._made_depth += 1
            try:
                v = self.effect_worth(run, lambda t, k=k: t.use_consumable(k, []))
            finally:
                self._made_depth -= 1
            return max(sale, v)
        return self.keep_worth(run, c)

    KEEP_MEASURED = True   # a Tarot or Spectral kept for a hand to use it on is worth what it typically does there
    KEEP_HANDS = 4         # (keep_worth), not w.keep whatever it is: The Sun was bought for a build no Heart helps (27 Oct).
                           # On 480 seeds with MADE_MEASURED: 49.0% against 47.3% (+1.7 ± 1.9), progress even; 25s a
                           # game against 15s
    KEEP_TRUST = 2.0       # the measured keep times this: a card changed stays for the run and works with jokers still to
                           # come, which today's sample hands don't see (measured: the Devil 0.06, Magician 0.05, suit
                           # Tarots 0.004, against w.keep 0.1 for each; 48 games, 27 Oct). 2 against 1: set 90210
                           # +0.2 ± 1.4 points, set 777 +2.3 ± 1.6, both +1.1 ± 1.0 (progress +0.12 ± 0.07); games
                           # with Perkeo +2.5 ± 4.0. 3 did as well on set 777 but lost with Perkeo (−1.7 ± 4.6)

    def keep_worth(self, run, c, measured: bool | None = None) -> float:
        """What consumable `c`, held for a later hand, is worth. Measured (KEEP_MEASURED, or `measured`), one used on
        cards in hand: the mean, over KEEP_HANDS hands dealt from the deck (a player knows the deck, not the hands to
        come), of its best use there as the bot picks them (_uses, each tried on a copy: effect_worth), none below 0 (it
        waits, and is sold in the end), and at least what it sells for. Else w.keep. Remembered for the shop or round."""
        if c.kind == "Planet" and run.has_voucher("Observatory"):   # held, x1.5 Mult each time its hand is played: the
            saved = run.consumables                                # build's power with it held, against without (it
            try:                                                   # was the flat w.keep, so the stack Observatory pays
                run.consumables = [x for x in saved if x is not c]  # for was never built: the voucher audit, 29 Oct)
                before = self.power(run, fresh=True)
                run.consumables = run.consumables + [c]
                after = self.power(run, fresh=True)
            finally:
                run.consumables = saved
            return max(self.w.keep, after - before)
        if not (self.KEEP_MEASURED if measured is None else measured) or not run.deck:
            return self.w.keep
        if c.max_targets == 0:                  # acts on no cards: it is used when it can be; one that can't (Judgement
            if self.UNUSABLE_SELLS and not c.can_use(run, []):    # with no joker slot free) only sells
                return self.w.money * run.sell_value(c)
            return self.w.keep
        return max(self.w.money * run.sell_value(c), self.KEEP_TRUST * self._keep_measure(run, c))

    def _keep_measure(self, run, c) -> float:
        """_measured_keep, remembered for the shop or round."""
        key = (run.seed, run.ante, run.rounds_played, run.shops_seen, len(run.deck), run.consumables_used.total(),
               tuple(j.name for j in run.jokers), tuple(run.hand_levels.values()), c.name)
        memo = self.__dict__.setdefault("_keeps", {})
        if key not in memo:
            if len(memo) > 256:
                memo.clear()
            memo[key] = self._measured_keep(run, c)
        return memo[key]

    PACK_MEASURED = False  # Arcana and Spectral packs worth the cards they likely show, each as the bot values it (one
                           # used on cards: its measured keep, KEEP_TRUST and all; one that needs none: what using it
                           # does), the best `chosen` of `shown`; not the flat w.packs. ALEEB (28 Oct): since KEEP_TRUST 2
                           # a single Tarot outbid a pack of three (The Empress $3 +0.250, the Arcana Pack $4 +0.070; the
                           # pack held The Soul). Off until measured
    PACK_DRAWS = 6         # of the cards a pack can show, this many weighed (drawn afresh each shop), for that
    CONSUMABLE_SWAP = True   # the consumable slots full, a Tarot or Spectral on offer is weighed against the held card
                             # worth least, which is sold for it when the offer is clearly worth more (w.sell_margin), as
                             # jokers swap; it used not to be weighed at all (MLQUG157, 28 Oct: Justice held, The Chariot
                             # offered). A fix, level, adopted 28 Oct: +0.0 +- 0.3 and +0.2 +- 0.2 points
    PACK_TRUST = False     # the cheap way to the same end: the flat Arcana and Spectral weights times KEEP_TRUST. Off
                           # until measured

    def pack_weight(self, run, p) -> float:
        """A pack's worth before its price: w.packs for its kind, by its size; an Arcana or Spectral pack measured
        (PACK_MEASURED: pack_worth) or at its weight times KEEP_TRUST (PACK_TRUST)."""
        if p.kind in ("Arcana", "Spectral"):
            if self.PACK_MEASURED:
                return self.pack_worth(run, p)
            if self.PACK_TRUST:
                return self.w.packs.get(p.kind, 0.0) * PACK_SIZE.get(p.size, 1.0) * self.KEEP_TRUST
        return self.w.packs.get(p.kind, 0.0) * PACK_SIZE.get(p.size, 1.0)

    def pack_worth(self, run, p) -> float:
        """An Arcana or Spectral pack's worth: the expected best `chosen` of the `shown` cards it deals, from PACK_DRAWS
        of the cards it can deal (drawn afresh each shop), each worth what the bot makes of it: one used on cards its
        measured keep at KEEP_TRUST (a pack deals a hand to use it on, as a typical hand), one that needs none what
        using it now does (nothing if it can't be used). The Soul and Black Hole, rare, are left out."""
        kind = {"Arcana": "Tarot", "Spectral": "Spectral"}[p.kind]
        gone = pool.taken(run) | pool.PACK_ONLY
        names = sorted(n for n, cls in CONSUMABLES.items() if cls.kind == kind and n not in gone and cls.can_spawn(run))
        rng = random.Random(f"{run.seed}|{run.shops_seen}|{p.kind}|pack")
        values = sorted((self._pack_card_worth(run, CONSUMABLES[n]()) for n in rng.sample(names, min(self.PACK_DRAWS, len(names)))),
                        reverse=True)
        return _top_sum(values, p.shown, p.chosen)

    def _pack_card_worth(self, run, c) -> float:
        if c.max_targets > 0:
            return self.KEEP_TRUST * self._keep_measure(run, c)
        key = (run.seed, run.ante, run.rounds_played, run.shops_seen, len(run.deck), run.consumables_used.total(),
               tuple(j.name for j in run.jokers), tuple(run.hand_levels.values()), run.joker_slots, run.money, c.name, "use")
        memo = self.__dict__.setdefault("_keeps", {})
        if key not in memo:
            if len(memo) > 256:
                memo.clear()
            memo[key] = max(0.0, self.effect_worth(run, lambda t: t.apply_consumable(copy.deepcopy(c), []))) \
                if c.can_use(run, []) else 0.0
        return memo[key]

    def _measured_keep(self, run, c) -> float:
        """keep_worth's mean over hands dealt from the deck, as in a round (a hand to use it on)."""
        rng = random.Random(f"{run.seed}|{run.rounds_played}|{run.shops_seen}|keep")
        saved = run.hand, run.current_shop, run.open_pack_state
        total = 0.0
        try:
            run.current_shop = run.open_pack_state = None
            for _ in range(self.KEEP_HANDS):
                run.hand = rng.sample(run.deck, min(run.hand_size, len(run.deck)))
                best = 0.0
                for targets, _ in self._uses(run, c, run.hand):
                    best = max(best, self.effect_worth(
                        run, lambda t, ts=targets: t.apply_consumable(copy.deepcopy(c), t.cards_at(ts))))
                total += best
        finally:
            run.hand, run.current_shop, run.open_pack_state = saved
        return total / self.KEEP_HANDS

    def adjust(self, run, base: float):
        """The network's corrections for this decision, as item key -> power (none without a network); with PLAN, plus
        what a joker bought or sold, a pack or a voucher adds to the build plan (_plan_adjust)."""
        if self.net is None:
            net = lambda key: 0.0                                               # noqa: E731
        else:
            h = self.net.hidden(run, base)
            net = lambda key: self.net.correction(h, key)                       # noqa: E731
        if not self.PLAN:
            return net
        return lambda key: net(key) + self._plan_adjust(run, key)

    RESERVE_EXTRA = 10        # dollars held beyond what earns the most interest, for the next shop (price): 0 -2.7 +- 2.0,
                              # 20 -2.3 +- 1.9 points on set 90210 (29 Oct, progress level): 10 kept. Before that never
                              # measured. Shops at ante 3+ are left at $35-44 (29 Oct, `probe_reserve.py`)

    def price(self, run, cost: int) -> float:
        """What spending `cost` costs, in power: each $1 at the money weight, but only spare_money of that for
        money beyond a reserve (what earns the most interest, plus RESERVE_EXTRA for the next shop), which otherwise
        just sits there; plus the interest the spending loses, and what it takes from Bull and Bootstraps."""
        interest = (lambda m: min(run.interest_cap, max(0, m) // 5)) if run.interest_enabled else (lambda m: 0)
        reserve = 5 * run.interest_cap + self.RESERVE_EXTRA
        spare = min(max(0, cost), max(0, run.money - reserve))
        money = self.w.money * (cost - spare + self.spare_money * spare)
        if self.INTEREST_REFILL:                     # the interest lost until both purses reach the cap
            lost = self._interest_lost(run.money, cost, interest)
            held = self.w.money * lost
        else:
            held = self.w.interest * (interest(run.money) - interest(run.money - cost))
        bull = spend_cost(self, run, cost)
        if self.MONEY_ONCE:                          # money is spent later or held for Bull's chips, not both
            return max(money, bull) + held
        return money + held + bull

    INTEREST_REFILL = False   # interest lost by spending counted in dollars, round by round until the purse is back at the
                              # cap (each round paying ROUND_PAY besides interest): $32 -> $22 loses $1 once, not $1 a
                              # round at w.interest (0.1, five dollars' worth). Off until measured
    ROUND_PAY = 6             # a round's cash-out besides interest: the blind's reward and $1 a hand left, about
    MONEY_ONCE = False        # with Bull or Bootstraps, spending costs the larger of the money's worth and the chips (or
                              # Mult) it holds up, not both: money held for Bull is money not spent. Off until measured
    RISK_MONEY = 0.0          # money in the shop worth less the likelier the next boss ends the run, at this trust
                              # (money_scale). Lost, the more the stronger (28 Oct, 480 seeds): 0.25 -5.8 +- 2.2 and
                              # -3.1 +- 2.4 points on the two sets, 0.5 -9.4 +- 2.3 and -9.4 +- 2.4. Off
    SWAP_EXACT = True         # a joker sold for another (shop swap, Buffoon pick, a sale to afford one) scored as the
                              # lineup it leaves: power with the new one in the old one's place, not the new one's worth
                              # beside every joker held less the old one's. The replay review (29 Oct, M1): 7S5X1EZS sold
                              # Baseball Card for a Rough Gem worth +0.83 only beside it (+0.18 without). A plain bug:
                              # on at once (the user, 29 Oct 21:00), measured with the review's other fixes together
    END_MONEY = True          # money worth nothing in the run's last shop, interest only over the shops left to spend
                              # it in (money_scale). Level, adopted 28 Oct: +0.6 +- 0.7 and +0.6 +- 0.8 points on the two
                              # sets (45 and 55 of 480 games change, all at antes 7-8)
    INTEREST_SHOPS = 5        # shops $1 of interest a round is counted for (w.interest is 5 times w.money)
    MONEY_SCALE = 1.25        # money and interest in the shop worth this share of their weights (money_scale): the
                              # weights were tuned before KEEP_MEASURED and the rest; RISK_MONEY (less in danger) lost the
                              # more the stronger, and losing runs fall behind from ante 3-4 (28 Oct). Adopted 28 Oct:
                              # +4.8 +- 2.2 and +4.2 +- 2.3 points on the two sets (1.5: +4.6 +- 2.4 on the first)
    SURPLUS = 0.0             # money and interest worth up to this share more the surer the build beats the next boss
                              # (money_scale; the user's point on Reserved Parking: "by the time it matters I'll have
                              # the profit"). MONEY_SCALE 1.5 everywhere was a plateau, 2.0 lost: more only with room.
                              # Off until measured
    INTEREST_SCALE = None     # interest alone worth this share of its weight (money_scale); None: as MONEY_SCALE. The
                              # 28 Oct gain moved both together. 1.0: -5.0 +- 1.8, 1.5: -2.7 +- 1.9 points (29 Oct): kept
                              # with money at 1.25

    def _next_boss_odds(self, run) -> float:
        ahead = run.blind is not None and run.blind.kind < 2
        return self.boss_odds(run, run.ante_boss if ahead else None)

    BEHIND_GAMBLE = True    # (on 30 Oct: level-positive on both sets) in the shop before a boss the build likely loses to (boss_odds under BEHIND_ODDS): money worth
                            # its chance of mattering (the odds of surviving), and a reroll worth the odds it may add (the
                            # recent best offers' gain in margin through the boss's odds, convex when behind), not its
                            # mean power: the user (29 Oct, 6X7SCM12 at $76 into The Mouth at 0.38): "shouldn't it have
                            # tried to find another joker, accepting the tradeoff?". Off until measured
    BEHIND_ODDS = 0.5

    def _behind(self, run) -> float | None:
        """BEHIND_GAMBLE: the odds of beating this ante's boss when the next blind is it and they are under
        BEHIND_ODDS; else None."""
        if not self.BEHIND_GAMBLE or run.blind is None or run.blind.kind != 1 or run.ante_boss is None:
            return None
        odds = self.boss_odds(run, run.ante_boss)
        return odds if odds < self.BEHIND_ODDS else None

    def _behind_hope(self, run) -> float:
        """What a reroll may add to the odds of beating the boss ahead (BEHIND_GAMBLE): each recent best offer's gain
        (in power, the margin times e^that) through the odds (m^4 / (1 + m^4)), at DEATH, the mean of them, at
        REROLL_SHARE; 0 when not behind or with fewer than three offers seen."""
        if self._behind(run) is None:
            return 0.0
        memo = self.__dict__.get("_rerolls")
        seen = memo[2][-self.REROLL_MEMORY:] if memo is not None and memo[0] == id(run) else []
        if len(seen) < 3:
            return 0.0
        m = self.boss_margin(run, run.ante_boss)
        odds = lambda x: self.margin_odds(x, run=run)      # noqa: E731
        return self.REROLL_SHARE * DEATH * sum(odds(m * math.exp(b)) - odds(m) for b in seen) / len(seen)

    def money_scale(self, run) -> tuple[float, float]:
        """What money and interest are worth in this shop, as shares of their weights. The losses read on 28 Oct
        (200 seeds) died holding the interest reserve ($35 median, 71 of 92 with $30 or more), 67 of them with a
        typical round already short of the target: money is only worth something to a run that goes on.
        RISK_MONEY: both divided by 1 + RISK_MONEY * DEATH * 4 * (1 - odds), the odds of beating the next boss (this
        ante's while it is ahead, else one drawn at random); 4 * (1 - odds) is what power does for the log of those
        odds (boss_odds: m^4 / (1 + m^4)), so a hopeless build spends most freely and a safe one as before.
        END_MONEY: nothing in the run's last shop, and interest only for the shops left after this one.
        MONEY_SCALE: both times this everywhere (the other side of RISK_MONEY, which lost the more the stronger);
        INTEREST_SCALE, when set, for interest instead.
        SURPLUS: both times 1 + SURPLUS * (2 * odds - 1) where the odds are better than even, nothing more below."""
        money = self.MONEY_SCALE
        interest = money if self.INTEREST_SCALE is None else self.INTEREST_SCALE
        if self.RISK_MONEY:
            f = 1 / (1 + self.RISK_MONEY * DEATH * 4 * (1 - self._next_boss_odds(run)))
            money, interest = money * f, interest * f
        if self.SURPLUS:
            f = 1 + self.SURPLUS * max(0.0, 2 * self._next_boss_odds(run) - 1)
            money, interest = money * f, interest * f
        if self.END_MONEY:
            left = shops_left(run)
            money *= left > 0
            interest *= min(1.0, left / self.INTEREST_SHOPS)
        behind = self._behind(run)                   # BEHIND_GAMBLE: money only matters if the boss ahead is beaten
        if behind is not None:
            money, interest = money * behind, interest * behind
        return money, interest

    def _interest_lost(self, money: int, cost: int, interest) -> float:
        """Dollars of interest spending `cost` loses: the purse with it and without, each earning ROUND_PAY and its
        interest a round, until both earn the same (the cap; a few rounds at most)."""
        a, b, lost = money, money - cost, 0.0
        for _ in range(8):
            ia, ib = interest(a), interest(b)
            if ia == ib:
                break
            lost += ia - ib
            a, b = a + self.ROUND_PAY + ia, b + self.ROUND_PAY + ib
        return lost

    HAND_INCOME = True        # jokers that pay as hands are played (Reserved Parking, Business Card, Rough Gem, Golden
                              # Ticket) worth what they typically bring a round (modifiers.hand_pay), like Golden Joker's
                              # $4: they counted 0 when bought (27 Oct, Reserved Parking at -0.43). Level on 480 seeds
                              # each (28 Oct, on KEEP_TRUST 2): set 90210 -0.8 +- 1.0 points, set 777 +0.8 +- 0.9
    DISCARD_INCOME = False    # jokers that pay for discards (Mail-In Rebate, Trading Card, Faceless Joker) worth what
                              # they typically bring a round (modifiers.discard_pay): they counted 0 when bought
                              # (C5X6MXUN, 28 Oct: Mail-In Rebate 0.00 in an Abandoned Deck, behind a dead Sock and
                              # Buskin at +0.05). Off until measured
    INCOME_STRENGTH = None    # the strength of the income rules set to 0 (modifiers.OFF: Golden Joker, Rocket, Cloud 9,
                              # To the Moon, Egg) when the bot of 24% hoarded money; MONEY_SCALE's win says money is now
                              # worth more, not less (C5X6MXUN, 28 Oct: Cloud 9's $4 a round worth 0.05). None: as set
    PAY_FROM_PLAY = False     # what the hand payers bring from this run's own hands (faces, Diamonds, Gold cards scored,
                              # faces held a hand: run.pay_seen) once it has played 6, not the deck's share times 3 scored
                              # cards (they paid 1.5-1.9x that, 28 Oct); Satellite with the new Planet types to come at
                              # the run's rate so far (the user's point: these should follow the run). Lost (29 Oct):
                              # -2.5 +- 1.1 and -3.1 +- 1.2 points on the two sets. Closer to what they pay, they are
                              # bought more, and the slots score less: money from them is worth less than its dollars. Off
    MIME_HELD = True        # held cards' end-of-round payments (Gold $3, Blue Seal Planet) once per trigger: Mime's
                              # second payment in its income (modifiers.mime_pay), and Red Seals and Mimes in a card's
                              # worth and in what playing it forfeits. Mime counted its scoring only (28 Oct, a Plasma game
                              # with 18 Gold cards: +0.016, and the bot would sell it for Satellite). Level on 480 seeds
                              # each (only 9 of 960 games change): set 90210 +0.2 +- 0.4 points, set 777 -0.2 +- 0.2

    # ---- consumables ------------------------------------------------------------------------------
    def kept_list(self) -> list:
        return self.__dict__.setdefault("kept", [])

    def is_kept(self, c) -> bool:
        return any(c is k for k in self.kept_list())

    def _kept_now(self, run) -> list:
        """Consumables kept this round, or in this shop: weighed again in the next."""
        key = (id(run), run.rounds_played, run.in_round)
        memo = self.__dict__.get("_kept_round")
        if memo is None or memo[0] != key:
            memo = self._kept_round = (key, [])
        return memo[1]

    def held_back(self, run, c) -> bool:
        """Kept for good (the planner's choice) or for now."""
        return self.is_kept(c) or any(c is k for k in self._kept_now(run))

    PURPLE_ROOM = True        # (on 30 Oct, a clear fix: a switch only to measure it apart; with modifiers' purple_forfeit)
    MAKER_WAIT = 0.8          # what The High Priestess's (The Emperor's) full output later is worth against now, when full
                              # slots would cut what it makes (consumable_choice)

    def consumable_choice(self, run, c, uses) -> int:
        """Which of `uses` to make now, or len(uses) to keep `c`. A Planet that levels a hand the sample hands
        never make measures 0: it is used all the same (a level never hurts), unless Observatory pays for holding it."""
        if any(j.name == "Perkeo" for j in run.jokers) and not any(self.held_back(run, k) for k in run.consumables):
            if not self.SMALL or c is self._perkeo_pick(run):
                return len(uses)                               # Perkeo copies what is held at each shop's end
        if c.name in SUIT_TAROT and self.BOSS_AWARE and self._boss_ahead_debuffs(run, SUIT_TAROT[c.name]):
            return len(uses)                                   # not into the suit this ante's boss debuffs: kept
        i = next(k for k, x in enumerate(run.consumables) if x is c)
        adj = self.adjust(run, self.power(run))
        best, choice = adj(("keep", c.kind)) + self._plan_keep(run, c, full=True), len(uses)
        creates = sum((getattr(c, "spec", None) or {}).get("creates", {}).values())
        if creates and self.MAKER_WAIT > 0:                    # The High Priestess, The Emperor: as many as there is room
            held = sum(x.edition != "Negative" for x in run.consumables if x is not c)   # for once it is used
            short = creates - max(0, run.consumable_slots - held)
            if short > 0:                                      # kept, it makes them all once a slot is free (the user,
                def full(trial, k=i, extra=short):              # CCU44VLE: one Planet of two, with The World held)
                    trial.consumable_slots += extra
                    trial.use_consumable(k, [])
                best = max(best, self.MAKER_WAIT * self.effect_worth(run, full))
        quick = self.planet_worth(run, c, held=c) if c.kind == "Planet" else None
        level = c.kind == "Planet" and not run.has_voucher("Observatory")
        freed = 0.0                                            # slots full in a round, a Purple Seal card waiting for a
        if (self.PURPLE_ROOM and run.in_round and run.discards_left > 0 and not run.consumable_room()
                and c.edition != "Negative"                                                                    # discard:
                and any(x.seal == "Purple" and not x.debuffed for x in run.hand) and not creates):  # the slot used frees
            freed = strength(self, "Purple Seal") * self.w.keep                  # is its Tarot's (CCU44VLE, the user)
        for k, (targets, _) in enumerate(uses):
            v = quick if quick is not None else self.effect_worth(run, lambda trial, t=targets: trial.use_consumable(i, t))
            v += adj((c.kind.lower(), c.name)) + planet_bonus(self, run, c) + self._plan_use(run, c, targets) + freed
            if v > best or (level and v >= best and choice == len(uses)):
                best, choice = v, k
        return choice

    def _perkeo_pick(self, run):
        """The consumable to hold for Perkeo to copy: the Planet whose level adds most (a Negative copy every shop), else
        the first held. With PERKEO_FOCUS, the one whose copy is worth most (_copy_worth)."""
        if self.PERKEO_FOCUS:
            scored = [(self._copy_worth(run, c), -k, c) for k, c in enumerate(run.consumables)]
            return max(scored)[2] if scored else None
        planets = [(self.planet_worth(run, c) or 0.0, -k, c) for k, c in enumerate(run.consumables) if c.kind == "Planet"]
        return max(planets)[2] if planets else (run.consumables[0] if run.consumables else None)

    PERKEO_FOCUS = True   # Perkeo copies a card held at random at each shop's end: with this, the bot holds what is worth
                          # copying (sells what waters the copies down, buys a Planet to be copied). Without, it held
                          # whatever it had. On 120 seeds given Perkeo (27 Oct): one kind held at 78% of shop ends
                          # against 35%, beat ante 8 in 90 against 73 (+14.2 ± 4.5 points, progress +0.84 ± 0.32)

    def _perkeo_on(self, run) -> bool:
        return self.PERKEO_FOCUS and any(j.name == "Perkeo" for j in run.active_jokers())

    UNUSABLE_SELLS = True  # a card that acts on no cards and can't be used now (Judgement with the joker slots full) is
                           # worth what it sells for, kept or copied; one that can be used, as a copy, what using it does.
                           # It was w.keep either way: ALEEB's Perkeo copied Judgement over Jupiter with no slot free,
                           # and the Negative Judgements piled up (27 Oct)

    def _copy_worth(self, run, c) -> float:
        """What a Negative copy of consumable `c` is worth: a Planet the level it adds (level_worth: planet_worth gives
        up with a copier held), one acting on no cards what using it does (UNUSABLE_SELLS: what it sells for if it can't
        be used now), any other card as one kept, measured (with w.keep for every Tarot, the choice was a tie)."""
        hand = getattr(c, "hand", None)
        if c.kind == "Planet" and hand:
            return self.level_worth(run, hand)
        if c.max_targets == 0 and self.UNUSABLE_SELLS and c.can_use(run, []):
            key = (run.seed, run.ante, run.rounds_played, run.shops_seen, len(run.deck), run.consumables_used.total(),
                   tuple(j.name for j in run.jokers), run.joker_slots, run.money, c.name, "copy")
            memo = self.__dict__.setdefault("_keeps", {})
            if key not in memo:
                memo[key] = max(self.w.money * run.sell_value(c),
                                self.effect_worth(run, lambda t: t.apply_consumable(copy.deepcopy(c), [])))
            return memo[key]
        return self.keep_worth(run, c, measured=True)

    def _copies_gain(self, run, held: list, then: list) -> float:
        """What Perkeo's copies over the shops ahead (rounds_left: as legend_worth counts them) gain if the cards held at
        each shop's end are `then` instead of `held`: each copy is a draw among them, so their mean copy worth."""
        rate = lambda cards: sum(self._copy_worth(run, c) for c in cards) / len(cards) if cards else 0.0   # noqa: E731
        return rounds_left(run) * (rate(then) - rate(held))

    @staticmethod
    def _boss_ahead_debuffs(run, suit: str) -> bool:
        """Is this ante's boss still to be beaten, and does it debuff `suit` (The Head Hearts, The Club Clubs...)?"""
        boss = run.ante_boss
        beaten = run.blind is not None and run.blind.kind == 2 and not run.in_round   # the shop after it
        return boss is not None and not beaten and boss.debuffs(run, Card(14, suit))

    def _use_or_keep(self, run, c, uses) -> list[int] | None:
        """Use `c` now (returns the targets) or keep it for now (returns None): it is weighed again next round or
        shop, when another hand may give it a use. (It used to be kept for good, and 67 of 80 runs lost on 480
        seeds died holding cards they never looked at again.)"""
        if self.held_back(run, c):
            return None
        k = self.consumable_choice(run, c, uses)
        if k < len(uses):
            return uses[k][0]
        self._kept_now(run).append(c)
        return None

    def _use(self, run):
        for i, c in enumerate(run.consumables):
            if self.held_back(run, c):
                continue
            uses = self._uses(run, c, run.hand)
            if uses:
                targets = self._use_or_keep(run, c, uses)
                if targets and self.USE_GUARD and run.in_round and not self._keeps_best_play(run, c, targets):
                    continue                    # its worth is the deck's in the long run: not at this hand's cost
                if targets is not None:
                    return ("use", i, targets)
        return None

    def _keeps_best_play(self, run, c, targets) -> bool:
        """Using Tarot `c` on hand positions `targets` leaves the best play of the hand held as good (USE_GUARD), tried
        on a copy of the run."""
        trial = self._trial(run)                         # without the game seed's streams, its own streams reseeded,
        for name, stream in trial.rng.items():           # as effect_worth's copies (the review's n1)
            stream.seed(f"{run.seed}|{run.rounds_played}|{run.shops_seen}|{run.ante}|{name}|guard")
        trial.apply_consumable(copy.deepcopy(c), trial.cards_at(targets))
        best = lambda r: max((s for s, _, _ in ranked_plays(r, top=1)), default=0)   # noqa: E731
        before, after = best(run), best(trial)
        if not self.GUARD_AT_RISK:
            return after >= before
        needed, hands = run.blind.chips - run.round_score, max(1, run.hands_left)
        return not (after < needed <= before or after * hands < needed <= before * hands)

    def _planet(self, run):
        use = self._use(run)
        return use[1] if use else None

    # ---- skipping blinds ----------------------------------------------------------------------------
    def skip_blind(self, run, blind, tag) -> bool:
        """Skip this Small or Big Blind for its tag when the tag is worth more than playing the blind brings (its
        reward, a round of interest and a dollar for a hand left over, and the shop after it), and the build is safe
        without that shop: a round of its typical best hand (every hand) beats the next blind's target by
        `skip_safety` (before the boss, with what its effect takes: boss_margin)."""
        self._live = run
        if tag is None:
            return False
        hands = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
        if self.ODDS_CALIBRATED:                           # the risk paid for, not a margin to clear (the shop given up
            interest = min(run.interest_cap, max(0, run.money) // 5) if run.interest_enabled else 0   # is in `played`)
            played = self.w.money * (blind.reward + interest + 1) + self.skip_shop_worth(run) + self.round_income(run)
            odds, _ = self._skip_odds(run, blind, tag)
            now = sum(self.tag_copies_worth(run, tag)) - DEATH * (1 - odds)
            return self._double_lookahead(run, blind, tag, now, played)
        if blind.kind + 1 == 2 and run.ante_boss is not None and self.BOSS_AWARE:   # the boss next: its effect too;
            facing = None if tag.name == "Boss Tag" else run.ante_boss    # a Boss Tag replaces it with one at random
            if self.boss_margin(run, facing) < self.w.skip_safety:         # (it was tested against the boss it removes:
                return False                                               # 0 of 60 taken; the second review's m1)
        elif math.expm1(self.power(run, plain=True)) * hands < run.make_blind(blind.kind + 1).chips * self.w.skip_safety:
            return False
        elif (self.SKIP_BOSS_SMALL and blind.kind == 0 and run.ante_boss is not None and self.BOSS_AWARE
              and self.boss_margin(run, run.ante_boss) < self.w.skip_safety):
            return False                                   # the Small Blind's shop is one before the boss too
        interest = min(run.interest_cap, max(0, run.money) // 5) if run.interest_enabled else 0
        played = self.w.money * (blind.reward + interest + 1) + self.skip_shop_worth(run) + self.round_income(run)
        now = sum(self.tag_copies_worth(run, tag))
        return self._double_lookahead(run, blind, tag, now, played)

    SKIP_ROUND_INCOME = True  # (on 30 Oct, a correctness fix) a blind played is also worth what its round pays besides
                              # the reward, interest and $1 a hand left (round_income). The user's 6AWQ2FCT, "how does
                              # it calculate garbage tag?": $35 of unused discards against $10 and the shop, where the
                              # user's lone Lucky cards with Hanging Chad roll $20 at 1 in 15 three times a hand

    SKIP_SHOP_MEASURED = False  # the shop a skip gives up worth what this run's shops have offered (GLYPH_SHOP_SHARE of
                                # their recent best offer, as _glyph_worth counts a shop), not the flat skip_shop (0.25 in
                                # every run). The user's 6AWQ2FCT, "does it account for skipped shop as well?": $72 to
                                # spend after the Garbage Tag and X Mult wanted. Off until measured

    def skip_shop_worth(self, run) -> float:
        """What the shop after a blind is worth to playing it (skip_blind): the flat skip_shop; with SKIP_SHOP_MEASURED,
        GLYPH_SHOP_SHARE of the best card offers of the run's recent shops (net of price, as a reroll's hope reads
        them), once three sets of them have been seen."""
        if not self.SKIP_SHOP_MEASURED:
            return self.w.skip_shop
        memo = self.__dict__.get("_rerolls")
        seen = memo[2][-self.REROLL_MEMORY:] if memo is not None and memo[0] == id(run) else []
        return self.GLYPH_SHOP_SHARE * sum(seen) / len(seen) if len(seen) >= 3 else self.w.skip_shop

    def round_income(self, run) -> float:
        """SKIP_ROUND_INCOME: what a round pays besides its blind's reward, interest and the $1 a hand left, at money's
        weight: the jokers that pay as it ends or as hands are played (modifiers.round_dollars: the dollars, whatever
        strength the income rules have in a joker's worth), the Gold cards held as it ends ($3 each, about the share of
        the deck a hand holds) and, with LUCKY_MONEY, the Lucky cards' $20 rolls at this run's own rate of them a round
        (Hanging Chad's retriggers among them: not counted twice)."""
        if not self.SKIP_ROUND_INCOME:
            return 0.0
        rolls = self.LUCKY_MONEY and run.rounds_played > 0
        v = self.w.money * sum(round_dollars(self, run, j) for j in run.active_jokers()
                               if not (rolls and j.name == "Hanging Chad"))
        golds = sum(held_triggers(run, c) for c in run.deck if c.enhancement == "Gold" and not c.debuffed)
        v += self.w.money * 3 * golds * run.hand_size / max(1, len(run.deck))
        if rolls:
            v += self.w.money * run.pay_seen["lucky"] / run.rounds_played * lucky_each(run)
        return v

    DOUBLE_LOOKAHEAD = True   # (on 30 Oct, a clear fix: a switch only to measure it apart)

    def _double_lookahead(self, run, blind, tag, now: float, played: float) -> bool:
        """Skip (`now`: what the skip is worth, risk paid) or play (`played`). With Double Tags held at a Small Blind,
        they copy the next tag taken: the skip is weighed as the whole line (this tag with the copies, then the Big
        Blind played or skipped for one of its own) against playing (then the Big Blind played or skipped with the
        copies on its tag), each skip at its risk. Spent on a Foil Tag with the slots full, two Double Tags missed
        three Negative ones a blind later (CCU44VLE, the user, 30 Oct)."""
        copies = self.tag_copies(run, tag)
        nxt = run.ante_tags[1] if blind.kind == 0 and len(run.ante_tags) > 1 and self.DOUBLE_LOOKAHEAD else None
        if copies <= 1 or nxt is None:
            return now > played
        big = run.make_blind(1)
        interest = min(run.interest_cap, max(0, run.money) // 5) if run.interest_enabled else 0
        play_big = self.w.money * (big.reward + interest + 1) + self.skip_shop_worth(run) + self.round_income(run)
        one, every = self.tag_copies_worth(run, nxt, 1)[0], sum(self.tag_copies_worth(run, nxt))
        if self.ODDS_CALIBRATED:
            risk = DEATH * (1 - self._skip_odds(run, big, nxt)[0])
        elif run.ante_boss is not None and self.BOSS_AWARE:
            facing = None if nxt.name == "Boss Tag" else run.ante_boss
            risk = 0.0 if self.boss_margin(run, facing) >= self.w.skip_safety else float("inf")
        else:
            risk = 0.0
        skip_line = now + max(play_big, one - risk)              # (the Double Tags spent: one of it)
        play_line = played + max(play_big, every - risk)
        return skip_line > play_line

    def _skip_odds(self, run, blind, tag) -> tuple[float, str]:
        """ODDS_CALIBRATED: the chance the build beats the blind after this one without the shop a skip gives up (the
        boss, with its effect, or the Big Blind), and what it is against."""
        if blind.kind + 1 == 2 and run.ante_boss is not None and self.BOSS_AWARE:
            facing = None if tag.name == "Boss Tag" else run.ante_boss
            return self.boss_odds(run, facing), f"{'a boss at random' if facing is None else facing.name}"
        if self.ROLLOUT_ODDS:
            return self.outlook_odds(run, blind.kind + 1), "the next blind, played out"
        hands = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
        m = math.expm1(self.power(run, plain=True)) * hands / max(1, run.make_blind(blind.kind + 1).chips)
        return self.margin_odds(m, boss=False, run=run), "the next blind"

    def skip_parts(self, run, blind, tag) -> dict:
        """skip_blind's numbers, for the Play tab's breakdown: what playing the blind brings and its parts, what the skip
        brings (the tag, times the copies Double Tags make), and the safety test (the build's margin over the next blind
        or boss, against skip_safety) with whether it passes."""
        interest = min(run.interest_cap, max(0, run.money) // 5) if run.interest_enabled else 0
        m = self.w.money
        play = [(f"the blind's reward (${blind.reward})", m * blind.reward), (f"a round of interest (${interest})", m * interest),
                ("$1 for a hand left over", m), ("the shop after it", self.skip_shop_worth(run))]
        if self.SKIP_ROUND_INCOME:
            play.append(("what else the round pays (jokers, Gold cards held, Lucky cards' rolls at this run's rate)",
                         self.round_income(run)))
        out = {"play": sum(v for _, v in play), "play_parts": play}
        if tag is None:
            return out
        each = self.tag_copies_worth(run, tag)
        skip = [(f"the {tag.name}", each[0])] + ([(f"{len(each) - 1} more of it (Double Tags held)", sum(each[1:]))]
                                                if len(each) > 1 else [])
        if self.ODDS_CALIBRATED:
            odds, what = self._skip_odds(run, blind, tag)
            skip.append((f"the risk: {what} beaten {100 * odds:.0f}% of the time without the shop, a lost run at {DEATH:g}",
                         -DEATH * (1 - odds)))
            out.update(skip=sum(v for _, v in skip), skip_parts=skip, safe=True,
                       safety="the shop given up is counted in playing's worth; the risk above in skipping's")
            return out
        hands = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
        if blind.kind + 1 == 2 and run.ante_boss is not None and self.BOSS_AWARE:
            facing = None if tag.name == "Boss Tag" else run.ante_boss
            margin, what = self.boss_margin(run, facing), f"over {'a boss at random' if facing is None else facing.name}"
        else:
            margin = math.expm1(self.power(run, plain=True)) * hands / max(1, run.make_blind(blind.kind + 1).chips)
            what = "over the next blind"
        safe = margin >= self.w.skip_safety
        if (safe and self.SKIP_BOSS_SMALL and blind.kind == 0 and run.ante_boss is not None and self.BOSS_AWARE
                and self.boss_margin(run, run.ante_boss) < self.w.skip_safety):
            safe, what = False, f"over {run.ante_boss.name} (the Small Blind's shop is one before it)"
        out.update(skip=sum(each), skip_parts=skip, safe=safe,
                   safety=f"safe without the shop? the build's margin {what}: {margin:.2f}, {self.w.skip_safety:.2f} needed: "
                          + ("yes" if safe else "no, so it plays"))
        return out

    SKIP_BOSS_SMALL = True    # (on 30 Oct: a correctness fix, level) a Small Blind skipped only if the build also clears this ante's boss by skip_safety (it
                              # tested only the Big Blind's target: 3 of 109 skips were followed by losing that ante's
                              # boss, all Small Blind skips at antes 6-7; the second review's m3). Off until measured
    DOUBLE_TAGS = True   # a skip's tag counted once more for each Double Tag held (each becomes a copy of it). It used
                         # to count once: on the Anaglyph Deck (one each boss) half were never used, 3 a game (27 Oct)
    NO_STACK = {"Boss Tag", "D6 Tag", "Double Tag"}    # tags a second copy adds nothing to

    def tag_copies(self, run, tag) -> int:
        """How many of `tag` a skip brings: one, and one for each Double Tag held."""
        if not self.DOUBLE_TAGS or tag.name in self.NO_STACK:
            return 1
        return 1 + sum(t.name == "Double Tag" for t in run.tags)

    def boss_margin(self, run, boss) -> float:
        """How far a round of the build's typical hand (the plain estimate, every hand) gets past this ante's boss
        `boss` (None: one drawn at random, 2x the base and AVERAGE_STRAIN): its target from its chip multiple, the
        score its effect leaves (BOSS_STRAIN, and the share of the deck it debuffs), The Needle's one hand."""
        hands = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
        base = run.ante_table[min(max(run.ante, 0), max(run.ante_table))] * run.blind_scale
        typical = math.expm1(self.power(run, plain=True))
        if boss is None:
            return typical * hands * AVERAGE_STRAIN / max(1.0, 2 * base)
        strain = BOSS_STRAIN.get(boss.name, 1.0)
        if run.deck:
            strain *= max(0.3, 1 - sum(boss.debuffs(run, c) for c in run.deck) / len(run.deck))
        if boss.name == "The Needle":
            hands = 1
        return typical * hands * strain / max(1.0, base * boss.chip_mult)

    def boss_odds(self, run, boss) -> float:
        """The chance the build beats `boss` (None: one drawn at random), from its margin m: m^4 / (1 + m^4), even
        at 1, 94% at 2, 6% at 1/2. ROLLOUT_ODDS: this ante's own boss played out (outlook_odds), out of a round."""
        if self.ROLLOUT_ODDS and boss is not None and boss is run.ante_boss and not run.in_round:
            return self.outlook_odds(run, 2)
        return self.margin_odds(self.boss_margin(run, boss), run=run)

    ODDS_CALIBRATED = False   # margins read as odds by the fit of what the bot's play beats (ODDS_FIT), not m^4/(1+m^4);
                              # and a skip pays for the chance of losing the next blind without the shop (skip_blind),
                              # not a margin of skip_safety. Off until measured

    ODDS_BY_ANTE = False      # with ODDS_CALIBRATED, the curve's centre by ante (ODDS_CENTRE). Off until measured

    def margin_odds(self, m: float, boss: bool = True, run=None) -> float:
        """The chance a blind is beaten at margin m: ODDS_FIT (a boss's, or a Small or Big Blind's) with
        ODDS_CALIBRATED, its centre by `run`'s ante with ODDS_BY_ANTE; else m^4 / (1 + m^4)."""
        m = max(0.0, m)
        if not self.ODDS_CALIBRATED:
            return m ** 4 / (1 + m ** 4)
        kind = "boss" if boss else "blind"
        k, c = ODDS_FIT[kind]
        if self.ODDS_BY_ANTE and run is not None:
            c = ODDS_CENTRE[kind][0 if run.ante <= 3 else 1 if run.ante <= 5 else 2]
        return m ** k / (m ** k + c ** k)

    ROLLOUT_ODDS = False      # a blind's odds by playing it out on copies of the run (blind_outlook), not the margin
                              # curve: the curve, pooled over builds that outscore their typical hand by far, read
                              # CCU44VLE's ante-7 Big Blind at 88%; the rollouts 0 of 100, the advisor's play 0 of 201
                              # (30 Oct; the sample hands' spread didn't help, logs/fit_spread.log). Off until measured
    ROLLOUTS = 24

    def blind_outlook(self, run, kind: int) -> tuple[float, float]:
        """How a round of this ante's blind `kind` goes for the build as it stands: ROLLOUTS copies of the run (no seed
        streams: the deck shuffled and every chance drawn from a stream of their own, as a player can't know them),
        each round played by RolloutPolicy to its last hand; the mean and spread of the log of the score over the
        target. Not in a round (the hand dealt is known there)."""
        key = (id(run), run.rounds_played, run.shops_seen, run.ante, kind, tuple(map(id, run.jokers)),
               tuple(_joker_state(j) for j in run.jokers), tuple(run.hand_levels.values()),
               tuple((c.uid, _looks(c)) for c in run.deck), run.hand_size, run.base_hands, run.base_discards,
               tuple(t.name for t in run.tags), run.ante_boss.name if run.ante_boss else None, run.money,
               tuple(map(id, run.consumables)))
        memo = self.__dict__.setdefault("_outlooks", {})
        if key in memo:
            return memo[key]
        if len(memo) > 64:
            memo.clear()
        base = self._trial(run)
        target = max(1, base.make_blind(kind).chips)
        logs = []
        for i in range(self.ROLLOUTS):
            t = copy.deepcopy(base, {id(self): self})
            t.agent = RolloutPolicy(target)
            t.rng = {name: random.Random(f"outlook:{run.seed}:{run.rounds_played}:{run.shops_seen}:{kind}:{i}:{name}")
                     for name in t.rng}
            t.blind = t.make_blind(kind)
            t.blind.chips = OPEN_TARGET
            t.play_round()
            logs.append(math.log(max(1.0, t.round_score) / target))
        mean = sum(logs) / len(logs)
        spread = max(0.05, math.sqrt(sum((x - mean) ** 2 for x in logs) / max(1, len(logs) - 1)))
        memo[key] = (mean, spread)
        return memo[key]

    def outlook_odds(self, run, kind: int, gain: float = 0.0) -> float:
        """ROLLOUT_ODDS: the chance the bot beats this ante's blind `kind`: blind_outlook's rollouts as a z-score (moved
        and scaled by ROLLOUT_FIT for the bot's own play) blended with the margin (ROLLOUT_BLEND); `gain`: a change to
        the build's power (a log of its score), moving every rollout and the margin by it."""
        mean, spread = self.blind_outlook(run, kind)
        c, s = ROLLOUT_FIT
        a, b, d, e = ROLLOUT_BLEND
        z = max(-8.0, min(8.0, (mean + c + gain) / (s * spread)))
        x = a + b * z + d * (math.log(max(1e-3, self._next_margin(run, kind))) + gain) + e * (kind == 2)
        return 1 / (1 + math.exp(-max(-50.0, min(50.0, x))))

    def _next_margin(self, run, kind: int) -> float:
        """The margin the odds have read (boss_margin for this ante's boss, else a round of the typical hand over the
        target), for outlook_odds' blend."""
        if kind == 2 and run.ante_boss is not None:
            return self.boss_margin(run, run.ante_boss)
        hands = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
        return math.expm1(self.power(run, plain=True)) * hands / max(1, run.make_blind(kind).chips)

    SURVIVAL = False          # a shop's leading options also worth what they add to the odds of beating the next blind
                              # (DEATH per whole chance, times SURVIVAL_WEIGHT; the odds played out, outlook_odds): a
                              # purchase counted only the power it adds, the same lifting a must-win round from 86% to
                              # 95% as in a safe one, and a sale that weakens it cost nothing more (the user's priority,
                              # 30 Oct: survival before tweaks). Off until measured
    SURVIVAL_WEIGHT = 1.0
    SURVIVAL_TOP = 4          # the options it is weighed for: the best few by the rest of their worth, and leaving
    SURVIVAL_SURE = 0.995     # odds above this: a purchase has nothing to add (a sale is still weighed)

    def next_blind_kind(self, run) -> int | None:
        """The blind after this shop: this ante's next, or the next ante's Small Blind after a boss (the ante has moved
        on by then); None once the run's last ante is over."""
        if run.blind is None:
            return 0
        kind = (run.blind.kind + 1) % 3
        return None if kind == 0 and run.ante > run.max_ante else kind

    @staticmethod
    def _capacity(run) -> tuple:
        jokers = run.active_jokers()
        return (run.base_hands + sum(j.hands_bonus for j in jokers), run.base_discards + sum(j.discards_bonus for j in jokers),
                run.hand_size)

    def _honest_copy(self, run, salt: str):
        """A copy of the run to try something on: its random streams its own (`salt` names what is tried), no seed
        streams, no frames or log."""
        frames, log = run.frames, run.log
        run.frames = run.log = None
        try:
            trial = copy.deepcopy(run, {id(self): self})
        finally:
            run.frames, run.log = frames, log
        for name, stream in trial.rng.items():
            stream.seed(f"{run.seed}|{run.rounds_played}|{run.shops_seen}|{run.ante}|{name}|{salt}")
        trial.seedrng = None
        return trial

    def _apply_shop_act(self, trial, act) -> None:
        """A shop action taken on a copy of the run (what the run's shop does with it)."""
        name = act[0]
        if name == "buy":
            ok = trial.current_shop.buy(act[1], act[2])
        elif name == "buy_use":
            ok = trial.current_shop.buy("card", act[1], use=True, targets=act[2] if len(act) > 2 else [])
        elif name == "sell_joker":
            ok = trial.sell_joker(act[1])
        elif name == "sell_consumable":
            ok = trial.sell_consumable(act[1])
        else:
            raise ValueError(name)
        if ok is False:
            raise ValueError(act)

    def survival_gain(self, run, act, then=None, kind: int | None = None) -> float:
        """SURVIVAL: what taking `act` (and `then`, the buy a sale makes room for) adds to the odds of beating the next
        blind, at DEATH per whole chance, times SURVIVAL_WEIGHT. Tried on a copy of the run whose random streams are its
        own (as effect_worth's): the change in the build's power (its plain score) moves the rollouts; where the action
        changes the round's hands, discards or hand size, the blind is played out on the copy. Nothing for leaving, a
        reroll or a pack (what they bring isn't known yet)."""
        if act[0] in ("leave", "reroll") or "pack" in (act[1:2] + (then or ())[1:2]):
            return 0.0
        kind = self.next_blind_kind(run) if kind is None else kind
        if kind is None or run.current_shop is None:
            return 0.0
        now = self.outlook_odds(run, kind)
        trial = self._honest_copy(run, f"survival {act} {then}")
        try:
            for a in (act, then):
                if a is not None:
                    self._apply_shop_act(trial, a)
        except Exception:
            return 0.0
        if self._capacity(trial) != self._capacity(run):
            after = self.outlook_odds(trial, kind)
        else:
            after = self.outlook_odds(run, kind, self.power(trial, plain=True, fresh=True) - self.power(run, plain=True))
        return self.SURVIVAL_WEIGHT * DEATH * (after - now)

    def _survival_pick(self, run) -> tuple:
        """SURVIVAL and SCALING: the shop's choice once its leading options (SURVIVAL_TOP of them by the rest of their
        worth, and leaving) count what they add to the odds of the next blind (survival_gain) and of ante 8's boss
        (scaling_gain; the Play tab's breakdown shows both)."""
        kind = self.next_blind_kind(run)
        known = [(v, k) for k, v in self.worths.items() if k in self._acts]
        if kind is not None and known:
            sure = self.SURVIVAL and self.outlook_odds(run, kind) > self.SURVIVAL_SURE
            top = [k for _, k in sorted(known, key=lambda t: -t[0])[:self.SURVIVAL_TOP]]
            for key in top:
                act, then = self._acts[key]
                gains = {}
                if self.SURVIVAL and not (sure and not act[0].startswith("sell")):
                    gains["survival"] = self.survival_gain(run, act, then, kind)
                if self.SCALING:
                    gains["ante 8"] = self.scaling_gain(run, act, then)
                for part, gain in gains.items():
                    if gain:
                        self.worth_parts.setdefault(key, {"gross": self.worths[key], "price": 0.0, "cost": 0})[part] = gain
                        self.worths[key] += gain
        best = max((k for k in self.worths if k in self._acts), key=lambda k: self.worths[k], default=("leave",))
        return self._acts[best][0] if self.worths.get(best, 0.0) > 0 or best == ("leave",) else ("leave",)

    SCALING = False           # a shop's leading options (as SURVIVAL's) also worth what they add to the odds of beating
                              # ante 8's boss (DEATH per whole chance, times SCALING_WEIGHT; scaling_odds, fitted on the
                              # bot's own games): survival looks one blind ahead, and 60% of the losses are at antes 7-8
                              # (the user's priority, 30 Oct: scaling toward ante 8). Off until measured
    SCALING_WEIGHT = 1.0
    GOAL_ANTE = 8

    def rounds_to_goal(self, run) -> float:
        """From a shop (or before a run's first blind), the rounds before ante 8's boss and half of it (what grows in a
        round grows through it); 0 once it is beaten."""
        kind = self.next_blind_kind(run)
        if kind is None or run.ante > self.GOAL_ANTE:
            return 0.0
        return 3 * (self.GOAL_ANTE - run.ante) + 2 - kind + 0.5

    def goal_margin(self, run, trial=None) -> float:
        """The log of how far a round of the build's typical hand (the plain estimate, every hand) gets past ante 8's
        boss (its base at 2x and AVERAGE_STRAIN, as boss_margin reads a boss at random), the build projected to stand
        there: growing jokers grown and wearing ones worn over the rounds to it (_grown_value, at this run's rates;
        Seltzer gone once its hands run out), and the hand levels the run has gained a round so far gained again, on
        the same hands (none yet: none projected). On `trial` (a copy, changed by it) if given, else on a copy of run."""
        ahead = self.rounds_to_goal(run)
        if trial is None:
            trial = self._honest_copy(run, "goal") if ahead > 0 else run
        if ahead > 0:
            plays = self._sample_plays(run)
            rounds = max(1, run.rounds_played)
            hands = run.hands_played / rounds if run.rounds_played else 3.0
            for j in list(trial.jokers):
                if j.name == "Seltzer":
                    if j.hands <= hands * ahead:
                        trial.jokers.remove(j)
                elif j.name in GROWTH and GROWTH[j.name][0] != "hand_size_bonus":
                    attr, step = GROWTH[j.name]
                    grown = self._grown_value(run, j, attr, getattr(j, attr), step, plays, hands, rounds, ahead,
                                              self.GROWN_FROM_NOW)
                    if grown is not None:
                        setattr(j, attr, grown)
            gained = {h: lv - 1 for h, lv in run.hand_levels.items() if lv > 1}
            total = sum(gained.values())
            for h, g in gained.items():
                trial.hand_levels[h] += int(round(total / rounds * ahead * g / total))
        base = run.ante_table[min(self.GOAL_ANTE, max(run.ante_table))] * run.blind_scale
        typical = math.expm1(self.power(trial, plain=True, fresh=trial is not run))
        return math.log(max(1e-3, typical * self._capacity(trial)[0] * AVERAGE_STRAIN / (2 * base)))

    def scaling_state(self, run, trial=None) -> tuple[float, float, int]:
        """What scaling_odds reads, out of a round: the projected margin over ante 8's boss (goal_margin), the log of
        1 + the money, and the joker slots free (a Negative takes none). Of `trial` (a copy of run, changed by it) if
        given."""
        t = run if trial is None else trial
        money, free = math.log1p(max(0, t.money)), t.joker_slots - sum(j.edition != "Negative" for j in t.jokers)
        return self.goal_margin(run, trial), money, free

    def scaling_odds(self, run, trial=None) -> float:
        """SCALING: the chance the run beats ante 8's boss, from scaling_state by SCALING_FIT (a constant for each ante:
        how much the bot's builds still grow from there; slopes for antes 1-3, 4-5 and 6-8); 1 once it is beaten."""
        if self.rounds_to_goal(run) <= 0:
            return 1.0
        state = self.scaling_state(run, trial)
        consts, slopes = SCALING_FIT
        group = slopes[0 if run.ante <= 3 else 1 if run.ante <= 5 else 2]
        x = consts[max(1, run.ante) - 1] + sum(b * v for b, v in zip(group, state))
        return 1 / (1 + math.exp(-max(-50.0, min(50.0, x))))

    def scaling_gain(self, run, act, then=None) -> float:
        """SCALING: what taking `act` (and `then`, the buy a sale makes room for) adds to the odds of beating ante 8's
        boss (scaling_odds), at DEATH per whole chance, times SCALING_WEIGHT; tried on a copy of the run whose random
        streams are its own. Nothing for leaving, a reroll or a pack (what they bring isn't known yet)."""
        if act[0] in ("leave", "reroll") or "pack" in (act[1:2] + (then or ())[1:2]):
            return 0.0
        if run.current_shop is None or self.rounds_to_goal(run) <= 0:
            return 0.0
        key = (id(run), run.rounds_played, run.shops_seen, tuple(map(id, run.jokers)),
               tuple(_joker_state(j) for j in run.jokers), tuple(run.hand_levels.values()), run.money,
               tuple(map(id, run.consumables)), len(run.deck))
        memo = self.__dict__.setdefault("_scaling_now", {})
        if key not in memo:
            if len(memo) > 16:
                memo.clear()
            memo[key] = (self.scaling_odds(run), run)            # (the run held, so its id stays unique)
        trial = self._honest_copy(run, f"scaling {act} {then}")
        try:
            for a in (act, then):
                if a is not None:
                    self._apply_shop_act(trial, a)
        except Exception:
            return 0.0
        return self.SCALING_WEIGHT * DEATH * (self.scaling_odds(run, trial) - memo[key][0])

    def boss_reroll_worth(self, run) -> float:
        """Director's Cut: a reroll of each ante's boss from now on, taken when the boss is worse than average: for
        each ante left (to ante 8), what it adds on average over the bosses that ante can bring (the odds of one drawn
        again, less this one's, when that is more), at DEATH per whole chance; ante 8 by its showdown bosses (Violet
        Vessel at 6x). Measured against the build as it stands."""
        def gain(showdown: bool) -> float:
            names = [b["name"] for b in entries("boss")
                     if b["showdown"] == showdown and (showdown or b["min_ante"] <= max(1, run.ante))]
            odds = [self.boss_odds(run, BOSSES[n]()) for n in names]
            mean = sum(odds) / len(odds)
            return sum(max(0.0, mean - o) for o in odds) / len(odds)
        regular = max(0, round(self._antes_ahead(run, 9 - run.ante)) - 1)
        return DEATH * (regular * gain(False) + (gain(True) if run.ante <= 8 else 0.0))

    def reroll_boss(self, run, boss) -> bool:
        """Director's Cut or Retcon: draw the boss again when the odds it changes are worth more than the $10."""
        return self.BOSS_AWARE and DEATH * (self.boss_odds(run, None) - self.boss_odds(run, boss)) > self.price(run, 10)

    EDITION_TAGS_MEASURED = True    # Foil, Holographic and Polychrome Tags worth what their edition adds to the build
                                    # (edition_worth), not a flat 0.15-0.4: +50 chips doubles an ante-1 hand (the user's
                                    # CCU44VLE: "foil joker will bring us over the edge"). On 30 Oct: +0.8 ± 0.9 and
                                    # +0.8 ± 1.1 points, progress +0.15 ± 0.06 and +0.13 ± 0.08 (e-edtags, e777-edtags)

    def common_joker_worth(self, run) -> float:
        """What a Common joker adds to the build, as a mean over RIFF_SAMPLE of them, each Negative (in a slot of its
        own) and worth at least its resale: the Negative Tag's joker (the shop's next base edition joker, made free and
        Negative), against the Foil, Holographic and Polychrome Tags measured by their edition."""
        key = (id(run), run.shops_seen, run.rounds_played, tuple(map(id, run.jokers)), run.money)
        if self.__dict__.get("_common", (None,))[0] != key:
            commons = sorted(n for n, c in CATALOG.items() if c.rarity == "Common")
            pick = commons[::max(1, len(commons) // self.RIFF_SAMPLE)][:self.RIFF_SAMPLE]
            base = self.power(run)
            each = [max(self.joker_worth(run, CATALOG[n]("Negative"), base), run.sell_value(CATALOG[n]()) * self.w.money)
                    for n in pick]
            self._common = (key, sum(each) / max(1, len(each)))
        return self._common[1]

    def edition_worth(self, run, edition: str) -> float:
        """What `edition` on a joker adds to the build: its power with a plain Joker in that edition against a plain
        one (the joker itself the same on both sides, so only the edition counts)."""
        saved = run.jokers
        try:
            with_ed, plain = saved + [CATALOG["Joker"](edition)], saved + [CATALOG["Joker"]()]
            run.jokers = [with_ed[i] for i in self.best_order(run, with_ed)]
            a = self.power(run)
            run.jokers = [plain[i] for i in self.best_order(run, plain)]
            return a - self.power(run)
        finally:
            run.jokers = saved

    def tag_copies_worth(self, run, tag, copies: int | None = None) -> list[float]:
        """What each of the `copies` (tag_copies: one, and one for each Double Tag held) of a tag brings. A joker tag
        with no slot free brings a joker that replaces one: the first over the weakest joker, the next over the one after
        (three Rare Tags with the slots full had counted thrice over the weakest; CCU44VLE, the user, 30 Oct)."""
        copies = self.tag_copies(run, tag) if copies is None else copies
        if tag.name not in SLOT_TAGS or run.joker_room():
            return [self.tag_worth(run, tag)] * copies
        gross = self.tag_worth(run, tag, full=True)
        base = self.power(run)
        weakest = sorted(max(0.0, self.owned_worth(run, k, base)) for k, j in enumerate(run.jokers)
                         if not j.eternal and j.edition != "Negative")
        return [max(0.0, gross - weakest[k]) if k < len(weakest) else 0.0 for k in range(copies)]

    def tag_worth(self, run, tag, full: bool = False) -> float:
        """A tag's worth: the money it brings, the pack it opens at once (free), the levels it adds, and its weight.
        A joker tag with no slot free: over the weakest joker it would replace (`full`: as if there were room)."""
        name, w = tag.name, self.w
        v = w.money * TAG_MONEY.get(name, lambda r: 0)(run) + w.tags.get(name, 0.0)
        if self.EDITION_TAGS_MEASURED and name in EDITION_OF_TAG:   # the edition's own worth to this build, not a flat one
            v += self.edition_worth(run, EDITION_OF_TAG[name]) - w.tags.get(name, 0.0)
        if self.EDITION_TAGS_MEASURED and name == "Negative Tag":   # a joker in a slot of its own: what a typical one
            v += self.common_joker_worth(run) - w.tags.get(name, 0.0)   # adds (measured beside the measured Foil Tag)
        pack = PACKS.get(TAG_PACK.get(name, ""))
        if pack is not None and (pack.kind != "Buffoon" or run.joker_room()):
            v += self.pack_weight(run, pack) + w.money * pack.cost
        if name == "Top-up Tag":
            v *= min(2, run.joker_slots - sum(j.edition != "Negative" for j in run.jokers))
        if name in SLOT_TAGS and not full and not run.joker_room():   # the joker it brings can only replace one: worth what it
            base = self.power(run)                       # adds over the weakest
            weakest = min((self.owned_worth(run, k, base) for k, j in enumerate(run.jokers)
                           if not j.eternal and j.edition != "Negative"), default=None)
            v = 0.0 if weakest is None else max(0.0, v - max(0.0, weakest))
        if name == "Boss Tag" and run.ante_boss is not None and self.BOSS_AWARE:   # the boss drawn again: its odds
            v += DEATH * max(0.0, self.boss_odds(run, None) - self.boss_odds(run, run.ante_boss))
        if name == "Orbital Tag":                      # +3 levels to one visible poker hand: the one the tag shows (the
            with self._ranked_at(run.hand_levels):     # game names it as it is offered; the review's m7), else on average
                base = self.power(run)
                visible = [h for h, n in run.hand_levels.items() if n >= 1 and (h not in SECRET_HANDS or run.hand_plays[h])]
                if getattr(tag, "hand", None) in visible:
                    visible = [tag.hand]
                gains = []
                for h in visible:
                    run.hand_levels[h] += 3
                    try:
                        gains.append(self.power(run) - base)
                    finally:
                        run.hand_levels[h] -= 3
            v += sum(gains) / max(1, len(gains))
        return v

    # ---- shop and packs ---------------------------------------------------------------------------
    def shop_action(self, run, shop):
        self._live = run
        money, interest = self.money_scale(run)
        if money == interest == 1.0:
            return self._shop_action(run, shop)
        own = self.__dict__.get("w")                     # the weights scaled for this decision (money_scale)
        self.w = replace(self.w, money=self.w.money * money, interest=self.w.interest * interest)
        try:
            return self._shop_action(run, shop)
        finally:
            if own is None:
                del self.w
            else:
                self.w = own

    def _shop_action(self, run, shop):
        reorder = self._reorder(run)
        if reorder:
            return reorder
        use = self._use(run)
        if use:
            return use
        w, spend = self.w, run.money - run.debt_limit
        base = self.scoring_power(run)
        adj = self.adjust(run, base)
        best, action = 0.0, ("leave",)
        card_best = 0.0                                  # the best a card offer is worth (for what a reroll may bring)

        self.worths = {("leave",): 0.0}
        self.worth_parts = {}
        self._acts = {("leave",): (("leave",), None)}   # each key's action and the buy it opens room for (SURVIVAL)

        def consider(worth, cost, act, card=False, then=None):
            nonlocal best, action, card_best
            gross, paid = worth, self.price(run, cost)
            worth -= paid
            key = action_key(act)                        # (one sell may open room for several offers: its best)
            if worth >= self.worths.get(key, worth):     # (its parts, for the Play tab's breakdown)
                self.worth_parts[key] = {"gross": gross, "price": paid, "cost": cost}
                self._acts[key] = (act, then)
            self.worths[key] = max(worth, self.worths.get(key, worth))
            if card:
                card_best = max(card_best, worth)
            if worth > best:
                best, action = worth, act

        fire = sell_bonus(self, run) if self.FEED else 0.0   # Campfire: X0.25 for each card sold
        for k, c in enumerate(run.consumables if fire > 0 else []):
            if not self.is_kept(c):                      # one not held for the planner's line: sold for the fire
                consider(fire - self.keep_worth(run, c), -run.sell_value(c), ("sell_consumable", k))
        if self.STALE_ROUNDS:                            # held an ante without a use: sold, its slot freed
            since = self.__dict__.setdefault("_held_since", {})
            held = {id(c) for c in run.consumables}
            for key in [k for k in since if k not in held]:
                del since[key]
            pick = self._perkeo_pick(run) if any(j.name == "Perkeo" for j in run.jokers) else None
            for k, c in enumerate(run.consumables):
                first = since.setdefault(id(c), run.rounds_played)
                if run.rounds_played - first >= self.STALE_ROUNDS and not self.is_kept(c) and c is not pick:
                    consider(0.0, -run.sell_value(c), ("sell_consumable", k))
        perkeo = self._perkeo_on(run)
        held = list(run.consumables)
        for k, c in enumerate(held if perkeo else []):   # each held card is as likely to be copied: one worth less
            if not self.is_kept(c):                        # than the rest is sold when the copies gain more than it is
                gain = self._copies_gain(run, held, held[:k] + held[k + 1:])
                consider(gain - self.keep_worth(run, c), -run.sell_value(c), ("sell_consumable", k))
        weakest, owned = None, []
        if run.jokers:
            lineup = (run.shops_seen, tuple(run.jokers), w.money)          # (money_scale changes money's weight)
            if self.__dict__.get("_owned", (None,))[0] != lineup:
                self._owned = (lineup, [(self.owned_worth(run, k, base) + adj(("joker", j.name)), k)
                                        for k, j in enumerate(run.jokers) if not j.eternal])
            owned = self._owned[1]
            for v, k in owned:                               # clearly worth more sold than kept (by the margin a
                fed = fire if run.jokers[k].name != "Campfire" else 0.0      # (a Campfire sold feeds none)
                sale = run.sell_value(run.jokers[k]) * w.money + fed
                if v + w.sell_margin < sale:                 # (the margin a swap needs: a joker that does nothing in a
                    # few hands may still do something). Weighed with the rest, not taken at once: kept worth counts the
                    # slot left empty, which Joker Stencil pays for, so Ice Cream measured -0.58 and was sold for
                    # Obelisk to fill its slot, where selling the Stencil (X1 with five held) for Obelisk left more
                    # (EURSXV11, the user, 30 Oct). Its parts for the Play tab's breakdown.
                    consider(sale - v, 0, ("sell_joker", k))
                    if self.worths[("sell_joker", k)] == sale - v:
                        self.worth_parts[("sell_joker", k)] = {"gross": sale - v, "price": 0.0, "cost": 0, "kept": v,
                                                               "sale": sale}
                    continue
                dup = self._duplicate_worth(run, k)          # Invisible Joker, ripe: sold, it copies another joker;
                if dup and dup + run.sell_value(run.jokers[k]) * w.money - (v - self.bonus(run.jokers[k], run)) > w.sell_margin:
                    return ("sell_joker", k)                 # kept, it's worth only what it adds to the build (its
                                                             # bonus stood for the copy, now counted)
            if not run.joker_room():
                sellable = [(v, k) for v, k in owned if run.jokers[k].edition != "Negative"]   # a Negative frees no slot
                weakest = min(sellable) if sellable else None
        for i, o in enumerate(shop.cards):
            cost = cost_of(run, o)
            item = o.item
            if isinstance(item, Joker):
                # a free one is worth at least what it sells back for (free money); one paid for isn't: spending above
                # the reserve is priced at a tenth, the resale at the whole weight, and a joker worth -0.255 was bought
                # for $8 to be sold at once for $4 (14TWBQSA, the replay review's m3)
                v = self.joker_worth(run, item, base) + adj(("joker", item.name))
                if cost == 0:
                    v = max(v, run.sell_value(item) * w.money + fire)
                if run.joker_room(item):
                    if cost <= spend:
                        consider(v, cost, ("buy", "card", i), card=True)
                    elif self.SWAP_EXACT:                   # a few dollars short: the sale that leaves the best build
                        funds = self._funds_exact(run, owned, cost - spend, item, v, adj)
                        if funds and funds[0] > w.sell_margin:
                            consider(funds[0], cost - funds[1], funds[2], card=True, then=("buy", "card", i))
                    else:                                   # a few dollars short: sell what the build misses least
                        funds = self._funds(run, owned, cost - spend)
                        if funds and v - funds[0] > w.sell_margin:
                            consider(v - funds[0], cost - funds[1], funds[2], card=True, then=("buy", "card", i))
                elif weakest and self.SWAP_EXACT:
                    swap = self._best_swap(run, item, adj, [k for _, k in sellable])
                    if swap and swap[0] > w.sell_margin:
                        back = run.sell_value(run.jokers[swap[1]])
                        if cost <= spend + back:
                            consider(swap[0], cost - back, ("sell_joker", swap[1]), card=True, then=("buy", "card", i))
                elif weakest and v - weakest[0] > w.sell_margin:
                    back = run.sell_value(run.jokers[weakest[1]])
                    if cost <= spend + back:
                        consider(v - weakest[0], cost - back, ("sell_joker", weakest[1]), card=True,
                                 then=("buy", "card", i))
            elif cost > spend:
                continue
            elif isinstance(item, Consumable):
                if item.can_use(run, []):
                    v = self.planet_worth(run, item)
                    if v is None:
                        v = self.effect_worth(run, lambda trial, it=item: trial.apply_consumable(copy.deepcopy(it), []))
                    consider(v + adj((item.kind.lower(), item.name)) + planet_bonus(self, run, item), cost, ("buy_use", i, []),
                             card=True)
                    if perkeo and item.kind == "Planet" and run.consumable_room(item):    # held, for Perkeo to copy
                        consider(self._copies_gain(run, held, held + [item]) + adj(("keep", item.kind)), cost,
                                 ("buy", "card", i), card=True)
                elif run.consumable_room(item) and item.max_targets > 0:
                    # kept to use on a later hand; one that needs no cards but can't be used now waits on something
                    # a hand won't bring (Judgement and Wraith a free joker slot): not bought to keep
                    copies = self._copies_gain(run, held, held + [item]) if perkeo else 0.0
                    consider(self.keep_worth(run, item) + copies + adj(("keep", item.kind)) + self._plan_keep(run, item),
                             cost, ("buy", "card", i), card=True)
                elif item.max_targets > 0 and self.CONSUMABLE_SWAP and not perkeo and run.consumables:
                    # the slots full: the held card worth least sold for it, if it is clearly worth more (as jokers swap)
                    least, k = min((self.keep_worth(run, c), k) for k, c in enumerate(run.consumables))
                    if not self.is_kept(run.consumables[k]):
                        gain = self.keep_worth(run, item) + adj(("keep", item.kind)) + self._plan_keep(run, item) - least
                        if gain > w.sell_margin:
                            consider(gain, cost - run.sell_value(run.consumables[k]), ("sell_consumable", k), card=True)
                if fire > 0 and run.consumable_room(item):    # bought to be sold again, for Campfire
                    consider(fire + run.sell_value(item) * w.money, cost, ("buy", "card", i), card=True)
            elif isinstance(item, Card):
                consider(w.card + card_bonus(self, run) + self.card_add_worth(run, item) + self._plan_card(run, item), cost,
                         ("buy", "card", i), card=True)
        hope = max(self._reroll_hope(run, shop, card_best), self._behind_hope(run))
        skip = skip_bonus(self, run) if shop.packs else 0.0     # Red Card: a pack is worth at least skipping it
        for i, o in enumerate(shop.packs):
            cost, p = cost_of(run, o), o.item
            if cost <= spend and (p.kind != "Buffoon" or run.joker_room() or skip > 0 or (weakest and self.PACK_SWAPS)):
                v = self.pack_weight(run, p) + adj(("pack", p.name))
                if p.kind == "Celestial" and self.CELESTIAL_MEASURED:
                    v = self.celestial_worth(run, p) + adj(("pack", p.name))
                if p.kind == "Buffoon" and not run.joker_room() and weakest:   # its joker in for the weakest
                    v = max(0.0, v - max(0.0, weakest[0]))
                if p.kind == "Standard" and self.FEED:                       # Hologram: the cards it adds
                    v += card_bonus(self, run, p.chosen)
                consider(max(v, skip) if skip else v, cost, ("buy", "pack", i))
        for i, o in enumerate(shop.vouchers):
            cost = cost_of(run, o)
            v = self.voucher_worth(run, o.name, base) + adj(("voucher", o.name))
            up = UPGRADES.get(o.name)                        # a base voucher opens the way to its upgrade
            if up:
                v += UPGRADE_SHARE * max(0.0, self.voucher_worth(run, up["name"], base) - self.price(run, up["cost"]))
            if cost <= spend:
                consider(v, cost, ("buy", "voucher", i))
            else:                                            # a few dollars short: a sale, as for a joker (the user's
                funds = self._funds(run, owned, cost - spend)   # NNVPEGNB: Grabber at $10 with $9 never weighed, in
                if funds and v - funds[0] > w.sell_margin:      # the ante's last shop before it goes)
                    consider(v - funds[0], cost - funds[1], funds[2], then=("buy", "voucher", i))
        reroll = w.reroll + reroll_bonus(self, run) + hope + self._plan_reroll(run)   # Flash Card grows with each
        if reroll > 0 and shop.reroll_cost <= spend:
            consider(reroll, shop.reroll_cost, ("reroll",))
        if self.SURVIVAL or self.SCALING:
            action = self._survival_pick(run)
        if self.DISCOUNT_FIRST and action[0] in ("buy", "buy_use", "reroll") and action[1:2] != ("voucher",):
            # a discount voucher worth buying here goes first: what is bought after it costs less (the user's point,
            # C5X6MXUN 28 Oct: a pack bought ahead of Liquidation paid full price)
            for i, o in enumerate(shop.vouchers):
                if o.name in DISCOUNTS and self.worths.get(action_key(("buy", "voucher", i)), 0.0) > 0:
                    return ("buy", "voucher", i)
        if action == ("reroll",) and self.CARDS_BEFORE_REROLL:
            first = self._before_reroll(run, shop, spend)
            if first:
                return first
        return action

    CARDS_BEFORE_REROLL = True   # (on 30 Oct, a correctness fix) a reroll throws away the cards on offer: one used at once
                                 # and worth buying goes first while the reroll stays affordable, the reroll weighed again
                                 # after it. The user's 6AWQ2FCT ante 8, $77: "why not buy pluto while we are here? its
                                 # like it rerolls for rerolling" (reroll +0.057 against Pluto +0.040: Pluto lost)

    BEFORE_REROLL_MIN = 0.02     # what a card bought ahead of a reroll must be worth: the Play tab's coin-flip margin
                                 # (about 2% of a typical score). At more than nothing, Jupiter at +0.002 went first, a
                                 # Flush level the user's run hardly plays ("its almost of no use to me", 6AWQ2FCT)

    def _before_reroll(self, run, shop, spend: int):
        """CARDS_BEFORE_REROLL: the best card offer used as it is bought (a Planet, a Tarot needing no cards) worth at
        least BEFORE_REROLL_MIN, its price leaving the reroll affordable; None if there is none. Jokers and cards kept
        stay out: they take a slot a reroll's find may want."""
        best, pick = self.BEFORE_REROLL_MIN, None
        for i, o in enumerate(shop.cards):
            worth = self.worths.get(action_key(("buy_use", i, [])), 0.0)
            if worth > best and cost_of(run, o) + shop.reroll_cost <= spend:
                best, pick = worth, ("buy_use", i, [])
        return pick

    def voucher_worth(self, run, name: str, base: float) -> float:
        """A voucher's worth in this run (`base`: power(run)): one that adds or takes hands or discards, the change in a
        round's capacity (its hands, and its discards as half a hand each) as a log, at CAPACITY_WEIGHT; one that
        adds a card to the hand, the build's power with it, measured; its weight on top (for
        Hieroglyph and Petroglyph, the ante they give back). Nothing for one the bot can't use."""
        if name in ("Director's Cut", "Retcon") and self.REROLL_VOUCHERS and self.BOSS_AWARE:
            return self.boss_reroll_worth(run) * (1.5 if name == "Retcon" else 1.0)   # (Retcon: as often as wanted)
        if name in UNUSED_VOUCHERS:
            return 0.0
        if self.VOUCHERS_MEASURED and name in MEASURED_VOUCHERS:
            return self._measured_voucher(run, name)
        if self.GLYPH_MEASURED and name in ("Hieroglyph", "Petroglyph"):
            return self._glyph_worth(run, name)
        late = min(1.0, max(1, self._antes_ahead(run, 9 - run.ante)) / VOUCHER_ANTES) if self.SMALL else 1.0   # fewer antes left
        v = self.w.vouchers.get(name, 0.1)
        hands = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
        discards = max(0, run.base_discards + sum(j.discards_bonus for j in run.active_jokers()))
        if name in HANDS_FROM or name in DISCARDS_FROM:
            now = hands + DISCARD_AS_HANDS * discards
            after = max(1, hands + HANDS_FROM.get(name, 0)) + DISCARD_AS_HANDS * max(0, discards + DISCARDS_FROM.get(name, 0))
            v += CAPACITY_WEIGHT * math.log(after / now)
        if name in HAND_SIZE_FROM:
            run.base_hand_size += HAND_SIZE_FROM[name]
            try:
                v += self.power(run, fresh=True) - base
            finally:
                run.base_hand_size -= HAND_SIZE_FROM[name]
        return v * late if v > 0 else v                # (what a voucher takes, Hieroglyph's hand, stays whole)

    VOUCHERS_MEASURED = True    # (on 30 Oct: a correctness fix, level) Overstock and Reroll Surplus/Glut worth what they bring over the shops left, not a flat
                                # weight (Overstock 0.4 against a $10 price of 0.5 at $25 or less: a flat voucher
                                # cleared its price only above ~$40, so it was seldom bought early, when it pays most;
                                # the voucher check and the user, 29 Oct). Off until measured
    OVERSTOCK_SHARE = 0.2       # a third shop card adds this share of the shop's best offer (a best of three against
                                # two: an eighth to a quarter of it for offers spread evenly to exponentially)
    BEST_OFFER_PRIOR = 0.3      # a shop's best offer before the run has seen three (median joker buys net ~0.47)

    def _measured_voucher(self, run, name: str) -> float:
        """VOUCHERS_MEASURED: Overstock (Plus), one more card in every shop ahead: OVERSTOCK_SHARE of the run's recent
        best offer a shop (as _reroll_hope remembers them; BEST_OFFER_PRIOR before three). Reroll Surplus (Glut), $2
        off each reroll: the rerolls a shop ahead (the run's own so far, or the bot's own rate at the antes ahead,
        rerolls_ahead, whichever is more), the dollars saved worth what dollars_worth says (the bot rerolls with
        money past the reserve, which price charges at a tenth). Shops counted as lasting things are, a shop a
        round over the rounds the run is likely to last (rounds_left: survival-weighted, discounted; all the shops
        to ante 16 counted whole made Overstock 2.8 at ante 1)."""
        left = rounds_left(run)
        if name in ("Overstock", "Overstock Plus"):
            memo = self.__dict__.get("_rerolls")
            seen = memo[2][-self.REROLL_MEMORY:] if memo is not None and memo[0] == id(run) else []
            best = sum(seen) / len(seen) if len(seen) >= 3 else self.BEST_OFFER_PRIOR
            return self.OVERSTOCK_SHARE * best * left
        rate = max(run.rerolls_done / max(1, run.shops_seen), rerolls_ahead(run, left))
        return self.dollars_worth(run, 2 * rate * left)      # (rerolls spend money past the reserve, mostly)

    GLYPH_MEASURED = False      # Hieroglyph and Petroglyph worth an ante replayed less what a hand (a discard) a round
                                # costs at the margin, not a flat 0.1 for the ante against the log rule tuned on Grabber
                                # at 4 hands (-0.48 for a 6th hand the bot seldom uses: the user's NNVPEGNB, ante 5, -0.76
                                # in all, 29 Oct). Off until measured
    GLYPH_SHOP_SHARE = 0.5      # of a shop's best offer, each of the ante's 3 shops counted (not every best is bought)

    def _glyph_worth(self, run, name: str) -> float:
        """GLYPH_MEASURED: the ante back (its three shops at GLYPH_SHOP_SHARE of the run's recent best offer a shop,
        BEST_OFFER_PRIOR before three; three rounds' cash-out and interest at money's weight; less DEATH times the chance
        of losing the replayed ante's boss, at the lower ante's target, where this ante's would have been beaten) less
        the hand (Hieroglyph) or discard
        (Petroglyph) a round it takes: $1 of cash-out a round for a hand, and the capacity rule (CAPACITY_WEIGHT on the
        log of the change) times the share of them the run uses (hands_played a round against what it had), over the
        rounds the run is likely to last (rounds_left; the capacity part over a round's worth of them, as for Grabber)."""
        memo = self.__dict__.get("_rerolls")
        seen = memo[2][-self.REROLL_MEMORY:] if memo is not None and memo[0] == id(run) else []
        best = sum(seen) / len(seen) if len(seen) >= 3 else self.BEST_OFFER_PRIOR
        interest = min(run.interest_cap, max(0, run.money) // 5) if run.interest_enabled else 0
        shops = SHOPS_AN_ANTE * (self.GLYPH_SHOP_SHARE * best + self.w.money * (self.ROUND_PAY + interest))
        risk = 0.0
        if run.ante > 1:                                     # the boss replayed at the ante below, its target lower: lost
            table = run.ante_table                           # there, it costs only where the run would have gone on
            m0 = self.boss_margin(run, None)                 # (beaten this ante's boss)
            m = m0 * table[run.ante] / max(1, table[run.ante - 1])
            risk = DEATH * (1 - self.margin_odds(m, run=run)) * self.margin_odds(m0, run=run)
        hands = max(1, run.base_hands + sum(j.hands_bonus for j in run.active_jokers()))
        discards = max(0, run.base_discards + sum(j.discards_bonus for j in run.active_jokers()))
        now = hands + DISCARD_AS_HANDS * discards
        rounds = max(1, run.rounds_played)
        if name == "Hieroglyph":
            after = max(1, hands - 1) + DISCARD_AS_HANDS * discards
            used = min(1.0, run.hands_played / rounds / max(1, hands - 1)) if run.rounds_played else 1.0
            cash = self.w.money * rounds_left(run)          # $1 a round of cash-out for the hand not left over
        else:
            after = hands + DISCARD_AS_HANDS * max(0, discards - 1)
            spent = discards - run.unused_discards / rounds if run.rounds_played else discards   # discards used a round
            used = min(1.0, max(0.0, spent) / max(1, discards - 1))
            cash = 0.0
        lost = -CAPACITY_WEIGHT * math.log(after / now) * used + cash
        return shops - risk - lost

    REROLL_MEMORY = 12   # fresh sets of shop cards a reroll's hope is drawn from (the run's most recent)
    REROLL_SHARE = 0.25  # of their average best offer counted as a reroll's hope: on 480 seeds 0.25 beat ante 8 in
                         # 35.6%, all of it 19.8% (rerolls bought on hope too often), none 30.4%; on set 777, 39.6%
                         # against 36.5% at 0.125 and 33.3% at none

    def _reroll_hope(self, run, shop, card_best: float) -> float:
        """What a reroll may bring: the best card offer (net of its price, a joker in for the weakest when the slots
        are full) of the run's recent fresh sets of shop cards, a new shop's or a reroll's, on average; nothing it
        doesn't want counts below 0. This shop's cards are noted the first time they are weighed. Without three
        such sets yet, nothing. (A seeded run's next shop could be known; this only goes by what it has seen.)"""
        memo = self.__dict__.get("_rerolls")
        if memo is None or memo[0] != id(run):
            memo = self._rerolls = (id(run), set(), [])
        gen = (run.shops_seen, shop.rerolls, shop.free_rerolls)     # not id(shop): a later shop can get a dead one's
        if gen not in memo[1]:
            memo[1].add(gen)
            memo[2].append(max(0.0, card_best))
        seen = memo[2][-self.REROLL_MEMORY:]
        return self.REROLL_SHARE * sum(seen) / len(seen) if len(seen) >= 3 else 0.0

    def _duplicate_worth(self, run, k: int) -> float:
        """Invisible Joker at position k, 2 rounds in: what selling it brings, a copy of a random other joker
        (Negative dropped), on average over the jokers it could copy, worth to the build without it; 0 for any
        other joker, or with nothing to copy or no room for the copy."""
        j = run.jokers[k]
        if j.name != "Invisible Joker" or j.rounds < 2 or j.disabled or j.perished:
            return 0.0
        saved = run.jokers
        run.jokers = saved[:k] + saved[k + 1:]
        try:
            if not run.jokers or not run.joker_room():
                return 0.0
            base = self.power(run)
            worths = []
            for o in run.jokers:
                twin = copy.deepcopy(o, {id(run): run})
                if twin.edition == "Negative":
                    twin.edition = None
                worths.append(self.joker_worth(run, twin, base))
            return sum(worths) / len(worths)
        finally:
            run.jokers = saved

    def _funds(self, run, owned, short: int):
        """The one sale that raises `short` dollars for the least the build loses: an owned joker (`owned`: its
        worth, its position) or a held consumable (worth one kept), as (worth lost, dollars back, the sale); None if
        no single sale raises that much. The next shop action, with the money in hand, buys."""
        options = [(ow, run.sell_value(run.jokers[k]), ("sell_joker", k)) for ow, k in owned]
        options += [(self.keep_worth(run, c), run.sell_value(c), ("sell_consumable", i)) for i, c in enumerate(run.consumables)]
        options = [o for o in options if o[1] >= short]
        return min(options, key=lambda o: o[0]) if options else None

    def _funds_exact(self, run, owned, short: int, j, v: float, adj):
        """_funds under SWAP_EXACT: the one sale raising `short` dollars that leaves the best build once joker j (worth
        `v` beside the jokers held) is bought, as (what the sale and the buy add together, dollars back, the sale): a
        joker's sale by swap_worth, a consumable's as v less what keeping it is worth; None if no single sale will do."""
        options = [(self.swap_worth(run, k, j, adj), run.sell_value(run.jokers[k]), ("sell_joker", k)) for _, k in owned]
        options += [(v - self.keep_worth(run, c), run.sell_value(c), ("sell_consumable", i)) for i, c in enumerate(run.consumables)]
        options = [o for o in options if o[1] >= short]
        return max(options, key=lambda o: o[0]) if options else None

    def pack_action(self, run, pack):
        self._live = run
        base = self.scoring_power(run)
        adj = self.adjust(run, base)
        best, action = skip_bonus(self, run), ("skip",)     # Red Card grows with each pack skipped
        self.worths = {("skip",): best}
        self.worth_parts = {}

        def consider(worth, act):
            nonlocal best, action
            self.worths[action_key(act)] = worth
            self.worth_parts[action_key(act)] = {"gross": worth, "price": 0.0, "cost": 0}
            if worth > best or (self.PICK_TIES and act[0] == "pick" and action == ("skip",) and worth >= max(best, 0.0)):
                best, action = worth, act                     # a free pick worth what skipping is: taken

        weakest = None                                        # slots full: the joker to sell for a pick
        fire = sell_bonus(self, run) if self.FEED else 0.0    # Campfire: X0.25 for each card sold
        if not run.joker_room() and self.PACK_SWAPS:
            sellable = [(self.owned_worth(run, k, base) + adj(("joker", j.name)), k) for k, j in enumerate(run.jokers)
                        if not j.eternal and j.edition != "Negative"]
            weakest = min(sellable) if sellable else None
        for i, item in enumerate(pack.cards):
            if isinstance(item, Joker):
                v = self.joker_worth(run, item, base) + adj(("joker", item.name))
                if not item.eternal:                          # free, so worth at least what it sells back for: sold
                    v = max(v, run.sell_value(item) * self.w.money + fire)   # before the next hand (_dead_sale) if
                if run.joker_room(item):                      # it hurts the build (Joker Stencil: EURSXV11, the user)
                    consider(v, ("pick", i, []))
                elif weakest and self.SWAP_EXACT:                          # the sale that leaves the best build
                    swap = self._best_swap(run, item, adj, [k for _, k in sellable])
                    if swap and swap[0] > self.w.sell_margin:
                        consider(swap[0], ("sell_joker", swap[1]))
                elif weakest and v - weakest[0] > self.w.sell_margin:     # sold first, picked on the next call
                    consider(v - weakest[0], ("sell_joker", weakest[1]))
            elif isinstance(item, Consumable) and item.name in JOKER_MAKERS and weakest and not run.joker_room():
                k = weakest[1]                                # The Soul, Judgement, Wraith: room made for its joker
                v = self.effect_worth(run, lambda trial, i=i, k=k: (trial.sell_joker(k),
                                                                    trial.take_from_pack(trial.open_pack_state, i, [])))
                if v > self.w.sell_margin:
                    consider(v, ("sell_joker", k))
            elif isinstance(item, Consumable):
                quick = self.planet_worth(run, item) if item.kind == "Planet" else None
                for targets, _ in self._uses(run, item, run.hand):
                    consider((quick if quick is not None else self.effect_worth(
                        run, lambda trial, k=i, t=targets: trial.take_from_pack(trial.open_pack_state, k, t)))
                        + adj((item.kind.lower(), item.name)) + planet_bonus(self, run, item)
                        + self._plan_use(run, item, targets), ("pick", i, targets))
            elif isinstance(item, Card):
                consider(self.w.card + card_bonus(self, run) + self.card_add_worth(run, item) + self._plan_card(run, item),
                         ("pick", i, []))
        return action
