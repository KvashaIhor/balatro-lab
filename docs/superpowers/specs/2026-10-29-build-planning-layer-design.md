# A build planning layer for the value bot

Date: 2026-10-29. Status: design approved by the user (four parts, 29 Oct 10:45-11:00); revised after three spec
reviews (the third approved it, with clarifications now in) and the voucher check (power's unpaired sample hands).

## 1. Why

The value bot (`balatro/strategy.py`, `ValueBot`) values every shop item, pack pick, Tarot use, Planet and discard
by the change it makes to today's power: the mean log of the best score over sample hands drawn from today's deck,
with today's jokers and levels. An engine that needs several pieces never looks worth building, because each piece
is worth little alone.

The user's run E8G18YRT (Ghost Deck, White Stake, on their phone) reached ante 14 with such an engine:

- DNA, with Brainstorm copying it, on one-card first hands: Kings copied into the deck every round.
- Steel Kings with Red Seals held in hand, Mime retriggering them: each held King X1.5 three times.
- Steel Queens with Blue Seals held at the round's end, Mime doubling them: Plutos every round, High Card at level
  75 (played 54 times).
- Cavendish, Baseball Card.

The bot on the same seed (`balatro/gameseed.py` gives it the game's own deck order, shops, rerolls and packs) dies
at ante 6 with Wee Joker, Satellite, Mime, Jolly Joker and Card Sharp (`logs/user_run_worths.log`):

- DNA ($8, ante 6) valued below every joker it owned: not even among the options worth anything.
- Pluto worth 0 in six Celestial packs and shops: the bot never plays High Card.
- The Chariot and Mime only at ante 6, each for what it adds to today's build.

Earlier work (BACKLOG, "A build layer"): `TARGET` valued shop items as if one chosen hand had 3 more levels. It did
little, because nothing else steered toward the target: discards, Tarots, Planets and rerolls stayed as they were.

Guides agree on the engines (sources in the BACKLOG entry): Baron and Mime on red-sealed Steel Kings is one of the
few builds that reaches ante 12; Steel and Red Seal cards also come from Standard packs; DNA is strongest on High
Card first hands with Steel or sealed cards; Blue Seals with Mime into Plutos is the High Card route; Flush needs
suit Tarots, The Lovers' Wild cards and off-suit discards. One reported run found Baron at ante 6 and Mime at ante
8: pieces arrive late, so a plan has to hold through long gaps.

## 2. Goal and how it is judged

The bot builds toward engines: it chooses the engines the run can most likely complete, values every decision by
what it adds to them, and steers its plays, discards, Tarots, Planets, pack picks, rerolls and sells toward them.

Judged on both, and kept for what works best (the user's call):

- Beat ante 8: 480 paired seeds on set 90210 against the current baseline, confirmed on set 777 (the protocol).
- Depth: the same seeds played on to ante 16, compared by the ante reached and progress.

## 3. Constraints

- No peeking: the bot never reads the seed's future (`run.seedrng`, the draw pile's order, future shops). Every
  probability comes from the pool rates (`data/shop.json`, spawn conditions included), rarities, the run's own
  reroll rate and the number of shops ahead. Checked by a test (section 8).
- Off by default: a master switch `PLAN = False` and one boolean per engine (`PLAN_HELD`, `PLAN_DNA`,
  `PLAN_LEVELS`, `PLAN_FLUSH`, all True so `PLAN` alone turns on every engine written so far; a step's measurement
  sets the others False). The eval harness (`eval_patched.py`, in the session scratchpad) passes booleans as
  `BOT=PLAN=1,PLAN_FLUSH=0`.
- One change at a time: each step of section 10 is measured alone.

## 4. Architecture

### 4.1 `balatro/engines.py` (new)

An engine is data plus a few small functions. The module does not import `strategy.py`. The bot passes itself in
where an engine needs `power`, `deck_change_worth`, `level_worth` or a trial run.

| Part | What it is |
|---|---|
| `name`, `fits` | the engine's key, and the engines it combines with |
| `required` | one any-of group of jokers (or none): the engine needs one of them (5.1-5.4) |
| `support` | jokers, vouchers and consumables that add to it but aren't needed |
| `cards` | the card changes it wants (enhancement, seal, rank, suit) and the consumables that make them |
| `progress(run) -> float` | 0 to 1, as each engine defines it (5.1-5.4) |
| `project(bot, run, trial)` | applies its expected card changes and levels over the horizon to `trial` (section 6) |
| `steer` | the play pattern: cards to hold, discard preference, preferred Tarot targets, the hand type for Planets |

### 4.2 The plan's value: one joint projection, each chance applied once

A plan is a set of engines that fit together, with a main one. Its value in a run state S:

```
R(S)        = a trial copy of S (seedrng None) to which the plan's engines apply their expected changes over the
              horizon in a fixed order: card changes, then levels, then DNA's copies (so DNA copies the projected
              Steel Kings)
V(plan, S)  = value(R(S)) + sum over the plan's missing groups g of P(g) * (value(R_g(S)) - value(R(S)))
R_g(S)      = the projection redone with g's best joker owned (so a missing DNA adds its copies, a missing Mime
              doubles the Blue Seal Planets)
```

- `value(R)` = `power` on today's deck with R's jokers and levels, plus `deck_change_worth` from today's deck to R's
  deck under those jokers and levels. `power` never runs on the projected deck: a card added (a DNA copy, a
  Standard pack's King) changes the deck's size and with it power's sample key (strategy.py:1002), so options
  would no longer meet the same hands.
- `power` here uses `PLAN_HANDS` sample hands (36: projected engine cards are few, and 12 hands rarely hold them),
  with its own sample key and cache per hand count (power's cache key, `_mean_log`'s divisor `self.HANDS` and
  `deck_change_worth`'s `self._idx` all assume 12 today), so 12- and 36-hand values never overwrite each other.
  Hand-size changes use paired positions (`POWER_PAIRED`, step 0).
- `P(g)`: the chance one joker of group g arrives within the horizon (section 6). It appears only here. There is
  no other completion factor.
- "g's best joker": the group's joker that adds most. With a free joker slot it is added; with the row full, it goes
  in for the joker of least worth outside the plan, or, when every slot holds a plan piece, the plan piece of least
  plan worth.

### 4.3 Choosing the plan

- Each engine's score: `V({e}, S) - power(S)`, with the engine alone.
- There is a plan only when the best score is above `PLAN_MIN` (0 to start: engine scores over 2 antes run
  ~0.02-0.03, measured in the plan review; step 4's sweeps set it). The main engine is the best score. It changes only when another's score exceeds the main's by
  `PLAN_SWITCH` times the main's score (0.25 to start), so the bot doesn't flip-flop. When the main's score drops to
  `PLAN_MIN` or below, the plan is dropped and chosen afresh.
- The plan is the main engine, plus every engine that fits it and has progress above 0.
- Chosen once per decision point (shop, pack, round start), cached on the run state like `power`.

### 4.4 Plan worth

```
plan_worth(X) = PLAN_WEIGHT * (V(plan', S with X) - V(plan, S))
```

- "S with X": the run as the decision would leave it: a joker added (with the row full, in for the joker of least
  worth outside the plan, or, when every slot holds a plan piece, the plan piece of least plan worth); a card
  change on its own targets; a level for a Planet; a card added; X sold. A Tarot or Spectral bought or held to keep
  (no targets yet): the use on a preferred target in the deck, times `PLAN_KEEP` (4.5), the shop's route to The
  Chariot, Deja Vu and Trance.
- A joker that fills a missing group makes that group owned: its expectation term becomes the real thing.
- `plan'` is the plan as X leaves it: the same plan, or with the engine X would start when X belongs to the group of
  an engine not in the plan that fits the main one (DNA starts `dna`; with nothing in the plan yet, any engine).
  Without this, no first piece of an engine could look worth buying. An engine that doesn't fit the main one counts
  only if, with X, its score would beat the main's by `PLAN_SWITCH`; then `plan'` is the new plan.
- `plan_worth` is added to today's worth, which is unchanged, at these call sites:
  - joker worths in `shop_action` and `pack_action`;
  - `owned_worth` (sells and swaps: a plan piece's sale loses its plan worth, so the bot doesn't sell Baron). Through
    `owned_worth` it also reaches `havoc` (Madness, Ceremonial Dagger), `jev.py`'s hints and the tag rule at
    strategy.py:1997: a plan piece destroyed counts as lost there too, as it should;
  - `consumable_choice`, per use, on that use's own targets; and the keep option (4.5);
  - keep worth (`keep_worth`); `voucher_worth`;
  - playing cards: `pack_action`'s Card branch and shop playing cards (a Steel King or Red Seal card from a
    Standard pack is a card added to the projection);
  - Planets at the call sites (`consumable_choice`, pack picks), not inside `planet_worth`: Constellation, a
    `levels` support piece, makes `planet_worth` return None and the worth go through `effect_worth`;
  - pack buys (4.5).

### 4.5 Steering, through the existing decisions

| Decision | Where | Change under the plan |
|---|---|---|
| Joker, voucher and consumable buys | `shop_action`, `pack_action` | worths include `plan_worth` |
| Sells and swaps | `owned_worth` | a plan piece's sale counts its plan worth lost |
| Playing cards | `pack_action` Card branch, shop cards | each card's `plan_worth` as a card added |
| Packs bought | `shop_action` (pack offers) | plus, for each plan piece the pack can hold, its chance in the pack times its `plan_worth`: The Chariot or Strength in an Arcana pack, H's Planet in a Celestial pack, Deja Vu or Trance in a Spectral pack, a Steel card or Red Seal in a Standard pack |
| Rerolls | `_reroll_hope` | plus the chance a missing group's joker shows in a reroll times its `plan_worth` |
| Tarot and Spectral targets | `_uses`, `consumable_choice` | `_uses` also offers the engine's preferred targets (Kings for The Chariot and Deja Vu, off-suit cards for suit Tarots); each use's plan worth is measured on its own targets |
| Keeping a Tarot for a better target | `consumable_choice`'s keep option | when the hand holds no preferred target and the deck does: the plan worth of the use on a preferred target in the deck, times `PLAN_KEEP` (0.8: it may not come in time). So The Chariot waits for a King instead of going on an Ace |
| Planets | `consumable_choice`, pack picks | each Planet's plan worth (the plan's hand type in the projection) |
| Discards | `_discard` | held-engine cards never discarded; off-suit cards first for Flush; with Burnt Joker in a `levels` plan, the round's first discard is an H |
| Plays | `play_bonus` | a cost for playing a held-engine card: its held effect lost for the rest of the round (`PLAN_HOLD`). `_measure` returns a Measure when a plan with held cards is on, so `play_bonus` runs |

DNA's one-card play already exists (`_dna_play`, `_copy_plan`). The plan changes how DNA is valued, not how it is
played.

## 5. The four engines

**Revision, 29 Oct 18:50 (the user: "DNA is more of a deckbuilding tool than strategy").** The library has two
kinds. *Strategies* (held, levels, flush) win rounds: they are scored (4.3), and the main engine is always one. *Tools*
(DNA first; later Cryptid, Death, The Hanged Man, Trading Card, Strength, Sigil, Ouija) shape the deck toward
whichever strategy is main: no score of their own, never the main engine, never starting a plan alone; a tool joins
the plan when it is owned or the main strategy has a card for it to work on. Each strategy names its *key card*, the
card a tool copies: held, a Steel Red Seal King (then a Steel King, a Red Seal King, a Steel card, a King); levels, a
Blue Seal card; flush, the best card of its suit. With no such card, a tool adds nothing to the plan (its own worth
today still counts). Progress counts what the run has added, not what every deck starts with (the starting Kings).

### 5.1 Held Steel / Kings (`held`)

- Required group: {Baron, Mime, Shoot the Moon, Steel Joker}.
- Support: the other three; Blueprint or Brainstorm copying one of them; hand size (Paint Brush, Palette,
  Juggler, Turtle Bean); Raised Fist.
- Cards: Steel (The Chariot), Red Seals (Deja Vu), Kings (Strength on Queens), held cards from Standard packs.
- Progress: half for the group owned; half for the deck's engine cards against 6 (Steel cards and Kings, a Steel
  King counting twice).
- Projection: the expected Chariots and Deja Vus over the horizon on Kings, Steel first.
- Steering: hold Steel cards and Kings; win with the cheapest hand from the other cards; never discard them; The
  Chariot and Deja Vu on Kings first.
- Fits: `dna`, `levels` (with High Card or Pair as its hand).

### 5.2 DNA / one-card (`dna`, a tool since the revision above)

- Required group: {DNA}.
- Support: Blueprint or Brainstorm placed to copy DNA, Hanging Chad.
- Cards: the main strategy's key card (step 1 used a fixed stand-in, `_copy_rank`).
- Progress: DNA owned (step 1: half for DNA owned, half for 2 cards worth copying).
- Projection: that card copied once a round for each time DNA fires (`copy_fires`) over the horizon, applied last
  (4.2's fixed order), whichever engine is the main one.
- Steering: as today (`_dna_play`).
- Fits: `held`, `levels`.

### 5.3 Level one hand with Planets (`levels`)

- Required group: none (the Planets are the engine). In a plan only while another engine fits it, or H's level
  leads the next hand's by 3 or more.
- H: the hand the plan plays (High Card for `held`; otherwise the most played hand).
- Support: Space Joker, Burnt Joker, Constellation, Satellite; Telescope and Observatory; Black Hole; Certificate.
- Cards: Blue Seals (Trance) held at the round's end, doubled by Mime.
- Progress: half for H's lead over the next hand against 3 levels; half for Blue Seal cards against 2.
- Projection: H's level plus the expected levels over the horizon: Blue Seal Planets a round times Mime; Celestial
  packs at their rate (with Telescope, H's Planet is certain only when H is the most played hand, as Telescope
  gives the most played hand's); Space Joker; Burnt Joker.
- Steering: H's Planet first in Celestial packs; Blue Seal cards held at the round's end (already in
  `held_forfeit`); with Burnt Joker, the round's first discard is an H (4.5).
- Fits: `held`, `dna`.

### 5.4 Flush (`flush`)

- Required group: {Greedy Joker, Lusty Joker, Wrathful Joker, Gluttonous Joker, The Tribe, Droll Joker, Crafty
  Joker, Bloodstone, Arrowhead, Onyx Agate, Rough Gem}.
- Support: Smeared Joker, Four Fingers; Jupiter.
- Suit S: the suit of the suit jokers owned, else the deck's most common.
- Cards: S (suit Tarots: The Star, The Moon, The Sun, The World; Sigil; The Lovers' Wild cards); off-suit cards
  cut (The Hanged Man, Immolate).
- Progress: half for the group owned; half for the deck's share of S against 60% (S and its pair with Smeared
  Joker).
- Projection: the expected suit Tarots over the horizon turning off-suit cards to S.
- Steering: discard off-suit cards first; suit Tarots on off-suit cards; Jupiter first in Celestial packs.
- Fits: none of the three above (it plays five cards of a suit).

## 6. Projection: the odds, never the future

- Horizon: `PLAN_HORIZON` antes ahead (2 to start), about 3 shops an ante (fewer when the bot skips).
- Cards seen in a shop: its card slots, plus 2 a reroll at the run's own reroll rate so far (the bot rerolls 4-7
  times in a rich shop), plus Buffoon pack cards at the rate the bot buys them.
- A named joker of rarity r per card seen: the joker share of a slot times r's share, divided by the jokers of
  rarity r not owned and able to appear (spawn conditions from `data/shop.json`, such as Steel Joker needing Steel
  cards in the deck); about 0.0028 for a named Uncommon. A group: the sum over its jokers. Over the horizon:
  `P(g) = 1 - (1 - q)^cards`.
- Consumables (The Chariot, Strength, Deja Vu, Trance, suit Tarots, H's Planet): the same from the shop's
  consumable slots (Tarot, Planet, and Spectral on the Ghost Deck) and the Arcana, Celestial, Spectral and Standard
  packs at their rates.
- The projection R holds the owned pieces, card changes at their expected count rounded down (2.6 Chariots: 2
  Steel Kings), and levels at their expected count. Jokers the run doesn't own enter only through 4.2's expectation
  term.
- Nothing here calls `run.seedrng` or reads the draw pile's order. Every trial the projection makes has
  `seedrng = None`, as `effect_worth` does (strategy.py:1505).

## 7. Cost

Each decision with a plan adds a projection (a trial copy and its card changes) and its values: `power` on
`PLAN_HANDS` hands, `deck_change_worth`, `level_worth`, for S and for each option. Values are cached per (plan, run
state) like `power`'s own cache. Watched as seconds per game (eval JSON `seconds_per_game`). If it more than
doubles: `PLAN_HANDS` down to 24, then only the main engine's missing group in the expectation term.

## 8. Testing

`tests/test_engines.py`, on runs built by hand (the style of `tests/test_strategy.py`):

- `progress` counts the right things for each engine. `project` applies the right card changes and levels to the
  trial, DNA after the held engine's, and leaves the real run unchanged.
- Plan worth ranks things right:
  - With Baron and Mime owned and Steel Red Seal Kings in the deck, DNA above Wee Joker.
  - The rule for an engine an item would start: a plain deck with no engine above `PLAN_MIN`, so no plan: Baron
    offered starts `held` and its plan worth is positive; with a `flush` plan, Baron's plan worth is 0 unless `held` would beat `flush` by
    `PLAN_SWITCH`.
  - Pluto above Uranus when the plan plays High Card.
  - The Chariot's use on a King above the same use on an Ace; with an Ace and no King in hand and Kings in the
    deck, The Chariot kept.
  - A Standard pack's Steel King picked over a plain 5.
  - A Flush discard throws off-suit cards.
  - Baron's sale under a `held` plan worth less than with `PLAN` off.
- Each chance counted once: with one missing group of P = 0.5, V lies halfway between the projection without the
  group's joker and with it.
- No peeking: the real run's `seedrng` wrapped in a recorder while the plan worths are computed: no call recorded;
  the draw pile shuffled first: the same plan worths.
- `POWER_PAIRED`: with hand size n and n+1, the n-card sample hands are the first n cards of the n+1-card ones;
  `_reach_bonus` and `deck_change_worth` read the n-card slice.
- With `PLAN` off, every existing test passes unchanged (667 today).

## 9. Measurement

- `PLAN` on against off: 480 seeds on set 90210 against the baseline of the day (queue 16's g-guard), then set 777
  against g777-guard. Step by step (section 10), each step's engines on and the rest off.
- Depth: both sides played on to ante 16 (eval_value gains `--max-ante`; eval_patched passes it), compared by the
  ante reached and progress.
- A plan log per game in the eval JSON (`plan`: ante, the plan, each engine's progress and score at each change).
  An engine counts as finished when its group is owned and its progress is at least 0.75. The watch script shows
  engine frequency, finish rate and win rate by engine.
- Showcase seeds, checked by hand in the run viewer: E8G18YRT (Ghost Deck), RZ364T64 and C5X6MXUN (Abandoned Deck).
- Queue: step 0 and step 1 go ahead of queues 17-19, which move back (the user's call).

## 10. Order of work

Each step is built, tested and measured before the next:

0. `POWER_PAIRED` (a correctness fix found by the voucher check, 29 Oct): power's sample positions drawn once for a
   fixed ceiling (the largest hand size plus `EXTRA` the run can have: 16 cards, capped at the deck's size),
   smaller hands taking the first n of each, so options that change the hand size (Paint Brush, Palette, Juggler,
   Turtle Bean...) compare on the same hands. Adopted if level.
1. The framework (`engines.py`, the joint projection, plan choice, `plan_worth`, the steering hooks), with `held`
   and `dna`: the core of the user's run.
2. `levels`.
3. `flush`.
4. All together; sweeps of `PLAN_WEIGHT`, `PLAN_HORIZON`, `PLAN_MIN`, `PLAN_SWITCH`, `PLAN_HOLD`, `PLAN_KEEP`.

## 11. Data track: playthroughs (its own plan)

Independent of the bot work above, planned and run on its own:

- First, text sources (the Balatro wiki, build guides) for each engine's pieces and the order players get them.
- Then a short list of strong YouTube runs (title, channel, length, size) for the user's approval. Nothing is
  downloaded before the user approves each one. Downloads go in their own folder and are treated as untrusted.
- From approved videos: frames around each shop and pack, read for what was bought and when, into
  `data/engines_observed.json`. Like the earlier footage, the video and what is derived from it stay local and are
  never published.
- Uses: each engine's pieces and their order, the ante by which each engine is usually set up, and engines to add
  after these four.

## 12. Not in scope

- Engines beyond the four (added after, from the data track).
- Lookahead over sampled futures (approach B): may later replace an engine's projection.
- Anything that reads the seed's future, and the Seed Planner (it plans with known shops; this layer must not).
- Changes to in-round play beyond the hooks in 4.5.
- The voucher check's other proposals (`VOUCHER_SCALE`, `VOUCHERS_MEASURED`): queued separately (BACKLOG).

## 13. Risks

- Over-commitment: the bot gives up today's strength for an engine that doesn't arrive and dies early. Mitigated by
  the expectation term (missing jokers count at their chance), `PLAN_WEIGHT`, and the ante-8 gate.
- Cost: see section 7.
- Misjudged odds: a wrong rate makes an engine look closer than it is. The no-peeking test catches leaks, not bad
  rates. The per-game plan log shows how often a chosen engine finishes.
