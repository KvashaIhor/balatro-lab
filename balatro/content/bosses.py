"""The 28 boss blinds: 23 regular, 5 Showdown (antes 8, 16, ...). Chip multiple, reward and minimum
ante come from data/bosses.json; The Wall, The Needle and Violet Vessel need nothing but those numbers.

Judgement calls (data/bosses.json, data/OPEN_QUESTIONS.md, balatrowiki.org):
- `triggered` (Matador) is per hand: cleared when Play is pressed, then set when that hand is not
  allowed, scores a debuffed card, or meets the boss's own effect (The Hook, The Tooth, The Arm at level
  2+, The Ox on its hand, The Flint always, Crimson Heart while you have jokers).
- The Hook discards 2 random held cards when Play is pressed: jokers' discard effects fire (not as a
  first discard, so Burnt Joker ignores it) and Purple Seals make a Tarot; it costs no discard.
- The Ox uses the most played hand at blind select (ties to the higher hand, as `run.most_played_hand`).
  The wiki fixes it when the ante starts, which the run doesn't record yet.
- Suit bosses use `has_suit`: Wild cards are debuffed, Stone cards aren't, Smeared Joker spreads the debuff
  to the other suit of the same colour (the game's `is_suit`). The Mark and The Plant honour Pareidolia.
- The Arm lowers the level in `before_score`; for a bot's estimate `modify_base` takes one level off the
  base instead, so estimates match what the hand will score.
- The Manacle disabled mid-round draws the card the extra hand size allows, as the game does.
- Amber Acorn shuffles the jokers after the jokers' blind-select effects (Ceremonial Dagger cuts first),
  or when Chicot disables it, so Chicot doesn't stop the shuffle. The shuffle stays.
- Crimson Heart disables a random joker once the first hand is dealt and re-picks after every hand
  (never the same joker twice in a row unless it is the only one; perished jokers are never picked). After
  the winning or the last hand it doesn't re-pick, so that joker stays disabled for the rest of the round.
- Cerulean Bell picks a random card in hand after each draw when none of its picks is still held.
- Verdant Leaf ends when a joker is sold during its round.
"""
from __future__ import annotations

import math

from ..hands import evaluate
from ..items import Boss, boss
from ..jokers import Joker
from ..scoring import HAND_BASE


class _Boss(Boss):
    """Clears `triggered` when Play is pressed; a disallowed hand or a debuffed scoring card sets it."""

    def press_play(self, run, played):
        result = evaluate(played, run.rules)
        self.triggered = not self.allows(run, result, played) or any(played[i].debuffed for i in result.scoring)


# ---- debuffs ------------------------------------------------------------------------------------

class _SuitBoss(_Boss):
    suit = "?"

    def debuffs(self, run, card):
        return card.has_suit(self.suit, run.smeared)


@boss
class TheClub(_SuitBoss):
    name, suit = "The Club", "Clubs"


@boss
class TheGoad(_SuitBoss):
    name, suit = "The Goad", "Spades"


@boss
class TheWindow(_SuitBoss):
    name, suit = "The Window", "Diamonds"


@boss
class TheHead(_SuitBoss):
    name, suit = "The Head", "Hearts"


@boss
class ThePlant(_Boss):
    name = "The Plant"

    def debuffs(self, run, card):
        return card.is_face(run.pareidolia)


@boss
class ThePillar(_Boss):
    name = "The Pillar"

    def debuffs(self, run, card):
        return card.uid in run.played_this_ante


@boss
class VerdantLeaf(_Boss):
    name = "Verdant Leaf"

    def debuffs(self, run, card):
        return True

    def on_sell(self, run, item):
        if isinstance(item, Joker) and run.current_shop is None:
            run.disable_boss()


# ---- hands that score nothing -------------------------------------------------------------------

@boss
class ThePsychic(_Boss):
    name = "The Psychic"

    def allows(self, run, result, played):
        return len(played) >= 5


@boss
class TheMouth(_Boss):
    name = "The Mouth"

    def allows(self, run, result, played):
        first = next(iter(run.round_hand_types), None)  # hand types in the order first played
        return first is None or result.name == first


@boss
class TheEye(_Boss):
    name = "The Eye"

    def allows(self, run, result, played):
        return run.round_hand_types[result.name] == 0


# ---- hands, discards, hand size -----------------------------------------------------------------

@boss
class TheNeedle(_Boss):
    name = "The Needle"

    def __init__(self):
        super().__init__()
        self.removed = 0

    def on_select(self, run):
        self.removed = max(0, run.hands_left - 1)
        run.hands_left -= self.removed

    def on_disable(self, run):
        run.hands_left += self.removed


@boss
class TheWater(_Boss):
    name = "The Water"

    def __init__(self):
        super().__init__()
        self.removed = 0

    def on_select(self, run):
        self.removed = run.discards_left
        run.discards_left = 0

    def on_disable(self, run):
        run.discards_left += self.removed


@boss
class TheManacle(_Boss):
    name = "The Manacle"

    def __init__(self):
        super().__init__()
        self.dealt = False

    def on_select(self, run):
        run.hand_size_delta -= 1

    def after_draw(self, run):
        self.dealt = True

    def on_disable(self, run):
        run.hand_size_delta += 1
        if self.dealt and run.current_shop is None:
            run.draw("disable")


@boss
class TheWall(_Boss):
    name = "The Wall"


@boss
class VioletVessel(_Boss):
    name = "Violet Vessel"


# ---- face-down cards and draws ------------------------------------------------------------------

@boss
class TheHouse(_Boss):
    name = "The House"

    def face_down(self, run, card, when):
        return when == "start"


@boss
class TheFish(_Boss):
    name = "The Fish"

    def face_down(self, run, card, when):
        return when == "play"


@boss
class TheMark(_Boss):
    name = "The Mark"

    def face_down(self, run, card, when):
        return card.is_face(run.pareidolia)


@boss
class TheWheel(_Boss):
    name = "The Wheel"

    def face_down(self, run, card, when):
        return run.chance(7, "misc")


@boss
class TheSerpent(_Boss):
    name = "The Serpent"

    def draw_count(self, run, default, when):
        return 3


@boss
class CeruleanBell(_Boss):
    name = "Cerulean Bell"

    def __init__(self):
        super().__init__()
        self.forced = None

    def after_draw(self, run):
        if run.hand and self.forced_selection(run) is None:
            self.forced = run.rng["misc"].choice(run.hand)

    def forced_selection(self, run):
        return next((i for i, c in enumerate(run.hand) if c is self.forced), None)

    def on_disable(self, run):
        self.forced = None


# ---- on play ------------------------------------------------------------------------------------

@boss
class TheHook(_Boss):
    name = "The Hook"

    def press_play(self, run, played):
        super().press_play(run, played)
        cards = run.rng["misc"].sample(run.hand, min(2, len(run.hand)))
        if not cards:
            return
        gone = {id(c) for c in cards}
        run.hand = [c for c in run.hand if id(c) not in gone]
        for j in list(run.active_jokers()):
            j.on_discard(run, cards, False)
        for c in cards:
            if c.seal == "Purple" and not c.debuffed:
                run.create_consumable("Tarot", source="8ba")
        run.emit("hook", [c.label() for c in cards])
        self.triggered = True


@boss
class TheTooth(_Boss):
    name = "The Tooth"

    def press_play(self, run, played):
        super().press_play(run, played)
        run.money -= len(played)
        self.triggered = True

    def money_when_scored(self, run, result, played):
        return run.money - len(played)


@boss
class TheArm(_Boss):
    name = "The Arm"

    def before_score(self, run, result):
        if run.hand_levels[result.name] > 1:
            run.level_up(result.name, -1)
            self.triggered = True

    def modify_base(self, ctx, score):
        chips, mult, dc, dm = HAND_BASE[ctx.result.name]
        if ctx.estimating and score.chips > chips:  # live hands already lost the level in before_score
            score.chips, score.mult = score.chips - dc, score.mult - dm
            score.note(self.name, "level -1", score.chips * score.mult)


@boss
class TheOx(_Boss):
    name = "The Ox"

    def __init__(self):
        super().__init__()
        self.hand = None

    def on_select(self, run):
        # TODO(engine): the wiki fixes the hand when the ante starts; the run should record
        # most_played_hand() in start_ante for The Ox to read (a reroll into The Ox uses it too).
        self.hand = run.most_played_hand() or "High Card"

    def before_score(self, run, result):
        if result.name == self.hand:
            run.money = 0
            self.triggered = True

    def money_when_scored(self, run, result, played):
        return 0 if result.name == self.hand else run.money


@boss
class TheFlint(_Boss):
    name = "The Flint"

    def modify_base(self, ctx, score):
        score.chips = max(0, math.floor(score.chips / 2 + 0.5))
        score.mult = max(1, math.floor(score.mult / 2 + 0.5))
        score.note(self.name, "base halved", score.chips * score.mult)

    def before_score(self, run, result):
        self.triggered = True


# ---- jokers -------------------------------------------------------------------------------------

@boss
class AmberAcorn(_Boss):
    name = "Amber Acorn"

    def __init__(self):
        super().__init__()
        self.shuffled = False
        self.before: list = []
        self.seen: dict = {}            # each joker (by id: a player follows it as it moves) -> the effects seen of it

    def noticed(self, run, score) -> None:
        """What a scored hand showed of each joker: the effects it made (kind and amount), each on its joker."""
        for (_, kind, amount), w in zip(score.log, score.who):
            if w is not None and 0 <= w < len(run.jokers):
                self.seen.setdefault(id(run.jokers[w]), []).append((kind, round(float(amount), 2)))

    def known(self, run) -> set:
        """The jokers a player can tell where they are: each whose effects seen are its own (no other joker showed the
        same, but one of its name); then by elimination, the last one left, or the rest when all alike."""
        sig = {id(j): tuple(self.seen.get(id(j), ())) for j in run.jokers}
        known = {id(j) for j in run.jokers
                 if sig[id(j)] and all(x.name == j.name for x in run.jokers if sig[id(x)] == sig[id(j)])}
        rest = [j for j in run.jokers if id(j) not in known]
        if len(rest) <= 1 or len({j.name for j in rest}) == 1:
            known |= {id(j) for j in rest}
        return known

    def shuffle(self, run):
        # The jokers are flipped face down and shuffled for the round: which is where isn't known until the first hand
        # scores (its effects, and the jokers' shapes, show it: the user, 29 Oct). `before` keeps the order a player
        # last saw: agents weigh their first hand in it and don't reorder before then (the second replay review's B1;
        # the viewer still shows them face up)
        if not self.shuffled:
            self.shuffled = True
            self.before = list(run.jokers)
            run.rng["misc"].shuffle(run.jokers)

    def after_draw(self, run):
        self.shuffle(run)

    def on_disable(self, run):
        self.shuffle(run)


@boss
class CrimsonHeart(_Boss):
    name = "Crimson Heart"

    def __init__(self):
        super().__init__()
        self.dealt = False

    def pick(self, run):
        if len(run.jokers) < 2:
            pool = list(run.jokers)
        else:
            pool = [j for j in run.jokers if not (j.disabled or j.perished)]
        for j in run.jokers:
            j.disabled = False
        if pool:
            run.rng["misc"].choice(pool).disabled = True

    def after_draw(self, run):
        if not self.dealt:
            self.dealt = True
            self.pick(run)

    def press_play(self, run, played):
        super().press_play(run, played)
        if run.jokers:
            self.triggered = True

    def after_hand(self, run):
        # TODO(engine): the run clears j.disabled before end-of-round effects; the joker disabled on the
        # winning hand should stay disabled until the shop (no Golden Joker money, no Egg growth, ...).
        if run.round_score < run.blind.chips and run.hands_left > 0:
            self.pick(run)

    def on_disable(self, run):
        for j in run.jokers:
            j.disabled = False
