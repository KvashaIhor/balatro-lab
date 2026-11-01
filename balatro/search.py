"""Round search (ValueBot.ROUND_SEARCH): before a play or discard in a round in doubt, the bot's own pick and the
leading others (the top plays by score, the top discards it weighs) are each played out to the round's end by the bot,
over redraws of what a player can't see: the draw pile reshuffled, each face-down card in hand swapped with a card it
could be (under The Mark a face card), and every chance from streams of their own (the game seed's set aside). The
same redraws for every option. The option that wins the round most often is taken; the bot's own unless another
wins clearly more (SEARCH_MARGIN more of the play-outs, confirmed on SEARCH_CONFIRM more).

The boss-round test (scripts/boss_rounds.py, b1, 30 Oct; its face-down cards not yet redrawn): the same cards played
this way won 43 of 116 lost boss rounds and lost 3 of 122 won ones. The bot picks the play or discard whose next hand
scores best on average; the round is won by reaching the target with the hands left."""
from __future__ import annotations

import copy
import math
import random

from .bots import ranked_plays, surely_wins


def finish_round(t) -> bool:
    """play_round's loop from where the round stands: True if it is won (Mr. Bones too)."""
    for _ in range(500):
        if t.round_score >= t.blind.chips:
            return True
        if t.hands_left <= 0 or not t.hand:
            break
        action = t.ask(t.agent.round_action)
        if not t.hand:
            break
        if action[0] == "discard" and t.discards_left > 0:
            t.discard(action[1])
        else:
            t.play_hand(action[1] if action[0] in ("play", "discard") and len(action) > 1 else [0])
    return t.round_score >= t.blind.chips or any(j.on_fail(t) for j in t.each_joker())


def _key(action) -> tuple:
    return action[0], tuple(action[1])


def candidates(bot, run, own) -> list:
    """The bot's own pick first, then the top plays by score and the top discards it weighs."""
    needed = run.blind.chips - run.round_score
    out, seen = [own], {_key(own)}
    plays = ranked_plays(run, need=needed, top=bot.SEARCH_PLAYS)
    for _, idx, _ in plays[:bot.SEARCH_PLAYS]:
        a = ("play", list(idx))
        if _key(a) not in seen:
            out.append(a)
            seen.add(_key(a))
    if run.discards_left > 0:
        keep = plays[0][1] if plays else []
        for _, opt, _ in bot._ranked_discards(run, keep)[:bot.SEARCH_DISCARDS]:
            a = ("discard", list(opt))
            if opt and _key(a) not in seen:
                out.append(a)
                seen.add(_key(a))
    return out


def redrawn(bot, run, rng) -> object:
    """A copy of the run with what a player can't see drawn again: a copy of `bot` playing it (searching no further;
    the run's own agent may be the Play tab's script), the pile reshuffled, face-down cards in hand swapped with cards
    they could be, chance from new streams."""
    saved, run.agent = run.agent, bot
    try:
        t = copy.deepcopy(run)
    finally:
        run.agent = saved
    t.agent._in_search = True
    t.frames = t.log = None
    t.seedrng = None
    t.rng = {name: random.Random(f"{rng.random()}:{name}") for name in t.rng}
    down = [i for i, c in enumerate(t.hand) if c.face_down]
    pool = sorted(t.draw_pile + [t.hand[i] for i in down],          # the unseen cards in an order that tells nothing
                  key=lambda c: (c.uid, c.rank, c.suit, c.enhancement or "", c.edition or "", c.seal or ""))
    boss = t.active_boss
    mark = boss is not None and boss.name == "The Mark"
    for i in down:
        could = [c for c in pool if c.is_face(t.pareidolia)] if mark else pool
        c = rng.choice(could or pool)
        pool.remove(c)
        c.face_down = True
        t.hand[i] = c
    for c in pool:
        c.face_down = False
    rng.shuffle(pool)
    t.draw_pile = pool
    return t


def play_out(bot, run, action, i: int) -> tuple[bool, float]:
    """Play-out `i` of `action` and the rest of the round (the same redraw for every action at this decision)."""
    salt = f"search:{run.seed}:{run.rounds_played}:{run.round_hands_played}:{run.discards_left}:{len(run.draw_pile)}:{i}"
    t = redrawn(bot, run, random.Random(salt))
    if action[0] == "discard" and t.discards_left > 0:
        t.discard(action[1])
    else:
        t.play_hand(action[1])
    won = finish_round(t)
    return won, math.log(max(1.0, t.round_score) / max(1, t.blind.chips))


def choose(bot, run, own) -> tuple:
    """The action to take: `own` (the bot's play or discard) unless another wins the round clearly more often."""
    boss = run.active_boss
    if boss is not None and boss.name == "Amber Acorn":        # the jokers face down: the play-outs would know them
        return own
    if own[0] == "play" and surely_wins(run, *_estimate(run, own), run.blind.chips - run.round_score):
        return own
    frames, log = run.frames, run.log
    run.frames = run.log = None
    try:
        n = bot.SEARCH_ROLLOUTS
        mine = [play_out(bot, run, own, i) for i in range(n)]
        if all(w for w, _ in mine):
            return own
        scores = {_key(own): mine}
        for a in candidates(bot, run, own)[1:]:
            scores[_key(a)] = [play_out(bot, run, a, i) for i in range(n)]
        wins = lambda k: sum(w for w, _ in scores[k])       # noqa: E731
        best = max(scores, key=lambda k: (wins(k), sum(s for _, s in scores[k])))
        if best == _key(own) or wins(best) < wins(_key(own)) + 1:
            return own
        for k in (_key(own), best):                         # confirmed on more play-outs, the same for both
            scores[k] += [play_out(bot, run, (k[0], list(k[1])), i) for i in range(n, n + bot.SEARCH_CONFIRM)]
        changed = wins(best) >= wins(_key(own)) + bot.SEARCH_MARGIN
        notes = getattr(bot, "search_notes", None)          # (analysis: scripts/boss_rounds.py --explain)
        if notes is not None:
            n_all = n + bot.SEARCH_CONFIRM
            notes.append({"boss": boss.name if boss else None, "hand": [str(c) for c in run.hand],
                          "needed": run.blind.chips - run.round_score, "hands": run.hands_left,
                          "discards": run.discards_left, "own": [own[0], [str(run.hand[i]) for i in own[1]]],
                          "best": [best[0], [str(run.hand[i]) for i in best[1]]], "own_wins": wins(_key(own)),
                          "best_wins": wins(best), "of": n_all, "changed": changed})
        if changed:
            bot.search_changes = getattr(bot, "search_changes", 0) + 1
            return best[0], list(best[1])
        return own
    finally:
        run.frames, run.log = frames, log


def _estimate(run, action) -> tuple[int, list[int]]:
    """The bot's own play's estimated score, as surely_wins needs it."""
    from .bots import estimate
    from .hands import evaluate_cached
    played = [run.hand[i] for i in action[1]]
    held = [c for i, c in enumerate(run.hand) if i not in action[1]]
    return estimate(run, played, held, evaluate_cached(played, run.rules)), action[1]
