# Open questions, conflicts, gaps and assumptions

This file covers the non-joker rules data in `/Users/kvashaihor/Projects/evo/balatro/data/`. It does not cover `jokers.json`, which another researcher owns. Sources were fetched on 2026-10-25 for game version 1.0.1o-FULL (see `SOURCES.md`).

- **[INFERRED]** means the claim comes from my reading of the game's evaluation code. It is either reproduced by the Balatro-Simulation mod or recalled from the game's Lua source. No fetched wiki page states it.
- **Ranking:** items are listed roughly by how much they can change simulated outcomes.

## Top 10 (most important for the simulator)

### 1. The Flint and "before" jokers: which comes first?
- **Wiki:** Guide: Activation Sequence lists "Boss blind effects (The Flint, The Arm)" as step 1, before on-played jokers.
- **Simulation mod (and the game code as I recall it):** The Arm (level −1) runs first. Then the before-jokers run. Then base chips/mult are re-read from the hand level. Then Flint halves them.
- **Chosen:** the mod/code order.
- **When it matters:** only when a before-joker changes the hand level on a Flint round (Space Joker). The two orders then give different base values.

### 2. Do held-in-hand retriggers fire on a card that did nothing? [INFERRED]
- **Chosen:** a held card is retriggered (Red Seal, Mime) only if its first activation produced at least one effect. The code condition is `next(effects[1]) or #effects > 1`.
- **Effect:** with Reserved Parking, a face card whose first 1-in-2 roll failed is not re-rolled by Mime. The expected money is therefore lower than a naive "roll once per trigger" model.
- **Scoring effects** (Steel, Baron, Shoot the Moon) are unaffected, because they always produce an effect.

### 3. Ectoplasm hand-size cost
- **In-game text:** "−1 hand size".
- **Wiki:** the cost grows with use. The n-th Ectoplasm of a run costs −n, so three uses cost −6 in total.
- **Chosen:** the wiki's escalating value (`consumables.json`).
- **Status:** not verified against the code.

### 4. The Ox: ties for "most played hand"
- **Wiki:** the hand is fixed at ante start, and ties are broken randomly. The wiki tags this `{{verify}}` and notes it depends on Lua `pairs()` order.
- **Simulator:** pick uniformly among the tied hands, or treat the tie as unknown.

### 5. Boss selection details
- **Implemented:** the wiki rule. Bosses are eligible when `min_ante <= max(1, ante)`. Only Showdown bosses appear on multiples of 8. The pick is uniform among the least-used eligible bosses, and rerolls count as uses.
- **[INFERRED]** The game data also contains a boss "max" ante field (for example The Ox: min 6, max 10). As far as I know it is unused by selection. The wiki does not mention it.

### 6. Endless ante rounding
- **Wiki text:** the requirement is "rounded to two significant digits".
- **Wiki table:** shows truncation (floor). For example, ante 9 White: raw 115,405 → 110,000, not 120,000.
- **Chosen:** truncation. My Python formula reproduces the wiki table exactly for antes 9–12 at all three stake scalings.
- **Ante 13 and up:** I copied the wiki's two-significant-figure table (`blinds.json` `full_table_antes_0_to_39`) rather than trust float precision.

### 7. Order inside one scored-card activation
- **Chosen:** rank+enhancement chips → enhancement mult (Mult, Lucky) → Gold Seal / Lucky money → Glass x2 → edition (Foil, then Holo, then Poly) → on-scored jokers left to right.
- **Consequence:** a Holographic Glass card gives (mult x2) + 10, not (mult + 10) x2.
- **Agreement:**
  - The wiki ("enhancement, then seal, then edition") agrees.
  - The simulation mod agrees.
- **[INFERRED]** Within a single joker's result, the order is +chips, +mult, money, then xmult. In the joker pass it is +mult, +chips, then xmult. Vanilla jokers rarely return more than one kind, so this rarely matters.

### 8. Selection counts for tarots
- **In-game/wiki text:** "Enhances 2 selected cards".
- **Chosen:** "up to N, minimum 1" for Magician, Empress, Hierophant, Strength, Hanged Man, and the Star/Moon/Sun/World (up to 3). Death needs exactly 2.
- **Status:** low risk, but not stated on a fetched page.

### 9. Probability rules
- **"1 in N" listed probabilities:** they scale with Oops! All 6s (numerator x2 per copy). This covers Lucky, Glass break, Wheel of Fortune and The Wheel boss.
- **Not listed probabilities:** shop weights, edition rolls, sticker rolls, pack weights, The Soul / Black Hole 0.3% and Omen Globe 20%. Oops! All 6s does not change these.
- **[INFERRED]** A debuffed Glass card never breaks. A retriggered Glass card still rolls only once.

### 10. Version risk
- All data is for 1.0.1o-FULL (24 Feb 2025), the wiki's "current version" as of 2026-10-25.
- If a later balance patch (for example a 1.1 update) is released, the most likely changes are boss blinds, vouchers, pack weights and tags.
- The `update history` sections of the cited pages are the place to re-check.

## Other conflicts, gaps and assumptions

### Wiki errors and inconsistencies
- **Wiki data errors (ignored):**
  - The Planet Merchant infobox lists `previous = Planet Tycoon`. This is a wiki error; Planet Merchant is the base voucher.
  - The Hierophant infobox has `number = 7`, which collides with The Lovers. The Hierophant is #6 in the collection.
- **Blue Seal page:** it says "max 2 planets per round (3 with Crystal Ball)". That is just the consumable-slot limit; this data uses "needs room".

### Not stated by any fetched page
- **Reroll cost after a D6 Tag [INFERRED]:** the costs go $0, $1, $2, … The wiki only says rerolls "start at $0".
- **Rarity and per-variant pack weights [INFERRED]:**
  - Rarity roll thresholds: r > 0.95 Rare, r > 0.7 Uncommon. These match the wiki's 70/25/5.
  - The per-art-variant split of the pack weights is from memory. The per-kind totals match the wiki exactly (Normal 4 / Jumbo 2 / Mega 0.5 …).
- **Price formula:** `floor((base + edition + 0.5) * (100 - discount)/100)`, minimum $1. Recalled from `Card:set_cost` and consistent with the wiki ("round half down", examples checked).
  - The wiki's simplified line `buy_cost = (base_cost + edition_cost) * discount_percent` omits the rounding.
- **Default fallback cards for exhausted pools:**
  - Tarot → Strength, Planet → Pluto, Spectral → Incantation: from the wiki.
  - Joker → "Joker", Voucher → Blank: from the wiki (Wraith/Soul pages, the Vouchers page).
- **"After"-hand joker effects [INFERRED]:** these (Ice Cream decay, Seltzer/Popcorn counters) are placed after the Glass-break pass.

### Shop and pack rules
- **Illusion:**
  - In 1.0.1o it never adds seals, despite its text (wiki).
  - Its edition chances (20%; Poly/Holo/Foil 15/35/50) are not affected by Hone or Glow Up.
  - If a patch fixes the seal bug, `shop.json` `card_slot_weights.playing_cards` needs updating.
- **First shop's guaranteed normal Buffoon Pack:** taken from the wiki. The Jokerless challenge is excluded, which does not matter outside challenges.
- **Voucher persistence:**
  - The shop voucher is rolled once per ante and is not replaced after purchase until the next ante.
  - A Voucher-Tag extra voucher exists for one shop only.
  - The exact moment of the roll (ante start vs. first shop) is not stated. It is irrelevant except for Hieroglyph edge cases.
- **Standard pack seal types and enhancements:**
  - Seal types are uniform, 5% each of the 20% seal chance. The wiki says "evenly distributed".
  - Stone is included in the 8 possible enhancements there. The Familiar/Grim/Incantation pages explicitly exclude Stone only for those spectrals.
- **Telescope tie-break:** the higher-tier hand wins (wiki).

### Boss behaviour
- **Crimson Heart:** the joker disabled on the winning hand stays disabled until the next shop. It therefore misses end-of-round payouts (wiki).
- **The Hook:**
  - It discards when Play is pressed, before scoring.
  - Discard-triggered jokers fire for those cards (simulation mod).
  - Whether a Purple Seal discarded by The Hook creates a Tarot is not stated. [INFERRED: yes, it is a discard.]

### Run setup and economy
- **Stickers:**
  - They only appear on shop and Buffoon-pack jokers.
  - One roll decides Eternal vs. Perishable (30/30/40); Rental is rolled independently (30%).
  - The exclusivity and roll ranges come from my reading of the code. They match the wiki's "Eternal 30%, Perishable 30%, never both, 40% clean".
- **Interest timing:** interest is computed on money held before the cash-out payouts (wiki Interest page). Gold Cards and in-round money count; Golden Joker/Rocket-style cash-out money does not.
- **Erratic Deck:** each card is a uniformly random one of the 52 rank/suit combinations, so duplicates are possible. The wiki shows only distribution charts.
- **Hand-size, hands and discards floors:**
  - A round always starts with at least 1 hand.
  - Hand size ≤ 0 at blind start is a loss.
  - Discards can be 0 (The Water). No explicit floor was found for the discard count itself.
- **Not covered here:**
  - Challenge decks.
  - Unlock conditions, beyond noting that upgraded vouchers need their base voucher.
  - Seeds and RNG streams (the game uses per-purpose seeded streams such as `'boss'`, `'rarity'..ante`, `'cdt'..ante`, which are not needed for a stochastic simulator).
  - Profile-level unlocks (assume everything is unlocked).

## Hand-off to the jokers researcher

The scoring order needs per-joker timing classes. The wiki's "Activation Type" groups are: on played (before), on scored (individual/play), on held (individual/hand), independent (joker_main), on other jokers, on discard, end of round, on blind select, and passive. Spawn conditions also matter (for example, enhancement-based jokers need that enhancement in the deck; Gros Michel → Cavendish).

`modifiers.json` already lists the Eternal- and Perishable-incompatible jokers taken from `Module:Jokers/data`:
- 11 jokers cannot be Eternal.
- 18 jokers cannot be Perishable.
