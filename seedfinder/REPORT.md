# Balatro seed finder: feasibility study

> **Update 2026-10-25: verified in the real game.** The player entered the opening of an ordinary
> (unseeded) run on macOS into the Lab's Seed Finder: first hand K♦ Q♦ J♥ 10♠ 8♠ 8♣ 6♥ 4♦, boss The Manacle,
> tags Economy + Juggle, voucher Paint Brush. The scan found **DD8JI5Y5** after 18% of the 34^8 game-generated
> seeds (~25 min at ~199 M seeds/s), and the player confirmed it is the run's seed. This settles caveat 1
> (first hand and boss), confirms tags and voucher again, and suggests macOS builds do not fuse multiply-adds
> (caveat 2). The scanner has since gained precomputed jump tables for the generator warm-up (1.7x per core).

Date: 2026-10-25. Target: Balatro 1.0.1o, White Stake, Red Deck. Machine: Apple M5 Max (18 cores), Python 3.14.3, Apple clang 21.

## 1. Verdict: feasible, with caveats

A run's seed can be recovered from what the player sees at its start. You need the first hand of 8 cards, plus the Boss Blind, the two blind tags and the first shop's voucher. A full scan of all 8-character seeds takes about 4 hours on this machine. Game-generated seeds never contain the letter O, so a 34-character scan of those takes about 3.2 hours. The average time to find the seed is half of that.

- The RNG machinery is bit-exact. It matches published test vectors, all 35 known "NaN" seeds, and 26,767 Erratic Deck results from another implementation.
- Several observables are verified against claims players published from real games: tags, voucher, shop jokers and editions, Rare-Tag jokers, the forced Buffoon Pack, pack contents and The Soul's legendary. All 12 claims credited to a person pass. The 6 uncredited claims from one 2024 list do not match (section 5C).
- **Caveat 1, the most important.** The two observables the search depends on most have not been checked against the game. These are the first hand and the Boss Blind. No public seed with its first hand or ante-1 boss could be found. They agree with an independent implementation (Motely), and they run on the same verified machinery, but the user must confirm them with the four seeded runs in section 8. This takes about 10 minutes of play.
- **Caveat 2.** The results may depend on the platform. A build that fuses multiply-adds (FMA), for example a native ARM build, would change 3-38% of these predictions (section 9). Ground truth must come from the platform the user plays on.
- **Caveat 3.** The shop jokers and two of the tags depend on the player's profile unlocks. The first hand, boss and voucher do not.

## 2. Licences

| Source | Licence | What we did with it |
|---|---|---|
| Immolate, https://github.com/SpectralPack/Immolate (formerly MathIsFun0/Immolate), plus its C++ port in ABGamma/Brainstorm-Rerolled/Immolate | **CC BY-NC-SA 4.0** (Attribution-NonCommercial-ShareAlike). GitHub shows "Other" because CC is not a software licence. | Read `lib/util.cl`, `seed.cl`, `cache.cl`, `instance.cl`, `functions.cl`, `items.cl`, `filters/analyzer.cl` and the C++ `util.cpp`, `instance.hpp`, `functions.hpp` to learn the algorithm, key strings, pool orders and version differences. No code copied; our code is written from the algorithm. |
| dlew/balatro-erratic-generator | MIT | Read `src/main.rs`. Its test vectors, 25 rows of `result.txt` and the blog's named seeds are used as test data in `validate.py`, with attribution. |
| Motely (Tacodiva/Motely) | no licence file, so all rights reserved | Only the published test outputs (facts about 6 seeds) are transcribed for comparison. No code used. |
| Brainstorm-Rerolled (top level) | no licence, so all rights reserved | Not used. Read its README only. |
| LuaJIT (TW223 PRNG, `math.randomseed`) | MIT | Re-implemented from the description in Immolate and dlew, which cite `lib_math.c` and `lj_prng.c`. |
| Balatro (LocalThunk / Playstack) | proprietary | **No decompiled or extracted game code was read in this study.** Game rules come from Immolate, the project's wiki-sourced `../data/*.json`, and general knowledge of the game. Each place where a detail rests only on that general knowledge is flagged in this report. |

**What CC BY-NC-SA 4.0 allows.** Copying and adapting Immolate is allowed only for non-commercial purposes, with attribution (credit, a licence link, and a note of the changes). Any adaptation must be released under CC BY-NC-SA 4.0 or a compatible licence (ShareAlike).

- **Port Immolate's code?** A line-by-line translation into Python or C is an adaptation. It would be allowed for this non-commercial project, but the port would have to carry CC BY-NC-SA 4.0 and attribution, and could not be used commercially.
- **Use the algorithm?** Copyright covers the code's expression, not the algorithm or facts about the game (formulas, key strings like `"cdt1"`, pool orders). An independent re-implementation like ours is not restricted by the licence.
- **Attribute?** We attribute Immolate anyway, in the code headers and here, because our structure closely follows its description of the game. If the project could ever become commercial, keep the code clean-room, which it currently is, and get a legal review. This is not legal advice.

## 3. How a Balatro seed becomes what you see (plain words)

1. **Seed.** A seed is 1-8 characters from `1-9A-Z`; a typed 0 becomes O. Seeds the game makes itself are 8 characters and never contain O: none of 432 characters in 54 published random seeds is an O, and the chance of that if O were allowed is p ≈ 4e-6. There are 35^8 = 2.25e12 seeds (41.0 bits), or 34^8 = 1.79e12 game-generated seeds.
2. **String hash.** `pseudohash(s)` turns any string into a number in [0,1). It walks the string from the last character to the first, computing `num = frac(1.1239285023/num * byte * π + π * position)`. The run computes `hashed_seed = pseudohash(seed)` once.
3. **One stream per decision.** Every random decision names a key: `"boss"`, `"Tag1"`, `"Voucher1"`, `"cdt1"` (shop card type), `"rarity1sho"`, `"Joker2sho1"`, `"edisho1"`, `"shop_pack1"`, `"nr1"` (deck shuffle, ante 1), and so on. Each key has its own state. On first use the state starts as `pseudohash(key .. seed)`. Every use then sets `state = round13(frac(2.134453429141 + state*1.72431234))` and returns `(state + hashed_seed)/2`. Here `round13` is the game's `string.format("%.13f")`, an exact decimal rounding.
4. **LuaJIT generator.** That value seeds LuaJIT's `math.random`, a 4-part Tausworthe generator. Its state is the bit pattern of `d·π+e` iterated four times, followed by 10 warm-up steps. The game then draws:
   - `math.random()` for probabilities;
   - `math.random(n)` to pick from a list sorted into a fixed order;
   - a Fisher-Yates loop for shuffles.
5. **Unavailable entries.** Pools keep a fixed length. An entry that cannot appear (locked, already present, needs a missing condition) is "UNAVAILABLE". If one is drawn, the game redraws with the keys `key_resample2`, `key_resample3`, and so on, each with its own state.
6. **Order does not matter across keys.** Every call reseeds the generator, so only the order of calls that share a key matters.

What each opening observable uses (1.0.1, ante 1):

| Observable | Keys and rule |
|---|---|
| Small / Big Blind tag | 1st and 2nd use of `Tag1`. The pool has 24 tags and 15 are possible at ante 1. Rare Tag needs Blueprint discovered; Foil, Holo and Polychrome Tags need those editions discovered. |
| Boss Blind | `boss`, an index into the 8 ante-1 bosses sorted by internal key: Club, Goad, Head, Hook, Manacle, Pillar, Psychic, Window. |
| First hand | `nr1`. The 52 cards are sorted by creation order (suit C,D,H,S; rank 2-9,A,J,K,Q,T), shuffled with 51 swaps, and the top 8 are dealt. Only the first 8 swaps matter. The 2nd blind of the ante uses the 2nd `nr1`. |
| Voucher | `Voucher1` over 32 vouchers. Only the 16 base vouchers are available, so roughly half the time a resample is drawn. |
| Shop card ×2 | `cdt1` × 28 gives Joker (20), Tarot (4) or Planet (4). A joker then uses `rarity1sho` (&gt;0.95 rare, &gt;0.7 uncommon), `Joker{r}sho1` and the edition from `edisho1`. Tarots use `Tarotsho1`; planets use `Planetsho1`, with Planet X, Ceres and Eris unavailable. |
| Packs | Slot 1 is always a normal Buffoon Pack (1.0.1 rule, first shop of the run). Slot 2 comes from `shop_pack1` × 22.42 over the pack weights. |

## 4. What is implemented

| File | What |
|---|---|
| `rng.py` | `pseudohash`, exact `round13`, LuaJIT TW223 `math.random`/`randomseed`, per-key `pseudoseed`, `pseudorandom_element`, `pseudoshuffle`. |
| `opening.py` | `opening(seed)` shows tags, boss, first hand (optionally the 2nd blind's hand), voucher, 2 shop cards with rarity and edition, and 2 packs. The `Run` class also models later antes: shops with Rare/Uncommon tags, the voucher chain, the contents of Arcana, Celestial, Spectral and Buffoon packs, The Soul's legendary, and a 1.0.0 mode used for old claims. CLI: `python3 opening.py SEED [--second-hand] [--locked-jokers ...]`. |
| `validate.py` | Every check in section 5. |
| `fastcheck.c` | Our own C version: cached seed-prefix hashing, exact `round13`, TW223, an early-exit first-hand filter, boss, voucher, tags, and a multi-threaded search with progress, ETA and a log. |
| `crosscheck.py` | C against Python on 20,004 random seeds. |
| `bench.py`, `info.py` | Python speed; information content. |
| `find_seed.py` | End-to-end search: C stage 1, then Python stage 2. Has a `--demo` mode. |

**Status of each opening output:**

| Output | Status | How |
|---|---|---|
| RNG core | **verified** | 9/9 published vectors, bit-exact. All 35 "all 10 of Spades" Erratic seeds reproduced; this requires the hash to reach exactly 0.0, so the arithmetic must be bit-exact. 26,767/26,767 Erratic rows of dlew's search match once his approximate rounding is allowed for (section 5B). |
| Small/Big tags | **verified** | 10 independent player claims (section 5C) and 12/12 against Motely. |
| Voucher | **verified** | A 7-ante voucher chain with resamples and upgrades (11EVFRPQ), KH77XUG6, and 6/6 against Motely. |
| Shop cards (jokers, rarity, edition) | **verified** | Negative Blueprint (99K6IUBD), Joker Stencil, Golden Joker, Credit Card, Sock and Buskin, Rare-Tag jokers, ante-2 shops. Tarot/planet identity agrees only with Motely. The planet pool order (Mercury…Eris) is not independently confirmed. |
| Packs | **verified** | Forced Buffoon Pack (PKF1939A, 99K6IUBD) and slot-2 Arcana (RBPTDL2H). Pack contents and The Soul are verified through 6 claims. |
| Boss Blind | **not verified in-game** | Same 8-boss pool and sort as the wiki data; 6/6 against Motely. Ground truth needed. |
| First hand | **not verified in-game** | Deck order and shuffle from Immolate. C equals Python on 20,004 seeds. The rate of seeds sharing a hand matches theory (3 found vs 3.15 expected in 2.37e9 seeds; 10 vs 7.2 in 5.45e9). Ground truth needed. |
| In-shop duplicate rule | not verified | When slot 2 draws slot 1's card, we resample, as the game does for cards already present (general game knowledge, not from Immolate). This matters in about 1 seed in 40. |

## 5. Validation results (`python3 -u validate.py --erratic-all`, log `logs/validate.log`)

Summary: A 9/9 pass; B 8/8 pass; C 13 pass, 3 partial, 13 fail (see the version note below); D 37 pass, 3 informational; E 10 pass, 1 informational.

**A. RNG vectors** from dlew's Rust tests: 9/9 identical to the last bit. They cover `pseudohash`, `pseudoseed` and `math.random` after `randomseed`.

**B. Erratic Deck.** The Erratic Deck draws 52 cards from key `erratic`.

- **Named seeds:** the blog's I3EFEF17 (25 tens), RGJO14OZ (24 fours), 8778L6US (39 hearts) and 77XX2TEK (20 fours, 38 spades) all pass, and so does 11153DRU.
- **NaN seeds:** all 35 seeds whose hash hits NaN, including the community-known 7LB2WVPK, give 52 × 10♠ as in the game.
- **Full result set:** of dlew's 26,767 rows, 26,231 are identical. The other 536 (2.0%) differ only because dlew rounds with `(x*1e13).round()/1e13`, while we use the game's exact `%.13f`. With his rounding, all 26,767 match.
- **Which rounding is right:** we believe exact rounding is right, because Immolate also emulates exact `%.13f`. One in-game check settles it (section 8).

**C. Player claims.** Each claim is modelled as the scenario the player describes. Claims from before 1.0.1 (May 2024) are run in 1.0.0 mode. That mode uses the old joker pools, no forced Buffoon Pack, and legendary key `Joker4sou1` instead of `Joker4`.

| Seed | Source | Claim | Result |
|---|---|---|---|
| KH77XUG6 | Steam thread 4346607305576903701, 2024-02-26 | skip both blinds: Double + Investment Tag; Telescope and Walkie Talkie early | **pass**: tags exact; first shop (ante 2) has Telescope and Walkie Talkie |
| 11EVFRPQ | Insider Gaming 2025-01-09 (Reddit user Best-Idiot) | vouchers: Telescope (A1), Director's Cut (A2), Retcon (A3), Observatory (A4), Overstock (A7), Blank (A10), Antimatter (A12) | **pass 7/7**, buying each voucher |
| 8Q47WV6K | Insider Gaming; Comicbook 2025-02-14 | skip both: Double Tag + Mega Arcana; Triboulet and Perkeo; Temperance in 2nd pack | **pass**: Double + Charm, Soul in both packs giving Triboulet then Perkeo, Temperance in pack 2 |
| PKF1939A | Comicbook | two Rare Tags, then Buffoon pack: Burnt Joker, Brainstorm, Blueprint | **pass**: Rare+Rare; tag jokers Burnt Joker and Brainstorm; Blueprint in the forced Buffoon Pack |
| RBPTDL2H | Comicbook | skip both: Perkeo in first Arcana pack, Polychrome Fortune Teller | **pass**: Polychrome Tag; first joker Fortune Teller; Arcana Pack Soul gives Perkeo |
| 99K6IUBD | Comicbook | first shop: Negative Blueprint and Brainstorm | **pass**: slot 1 Negative Blueprint; Brainstorm in the shop's Buffoon Pack |
| AYU7KNQ7 | Comicbook | skip first blind: Polychrome Joker Stencil | **pass**: Polychrome Tag; first shop joker Joker Stencil |
| D97FB8XS | Insider Gaming | skip Small Blind for Triboulet | **pass**: Charm Tag; Mega Arcana has The Soul, giving Triboulet |
| 86GRJT3C | Insider Gaming | skip Small Blind for Triboulet | **pass**: same as above |
| LH28B6PF | Destructoid 2024-03-29 (Reddit) | skip Small: Perkeo; skip Big: Invisible Joker | **pass in 1.0.0 mode**. In 1.0.1 mode only the tags match, as expected for a pre-1.0.1 claim. |
| V14NKYRB | Destructoid (Reddit) | skip both: Blueprint and The Duo in shop, Triboulet in Arcana pack | **pass in 1.0.0 mode**: Rare+Coupon; The Duo and Blueprint; Jumbo Arcana Soul gives Triboulet |
| 6FCKWFSZ | Destructoid (Reddit) | skip Small: Polychrome Credit Card, Sock and Buskin, Triboulet from Arcana pack | **pass in 1.0.0 mode** |
| 5IVQ8I9Y | Destructoid (uncredited) | Golden Joker and "Discount voucher" in first shop | **partial**: Golden Joker yes; Clearance Sale is the ante-2 voucher, not ante-1 |
| 477S1AMK, X4WH84AX, VGSCB3QZ, BZBZBXCB, JXLYA4I8, ZURCAMOS | Destructoid (uncredited) | specific first-shop jokers / Soul / Ouija | **fail** in both 1.0.0 and 1.0.1 mode |

**Notes on section C:**

- **Pass count:** every claim credited to a person (12 claims) passes in the version that matches its date. All failures are uncredited entries from one March 2024 list. They may come from the pre-release demo, whose RNG differs.
- **Version check:** the same 1.0.0 claims fail in 1.0.1 mode in exactly the parts that 1.0.1 changed. This confirms the version differences we model.
- **Chance level:** several passes would be very unlikely by chance. A Negative Blueprint in a given slot has p ≈ 5e-6, and The Soul in a 5-card pack has p ≈ 1.5%.

**D. Motely** is an independent C# implementation; we compared its test snapshots for 6 Red/White seeds at ante 1.

- **Agreement:** boss 6/6, voucher 6/6, tags 12/12, pack types 6/6, Buffoon contents 6/6 and the other shop cards all agree.
- **The 3 differences:** Motely shows Ceres (twice) and Stone Joker, which the game makes unavailable at run start (secret planet; no Stone card in the deck). Our model resamples those draws. Section D of the log has the details.

**E. Pools against `../data/*.json`** (wiki-sourced): joker pools by rarity (61/64/20/5), voucher order, tag order and min-ante, the ante-1 boss set, tarot and spectral order all agree. The data lists planets by poker hand, so it cannot confirm the planet pool order.

**F. C against Python** (`crosscheck.py`): 20,004/20,004 seeds are identical in hashed seed bits, boss, voucher, both tags and all 8 cards.

## 6. Speed and projected search time

Python, single core (`bench.py`, log `logs/bench_python.log`):

| Check | seeds/s |
|---|---|
| boss only | 33,500 |
| voucher | 19,200 |
| first hand, early exit | 33,600 |
| first hand, full shuffle | 10,600 |
| full opening | 3,150 |

Python is far too slow: the cheapest check over 35^8 seeds would take 43 days on 18 cores.

C (`fastcheck.c`, `-O3 -ffp-contract=off`; logs `logs/bench_c.log`, `logs/search_threads18.log`, `logs/fastcheck_search.log`):

| Check | Single thread |
|---|---|
| hashes only (cached prefix) | 264 M/s |
| boss | 17.2 M/s |
| **first hand, early exit (the search filter)** | **14.6 M/s** |
| voucher (not prefix-cached) | 1.6 M/s |
| tags (not prefix-cached) | 1.7 M/s |

- **18 threads:** the hand filter, with boss and voucher on the few survivors, ran at 157-169 M seeds/s. That was 156.8 M/s over 15 s, and 166.3 M/s in the 33 s demo. Sustained speed drops to about 150 M/s as the machine heats up.
- **Demo** (`find_seed.py --demo`): a random secret seed, 2Q3VJKNJ, was recovered from its opening by scanning a 5.45e9-seed slice in 33 s. The hand alone left 10 candidates, hand + boss + voucher left 1, and the Python check confirmed it.

Projected full scan at 150-160 M seeds/s (18 cores), cheapest and most selective filter first (hand, then boss, then voucher in C, then everything else in Python):

| Seed space | Seeds | Full scan | Expected time to hit the true seed |
|---|---|---|---|
| game-generated, no O (34^8) | 1.79e12 | **3.1-3.3 h** | about 1.6 h |
| all 8-character seeds (35^8) | 2.25e12 | **3.9-4.2 h** | about 2 h |

Not yet done:

- Seeds of 1-7 characters add 3% more seeds.
- Further speed-ups: table-driven TW223 warm-up (about 1.5-2×), NEON batching, or a Metal GPU port (Immolate-style GPU searchers reach billions of seeds per second). These would bring the scan under 30 minutes.

## 7. Information content and what the user must enter

Measured on 40,000 random seeds (`info.py`, log `logs/info.log`). The seed space is 41.0 bits (35^8) or 40.7 bits (34^8).

| Observable | Bits |
|---|---|
| first hand (8 cards as a set) | 29.49 (exact, log2 C(52,8)) |
| Boss | 3.00 |
| Voucher | 4.00 |
| Small + Big tags | 7.81 (3.91 each) |
| 2 shop cards with edition | about 14.75 by model (13.9 from 40k samples) |
| pack slot 2 | 3.29 |
| 2nd blind's hand | another 29.49 |

How many other seeds also match typical inputs (35^8 space; the 34^8 space is about 21% fewer):

| Input | Other matching seeds | P(unique) |
|---|---|---|
| tags + boss (blind-select screen only) | 1.25e9 | 0 |
| tags + boss + voucher + shop cards + pack, **no hand** | about 291 | 0 |
| first hand | about 2,990 | 0 |
| hand + boss | about 374 | 0 |
| hand + boss + voucher | about 23 | 0 |
| hand + boss + tags | about 1.7 | 0.19 |
| **hand + boss + voucher + tags** | **0.10** | **0.90** |
| hand + boss + voucher + tags + 2 shop cards | 4e-6 | ≈1.0 |

**What the user should enter:** the 8 cards of the first hand, the Boss, the two tags, and the first shop's voucher and 2 cards. Also say whether the seed was game-generated (enables `--no-o`).

- Without the first hand the seed cannot be pinned down from the opening: hundreds of seeds remain, and every candidate would need the slower checks.
- If the first shop was not seen, the 2nd blind's first hand works as well.

Command:

```
python3 -u find_seed.py --hand "AS KH 10D 2C 9S 4H 7D QC" --boss "The Club" --voucher Hone \
    --tags "Charm Tag, Double Tag" --shop "Blueprint, The Fool" --no-o      # ~3.2 h; tail -f logs/fastcheck_search.log
```

## 8. Ground truth needed from the user (about 10 minutes of play)

Set up each run as follows:

- Balatro 1.0.1o, New Run, Red Deck, White Stake, **Seeded run** with the seed below.
- Play the Small Blind; do not skip it. Write down the 8 cards dealt before playing anything.
- Beat the blind without using consumables, then look at the shop without rerolling.
- Also record the platform (Windows / macOS / Steam Deck / mobile) and the version string shown on the title screen.

| Seed | Tags (Small, Big) | Boss | First hand | Shop voucher | Shop cards | Packs |
|---|---|---|---|---|---|---|
| 4Z7TWAWF | Holographic, D6 | The Window | K♦ 8♠ 6♦ 6♥ 6♠ 5♠ 4♠ 2♣ | Reroll Surplus (resampled) | Bull (Holographic); Pluto | Buffoon; Celestial |
| 1PSV32J4 | Double, Coupon | The Pillar | K♥ J♥ 10♥ 9♣ 9♠ 8♠ 7♥ 4♠ | Crystal Ball | The Moon; Mystic Summit (Negative) | Buffoon; Jumbo Arcana |
| 8MTHQKH1 | Rare, Uncommon | The Pillar | 10♠ 8♣ 8♥ 7♦ 6♦ 4♠ 3♠ 2♠ | Hieroglyph | Half Joker; Four Fingers | Buffoon; Celestial |
| XVXR3J1P | Investment, Speed | The Goad | A♠ Q♥ 9♦ 9♠ 8♠ 7♦ 5♣ 3♦ | Telescope | The Empress; Earth | Buffoon; Standard |

These four runs together exercise every unverified path: the boss, the first hand, the planet pool order (Pluto and Earth), tag and voucher resampling, a Negative edition, and three pack kinds.

Optional extra checks:

1. **Big Blind hand.** Also play the Big Blind, without buying anything that adds or removes playing cards. Its first hand should be, in seed order: Q♦ Q♥ 10♠ 9♥ 8♦ 8♥ 5♠ 2♠ / Q♣ J♣ J♠ 9♥ 9♠ 8♠ 7♠ 5♣ / A♦ A♥ Q♥ Q♠ J♣ 8♠ 3♦ 2♦ / K♥ Q♣ 10♣ 10♥ 10♠ 9♣ 9♥ 7♦.
2. **Rounding check.** Start an **Erratic Deck** run with seed **12LO5RDX** and open the deck view. Our model predicts 6 Kings and 18 Diamonds (C15 D18 H9 S10). The rejected approximate rounding predicts 20 Kings. Either result settles the rounding question.
3. **End-to-end test.** Play 2-3 ordinary unseeded runs and write down the seed shown in the pause/options menu together with the opening. This tests the whole pipeline on real random seeds and confirms the no-O rule.
4. **Profile.** Say whether the profile has all jokers unlocked and Blueprint plus all editions discovered. If not, list the locked jokers; this affects shop jokers and the Rare/edition tags only.

## 9. Risks

1. **Hand or boss logic wrong.** Both are unverified in-game; if either is wrong, the search silently finds nothing. Section 8 settles it.
2. **Platform floating point.**
   - **The assumption:** we reproduce the x86-64 build (no FMA), which matches all the evidence. Most published claims come from Windows players.
   - **The danger:** a build that fuses `a*b+c`, such as a native ARM build of LÖVE/LuaJIT on Apple Silicon or mobile, would differ. In an experiment with a fused build of our own C code, 3% of bosses, 15% of hands, 32% of tags and 38% of vouchers changed.
   - **Unknown:** whether the macOS or mobile game fuses.
   - **Mitigation:** our C code must stay at `-ffp-contract=off`, which clang on arm64 does not use by default.
3. **Profile dependence.** Shop jokers resample when a locked joker is drawn. Rare, Foil, Holographic and Polychrome Tags need discoveries. Use `--locked-jokers`; the hand, boss and voucher are unaffected.
4. **Game version.** We validated 1.0.1 against 2025 claims and 1.0.0 against early-2024 claims. 1.0.1f and 1.0.1o are assumed identical for the RNG. A future 1.1 could change pools.
5. **Player actions.** These change what is seen:
   - Skipping a blind with a Rare or Uncommon Tag changes the first shop's first slot.
   - Rerolling changes the shop.
   - Using a tarot before the 2nd blind changes its hand.
   - Tutorial-forced first runs differ.

   `opening.py` assumes the simple path: play the Small Blind, then look at the shop. `Run` models the tag variants.
6. **Rounding ties.** An exact `%.13f` tie needs a state that is a multiple of 2^-14; this is practically impossible and is ignored.
7. **Seed length.** Seeds of 1-7 characters (only possible when typed) are not scanned.

## 10. Recommended next steps

1. Collect the ground truth in section 8, then run `validate.py` and add those seeds as section C entries.
2. If the hand and boss pass, do one real recovery: give `find_seed.py` the opening of an unseeded run with `--no-o`, about 3.2 h on 18 cores.
3. Optional speed work:
   - table-driven TW223 warm-up;
   - prefix-cached voucher and tag keys in C (only matters when no hand is given);
   - a Metal GPU kernel, which would bring the scan to minutes.
4. Wire `opening.py` into the simulator: `../balatro/shop.py` could take its ante-1 shop from the seed so simulated runs replay real seeds.

## 11. Reproduce

```
cc -O3 -mcpu=native -ffp-contract=off -o fastcheck fastcheck.c -lpthread
python3 -u validate.py [--erratic-all]   # ~1 s / ~20 s   logs/validate.log
python3 -u crosscheck.py 20000           # ~5 s           logs/crosscheck.log
python3 -u bench.py --seconds 6          # ~30 s          logs/bench_python.log
./fastcheck bench 5 logs/bench_c.log     # ~25 s
python3 -u info.py 40000                 # ~15 s          logs/info.log
python3 -u find_seed.py --demo           # ~35 s          logs/find_seed.log, logs/fastcheck_search.log
python3 opening.py 4Z7TWAWF --second-hand
```

## Sources

- Immolate: https://github.com/SpectralPack/Immolate (LICENSE: CC BY-NC-SA 4.0); C++ port https://github.com/ABGamma/Brainstorm-Rerolled
- dlew, "Balatro's Least Erratic Decks": https://blog.danlew.net/2025/11/03/balatros-least-erratic-decks/; code https://github.com/dlew/balatro-erratic-generator (MIT)
- Motely: https://github.com/Tacodiva/Motely (test snapshots in `Motely.Tests/seeds`)
- Seed claims:
  - https://www.destructoid.com/best-balatro-seeds/
  - https://insider-gaming.com/best-balatro-seeds/
  - https://comicbook.com/gaming/news/best-balatro-seeds-strategy/
  - https://steamcommunity.com/app/2379780/discussions/0/4346607305576903701

## 12. Instant lookups: the precomputed table (added 2026-10-25)

`table.c` builds a rainbow table over all 34^8 game-generated seeds for the full opening key (first hand
as a set, boss, voucher, both skip tags; `rainbow.c` observe()). A chain alternates key = observe(seed)
and seed = reduce(key, column); only its end is stored, with its chain number (12 bytes).

- **Model checked by measurement** (`rainbow.c test`, `table.c selftest`, logs/rainbow.log and
  logs/table_selftest.log): success per table matches the standard coverage formula: 75.0% / 75.5% found
  at chains x length / seeds = 2 (theory 75.0%), 88.5-89.0% at 4 (theory 89.0%), 94.5% with two tables at 2
  (theory 93.8%). Keeping chains that merge matters: dropping them lost about a quarter of the coverage.
- **Cost.** Evaluating the full opening is ~18x the scanner's early-exit hand check. Lockstep evaluation
  (256 seeds per block, vectorized hashing, rerolls pooled, shared hash prefixes) made it 2.5x faster per
  core, bit-identical on 1,000,192 seeds: 29.4 M openings/s on all 18 cores.
- **GPU** (`gpu_probe.m`): 235 G 64-bit multiplies/s and 646 G simple 64-bit ops/s. Software double
  precision (no fp64 on Apple GPUs) would reach ~9-12 G hash steps/s, about the CPU's ~10 G/s: not pursued.
- **Table 0**: chain length 4000, 892,896,952 chains (x length / seeds = 2, 75% of seeds), 10.7 GB in 64
  segments under `tables/` (git-ignored); 2 x 34^8 = 3.57e12 evaluations, ~34 h at low priority. Segments
  are written whole, so an interrupted build resumes, and lookups use the segments already built.
  A second table with different reductions would lift success to ~94%.
- **Lookup**: about T^2/2 = 8e6 evaluations per table (~1.2 s on all cores). The Lab's Seed Finder tries the
  table first when the full opening is entered, then falls back to the 2.5 h scan.

```
nice -n 10 ./table build tables 0 4000 2 64 18 logs/table_build.log   # resumable; tail -f logs/table_build.log
./table info tables                                                    # segments built, expected success
./table seed tables DD8JI5Y5 18                                        # look up a seed's own opening
```
