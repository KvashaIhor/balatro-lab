# Build Planning Layer Implementation Plan (steps 0 and 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Any subagent dispatched for a task must be told: it must never spawn another agent (the user's hard rule).

**Goal:** The value bot builds toward engines (held Steel/Kings, DNA): it chooses a plan, values every decision by what
it adds to the plan beyond today, and steers buys, sells, packs, rerolls, Tarot targets, discards and plays toward it.
Step 0 first fixes power's unpaired sample hands.

**Architecture:** A new module `balatro/engines.py` holds the engines (data plus small functions) and the odds (from the
shop's rates, never the seed's future). `ValueBot` (balatro/strategy.py) gains the plan: a joint projection of the run
over `PLAN_HORIZON` antes, its value on the decision's own sample hands, the plan's choice, and `plan_worth`. Hooks go
through `adjust()` (jokers, packs, vouchers) and a few explicit call sites (consumable uses and keeps, playing cards,
rerolls, discards, plays). Everything is behind `PLAN = False` and `POWER_PAIRED = False`.

**Tech Stack:** Python 3.14, pytest. The eval harness (`scripts/eval_value.py`, the scratchpad's `eval_patched.py`,
`measure.sh`, `sweep.sh`, `compare_evals.py`).

**Spec:** `docs/superpowers/specs/2026-10-29-build-planning-layer-design.md`.

**No commits:** the project is not a git repository, and the user commits only when they ask. Each task ends with the
full test run instead.

**Run tests in the background** (the user's rule for anything over ~30 s): the full suite takes ~50 s:
`cd /Users/kvashaihor/Projects/evo/balatro && python3 -m pytest -q tests/ > logs/tests_plan.log 2>&1; echo "exit $?" >> logs/tests_plan.log`.
Single test files run in the foreground.

**Clarifications of the spec, settled while planning and in the plan review (11:55):**
- `plan_worth` is the plan's gain *beyond today's gain*, both measured the same way (`_plan_value` with and without
  the plan), wherever today's worth is measured (jokers, consumable uses, vouchers). Spec 4.4 adds plan worth to
  today's worth, so without the subtraction an item's own effect would count twice. Where today's worth is a flat
  weight (playing cards: `w.card`; packs: `pack_weight`; a Tarot kept: the keep option), the plan's gain is the full
  gain (`beyond_today=False`), or a Steel King would rank below a plain 5.
- `PLAN_MIN` starts at 0. A projection over 2 antes adds ~0.3 Chariots, so engine scores run ~0.02-0.03 (the reviewer
  measured them) and a 0.05 floor would leave every run without a plan. The sweeps of step 4 set it.
- For the jokers a decision adds or removes, their engines' chance terms are left out on both sides. A piece bought is
  certain. A piece sold is not counted as coming back. Otherwise "it may come later anyway" would make buying Baron
  worth less, and selling it cheaper.

**Scope cuts for step 1 (each noted in the code):**
- Plan worth reaches sells only through `adj` at the shop's and pack's call sites. `havoc`, `jev.py` and the tag rule
  are unchanged.
- An engine that doesn't fit the main one is not considered: `held` and `dna` fit each other. This comes with `flush`
  in step 3.
- A joker offered with a free slot gets plan worth only when it is a plan piece or starts an engine.
- DNA's best card is picked by a rank key (`_copy_rank`), not measured.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `balatro/engines.py` | create | the odds (`shops_ahead`, `cards_seen`, `joker_chance`, `pack_cards_seen`, `consumable_expected`), `expected_changes`, `Engine`, `HELD`, `DNA`, `ENGINES` |
| `balatro/strategy.py` | modify | `POWER_PAIRED` in `power`; the `PLAN*` switches; `_plan_hands`, `_trial`, `_project`, `_value_of`, `_best_of`, `_place`, `_plan_value`, `_plan`, `_current_plan`, `_plan_after`, `plan_worth`, `_plan_adjust`, `_plan_use`, `_plan_keep`, `_plan_card`, `_plan_pack`, `_plan_reroll`, `_holds`, `_prefers`; hooks in `adjust`, `consumable_choice`, `_uses`, `_shop_action`, `pack_action`, `_ranked_discards`, `_measure` |
| `balatro/modifiers.py` | modify | `plan_hold_cost`, subtracted in `play_bonus` |
| `scripts/eval_value.py` | modify | `--max-ante`; the per-game `plan` log |
| `tests/test_engines.py` | create | engines and odds; the bot's plan |
| `tests/test_strategy.py` | modify | `POWER_PAIRED` |
| scratchpad `prio_sweep.sh`, `queue20.sh`, `queue21.sh` | create | the measurement queue that puts the plan ahead of queues 17-19 |

Paths below are relative to `/Users/kvashaihor/Projects/evo/balatro`. The scratchpad is
`/private/tmp/claude-501/-Users-kvashaihor-Projects-evo/b504cf98-b6a4-4219-bcc8-62e92ceb2bb5/scratchpad` (`$S`).

---

### Task 0: `POWER_PAIRED`, power's hands paired across hand sizes (step 0)

**Files:**
- Modify: `balatro/strategy.py` (the switches near `TARGET`, ~line 839; `power`, lines 1002-1010)
- Test: `tests/test_strategy.py` (append)

- [ ] **Step 1: Write the failing test** (append to `tests/test_strategy.py`)

```python
def test_with_power_paired_a_hand_a_card_smaller_is_the_first_cards_of_the_larger_one():
    bot = ValueBot()
    bot.POWER_PAIRED = True
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    bot.power(run)
    small = [list(i) for i in bot._idx]
    run.base_hand_size += 1                         # Paint Brush: one card more in hand
    bot.power(run)
    big = [list(i) for i in bot._idx]
    assert len(big) == len(small) == bot.HANDS
    assert all(len(b) == len(s) + 1 and b[:len(s)] == s for s, b in zip(small, big))


def test_without_power_paired_power_samples_as_before():
    bot = ValueBot()
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    bot.power(run)
    rng = random.Random(str(bot._key) + bot.SAMPLE_SALT)
    n = len(bot._idx[0])
    assert bot._idx == [rng.sample(range(len(run.deck)), n) for _ in range(bot.HANDS)]
```

Add `import random` at the top of `tests/test_strategy.py` if it isn't there.

- [ ] **Step 2: Run it to see it fail**

Run: `python3 -m pytest -q tests/test_strategy.py -k power_paired`
Expected: FAIL (`AttributeError`, or the slices differ: n and n+1 are different hands today).

- [ ] **Step 3: Add the switches** (in `ValueBot`, after the `TARGET_LEVELS` line ~841)

```python
    POWER_PAIRED = False              # power's sample positions drawn once for PAIRED_CEILING cards, a smaller hand the
    PAIRED_CEILING = 20               # first n of each: options that change the hand size (Paint Brush, Palette, Juggler,
                                      # Turtle Bean) meet the same hands. The voucher check (29 Oct): Paint Brush read
                                      # -0.42 to +0.96 over 12 salts on n and n+1 different hands. Off until measured
```

- [ ] **Step 4: Pair the samples in `power`.** Replace lines 1002-1010 (from `key = (run.seed, ...` to
`self._key, self._idx = key, samples[key]`) with:

```python
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
```

With `HANDS` at its default and `POWER_PAIRED` off, `key` and the samples are exactly as before (`str(key)` is
unchanged), so nothing else moves. `_reach_bonus` and `deck_change_worth.rank_hits` read `self._idx`, which is now the
n-card slice.

- [ ] **Step 5: Run the two tests, then the full suite in the background**

Run: `python3 -m pytest -q tests/test_strategy.py -k "power_paired or samples_as_before"`. Expected: 2 passed.
Then the full suite (command in the header). Expected: `669 passed`, `exit 0`.

---

### Task 1: The eval harness: `--max-ante` and the plan log

**Files:**
- Modify: `scripts/eval_value.py` (`play`, ~line 63; `main`'s arguments and log line, ~lines 75-92)

- [ ] **Step 1: Add the argument and use it.** In `scripts/eval_value.py`:

```python
BOT = None
MAX_ANTE = 8                                           # --max-ante: play on past ante 8 (depth), 16 at most
```

(next to `BOT = None`, ~line 34). In `play`:

```python
    res = Run(bot, game_seed=seed, deck="Red Deck", max_ante=MAX_ANTE).play()
    out = {"seed": seed, "progress": res.progress, "won": res.won, "ante": res.ante, "seconds": time.time() - t}
    if getattr(bot, "plan_log", None):                   # the build plan's changes (strategy.py PLAN)
        out["plan"] = bot.plan_log
```

In `main`, after the `--rng` argument:

```python
    ap.add_argument("--max-ante", type=int, default=8)   # play on past ante 8 to see how deep runs go (the plan's depth)
```

and after `args = ap.parse_args()`:

```python
    global MAX_ANTE
    MAX_ANTE = max(8, min(16, args.max_ante))
```

(`global BOT, VALUE` is already declared at the top of `main`; add `MAX_ANTE` to it instead of a second `global` line.)
In the start log line change `Red Deck to ante 8` to `Red Deck to ante {MAX_ANTE}`.

- [ ] **Step 2: Check it runs** (two seeds, foreground, ~1 min):

Run: `cd /Users/kvashaihor/Projects/evo/balatro && VALUEBOT_WEIGHTS=hand python3 scripts/eval_value.py --bot base --label t-depth --seeds 2 --workers 2 --max-ante 12 2>&1 | tail -2`
Expected: a line `t-depth: beat ante 8 in .../2 ...; exit 0`. `runs/value/eval_t-depth.json` has two games. A game
that won may show `"ante"` above 8.

- [ ] **Step 3: Pass it through the scratchpad harness.** In `$S/measure.sh`, change the eval line to pass
`${MAXANTE:+--max-ante $MAXANTE}`:

```zsh
FROZEN_ROOT=$F VALUEBOT_WEIGHTS=hand nice -n 12 python3 -u $S/eval_patched.py --bot base --label $label --rng $rng --workers 16 ${MAXANTE:+--max-ante=$MAXANTE} >> $P/logs/value_eval.log 2>&1
```

(Write it as one word, `--max-ante=$MAXANTE`, exactly as in the line above: zsh doesn't split a space inside
`${...:+...}`, so a form with a space would hand argparse one unknown argument.)

`eval_patched.py` runs the snapshot's `scripts/eval_value.py` with `sys.argv` untouched, so the flag reaches it.
Snapshots frozen before this task don't know the flag, so depth runs need a snapshot taken after it.

---

### Task 2: `engines.py`, the odds

**Files:**
- Create: `balatro/engines.py`
- Test: `tests/test_engines.py` (create)

- [ ] **Step 1: Write the failing tests** (`tests/test_engines.py`)

```python
import random
import types

from balatro.cards import Card
from balatro.engines import consumable_expected, expected_changes, joker_chance, shops_ahead
from balatro.items import CONSUMABLES
from balatro.jokers import CATALOG
from balatro.run import Run
from balatro.strategy import ValueBot


def _run(bot=None, jokers=(), steel_kings=0, red=False):
    """A seeded Red Deck run out of a round, with these jokers and this many Kings made Steel (with Red Seals)."""
    run = Run(bot or ValueBot(), game_seed="DD8JI5Y5", deck="Red Deck")
    run.jokers = [CATALOG[n]() for n in jokers]
    for c in [c for c in run.deck if c.rank == 13][:steel_kings]:
        c.enhancement = "Steel"
        if red:
            c.seal = "Red"
    return run


def test_joker_chance_grows_with_the_cards_seen_and_counts_only_jokers_that_can_come():
    run = _run()
    one = joker_chance(run, ["Baron"], 10)
    assert 0 < one < joker_chance(run, ["Baron"], 40) < 1
    assert joker_chance(run, ["Baron", "Mime"], 10) > one
    assert joker_chance(run, ["Baron"], 10, buffoon=4) > one     # Buffoon pack cards are all jokers
    assert joker_chance(run, ["Steel Joker"], 10) == 0          # no Steel card in the deck: it can't come
    run.deck[0].enhancement = "Steel"
    assert joker_chance(run, ["Steel Joker"], 10) > 0
    run.jokers = [CATALOG["Baron"]()]
    assert joker_chance(run, ["Baron"], 10) == 0                 # owned


def test_consumables_expected_grow_with_the_shops_and_with_a_merchant():
    run = _run()
    few, more = consumable_expected(run, "The Chariot", 3), consumable_expected(run, "The Chariot", 6)
    assert 0 < few < more
    run.vouchers.append("Tarot Merchant")
    assert consumable_expected(run, "The Chariot", 3) > few
    assert shops_ahead(run, 2) == 6


def test_expected_changes_make_the_whole_ones_and_return_the_fraction():
    trial = types.SimpleNamespace(n=0)

    def one(t):
        t.n += 1
        return True
    rest = expected_changes(trial, 2.4, one)
    assert trial.n == 2 and len(rest) == 1 and abs(rest[0][0] - 0.4) < 1e-9
    assert expected_changes(trial, 0.004, one) == [] and trial.n == 2
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest -q tests/test_engines.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'balatro.engines'`.

- [ ] **Step 3: Write `balatro/engines.py`, the odds part**

```python
"""The build plan's engines (docs/superpowers/specs/2026-10-29-build-planning-layer-design.md): what each needs, how far
a run is toward it, the changes it can expect over the next antes (at the shops' odds, never the seed's future), and how
it plays. The value bot (strategy.py) chooses and values plans; this module knows only what it is passed."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .bots import copy_fires
from .items import CONSUMABLES
from .jokers import CATALOG
from .pool import PACK_ONLY, taken
from .shop import PACK_WEIGHTS, PACKS

RARITY_SHARE = {"Common": 0.7, "Uncommon": 0.25, "Rare": 0.05}     # data/shop.json joker_generation
SHOPS_AN_ANTE = 3
PACK_KIND = {"Tarot": "Arcana", "Planet": "Celestial", "Spectral": "Spectral"}


def shops_ahead(run, antes: int) -> int:
    """The shops in the next `antes` antes, none past the run's last boss."""
    return max(0, min(antes, run.max_ante + 1 - run.ante)) * SHOPS_AN_ANTE


def cards_seen(run, shops: int) -> float:
    """Shop cards seen over `shops` shops: the card slots, and 2 more a reroll at the run's own rate so far."""
    return shops * (run.shop_card_slots + 2 * run.rerolls_done / max(1, run.shops_seen))


def joker_chance(run, names, cards: float, buffoon: float = 0.0) -> float:
    """The chance one of the jokers `names` (not owned or on offer, able to appear: spawn conditions such as Steel
    Joker's Steel cards) is among `cards` shop cards or `buffoon` Buffoon pack cards: each shop card a joker at the
    slots' odds (a Buffoon card always), of its rarity at the rarity's share, then any of that rarity's jokers able to
    come."""
    weights = run.shop_weights()
    share = weights["Joker"] / sum(weights.values())
    gone = taken(run)
    live = {n: c for n, c in CATALOG.items() if n not in gone and c.can_spawn(run)}
    q = 0.0                                          # a joker card being one of them
    for n in names:
        cls = live.get(n)
        if cls is not None:
            q += RARITY_SHARE.get(cls.rarity, 0.0) / sum(1 for c in live.values() if c.rarity == cls.rarity)
    q = min(q, 1.0)
    return 1 - (1 - share * q) ** cards * (1 - q) ** buffoon


def pack_cards_seen(kind: str, shops: int) -> float:
    """Cards of a pack kind ("Arcana", "Celestial", "Spectral", "Standard") seen over `shops` shops, opening one pack a
    shop as the packs come (their weights)."""
    per = sum(w * p.shown for p, w in zip(PACKS.values(), PACK_WEIGHTS) if p.kind == kind) / sum(PACK_WEIGHTS)
    return shops * per


def consumable_expected(run, name: str, shops: int) -> float:
    """How many of consumable `name` the run can expect to come by over `shops` shops: its share of the shop's slots of
    its kind (cards_seen) and of the packs of its kind (pack_cards_seen)."""
    cls = CONSUMABLES[name]
    gone = taken(run) | PACK_ONLY
    if name in gone or not cls.can_spawn(run):
        return 0.0
    pool = sum(1 for n, c in CONSUMABLES.items() if c.kind == cls.kind and n not in gone and c.can_spawn(run))
    weights = run.shop_weights()
    slots = cards_seen(run, shops) * weights.get(cls.kind, 0) / sum(weights.values())
    return (slots + pack_cards_seen(PACK_KIND[cls.kind], shops)) / max(1, pool)


def expected_changes(trial, expected: float, apply_one) -> list:
    """Makes the whole number of an expected count of changes on `trial` (`apply_one(trial)` makes one, False when no
    card takes it); returns the fraction left as [(fraction, apply_one)], nothing once no card takes the change."""
    whole = int(expected)
    for _ in range(whole):
        if not apply_one(trial):
            return []
    rest = expected - whole
    return [(rest, apply_one)] if rest > 0.01 else []
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest -q tests/test_engines.py`
Expected: 3 passed.

---

### Task 3: `engines.py`, the held and DNA engines

**Files:**
- Modify: `balatro/engines.py` (append)
- Test: `tests/test_engines.py` (append; widen the engines import)

- [ ] **Step 1: Write the failing tests.** Change the engines import line to
`from balatro.engines import DNA, ENGINES, HELD, consumable_expected, expected_changes, joker_chance, shops_ahead`,
then append:

```python
def test_held_progress_counts_its_group_and_the_decks_steel_cards_and_kings():
    run = _run()
    assert abs(HELD.progress(run) - 0.5 * 4 / 6) < 1e-9          # 4 Kings of 6, no Baron or Mime
    run = _run(jokers=("Baron",), steel_kings=2)
    assert abs(HELD.progress(run) - (0.5 + 0.5)) < 1e-9          # Baron; 4 Kings + 2 Steel = 6
    assert HELD.owned(run) and not HELD.owned(_run())


def test_held_projection_puts_the_chariots_on_kings_and_leaves_the_run_unchanged():
    import copy
    run = _run(jokers=("Baron",))
    trial = copy.deepcopy(run)
    rest = HELD.project(run, trial, 30)                          # many shops: several Chariots expected
    steel = [c for c in trial.deck if c.enhancement == "Steel"]
    assert steel and all(c.rank == 13 for c in steel[:4])
    assert not any(c.enhancement == "Steel" for c in run.deck)
    assert all(0 < f < 1 for f, _ in rest)


def test_dna_projection_copies_the_best_card_once_a_round_for_each_time_dna_fires():
    import copy
    run = _run(steel_kings=1, red=True)
    run.jokers = [CATALOG["Blueprint"](), CATALOG["DNA"]()]          # Blueprint copies the joker to its right: DNA
    trial = copy.deepcopy(run)
    DNA.project(run, trial, 3)
    new = trial.deck[len(run.deck):]
    assert len(new) == 2 * 3                                         # DNA and its copy, 3 rounds
    assert all(c.rank == 13 and c.enhancement == "Steel" and c.seal == "Red" for c in new)


def test_the_held_engine_holds_steel_cards_and_kings_with_baron_and_wants_the_chariot_on_a_king():
    run = _run(jokers=("Baron",))
    king, ace = Card(13, "Spades"), Card(14, "Hearts")
    assert HELD.holds(run, king) and not HELD.holds(run, ace)
    assert HELD.holds(run, Card(14, "Hearts", enhancement="Steel"))
    assert HELD.prefers(run, "The Chariot", king) and not HELD.prefers(run, "The Chariot", ace)
    assert not HELD.prefers(run, "The Chariot", Card(13, "Spades", enhancement="Steel"))
    assert set(ENGINES) == {"held", "dna"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest -q tests/test_engines.py`
Expected: FAIL with `ImportError: cannot import name 'DNA'`.

- [ ] **Step 3: Append the engines to `balatro/engines.py`**

```python
@dataclass(frozen=True)
class Engine:
    name: str
    stage: str                     # when its changes are projected: "cards", "levels" or "copies" (spec 4.2's order)
    fits: frozenset                # the engines it combines with
    required: tuple                # an any-of group: the engine needs one of these jokers (empty: none)
    support: tuple                 # jokers that add to it, not needed
    consumables: tuple             # the consumables that make its cards (their uses and keeps get plan worth)
    progress: Callable             # (run) -> 0..1
    project: Callable              # (run, trial, shops) -> the fractions left: the whole changes made on `trial`
    holds: Callable = field(default=lambda run, c: False)            # a card it keeps in hand
    prefers: Callable = field(default=lambda run, name, c: False)    # a card it wants consumable `name` used on

    def owned(self, run) -> bool:
        return not self.required or any(j.name in self.required for j in run.jokers)

    def pieces(self) -> set:
        return set(self.required) | set(self.support)


def _king(c) -> bool:
    return c.rank == 13 and not c.is_stone


def _first(trial, wants, change) -> bool:
    """`change` made on the first card of the deck that each of `wants` in turn accepts; False when none does."""
    for want in wants:
        for c in trial.deck:
            if want(c):
                change(c)
                return True
    return False


# ---- held Steel / Kings (spec 5.1) --------------------------------------------------------------------------
HELD_GROUP = ("Baron", "Mime", "Shoot the Moon", "Steel Joker")


def _held_progress(run) -> float:
    group = 0.5 if any(j.name in HELD_GROUP for j in run.jokers) else 0.0
    cards = sum((c.enhancement == "Steel") + _king(c) for c in run.deck)     # a Steel King counts twice
    return group + 0.5 * min(1.0, cards / 6)


def _steel(trial) -> bool:
    """The Chariot as the held engine uses it: on a King, else a Queen (Strength's way to a King), else any card."""
    plain = lambda c: c.enhancement is None and not c.is_stone                # noqa: E731
    return _first(trial, (lambda c: plain(c) and _king(c), lambda c: plain(c) and c.rank == 12, plain),
                  lambda c: setattr(c, "enhancement", "Steel"))


def _red_seal(trial) -> bool:
    """Deja Vu as the held engine uses it: a Red Seal on a Steel King, else a King, else a Steel card."""
    free = lambda c: c.seal is None                                             # noqa: E731
    return _first(trial, (lambda c: free(c) and _king(c) and c.enhancement == "Steel", lambda c: free(c) and _king(c),
                          lambda c: free(c) and c.enhancement == "Steel"), lambda c: setattr(c, "seal", "Red"))


def _held_project(run, trial, shops) -> list:
    return (expected_changes(trial, consumable_expected(run, "The Chariot", shops), _steel)
            + expected_changes(trial, consumable_expected(run, "Deja Vu", shops), _red_seal))


def _held_holds(run, c) -> bool:
    names = {j.name for j in run.active_jokers()}
    return c.enhancement == "Steel" or (_king(c) and "Baron" in names) or (c.rank == 12 and "Shoot the Moon" in names)


def _held_prefers(run, name, c) -> bool:
    if name == "The Chariot":
        return _king(c) and c.enhancement is None
    if name == "Deja Vu":
        return _king(c) and c.seal is None
    return name == "Strength" and c.rank == 12


HELD = Engine("held", "cards", frozenset({"dna", "levels"}), HELD_GROUP,
              ("Blueprint", "Brainstorm", "Juggler", "Turtle Bean", "Raised Fist"),
              ("The Chariot", "Strength", "Deja Vu"), _held_progress, _held_project, _held_holds, _held_prefers)


# ---- DNA / one-card (spec 5.2) --------------------------------------------------------------------------------
def _dna_progress(run) -> float:
    has = 0.5 if any(j.name == "DNA" for j in run.jokers) else 0.0
    good = sum(1 for c in run.deck if c.enhancement in ("Steel", "Glass") or c.seal == "Red" or c.edition == "Polychrome")
    return has + 0.5 * min(1.0, good / 2)


def _copy_rank(c) -> tuple:
    """The card DNA's copies go to (a stand-in for the copy worth most, step 1): Steel or Glass, a Red Seal,
    Polychrome, a King, then rank."""
    return (c.enhancement in ("Steel", "Glass"), c.seal == "Red", c.edition == "Polychrome", _king(c), c.rank)


def _dna_project(run, trial, shops) -> list:
    """That card copied once a round for each time DNA fires (copy_fires: DNA and the copiers that reach it)."""
    fires = sum(n for j, n in zip(trial.jokers, copy_fires(trial.jokers)) if j.name == "DNA")
    best = max((c for c in trial.deck if not c.is_stone), key=_copy_rank, default=None)
    if fires and best is not None:
        trial.add_cards([trial.copy_card(best) for _ in range(fires * shops)])
    return []


DNA = Engine("dna", "copies", frozenset({"held", "levels"}), ("DNA",), ("Blueprint", "Brainstorm", "Hanging Chad"), (),
             _dna_progress, _dna_project)

ENGINES = {e.name: e for e in (HELD, DNA)}
```

- [ ] **Step 4: Run the engine tests**

Run: `python3 -m pytest -q tests/test_engines.py`
Expected: 7 passed. If `copy_card`'s copies land in `trial.deck` elsewhere than its end, compare by `uid` instead of
slicing: `new = [c for c in trial.deck if c.uid not in {x.uid for x in run.deck}]`.

---

### Task 4: The plan's value and its choice (ValueBot core)

**Files:**
- Modify: `balatro/strategy.py`: imports (line 31), switches (after `POWER_PAIRED`), new methods (after
  `deck_change_worth`'s helpers, before `_candidates`, ~line 1210)
- Test: `tests/test_engines.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def _plan_bot(**switches):
    bot = ValueBot()
    bot.PLAN = True
    for k, v in switches.items():
        setattr(bot, k, v)
    return bot


def test_a_missing_group_counts_once_at_its_chance(monkeypatch):
    import balatro.strategy as s
    bot = _plan_bot()
    run = _run(bot, steel_kings=3, red=True)                      # the held group missing
    values = {}
    for p in (0.0, 0.5, 1.0):
        monkeypatch.setattr(s, "joker_chance", lambda run, names, cards, buffoon=0.0, p=p: p)
        values[p] = bot._plan_value(run, run, ("held",))
    assert values[1.0] > values[0.0]
    assert abs(values[0.5] - (values[0.0] + values[1.0]) / 2) < 1e-9


def test_the_plan_never_reads_the_game_seed_nor_the_draw_piles_order():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron",), steel_kings=2)
    calls = []

    class Spy:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError(f"the plan read the game seed: {name}")

    add_mime = lambda t: t.jokers.append(CATALOG["Mime"]())                    # noqa: E731
    real, run.seedrng = run.seedrng, Spy()
    try:
        worth = bot.plan_worth(run, add_mime, names=("Mime",))
    finally:
        run.seedrng = real
    assert calls == [] and worth != 0
    run.blind = run.make_blind(0)                                 # in a round, with a draw pile to shuffle
    run.in_round, run.hand, run.draw_pile = True, run.deck[:8], run.deck[8:]
    worth = _plan_bot().plan_worth(run, add_mime, names=("Mime",))
    random.Random(1).shuffle(run.draw_pile)
    assert _plan_bot().plan_worth(run, add_mime, names=("Mime",)) == worth


def test_with_baron_and_steel_kings_the_plan_is_held_and_dna_fits_it():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron",), steel_kings=3, red=True)
    plan = bot._plan(run)
    assert set(plan) == {"held", "dna"}                           # dna: its Steel cards to copy (progress above 0)
    assert bot.plan_log and set(bot.plan_log[-1]["plan"]) == {"held", "dna"}
    assert _plan_bot(PLAN_MIN=99.0)._plan(run) == ()              # nothing scores that much: no plan
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest -q tests/test_engines.py -k "chance or game_seed or plan_is_held"`
Expected: FAIL with `AttributeError: 'ValueBot' object has no attribute '_plan_value'`.

- [ ] **Step 3: Imports.** In `balatro/strategy.py` change line 31 and add the engines import after it:

```python
from .jokers import CATALOG, Joker
from .engines import ENGINES, cards_seen, joker_chance, pack_cards_seen, shops_ahead
```

- [ ] **Step 3b: deck_change_worth's hands keyed on their count.** In `deck_change_worth` (~line 1129), after the
`key = (run.seed, ...)` line add:

```python
        if self.CARD_HANDS != type(self).CARD_HANDS:   # the plan's own count (PLAN_CARD_HANDS): its own hands
            key += (self.CARD_HANDS,)
```

`rng` is still seeded on `key[:5]`, so the first 8 of 24 hands are the usual 8.

- [ ] **Step 4: The switches** (in `ValueBot`, after `PAIRED_CEILING`)

```python
    PLAN = False              # the build plan (docs/superpowers/specs/2026-10-29-build-planning-layer-design.md): the
                              # engines the run can most likely complete (engines.py), every decision valued and steered
                              # toward them. Off until measured
    PLAN_HELD = True          # each engine, when PLAN is on (a step's measurement turns the others off)
    PLAN_DNA = True
    PLAN_WEIGHT = 1.0         # plan worth times this
    PLAN_HORIZON = 2          # antes the plan projects ahead
    PLAN_MIN = 0.0            # a plan only when its main engine scores above this (power): engine scores over 2 antes
                              # run ~0.02-0.03 (plan review, 29 Oct); step 4's sweeps set it
    PLAN_SWITCH = 0.25        # the main engine changes only for one scoring this share more than it
    PLAN_HANDS = 36           # power's sample hands for a plan's value: the engine cards a projection adds are few
    PLAN_KEEP = 0.8           # a Tarot kept for an engine's target: its use there, times this (the target may not come)
    PLAN_HOLD = 0.05          # playing a card the plan holds: this a hand left after this one (its held effect lost)
```

- [ ] **Step 5: The core methods** (in `ValueBot`, before `_candidates`)

```python
    # ---- the build plan (spec docs/superpowers/specs/2026-10-29-build-planning-layer-design.md) ---------------------
    def _engines(self) -> dict:
        on = {"held": self.PLAN_HELD, "dna": self.PLAN_DNA}
        return {k: e for k, e in ENGINES.items() if on.get(k)}

    PLAN_CARD_HANDS = 24      # deck_change_worth's shared hands for a plan's value (8 otherwise)

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
        horizon, card changes first, then levels, then DNA's copies; and the fractions left, [(fraction, apply_one)]."""
        trial = self._trial(state)
        shops = shops_ahead(state, self.PLAN_HORIZON)
        rest = []
        for stage in ("cards", "levels", "copies"):
            for e in engines:
                if e.stage == stage:
                    rest += e.project(state, trial, shops)
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
                deck = self.DECK_TRUST * self.deck_change_worth(run0, r)
                v += deck
                for fraction, apply_one in rest:
                    one = self._trial(r)
                    if apply_one(one):
                        v += fraction * (self.DECK_TRUST * self.deck_change_worth(run0, one) - deck)
        finally:
            run0.jokers, run0.base_hand_size = saved[0], saved[2]
            run0.hand_levels.clear()
            run0.hand_levels.update(saved[1])
        return v

    def _place(self, trial, joker, keep=()) -> bool:
        """`joker` into the trial's row: a free slot, else in for the joker worth least outside `keep` (the plan's
        pieces), else the plan piece worth least. False when no joker can go."""
        if trial.joker_room(joker):
            trial.jokers.append(joker)
            return True
        movable = [k for k, j in enumerate(trial.jokers) if not j.eternal and j.edition != "Negative"]
        pool_ = [k for k in movable if trial.jokers[k].name not in keep] or movable
        if not pool_:
            return False
        base = self.power(trial)
        trial.jokers[min(pool_, key=lambda k: self.owned_worth(trial, k, base))] = joker
        return True

    def _best_of(self, state, e, keep) -> str | None:
        """The joker of e's group (not owned, able to appear) that adds most to `state`, as a buy would place it;
        remembered for the decision."""
        key = (e.name, tuple(j.name for j in state.jokers), len(state.deck), tuple(state.hand_levels.values()))
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
        one of its jokers comes times what the best of them adds to the projection (redone with it)."""
        engines = [ENGINES[k] for k in plan]
        r, rest = self._project(state, engines)
        base = v = self._value_of(run0, r, rest)
        keep = set().union(*(e.pieces() for e in engines)) if engines else set()
        shops = shops_ahead(state, self.PLAN_HORIZON)
        cards, buffoon = cards_seen(state, shops), pack_cards_seen("Buffoon", shops)
        for e in engines:
            if e.required and e.name not in skip and not e.owned(state):
                p = joker_chance(state, e.required, cards, buffoon)
                best = self._best_of(state, e, keep) if p > 0 else None
                if best is not None:
                    g = self._trial(state)
                    self._place(g, CATALOG[best](), keep)
                    rg, rest_g = self._project(g, engines)
                    v += p * (self._value_of(run0, rg, rest_g) - base)
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
        engines = self._engines()
        none = self._plan_value(run, run, ())
        scores = {k: self._plan_value(run, run, (k,)) - none for k in engines}
        held = self.__dict__.get("_plan_main")
        main = held[1] if held and held[0] == id(run) else None
        best = max(scores, key=scores.get, default=None)
        if main not in scores or scores[main] <= self.PLAN_MIN:
            main = best if best is not None and scores[best] > self.PLAN_MIN else None
        elif scores[best] > scores[main] * (1 + self.PLAN_SWITCH):
            main = best
        plan = () if main is None else (main,) + tuple(
            k for k in engines if k != main and k in ENGINES[main].fits and ENGINES[k].progress(run) > 0)
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
```

- [ ] **Step 5b: Mark the live run at the entry points.** The bot values cards on copies of the run
(`effect_worth`, `keep_worth`), and a copy must never get a plan of its own: in review, 384 of one game's `_plan` calls
were on copies, 11 of 15 log entries duplicates, and the game took 87 s against 34. Add `self._live = run` as the first
line of `SmartBot.round_action` (strategy.py:148), `ValueBot.skip_blind` (~1920), `ValueBot.shop_action` (~2017) and
`ValueBot.pack_action` (~2248). A test that calls the plan's methods directly gets its first run as the live one
(`_is_live`'s `setdefault`).

- [ ] **Step 6: Run the tests**

Run: `python3 -m pytest -q tests/test_engines.py -k "chance or game_seed or plan_is_held"`
Expected: `test_a_missing_group_counts_once_at_its_chance` and `..._the_plan_is_held_and_dna_fits_it` pass. The
no-peeking test needs `plan_worth` (Task 5) and passes after it. If `_plan` gives `("held",)` alone, `dna`'s progress
read 0: check that `_dna_progress` counts the Steel Kings.

---

### Task 5: `plan_worth`, and jokers bought and sold

**Files:**
- Modify: `balatro/strategy.py` (`adjust`, ~line 1667; new methods after `_plan`; `pack_action`'s `weakest`, ~line 2261)
- Test: `tests/test_engines.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_with_steel_red_seal_kings_held_by_baron_and_mime_dna_is_worth_more_than_wee_joker():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron", "Mime"), steel_kings=3, red=True)
    base = bot.power(run)
    adj = bot.adjust(run, base)
    dna = bot.joker_worth(run, CATALOG["DNA"](), base) + adj(("joker", "DNA"))
    wee = bot.joker_worth(run, CATALOG["Wee Joker"](), base) + adj(("joker", "Wee Joker"))
    assert adj(("joker", "DNA")) > 0
    assert dna > wee


def test_an_item_can_start_an_engine_and_a_joker_outside_the_plan_gets_nothing_with_a_free_slot():
    bot = _plan_bot()
    run = _run(bot)                                                 # a plain deck
    adj = bot.adjust(run, bot.power(run))
    assert adj(("joker", "Baron")) > 0                              # starts held (or adds to it)
    assert adj(("joker", "Jolly Joker")) == 0


def test_with_dna_copying_kings_selling_baron_counts_what_the_plan_loses():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron", "DNA", "Jolly Joker"), steel_kings=2)
    adj = bot.adjust(run, bot.power(run))
    assert adj(("joker", "Baron")) > abs(adj(("joker", "Jolly Joker")))
    bot.PLAN = False
    assert bot.adjust(run, bot.power(run))(("joker", "Baron")) == 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest -q tests/test_engines.py -k "wee_joker or start_an_engine or selling_baron"`
Expected: FAIL (no plan part in `adjust`; `plan_worth` missing).

- [ ] **Step 3: `plan_worth` and its helpers** (after `_plan`)

```python
    def _plan_after(self, run, trial, plan) -> tuple:
        """The plan as a decision leaves it (spec 4.4): with the engine a joker it adds would start, when that engine
        fits the main one (or there is no plan yet). One that doesn't fit would need a switch: not with held and dna,
        which fit each other (it comes with flush, step 3)."""
        engines = self._engines()
        started = [k for k, e in engines.items() if k not in plan and e.required and e.owned(trial) and not e.owned(run)]
        if not started:
            return plan
        if not plan:
            main = started[0]
            return (main,) + tuple(k for k in engines if k != main and k in ENGINES[main].fits
                                   and ENGINES[k].progress(trial) > 0)
        return plan + tuple(k for k in started if k in ENGINES[plan[0]].fits)

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
        after = self._plan_after(run, trial, plan)
        if not plan and not after:
            return 0.0
        skip = frozenset(k for k, e in ENGINES.items() if set(names) & set(e.required))
        gain = self._plan_value(run, trial, after, skip) - self._plan_base(run, plan, skip)
        if not beyond_today:
            return self.PLAN_WEIGHT * gain
        today = self._plan_value(run, trial, (), skip) - self._plan_base(run, (), skip)
        return self.PLAN_WEIGHT * (gain - today)

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
            owned = [k for k, j in enumerate(run.jokers) if j.name == name]
            if owned:
                k = owned[0]
                v = -self.plan_worth(run, lambda t: t.jokers.pop(k), names=(name,))
            else:
                plan = self._plan(run)
                pieces = self._plan_pieces(plan)
                starts = any(name in e.required for e in self._engines().values())
                cls = CATALOG.get(name)
                if cls is not None and (name in pieces or starts or not run.joker_room()):
                    v = self.plan_worth(run, lambda t: self._place(t, cls(), pieces), names=(name,))
        elif kind == "pack":
            v = self._plan_pack(run, name)
        elif name in ("Paint Brush", "Palette") and "held" in self._plan(run):
            v = self.plan_worth(run, lambda t: setattr(t, "base_hand_size", t.base_hand_size + 1))
        if len(memo) > 256:
            memo.clear()
        memo[mkey] = v
        return v
```

Add `_plan_pack` now as a stub that Task 7 fills in, so `_plan_adjust` runs:

```python
    def _plan_pack(self, run, name) -> float:
        return 0.0                                     # Task 7
```

- [ ] **Step 4: Hook `adjust`.** Replace `adjust` (~line 1667) with:

```python
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
```

- [ ] **Step 5: Sells from a pack count it too.** In `pack_action` (~line 2261) change the `sellable` line to:

```python
            sellable = [(self.owned_worth(run, k, base) + adj(("joker", j.name)), k) for k, j in enumerate(run.jokers)
                        if not j.eternal and j.edition != "Negative"]
```

(`_shop_action`'s owned list, line 2079, already adds `adj(("joker", j.name))`.)

- [ ] **Step 6: Run the engine tests**

Run: `python3 -m pytest -q tests/test_engines.py`
Expected: 13 passed. If `dna > wee` fails while `adj(("joker", "DNA")) > 0` passes, print both sides. The DNA copies
are measured by `deck_change_worth`'s "card added" path, so check that `_value_of` sees `r.deck` longer than
`run0.deck`.

---

### Task 6: Consumables: preferred targets, uses and keeps

**Files:**
- Modify: `balatro/strategy.py`: `_uses` (~line 540, before `out = []`); `consumable_choice` (~lines 1810-1815);
  `_shop_action` (keep at ~2126, swap at ~2131); `pack_action`'s consumable picks (~2280); new methods after
  `_plan_adjust`
- Test: `tests/test_engines.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def _hand_of(run, ranks):
    """Plain hand cards taken from the run's own deck (so deck changes on them are seen), by rank, in order."""
    out, used = [], set()
    for r in ranks:
        c = next(c for c in run.deck if c.rank == r and c.enhancement is None and id(c) not in used)
        used.add(id(c))
        out.append(c)
    return out


def test_under_a_held_plan_the_chariot_is_offered_and_used_on_a_king():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron", "DNA"))
    chariot = CONSUMABLES["The Chariot"]()
    run.consumables = [chariot]
    run.hand = _hand_of(run, (14, 13, 7, 5, 3, 9, 2, 4))          # an Ace first, a plain King second
    uses = bot._uses(run, chariot, run.hand)
    assert [1] in [u[0] for u in uses]                             # the King is offered (today: highest and lowest only)
    k = bot.consumable_choice(run, chariot, uses)
    assert k < len(uses) and uses[k][0] == [1]


def test_keeping_the_chariot_for_a_king_is_worth_something_only_when_no_king_is_in_hand():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron", "DNA"))
    chariot = CONSUMABLES["The Chariot"]()
    run.consumables = [chariot]
    run.hand = _hand_of(run, (14, 7, 5, 3, 9, 2, 4, 6))
    assert bot._plan_keep(run, chariot, full=True) > 0
    run.hand = _hand_of(run, (13, 7, 5, 3, 9, 2, 4, 6))
    assert bot._plan_keep(run, chariot, full=True) == 0
```

The first test's choice is today's worth deciding (a Steel King held with Baron against a Steel Ace, often played),
now that the King is offered. Each use's plan worth beyond today is about 0 here: it only counts what the use changes
in the projection. If the choice fails, print both uses' `effect_worth` before changing anything.

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest -q tests/test_engines.py -k "chariot"`
Expected: FAIL (`_plan_use` missing; the King isn't offered: `_uses` gives the highest and lowest only).

- [ ] **Step 3: The methods** (after `_plan_adjust`)

```python
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
```

- [ ] **Step 4: Offer the preferred targets in `_uses`.** Just before `out = []` (~line 540):

```python
        if getattr(self, "PLAN", False):                 # the build plan's preferred targets (Kings for The Chariot)
            pref = [i for i in high if self._prefers(run, name, hand[i])][:n]
            if pref:
                sets.append(pref)
```

- [ ] **Step 5: `consumable_choice`.** Change the keep line (~1810) and the per-use line (~1815):

```python
        best, choice = adj(("keep", c.kind)) + self._plan_keep(run, c, full=True), len(uses)
```

```python
            v += adj((c.kind.lower(), c.name)) + planet_bonus(self, run, c) + self._plan_use(run, c, targets)
```

- [ ] **Step 6: The shop and the packs.** In `_shop_action`, the buy-to-keep `consider` (~2126):

```python
                    consider(self.keep_worth(run, item) + copies + adj(("keep", item.kind)) + self._plan_keep(run, item),
                             cost, ("buy", "card", i), card=True)
```

and the swap gain (~2131):

```python
                        gain = self.keep_worth(run, item) + adj(("keep", item.kind)) + self._plan_keep(run, item) - least
```

In `pack_action`'s consumable picks (~2280), add `+ self._plan_use(run, item, targets)` to the value passed to
`consider` (after `planet_bonus(self, run, item)`).

- [ ] **Step 7: Run the tests**

Run: `python3 -m pytest -q tests/test_engines.py -k chariot`. Expected: 2 passed. Then the full suite in the background.
Expected: `exit 0`, every earlier test unchanged (PLAN is off in them).

---

### Task 7: Playing cards, packs and rerolls

**Files:**
- Modify: `balatro/strategy.py` (`_plan_pack` replaces the stub; new `_plan_card`, `_plan_reroll`; `pack_action`'s Card
  branch ~2284; `_shop_action`'s Card branch ~2137 and the reroll ~2159)
- Test: `tests/test_engines.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_under_a_held_plan_a_standard_pack_gives_its_steel_king():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron", "DNA"), steel_kings=1)
    pack = types.SimpleNamespace(cards=[Card(5, "Clubs"), Card(13, "Hearts", enhancement="Steel")])
    assert bot.pack_action(run, pack) == ("pick", 1, [])
    bot.PLAN = False
    assert bot.pack_action(run, pack) == ("pick", 0, [])            # without the plan the two are alike


def test_under_a_held_plan_an_arcana_pack_is_worth_its_chance_of_the_chariot():
    bot = _plan_bot()
    run = _run(bot, jokers=("Baron", "DNA"))
    assert bot._plan_pack(run, "Arcana Pack") > 0
    assert bot._plan_pack(run, "Celestial Pack") == 0
    assert bot._plan_reroll(run) == 0                              # its groups are owned: nothing for a reroll to find
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest -q tests/test_engines.py -k "standard_pack or arcana_pack"`. Expected: FAIL.

- [ ] **Step 3: The methods** (replace the `_plan_pack` stub)

```python
    def _plan_card(self, run, card) -> float:
        """What adding playing card `card` to the deck adds under the plan, its own worth included (today's worth at
        these call sites is the flat w.card)."""
        if not self.PLAN or not self._plan(run):
            return 0.0
        return self.plan_worth(run, lambda t: t.add_cards([copy.deepcopy(card)]), beyond_today=False)

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
        keep, total = self._plan_pieces(plan), 0.0
        for e in (ENGINES[k] for k in plan):
            if e.required and not e.owned(run):
                p = joker_chance(run, e.required, 2)
                best = self._best_of(run, e, keep) if p > 0 else None
                if best is not None:
                    total += p * self.plan_worth(run, lambda t, b=best: self._place(t, CATALOG[b](), keep), names=(best,))
        return total
```

`_plan_pack` empties `run.hand` around `_plan_keep`: a card a pack may bring is valued by its use on a preferred card
in the deck, whatever the hand holds now.

- [ ] **Step 4: The hooks.** `pack_action`'s Card branch (~2284):

```python
                consider(self.w.card + card_bonus(self, run) + self._plan_card(run, item), ("pick", i, []))
```

`_shop_action`'s Card branch (~2137):

```python
                consider(w.card + card_bonus(self, run) + self._plan_card(run, item), cost, ("buy", "card", i), card=True)
```

and the reroll (~2159):

```python
        reroll = w.reroll + reroll_bonus(self, run) + hope + self._plan_reroll(run)   # Flash Card grows with each
```

The pack offers already add `adj(("pack", p.name))` (~2143), which now reaches `_plan_pack`.

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest -q tests/test_engines.py`. Expected: all pass. Then the full suite in the background: `exit 0`.

---

### Task 8: Steering in the round: held cards stay, and cost to play

**Files:**
- Modify: `balatro/strategy.py`: new `_holds`; `_ranked_discards` (after the `mods` options, ~line 432); `_measure`
  (~853). `balatro/modifiers.py`: `play_bonus`'s return (~line 279); new `plan_hold_cost`
- Test: `tests/test_engines.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
def _held_round(bot, hand, pile):
    """A Small Blind in play under a held plan: Baron and DNA, the hand's Kings plain (a Steel card is protected
    already: held_value), so only the plan keeps them."""
    run = _run(bot, jokers=("Baron", "DNA"))
    bot._plan(run)                                                  # chosen in the shop before the round
    run.blind = run.make_blind(0)
    run.in_round, run.round_score = True, 0
    run.hands_left, run.discards_left = 4, 3
    run.hand, run.draw_pile = hand(run), pile
    return run


def test_under_a_held_plan_a_discard_never_throws_a_held_card():
    bot = _plan_bot()
    run = _held_round(bot, lambda r: _hand_of(r, (13, 13, 2, 3, 5, 7, 9, 10)), [Card(4, "Spades"), Card(6, "Clubs")])
    assert bot._holds(run)(run.hand[0])
    for _, opt, _ in bot._ranked_discards(run, []):
        assert not any(run.hand[i].rank == 13 for i in opt)


def test_playing_a_held_card_costs_for_the_hands_left_after_this_one():
    from balatro.modifiers import plan_hold_cost
    bot = _plan_bot()
    run = _held_round(bot, lambda r: _hand_of(r, (13, 13, 2, 3, 5, 7, 9, 10)), [])
    kings = [run.hand[0], run.hand[1]]
    assert plan_hold_cost(bot, run, kings) == 2 * 3 * bot.PLAN_HOLD
    assert plan_hold_cost(bot, run, [run.hand[2]]) == 0
    assert bot._measure(run) is not None                            # so play_bonus runs
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m pytest -q tests/test_engines.py -k "held_card"`. Expected: FAIL.

- [ ] **Step 3: `_holds`** (after `_prefers`)

```python
    def _holds(self, run):
        """A test for the cards the current plan holds in hand (a Steel card, a King with Baron), or None."""
        engines = [ENGINES[k] for k in self._current_plan(run)] if self.PLAN else []
        if not any(e.name == "held" for e in engines):
            return None
        return lambda c: any(e.holds(run, c) for e in engines)
```

`_holds` is defined in `ValueBot`. `_ranked_discards` and `_measure` live in `SmartBot` and `ValueBot`, so call it
through `getattr(self, "_holds", lambda run: None)(run)`.

- [ ] **Step 4: Discards.** In `_ranked_discards`, after the `if mods:` options block (~line 432):

```python
        holds = getattr(self, "_holds", lambda run: None)(run)
        if holds:                                           # the build plan's held cards stay (spec 4.5); a face-down
            options = {o for o in options                   # card isn't known, so it isn't one
                       if not any(not hand[i].face_down and holds(hand[i]) for i in o)} or options
```

- [ ] **Step 5: `_measure`** (`ValueBot`'s, ~line 853). Add the plan's held cards to the gate:

```python
        boss = run.active_boss
        holds = self._holds(run)
        if (any(j.name in MOD_RULES for j in run.active_jokers())
                or any(not c.face_down and (c.seal in ("Purple", "Blue") or c.enhancement == "Gold") for c in run.hand)
                or (boss is not None and boss.name in TOLL_BOSSES and run.money > 0)
                or (holds is not None and any(not c.face_down and holds(c) for c in run.hand))):
            return Measure(self, run)
        return None
```

- [ ] **Step 6: `play_bonus`** (`balatro/modifiers.py`). Change its return and add the function after `held_forfeit`:

```python
    return (total - held_forfeit(measure, played) - boss_toll(bot, run, result, played)
            - plan_hold_cost(bot, run, played))
```

```python
def plan_hold_cost(bot, run, played) -> float:
    """Playing a card the build plan holds (a Steel card, a King with Baron): PLAN_HOLD for each hand left after this
    one, its held effect gone from them (spec 4.5)."""
    holds = bot._holds(run) if getattr(bot, "PLAN", False) else None
    if holds is None:
        return 0.0
    return bot.PLAN_HOLD * max(0, run.hands_left - 1) * sum(1 for c in played if not c.face_down and holds(c))
```

- [ ] **Step 7: Run the tests**

Run: `python3 -m pytest -q tests/test_engines.py`, then the full suite in the background. Expected: all pass, `exit 0`.

---

### Task 9: Speed, and the user's seeds by hand

**Files:** none changed (checks only). If speed fails, change `PLAN_HANDS` in `balatro/strategy.py`.

- [ ] **Step 1: Seconds per game, plan on and off** (background, logged; ~10 min):

```bash
cd /Users/kvashaihor/Projects/evo/balatro && S=/private/tmp/claude-501/-Users-kvashaihor-Projects-evo/b504cf98-b6a4-4219-bcc8-62e92ceb2bb5/scratchpad
( VALUEBOT_WEIGHTS=hand python3 -u $S/eval_patched.py --bot base --label t-off --seeds 16 --workers 2 ;
  BOT=PLAN=1 VALUEBOT_WEIGHTS=hand python3 -u $S/eval_patched.py --bot base --label t-plan --seeds 16 --workers 2 ) > logs/plan_speed.log 2>&1; echo "exit $?" >> logs/plan_speed.log
```

Watch: `tail -F /Users/kvashaihor/Projects/evo/balatro/logs/plan_speed.log`. Expected: both finish. Compare the
`s a game` figures. If t-plan is more than 2x t-off, set `PLAN_HANDS = 24` and run again. If it is still over 2x,
restrict `_plan_value`'s chance terms to the main engine (spec section 7) and run again.

- [ ] **Step 2: The plan logs make sense.** In `runs/value/eval_t-plan.json`, count the games whose `plan` mentions
`held` or `dna`, and look at three of them by hand. The plan should appear when Baron, Mime or DNA arrive or Steel
Kings build up, and stay put through the next shops.

- [ ] **Step 3: The showcase seeds,** plan off and on. The server's models don't take switches, so run them directly
(background, logged to `logs/plan_showcase.log`, a few minutes):

```bash
cd /Users/kvashaihor/Projects/evo/balatro && VALUEBOT_WEIGHTS=hand python3 -u - > logs/plan_showcase.log 2>&1 <<'EOF'
from balatro.models import make
from balatro.run import Run
for seed, deck in (("E8G18YRT", "Ghost Deck"), ("RZ364T64", "Abandoned Deck"), ("C5X6MXUN", "Abandoned Deck")):
    for plan in (False, True):
        bot = make("value"); bot.PLAN = plan
        res = Run(bot, game_seed=seed, deck=deck, max_ante=16).play()
        print(seed, deck, "PLAN" if plan else "off", "won" if res.won else "lost", "ante", res.ante,
              "best", res.best_hand, getattr(bot, "plan_log", [])[-3:])
EOF
```

Expected: six lines. Note in BACKLOG how far each seed goes, and on E8G18YRT whether DNA is now bought at ante 6.
These are three games, not a measurement.

---

### Task 10: The measurement queue, plan first

**Files:**
- Create: `$S/prio_sweep.sh`, `$S/queue20.sh`, `$S/queue21.sh`
- Modify: the queue chain (queue 17's waiter is replaced; 18 and 19 still wait on "queue 17 exit" and "queue 18
  exit")

Markers use file contents, not deletion (no `rm`): each plan queue has its own `logs/plan_priority_<queue>` holding
`on` or `off` (one queue's `off` can't open a gap while the next waits), and `logs/eval_running` holds `busy` or
`free`.

- [ ] **Step 1: `$S/prio_sweep.sh`** (sweep.sh that yields to the plan between runs)

```zsh
#!/bin/zsh
# prio_sweep.sh BASELINE RNG OUT SPEC...: as sweep.sh, but before each SPEC it waits while any logs/plan_priority_*
# says "on" (a plan measurement waiting for the CPU), and marks logs/eval_running "busy" while a SPEC plays.
set -u
base=$1; rng=$2; out=$3; shift 3
P=/Users/kvashaihor/Projects/evo/balatro
S=/private/tmp/claude-501/-Users-kvashaihor-Projects-evo/b504cf98-b6a4-4219-bcc8-62e92ceb2bb5/scratchpad
for spec in "$@"; do
  while cat $P/logs/plan_priority_*(N) /dev/null | grep -qs on; do sleep 60; done
  label=${spec%%|*}; envs=${spec#*|}
  [ "$envs" = "$spec" ] && envs=""
  echo busy > $P/logs/eval_running
  line=$(env ${=envs} $S/measure.sh $label $base $rng)
  echo free > $P/logs/eval_running
  echo "$(date '+%F %T')  [$envs] $line" >> $out
done
echo "$(date '+%F %T')  sweep done" >> $out
```

`chmod +x $S/prio_sweep.sh`.

- [ ] **Step 2: Re-chain queue 17.** Queue 17 is still waiting for queue 16 (it hasn't started). Stop its waiter (task
`bdjm6ey9f`, a wait loop, not a run) with TaskStop. Then start it again in the background with prio_sweep:

```zsh
cd /Users/kvashaihor/Projects/evo/balatro && S=/private/tmp/claude-501/-Users-kvashaihor-Projects-evo/b504cf98-b6a4-4219-bcc8-62e92ceb2bb5/scratchpad; F=$S/frozen-queue16; now() { date '+%F %T'; }; echo "$(now) queue 17 re-chained: yields to the plan's measurements between runs (prio_sweep.sh)" >> logs/sweep_queue17.log; until grep -q "queue 16 exit" logs/sweep_queue16.log; do sleep 60; done; echo "$(now) queue 16 over: queue 17 starts (after the plan's runs if any are waiting)" >> logs/sweep_queue17.log; SNAPSHOT=$F $S/prio_sweep.sh g-guard 90210 logs/sweep_queue17.log "k-rr15|BOT=REROLL_SHARE=0.15" "k-rr40|BOT=REROLL_SHARE=0.4" "k-sell05|W=sell_margin=0.05" "k-sell20|W=sell_margin=0.2" "k-shop10|W=skip_shop=0.1" "k-shop50|W=skip_shop=0.5" "k-safe10|W=skip_safety=1.0" "k-safe16|W=skip_safety=1.6"; code=$?; echo "$(now) queue 17 exit $code" >> logs/sweep_queue17.log
```

These are the original waiter's eight specs, copied exactly (checked against the session record, 29 Oct).

Re-chain queues 18 and 19 the same way, or one of them could start beside a plan run once queue 17 ends. Stop their
waiters (`be2cp1xtk`: its tests are done, it waits for "queue 17 exit"; `bct5atx9m`: it waits for "queue 18 exit").
Then start them again in the background, each with prio_sweep and its original specs and snapshots:

```zsh
cd /Users/kvashaihor/Projects/evo/balatro && S=/private/tmp/claude-501/-Users-kvashaihor-Projects-evo/b504cf98-b6a4-4219-bcc8-62e92ceb2bb5/scratchpad; F=$S/frozen-queue18; now() { date '+%F %T'; }; echo "$(now) queue 18 re-chained (prio_sweep.sh)" >> logs/sweep_queue18.log; until grep -q "queue 17 exit" logs/sweep_queue17.log; do sleep 60; done; echo "$(now) queue 17 over: queue 18 starts" >> logs/sweep_queue18.log; SNAPSHOT=$F $S/prio_sweep.sh g-guard 90210 logs/sweep_queue18.log "o-odds|BOT=LAST_HAND_ODDS=1"; c1=$?; SNAPSHOT=$F $S/prio_sweep.sh g777-guard 777 logs/sweep_queue18.log "o777-odds|BOT=LAST_HAND_ODDS=1"; c2=$?; echo "$(now) queue 18 exit $((c1 + c2))" >> logs/sweep_queue18.log
```

```zsh
cd /Users/kvashaihor/Projects/evo/balatro && S=/private/tmp/claude-501/-Users-kvashaihor-Projects-evo/b504cf98-b6a4-4219-bcc8-62e92ceb2bb5/scratchpad; F=$S/frozen-queue16; now() { date '+%F %T'; }; echo "$(now) queue 19 re-chained (prio_sweep.sh)" >> logs/sweep_queue19.log; until grep -q "queue 18 exit" logs/sweep_queue18.log; do sleep 60; done; echo "$(now) queue 18 over: queue 19 starts" >> logs/sweep_queue19.log; SNAPSHOT=$F $S/prio_sweep.sh g-guard 90210 logs/sweep_queue19.log "v-seed06|W=vouchers:Seed_Money=0.6" "v-seed12|W=vouchers:Seed_Money=1.2"; code=$?; echo "$(now) queue 19 exit $code" >> logs/sweep_queue19.log
```

`frozen-queue18` already exists (be2cp1xtk froze it after its tests).

- [ ] **Step 3: Queue 20, `POWER_PAIRED`** (once Task 0's full suite passes). `$S/queue20.sh`:

```zsh
#!/bin/zsh
# Queue 20: POWER_PAIRED on both sets against the day's baselines, ahead of queue 17 (logs/plan_priority).
set -u
P=/Users/kvashaihor/Projects/evo/balatro; S=/private/tmp/claude-501/-Users-kvashaihor-Projects-evo/b504cf98-b6a4-4219-bcc8-62e92ceb2bb5/scratchpad
cd $P; now() { date '+%F %T'; }; L=logs/sweep_queue20.log
F=$S/frozen-queue20; mkdir -p $F && rsync -a --exclude __pycache__ balatro data scripts $F/ && for d in runs logs seedfinder; do ln -sfn $P/$d $F/$d; done
echo on > logs/plan_priority_20
echo "$(now) queue 20 (snapshot $F): POWER_PAIRED on set 90210 against g-guard, then set 777 against g777-guard; waits for queue 16" >> $L
until grep -q "queue 16 exit" logs/sweep_queue16.log; do sleep 60; done
while grep -qs busy logs/eval_running; do sleep 60; done
SNAPSHOT=$F $S/sweep.sh g-guard 90210 $L "p-paired|BOT=POWER_PAIRED=1"
SNAPSHOT=$F $S/sweep.sh g777-guard 777 $L "p777-paired|BOT=POWER_PAIRED=1"
code=$?
echo off > logs/plan_priority_20
echo "$(now) queue 20 exit $code" >> $L
```

Run it in the background: `zsh $S/queue20.sh`. Tell the user the ETA (~1.6 h after queue 16 ends) and the watch command
`/Users/kvashaihor/Projects/evo/balatro/scripts/watch_jobs.sh` (it lists every `sweep_queue*.log`).

- [ ] **Step 4: Queue 21, step 1** (once Tasks 1-8 pass the full suite and Task 9's speed is acceptable).
`$S/queue21.sh`:

```zsh
#!/bin/zsh
# Queue 21: the build plan, step 1 (held + dna), on both sets, then depth to ante 16 for both sides; ahead of queue 17.
set -u
P=/Users/kvashaihor/Projects/evo/balatro; S=/private/tmp/claude-501/-Users-kvashaihor-Projects-evo/b504cf98-b6a4-4219-bcc8-62e92ceb2bb5/scratchpad
cd $P; now() { date '+%F %T'; }; L=logs/sweep_queue21.log
F=$S/frozen-queue21; mkdir -p $F && rsync -a --exclude __pycache__ balatro data scripts $F/ && for d in runs logs seedfinder; do ln -sfn $P/$d $F/$d; done
echo on > logs/plan_priority_21
echo "$(now) queue 21 (snapshot $F): PLAN (held, dna) on set 90210 against g-guard and set 777 against g777-guard; then to ante 16, plan off and on; waits for queue 20 and any run in progress" >> $L
until grep -q "queue 20 exit" logs/sweep_queue20.log; do sleep 60; done
while grep -qs busy logs/eval_running; do sleep 60; done
SNAPSHOT=$F $S/sweep.sh g-guard 90210 $L "b-plan|BOT=PLAN=1"
SNAPSHOT=$F $S/sweep.sh g777-guard 777 $L "b777-plan|BOT=PLAN=1"
SNAPSHOT=$F MAXANTE=16 $S/sweep.sh g-guard 90210 $L "d-off16|"
SNAPSHOT=$F MAXANTE=16 $S/sweep.sh d-off16 90210 $L "d-plan16|BOT=PLAN=1"
code=$?
echo off > logs/plan_priority_21
echo "$(now) queue 21 exit $code" >> $L
```

`d-off16`'s comparison line against g-guard is meaningless (different max ante). Read it only as d-off16's own numbers.
The depth result is d-plan16 against d-off16 (progress, and ante reached from the JSONs).

- [ ] **Step 5: Record.** BACKLOG.md (the "Engine planning" entry) and `runs/overnight-20261027.md`: what was built,
the queue order (20, 21, then 17-19), ETAs. Tell the user.

---

## Steps 2-4 (outline; their own plans when step 1 is measured)

- **Step 2, `levels`:** an Engine with `stage="levels"`, no required group, H from the plan (High Card under `held`,
  else the most played hand). Its projection adds H's expected levels (Blue Seal cards held times Mime, Celestial packs
  at their rate, Telescope only when H is the most played hand, Space Joker, Burnt Joker) to `trial.hand_levels`. Its
  consumables are H's Planet and Trance. Hooks: Planet plan worth at `consumable_choice` and the pack picks (never
  inside `planet_worth`: Constellation), Burnt Joker's first discard an H in `_ranked_discards`. Tests: Pluto above
  Uranus under a held plan playing High Card. Measured as queue 2x against b-plan's code, levels on vs off.
- **Step 3, `flush`:** an Engine with the suit group, S from the suit jokers owned or the deck's most common suit,
  projection by the expected suit Tarots on off-suit cards. It doesn't fit the others, so `_plan_after` gains the switch
  rule (another engine counts only if its score with the item beats the main's by `PLAN_SWITCH`). Discards: off-suit
  first. Tests per spec section 8.
- **Step 4, tuning:** sweeps of `PLAN_WEIGHT` (0.5, 2), `PLAN_HORIZON` (1, 3), `PLAN_MIN`, `PLAN_SWITCH`, `PLAN_HOLD`,
  `PLAN_KEEP`, on set 90210 with confirmation on set 777. The scope cuts above, revisited by what the plan logs show.
