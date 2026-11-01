# jokers.json: open questions, conflicts and assumptions

Covers `/Users/kvashaihor/Projects/evo/balatro/data/jokers.json` (150 entries, same order as `jokers_list.tsv`).
Compiled 2026-10-25.

## How the data was built

- **Wiki (primary prose source).** Raw wikitext of all 150 joker pages on balatrowiki.org (`index.php?title=<Name>&action=raw`),
  plus `Jokers`, `Activation_Type`, `Guide:_Activation_Sequence`, `Joker_slot`, `Listed_probability`, `Card_modifiers`
  and `Negative_Effects`. The infobox fields (rarity, buy price, activation type, copyable/eternal/perishable compatibility)
  and the "Update History" sections were checked for every joker.
- **Fandom wiki:** could not be used. `balatrogame.fandom.com` returned Cloudflare 403 to curl and HTTP 402 to WebFetch.
- **Game logic (verification source).** Every number, condition and timing was cross-checked against the Lua logic of
  game version **1.0.1o** (the latest 1.0.1 patch). The copy used is an unofficial decompiled mirror on GitHub
  (`balatro-src/balatro-src-reverse-engineering`, branch `asset-main`). The files read were `game.lua` (P_CENTERS joker
  configs), `card.lua` (`Card:calculate_joker`, `add_to_deck`, `update`, `calculate_dollar_bonus`, `is_face`, `is_suit`),
  `functions/state_events.lua` (`evaluate_play`, discard, end of round), `functions/misc_functions.lua` (poker-hand
  evaluation), `functions/common_events.lua`, `blind.lua` and `functions/button_callbacks.lua`. This mirror is a copy of
  proprietary code. It was used only to verify facts; no code was copied into the JSON.
- **Consistency check.** For all 150 jokers, rarity, cost, `blueprint_compat`, `eternal_compat` and `perishable_compat`
  are identical in the TSV, the wiki infoboxes and the game code. Every gameplay number in the game configs appears in
  the JSON. The only config numbers left out are unlock thresholds, plus one unused leftover (`Burnt Joker config.extra = 4`).
- **Detail level.** 147 entries are `detail_level: "full"`: the wiki and the game code agree, or the code settled
  something the wiki leaves out. 3 entries are `"inferred"`: Chaos the Clown, Mr. Bones and Showman (see below).
- **No `null` sticker flags.** Eternal and perishable compatibility is known for all 150 jokers. Legendaries are flagged
  compatible, as in the code, but they never receive these stickers naturally.

## Field conventions

- `cost`: buy price in $. It is 0 for Legendaries, as requested; `values.internal_cost = 20` and
  `values.sell_value = 10` hold the real numbers.
- `key`: the internal id (e.g. `j_caino` for Canio, `j_selzer` for Seltzer, `j_ring_master` for Showman).
- `timing`: one token or a list of tokens. The requested tokens are used, plus these extras:
  `on_other_joker` (Baseball Card), `on_consumable_used` (Constellation), `on_playing_card_added` (Hologram),
  `on_cards_destroyed` (Glass Joker, Canio), `on_round_start` (Certificate: first hand drawn),
  `on_hand_not_allowed` (Matador's path for a hand that the Boss Blind disallows).
  `on_shop` means end of the shop visit (Perkeo). `on_booster` covers both opening a pack (Hallucination) and
  skipping one (Red Card). `on_sell` covers selling this card (Luchador, Diet Cola, Invisible Joker) and selling
  any card (Campfire).
- `values`: exact numbers. `start_*` / `gain_*` / `*_lost_per_*` / `reset_to` describe scaling. `odds` is written as `"1 in N"`.
- `wiki_activation_type`: the wiki's own category, kept for reference.

## Scoring pipeline as implemented in 1.0.1o (the simulator should follow this order)

1. Press play: `hands_left -= 1`. Then the boss's press-play effects run (The Hook discards 2 random held cards, The Tooth takes $1 per played card).
2. The hand type is evaluated on all played cards. `hands[type].played` and `hands[type].played_this_round` are
   incremented **before** any joker runs, so Supernova, Card Sharp and Obelisk see the current play.
   Stone cards are always added to the scoring cards. With Splash, every played card scores.
3. If the Boss Blind disallows the hand (The Psychic, The Eye, The Mouth): there is no scoring and no
   before-scoring or joker-pass effects. Only Matador's not-allowed-hand path runs. The play counts above still increase.
4. Otherwise, base chips and mult come from the hand level. Then before-scoring jokers run left to right (Space Joker,
   Midas Mask, Vampire, DNA, To Do List, and the scaling of Ride the Bus, Green Joker, Runner, Square Joker, Spare
   Trousers and Obelisk). A Space Joker level-up re-reads the base values. Then The Flint halves the values.
5. Each scoring card, left to right. A debuffed card is skipped entirely (no retriggers) and marks the boss as triggered.
   Otherwise the number of triggers is 1, plus Red Seal retriggers, plus joker retriggers (left to right). Each trigger:
   the card's chips (rank value + bonus + Hiker bonus), its Mult enhancement / Lucky roll, Glass X2, money (Gold Seal $3,
   Lucky 1 in 15 for $20), its edition (Foil +50 chips, Holographic +10 Mult, Polychrome X1.5), then each joker's
   on-scored effect, left to right.
6. Each held card, left to right: Steel X1.5 and other held-card effects, then held-card jokers. A held card is
   retriggered (Red Seal, Mime) only if it produced at least one effect.
7. Joker pass, left to right over the jokers and then the consumables. For each joker: Foil/Holographic bonus,
   then the joker's independent effect, then every joker reacting to it (Baseball Card), then Polychrome X1.5.
   For consumables, Observatory gives X1.5 per Planet card matching the hand.
8. Deck final step (the Plasma deck balances chips and mult).
9. Destroy phase, per scoring card: Sixth Sense, then the Glass break roll (1 in 4, not for debuffed cards). Then
   jokers react to the destroyed cards (Canio, Glass Joker).
10. Score += floor(chips × mult). Then after-scoring jokers run (Ice Cream and Seltzer count down). This step also runs
    for disallowed hands. Last, `G.GAME.hands_played` and `current_round.hands_played` are incremented.

Money timing: `ease_dollars` is deferred during scoring. Vagabond therefore sees money from before the hand. Bull and
Bootstraps add a buffer, so they include money earned earlier in the same hand (Business Card, Gold Seal, Golden Ticket,
To Do List, etc.).

Sell value = max(1, floor(cost/2)) + extra value. The cost includes the edition surcharge (+$2 Foil, +$3 Holographic,
+$5 Polychrome, +$5 Negative), inflation and discounts. A Rental joker costs $1.
Stickers: Perishable jokers are debuffed after 5 rounds. Rental jokers cost $3 at each end of round. Eternal jokers
cannot be sold or destroyed. No joker can be both Eternal and Perishable.

## Top 10 open questions, ranked by impact on simulation

1. **Disallowed hands (The Psychic, The Eye, The Mouth) still tick counters.** In the code, a disallowed hand still
   raises its play counts (Supernova; Card Sharp's `played_this_round`; Obelisk's comparison base) and the run-wide
   hand count that Loyalty Card uses. Ice Cream and Seltzer still count down. Matador pays $8. Nothing scores, and
   Obelisk, Green Joker and the other before-scoring jokers do not run. The wiki documents only part of this
   (Obelisk, plus a visual bug on Loyalty Card). *Assumed: the code's behaviour.*
2. **Mr. Bones when the deck runs out (conflict; marked inferred).** The wiki says Mr. Bones does not save you when
   you run out of cards. But the code's out-of-cards path calls the same `end_round()` that runs the Mr. Bones check,
   possibly more than once in the same state. *Assumed: the wiki is right (no save when the hand and deck are empty).
   The normal "last hand played, at least 25% of the requirement" save is certain.* After a save, the Blind's reward
   money is not paid; interest and other end-of-round money are.
3. **"Contains" semantics for hand-type jokers (resolved from code; critical).** A hand contains a type if any subset
   of the PLAYED cards forms it; scoring status does not matter. Two Pair is contained in Two Pair, Full House and
   Flush House, but **not** in Four or Five of a Kind (rank groups are counted by exact size). Spare Trousers checks
   both Two Pair and Full House. A Flush with repeated ranks also contains Pair or Two Pair, and a Four of a Kind with
   5 same-suit cards contains a Flush. With Four Fingers, a Straight Flush can be built from different 4-card subsets.
4. **Money timing (resolved from code).** Vagabond (≤ $4) checks money from before the hand. Bull and Bootstraps
   include money earned earlier in the same hand. A simulator that updates money immediately will get these wrong.
5. **What Blueprint and Brainstorm copy.** They pass every trigger to their target. The target's own "not when copied"
   guards and its compatibility flag decide what happens. Copied: retriggers, XMult/Mult/Chips, card creation, money on
   triggers, Burglar's hands, Burnt Joker's level, and DNA's copy. Never copied: end-of-round money, passive rule
   changes, scaling increments (only the current value is copied), destruction, and the target's edition.
   **Luchador and Diet Cola are flagged copyable, but the copy only acts when the Blueprint/Brainstorm itself is sold.**
   *Assumed: implement this "sell the copier" behaviour.*
6. **Joker Stencil formula.** The code has two paths. The effective rule is X = (slot limit − jokers owned) + (number
   of Joker Stencils owned), applied when it is above 1. Negative jokers raise the slot limit. Blueprint copies the
   value but takes up a slot and is not a Stencil.
7. **Loyalty Card counter.** It is relative to when this copy was created (Ankh copies keep the counter) and it counts
   every hand in the run, across rounds. It fires when the number of hands already played since creation, taken mod 6,
   is 5: that is the 6th, 12th, ... hand.
8. **Obelisk tie rule.** After counting the current play, Obelisk resets only if this hand type's count is strictly
   greater than every other *visible* hand type's count. Ties keep scaling (+X0.2), and the gain applies to the current hand.
9. **Suit edge cases found in the code that the wiki does not state.** Seeing Double: with Smeared Joker, one scoring
   Spade or Club satisfies it alone. Flower Pot: with Smeared Joker, two red and two black scoring cards suffice;
   debuffed non-Wild cards still count by printed suit, but debuffed Wild cards count for nothing (a 1.0.1 bug).
   Blackboard: a debuffed Wild counts by its printed suit only.
10. **Chaos the Clown and Showman (marked inferred).** The reroll-cost function and the shop-pool code were not read.
    Chaos: assumed free rerolls refresh to (number of Chaos copies) at each round start, a free reroll does not raise
    the next price, and buying it mid-shop gives one immediately. Showman: assumed it only lifts the "already owned"
    duplicate block for jokers, Tarot, Planet and Spectral cards in the shop, packs and generators.

## Other notes per joker (assumptions and code-derived facts the wiki omits)

- **Gros Michel / Cavendish:** Only Gros Michel destroying itself (1 in 6, end of round) sets the extinct flag. After
  that, Cavendish can spawn and Gros Michel never appears again. Selling or destroying it any other way does nothing.
  Cavendish can reappear after its own 1-in-1000 extinction.
- **Ice Cream / Popcorn / Turtle Bean / Seltzer / Ramen lifetimes (exact, from the code):**
  - Ice Cream: 20 hands (100 down to 5 chips).
  - Popcorn: 5 rounds (20, 16, 12, 8, 4 Mult).
  - Turtle Bean: 5 rounds (+5 down to +1 hand size).
  - Seltzer: 10 hands.
  - Ramen: destroyed on the 100th card discarded.
  Each is destroyed when the next decrement would reach 0 (Ramen: X1).
- **Ceremonial Dagger:** gain = 2 × the sell value of the destroyed joker (sell value includes edition surcharge and
  extra value). An Eternal neighbour blocks it completely.
- **Madness:** gains +X0.5 even if nothing can be destroyed. It never acts on Boss Blinds.
- **Raised Fist:** picks the lowest rank (Ace is high). Ties go to the rightmost card. Stone cards are excluded. If the
  chosen card is debuffed it gives +0 and does not fall back to another card. The value is 2 × chip value, so J/Q/K
  give 20 and an Ace gives 22.
- **Hologram triggers (code):** Standard-pack picks, playing cards bought in the shop, DNA, Marble Joker, Certificate,
  Cryptid, Familiar, Grim and Incantation.
- **Glass Joker:** Glass cards destroyed by Spectral cards do not count (a bug). Shattering in play, Sixth Sense,
  Trading Card and The Hanged Man do count.
- **Canio:** counts face cards destroyed by any route, including Spectral cards (Familiar, Grim, Incantation, Immolate).
  Debuffed faces do not count (they are not faces for jokers). With Pareidolia every card is a face.
- **Swashbuckler / Abstract Joker / Baseball Card:** debuffed jokers still count (wiki "Negative Effects" page and the
  code agree).
- **Mail-In Rebate, Castle, The Idol:** the target is copied from a uniformly random non-Stone card in the full deck,
  so it is weighted by deck composition and can repeat. It is rolled at run start and at every end of round, and all
  copies share it. **Ancient Joker:** uniform among the 3 other suits (all 4 at run start). **To Do List:** uniform
  among visible hands other than the current target; each copy rolls independently; secret hands become eligible only
  after they have been played.
- **Discard-trigger jokers and The Hook:** The Hook's forced discards do trigger Green Joker (−1), Ramen, Yorick,
  Castle, Mail-In Rebate and Hit the Road. Faceless Joker also checks them, but The Hook discards only 2 cards, so it
  can never reach 3 faces. They do not trigger Burnt Joker and do not count as used discards (Delayed Gratification,
  Trading Card).
- **Hit the Road:** only real Jacks count (Pareidolia does not help); debuffed Jacks are excluded. It resets every round.
- **Campfire:** resets at the end of any Boss Blind round where its multiplier is above X1. *Inferred: this includes a
  boss round survived through Mr. Bones.*
- **Rocket:** the +$2 is added at the end of the Boss round, before that round's payout.
- **Invisible Joker:** the copy is made only if (jokers owned, including the Invisible being sold) ≤ slot limit. The
  wiki's Negative-Invisible slot-overflow edge case is not modelled.
- **Riff-Raff:** the sticker behaviour (no Eternal, Perishable or Rental except in challenges) comes from the wiki only.
- **Credit Card:** the bankruptcy threshold is lowered by $20 per copy. *Inferred: a purchase is allowed while
  money − price ≥ −20 (the shop code was not read).*
- **Hand-size jokers acquired mid-round** (Stuntman, Juggler, Turtle Bean, Merry Andy, Troubadour): the hand limit
  changes immediately, but no cards are discarded. Troubadour's −1 hand and Merry Andy's discards follow the wiki's
  timing notes.
- **Matador:** The Arm triggers it only if the hand's level is at least 2. The Ox triggers it when the most-played hand
  is played; money is set to $0 first, then Matador pays. A debuffed card must be among the scoring cards.
- **Sixth Sense:** the 6 is destroyed even when there is no consumable slot (code). Only the Spectral card needs room.
- **Burnt Joker:** `config.extra = 4` is an unused leftover from its old effect; it levels up by exactly 1.
- **Unlock conditions are not included.** The simulator is assumed to have every joker unlocked.
- **Probability scaling:** each Oops! All 6s doubles the probability numerator (2 copies give ×4). A chance is
  `rand < numerator / N`, so it is capped at certainty.
