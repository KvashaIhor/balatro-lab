# Balatro hand scoring order (rules for the simulator)

- **Source:** balatrowiki.org pages [Guide: Activation Sequence](https://balatrowiki.org/w/Guide:_Activation_Sequence) (the "Scoring" page redirects there), [Card modifiers](https://balatrowiki.org/w/Card_modifiers), [Jokers](https://balatrowiki.org/w/Jokers) (definition of "Retrigger"; the "Retrigger" page redirects there), [Activation Type](https://balatrowiki.org/w/Activation_Type), [Chips](https://balatrowiki.org/w/Chips), [Mult](https://balatrowiki.org/w/Mult), [Glass cards](https://balatrowiki.org/w/Glass_cards), [Lucky cards](https://balatrowiki.org/w/Lucky_cards), [Steel cards](https://balatrowiki.org/w/Steel_cards), [Stone cards](https://balatrowiki.org/w/Stone_cards), [Gold Seal](https://balatrowiki.org/w/Gold_Seal), [Red Seal](https://balatrowiki.org/w/Red_Seal), [Polychrome](https://balatrowiki.org/w/Polychrome), [Mime](https://balatrowiki.org/w/Mime), [Baseball Card](https://balatrowiki.org/w/Baseball_Card), [Splash](https://balatrowiki.org/w/Splash), [Hanging Chad](https://balatrowiki.org/w/Hanging_Chad), [The Flint](https://balatrowiki.org/w/The_Flint), [The Arm](https://balatrowiki.org/w/The_Arm), [The Hook](https://balatrowiki.org/w/The_Hook), [Plasma Deck](https://balatrowiki.org/w/Plasma_Deck), [Observatory](https://balatrowiki.org/w/Observatory), [Listed probability](https://balatrowiki.org/w/Listed_probability), [Poker hands](https://balatrowiki.org/w/Poker_hands).
- **Second source:** DivvyCr's Balatro-Simulation mod, which re-implements the game's score evaluation: https://github.com/DivvyCr/Balatro-Simulation/blob/main/src/Engine.lua.
- **Fetched:** 2026-10-25. The game version is 1.0.1o-FULL.
- **Markers:** **[INFERRED]** marks a detail that comes from my reading of the game's evaluation code, as reproduced by the simulation mod or recalled from `state_events.lua`/`card.lua`. No fetched wiki page states these details directly. All other steps are stated by the wiki.

Notation: `chips` and `mult` are the running totals. "+X" adds to the total. "xX" multiplies `mult`. Effects resolve strictly in the order listed. Order matters because `(m + a) * x` is not equal to `m * x + a`.

---

## 0. Which cards score

1. The played cards (1 to 5) determine the poker hand. The game uses the highest-priority hand type the cards satisfy (see `hands.json` `priority`). Card order does not change the hand type.
2. The **scoring cards** are only the cards that form that hand:
   - Pair: 2 cards. Two Pair: 4. Three of a Kind: 3. Four of a Kind: 4. High Card: the single highest card.
   - Straight and Flush: the 5 cards, or 4 with Four Fingers.
   - Full House and the five-of-a-kind family: 5 cards.
   - Unscored ("kicker") cards do nothing.
3. **Stone Cards** that were played always join the scoring cards, even though they have no rank or suit. A debuffed Stone card is still part of the scoring cards.
4. **Splash** (joker) makes every played card a scoring card.
5. Scoring cards are processed **left to right by their position on the table**.

## 1. Press-play boss effects (before anything scores)

- **The Hook:** discards 2 random cards still held in hand. Those cards therefore give no held-in-hand effects this hand. *[INFERRED: the timing is the press-play step in the simulation mod, which matches the "Hook can discard Steel cards before scoring" note on Steel cards.]*
- **The Tooth:** lose $1 per card played.
- The hand's play counters (`played`, `played_this_round`) are incremented now. Counter-based jokers such as Supernova see the current hand. *[INFERRED]*

## 2. Hand legality and level-changing boss checks (`debuff_hand`)

- **The Psychic, The Mouth, The Eye:** a hand that breaks their rule is "Not allowed!". It scores 0 (`chips = 0`, `mult = 0`). No card or joker scoring effects run, except jokers that react to a debuffed hand (for example Matador). The hand is still used up.
- **The Arm:** the played hand loses 1 level (minimum level 1) before its base values are read. The loss is permanent.
- **The Ox:** if the played hand type is the ante's "most played hand", money is set to $0.

## 3. "Before" / on-played joker effects (jokers left to right)

- These jokers trigger once per hand before any card scores. Examples: Green Joker, Ride the Bus, Square Joker, Runner and Spare Trousers scaling; Space Joker (1 in 4 to level up the hand); DNA; To Do List; Midas Mask (turns scored face cards Gold); Vampire (strips enhancements and scales).
- These effects see unscored cards too.
- A card that Midas Mask or Vampire changes here already scores with its new enhancement in step 6.

## 4. Base chips and mult from the hand level

- `chips = hand.chips(level)` and `mult = hand.mult(level)`. The level formula is in `hands.json`.
- **[INFERRED]** The values are read *after* step 3, so a Space Joker level-up counts for this same hand.

## 5. Boss modification: The Flint

- `chips = max(0, floor(chips/2 + 0.5))` and `mult = max(1, floor(mult/2 + 0.5))`. Halves round up. Example: High Card 5x1 becomes 3x1.
- This is the only boss that modifies the base values. The wiki lists Flint under "boss effects" (step 1 of its sequence). The simulation mod, and the game code as I recall it, apply Flint after steps 3–4. The order only matters when a "before" joker changes the level (Space Joker).

## 6. Scoring cards, one at a time, left to right

For each scoring card:

**6.0 Debuffed card** (boss suit or face debuffs, Pillar, Verdant Leaf, and so on): gives nothing at all. It gets no retriggers and triggers no on-scored joker effects.

**6.1 Build the retrigger list** *before* the first activation:
- `[initial]`
- **+1 for a Red Seal**, always first in the list.
- **+N from each retrigger joker, left to right:**
  - Hack: +1 if the card is a 2, 3, 4 or 5.
  - Sock and Buskin: +1 if it is a face card (Pareidolia makes every card a face card).
  - Hanging Chad: **+2** for the first scoring card.
  - Dusk: +1 on the last hand of the round.
  - Seltzer: +1 for each of the next 10 hands.
  - Blueprint or Brainstorm copying any of these adds another +N at the copier's position.
- Retriggers stack additively. A Red Seal is never retriggered: Red Seal plus Hack gives exactly 3 activations, not 4.

**6.2 One activation**, repeated for every entry in the list:
1. **Card chips:**
   - Rank chips: 2–10 give their face value; J, Q and K give 10; A gives 11; Stone gives 0.
   - Plus the enhancement chips: Bonus +30, Stone +50.
   - Plus permanent chips (Hiker +5 per earlier scoring).
2. **Card +Mult:**
   - Mult Card: +4.
   - Lucky Card: **1 in 5** roll for +20 Mult.
3. **Card money:**
   - Gold Seal: +$3.
   - Lucky Card: separate **1 in 15** roll for +$20.
4. **Card xMult:** Glass Card x2.
5. **Card edition:** Foil +50 chips, then Holographic +10 Mult, then Polychrome x1.5.
6. **On-scored joker effects, jokers left to right.**
   - Examples: Greedy Joker +3 Mult per Diamond, Scary Face +30 chips, Smiley Face +5 Mult, Fibonacci, Photograph x2 on the first face card, Triboulet x2 on K and Q, The Idol, Bloodstone (1 in 2 for x1.5 on Hearts), Ancient Joker, Walkie Talkie, Wee Joker and Hiker scaling, Rough Gem ($1 per Diamond), Golden Ticket ($4 per Gold card), Business Card (1 in 2 for $2 per face card), Lucky Cat scaling when a Lucky card hit.
   - Within one joker's result the order is +chips, then +mult, then money, then xmult. *[INFERRED: order of the `chips`, `mult`, `p_dollars`/`dollars`, `extra`, `x_mult` keys in `evaluate_play`. Score-irrelevant for vanilla jokers, which give one kind each.]*

The wiki's wording of 6.2: "Base effect (Chips) -> card modifiers: enhancement, then seal (Gold), then edition -> on-scored Jokers L->R". Every activation repeats steps 1–6 in full:
- the rank chips, enhancement, edition and Gold Seal money;
- **fresh Lucky rolls**;
- every on-scored joker trigger, including scaling.

A Glass card's x2 applies once per activation. Its **break roll is not repeated** (see step 10).

## 7. Cards held in hand, one at a time, left to right

These are the unplayed cards still in hand, minus any discarded by The Hook. For each card that is not debuffed:

1. **The card's own held effect:** Steel Card x1.5. Gold Cards and Blue Seals act only at end of round, see step 12.
2. **On-held joker effects, jokers left to right:**
   - Shoot the Moon: +13 Mult per Queen.
   - Baron: x1.5 per King.
   - Raised Fist: +2 x the rank value of the lowest-ranked held card, on that one card. Use 2–10 by value, J/Q/K = 10, A = 11.
   - Reserved Parking: 1 in 2 for $1 per face card.
   - Within one card the order is money, then +Mult, then xMult, effect source by effect source: the card itself first, then jokers left to right.
3. **Retriggers:** Red Seal first (+1), then Mime (+1). A Blueprint or Brainstorm copying Mime adds another +1, left to right. Each retrigger repeats 7.1 and 7.2 in full.
   - **[INFERRED]** A held card is retriggered only if its first activation produced at least one effect. The code condition is `next(effects[1]) or #effects > 1`. So a lone face card whose Reserved Parking roll failed is not retried.

## 8. Joker pass, then consumables

For each joker, left to right:
1. **Edition, additive part:** Foil +50 chips or Holographic +10 Mult. It is added *before* the joker's own effect, and it applies even if the joker's effect does nothing this hand.
2. **The joker's independent effect**, for example Joker +4, Sly Joker, The Duo x2, Blackboard, Fortune Teller, Steel Joker.
   - Order within one result: +mult, then +chips, then xMult. *[INFERRED: `mult_mod`, `chip_mod`, `Xmult_mod` order]*
   - Retriggers never affect this phase.
   - Blueprint or Brainstorm produce the copied joker's independent effect here, at the copier's position, with the copier's own edition.
3. **Joker-on-joker effects:** every joker gets a chance to react to the joker just processed. In vanilla only **Baseball Card** does: x1.5 if the processed joker is Uncommon. It therefore applies right after that Uncommon joker's own effect.
   - Per the wiki Jokers page, Baseball Card still fires for a debuffed Uncommon joker.
4. **Edition, multiplicative part:** Polychrome x1.5, applied *after* steps 2 and 3. For example, Polychrome Joker gives (+4) then x1.5.

A debuffed joker (Perishable expired, Crimson Heart) contributes nothing, edition included. Its Negative slot remains.

After all jokers, the consumable area is scanned left to right. With the **Observatory** voucher, each Planet card whose hand equals the played hand gives x1.5.

## 9. Deck final step: Plasma Deck

`chips = mult = floor((chips + mult) / 2)`. This is the very last change before the product. Because of the floor, a sum of 2n+1 gives n x n.

## 10. Final hand score and destruction

1. **Hand score = `floor(chips * mult)`.** It is added to the round score. The blind is beaten when the round score is greater than or equal to the requirement.
2. Totals are ordinary floating-point numbers during scoring. Nothing rounds them except The Flint, Plasma and this final floor. For example, x1.5 effects produce fractional mult.
3. Scores above about 1.8e308 overflow to `nan`, shown as "naneinf".
4. **Destruction pass**, over the scoring cards left to right:
   - First, jokers that destroy cards (for example Sixth Sense).
   - Then each **Glass Card** that is not debuffed rolls **once** to break, with probability `p = 1/4`. Each Oops! All 6s doubles the numerator: 2/4, 4/4 and so on.
   - The broken glass still gave its x2 this hand.
   - Destroyed cards leave the deck. Jokers react afterwards (Glass Joker, Canio, and so on).
5. **"After" joker effects** run next, for example Ice Cream losing chips and Seltzer/Popcorn counters. The hand is then discarded and cards are drawn. *[INFERRED placement of "after" effects]*

## 11. Probabilities ("listed probabilities")

- These are written "1 in N" and succeed with chance `G.probabilities.normal / N`. The base value is 1. Each Oops! All 6s doubles it.
- Affected: Lucky Card (1/5 Mult and 1/15 money, rolled separately), Glass break (1/4), Wheel of Fortune (1/4), The Wheel boss (1/7), and jokers that say "1 in N".

## 12. End of round (not part of hand score, listed for completeness)

- Held cards are processed left to right:
  - Gold Card gives $3.
  - Blue Seal creates the Planet for the last hand played, if there is room.
- These are retriggered by a Red Seal and by Mime. The same "only if it did something" rule applies. *[INFERRED]*
- This money arrives before interest is computed, so it counts toward interest.

## Retrigger summary

| Source | Applies to | Count | Repeats |
|---|---|---|---|
| Red Seal | that card, scored or held | +1 (first in the list) | everything in 6.2 or 7.1–7.2, and end-of-round Gold/Blue |
| Hack | scored 2/3/4/5 | +1 each | 6.2 |
| Sock and Buskin | scored face cards | +1 | 6.2 |
| Hanging Chad | first scoring card | +2 | 6.2 |
| Dusk | all scored cards on the last hand of the round | +1 | 6.2 |
| Seltzer | all scored cards for 10 hands | +1 | 6.2 |
| Mime | held-in-hand abilities (Steel, Baron, Shoot the Moon, Raised Fist, Reserved Parking, Gold Card, Blue Seal) | +1 | 7.1–7.2 and end-of-round. It does **not** re-trigger a Red Seal. |

Things that are **not** repeated by retriggers: a joker's independent (step 8) effect, joker editions, the Glass break roll, and the Red Seal itself.

## Worked check

- **Hand:** Level-1 Pair of Kings, both plain; no jokers.
  - Base: 10 chips x 2 mult.
  - Scoring: 10 + 10 + 10 = 30 chips.
  - Score: floor(30 x 2) = **60**.
- **Same hand on The Flint:**
  - Base halves to 5 x 1.
  - Chips: 5 + 20 = 25.
  - Score: floor(25 x 1) = **25**.
- **Same hand with a Polychrome Joker (+4):**
  - Mult: 2 + 4 = 6, then x1.5 = 9.
  - Score: 30 x 9 = **270**.
