# Backlog

Open work on the bot, in rough priority order. Each item has the evidence for it and how it will be measured, so it
survives a lost conversation. The protocol: a switch per change (off by default), 480 paired seeds against the current
code, confirm on set 777; game-specific changes also on seeds that start with the joker in question (scratch
`perkeo_eval.py` shows the pattern). Results go to `runs/overnight-<date>.md`; finished items move there.

## Priority from 30 Oct evening: structural changes first, tweaks after (the user)

Reference since queue 49 (30 Oct 18:29): h-base 64.8% / h777-base 69.2%. Before it the references were flat
(62-63% / 64-67%); the headroom check ("are we hitting our ceiling?",
below) puts the wall at late scaling and survival. In order:
1. **Odds of the next blind from the build itself.** The pooled margin curve read CCU44VLE's ante-7 Big Blind at 88%,
   beaten 0 of 201. The spread of the 12 sample hands does not fix it (`logs/fit_spread.log`, 5-fold on 3,586 rounds of
   "latest", runs/value/odds_spread.json): log-loss 0.0657 current, 0.0635 margin refit, 0.0643 with spread, 0.0977
   resampling the sample hands; the spread models still read that blind at 87-91%. The bot outscores its sample hands
   by about 25% in general (growth in the round, Lucky cards); that build loses chips as the round goes (Blue Joker,
   Ice Cream). **Written (off): `ROLLOUT_ODDS`** (blind_outlook / outlook_odds): 24 copies of the run, the deck and
   every chance from streams of their own, each round played to its last hand by RolloutPolicy (GreedyBot against
   the real target), about 0.2 s a blind; the log of score over target as a z-score (ROLLOUT_FIT, the bot's edge over
   GreedyBot) blended with the margin (ROLLOUT_BLEND), fitted on 3,637 blinds (runs/value/odds_rollout.json,
   logs/fit_rollout.log): log-loss 0.0466 against the curve's 0.0541 (5-fold), 0.269 against 0.317 on the rounds the
   curve reads at 60-97%; lost rounds read 0.63 on average against 0.77. Used by the skip, this ante's boss odds
   (Boss Tag, money before a boss, the gamble) when on. **Still short on CCU44VLE:** 76% (rollouts alone 29%): the
   bot usually beats GreedyBot by ~40%, on that build only ~12%. Next for it: a rollout policy closer to the bot's
   play, so the edge varies less by build.
2. **Survival in shop worth. Written (off): `SURVIVAL`** (survival_gain, _survival_pick): the shop's 4 leading options
   and leaving are tried on honest copies; the change in plain power moves the rollouts (or the next blind is played
   out on the copy where hands, discards or hand size change); DEATH × SURVIVAL_WEIGHT × the change in odds is added
   (the Play tab's breakdown shows it). A swap's sale is tried with the buy it makes room for. Not yet: packs and
   rerolls (what they bring isn't known: 0), pack picks, money's worth. On the probe (ante 3, one Joker): Cavendish
   +1.72 (the next blind from 1% to ~86%); selling the only joker at ante 2 −1.59.
   **Queue 48 (15:11):** g-base (MILK_LIKELY on) against f-base; g-surv (ROLLOUT_ODDS + SURVIVAL), g-roll
   (ROLLOUT_ODDS) against g-base, both sets. g-base 62.9% (+0.6 ± 0.9), g777-base 65.4% (+1.2 ± 1.0): level.
   **g-surv +1.7 ± 1.7, g777-surv +0.8 ± 1.7** (about +1.2 ± 1.2 together; games ~1.8x slower, 48 s against 27).
   **Why so small ("why winrate isnt improving?", 30 Oct 16:40):** the reference's 344 losses (both sets) are 13% at
   antes 1-4, 28% at 5-6, **60% at 7-8**. Early on the next blind is beaten whatever is bought (the term ~0); at 7-8
   the build is short by more than one shop. Survival left 322/480 and 334/480 games unchanged; the ~150 changed ones
   flipped both ways almost evenly (37 won/29 lost, 37/33, mostly antes 6-8): a re-roll with a small net edge.
3. **Scaling toward ante 8's boss:** the same odds over the antes ahead, with the build's projected growth. This is
   the step aimed at the 60%. **Design (30 Oct 16:40; the user: "i am fine with whatever works"). Written (off):
   `SCALING`** (rounds_to_goal, goal_margin, scaling_state, scaling_odds, scaling_gain; in _survival_pick; the Play
   tab's "ante 8" row; 2 tests). ~40 ms a projection. Probe `logs/scaling_probe.log` (360 games, seeds from
   Random(2468)) → runs/value/scaling_probe.json; fit: scratchpad fit_scaling.py → SCALING_FIT. The shop's leading
   options (as SURVIVAL's) also worth DEATH × the change in the odds of beating ante 8's boss, from a logistic fit
   on the bot's own games (a probe of ~300 games, seeds outside 90210 and 777, every shop: the outcome against
   (a) the projected margin at ante 8: the typical round with growing jokers grown and wearing ones worn to ante 8,
   hand levels raised at the run's own Planet rate, over ante 8's boss target; (b) money; (c) free joker slots;
   (d) a constant by ante, the growth still to come). 5-fold against the ante alone; if (a)-(c) add nothing, stop.
   Why not today's power projected: every option would move the odds in proportion to its power gain, the same
   ranking; money and slots priced in win odds by ante, and flat +Mult diluted by hand levels, are what change it.
   No rollouts (one power of a projected copy per option). Risk: correlation, not cause (rich runs win partly
   because strong builds earn); the paired measurement catches an overpriced money.
   **Gap (the user, 30 Oct 17:05, 6AWQ2FCT ante 1 Jumbo Buffoon: "i feel like card sharp is better choice here"):**
   Shoot the Moon +1.33 against Card Sharp [Foil] +1.18 by today's power. The projection scales only what the run
   has shown (levels gained, growing jokers): at ante 1 nothing, so it reads as today and flat +Mult isn't diluted.
   Next: project the build toward the Mult the bot's builds typically reach by ante 8 (levels and jokers by ante,
   from the probe), even before the run shows it. **Fork test (logs/fork_6awq2fct_pack.log, value bot, 41
   shuffles each): Card Sharp past ante 7's boss 78% against 32%, ante 8 beaten 22% against 0%, progress 23.0
   against 19.4.** The user was right; Shoot the Moon was mostly sold by the end.
   **Fixed and on 17:25 (`LUCKY_MONEY`; the user at The Goad: "if anything clears the win, it makes sense to use
   lucky just to get some money"):** modifiers.lucky_triggers/lucky_each in play_bonus (winning plays and milking
   pick the one that rolls the $20 most, retriggers too), _card_economy (a Lucky card's own worth), hand_pay's
   Hanging Chad (deck share; run.pay_seen["lucky first"] with PAY_FROM_PLAY, off: lost -2.5/-3.1 on 29 Oct),
   a Lucky card alone always among the plays weighed (bots.ranked_plays), _measure on with a Lucky card in hand.
   The Goad now: 2C[Lucky] alone (was A♥, then Q♥ Q♦ 2♠ 2♣); the pack: the plain bot keeps Chad, the advisor
   still sells (+0.14, was +0.23; it keeps it with PAY_FROM_PLAY). Chad fork (bot playing on, before the fix):
   keeping Chad past ante 10's boss 76% against 15%. Measured in queue 49's h-base with the Flash Card fix.
   **(was) Next clear fix (the user, 30 Oct 17:20, 6AWQ2FCT ante 4: "im using chad to trigger lucky cards"):** the bot
   counted selling Hanging Chad for Judgement at +0.23. A Lucky card is +4 Mult in estimates (_as_scored) and its
   1-in-15 $20 is never counted (Gold cards' money is); so Chad retriggering a lone Lucky card (6 in the deck: $4 and
   +12 Mult expected a hand against $1.33 and +4) is worth +8 Mult and $0 to it, and it never plays a lone Lucky card
   to farm the rolls. Fix: Lucky money expected in card worth (The Magician), in Chad's (and other retriggers')
   worth, and in the play once a round is safely won (MILK_LIKELY's milking). After queue 49's snapshot; measured
   in the next baseline. (The fork test logs/fork_6awq2fct_chad.log plays on with the bot: no farming, so "keep
   Chad" is undercounted there.)
   **Fixed and on (30 Oct 17:10), the user's 6AWQ2FCT ante 3: "flash card here beats sly given number of rerolls":**
   Flash Card grew at the run's own reroll rate so far (0 in 5 rounds: growth 0, worth 0.38 against every joker
   held at 0.37-0.43). Now at least the bot's own rate at the antes ahead (rerolls_ahead, 1.52 a shop there), as
   Reroll Surplus: growth 0.33, and the advisor sells Scholar for it (what the user did). Measured in queue 49's
   h-base. g777-roll cancelled at 48/480 (machine shared; g-roll level on 90210, +0.2 ± 1.6).
   **Queue 49 (17:29-18:29, snapshot frozen-queue49): the new reference.** h-base (Flash Card + LUCKY_MONEY) **64.8%,
   +1.9 ± 1.7 against g-base; h777-base 69.2%, +3.8 ± 1.6** (progress +0.12 ± 0.09 / −0.02 ± 0.09). Both fixes stay
   on. **SCALING alone: h-scale 65.2%, +0.4 ± 2.1; h777-scale 69.2%, +0.0 ± 1.9** (progress +0.01 ± 0.15 / +0.10 ±
   0.13): no effect, stays off (the viewer's "latest" still has it, harmless). As the fit said: +0.1 projected log
   margin is worth 0.006-0.044 at DEATH 2, so a shop item rarely changes the pick. The fitted slope may be shrunk by
   a noisy projection (a noisy regressor pulls a logistic slope toward 0); a SCALING_WEIGHT sweep would be a tweak.
   h777-scale's losses end at antes 5-8: 18/31/40/43.
4. **Next (proposed 30 Oct 18:30): mine the decisions that cost games.** Steps 1-3 each measured within noise
   (survival +1.7/+0.8, rollout odds +0.2, scaling +0.4/+0.0); the measured gains came from mistakes the user caught
   in play (Card Sharp's fork 78% against 32%, Flash Card, Lucky cards: +1.9/+3.8). Automate the user's fork test:
   for the reference's losing games, at each shop (and pack) decision, play on with the other leading options over
   reshuffles (scripts/fork_test.py), and record which choices change the outcome; group the costly ones by kind
   (which joker turned down, which sale, money held) to find the fix. Cost: a fork is ~N shuffles × the rest of the
   game, so sample (losses at antes 5-8, the first decisions after ante 2).
   **Written (the user: "yes", 18:35): `scripts/mine_decisions.py`** (trace / fork / report). Mines on fresh seeds
   (Random(4242), never 90210 or 777: what it finds is measured there). Trace: the value bot's every decision as
   fork_test's steps, and at shop and pack calls the options it weighed (bot.worths, bot._acts' sale-then-buy). Fork:
   close calls (runner-up within 0.5 power; the shop after ante 8's boss left out), 3 a lost game + 100 from won games
   as a check (selection on a loss may favour any change), the choice and the runner-up each played on over the same
   reshuffles (k ≥ 1; the head replayed scripted, so the bot's memos start empty after it, for both lines alike).
   Report: by the choice and runner-up's kinds, by ante, and the single decisions. fork_test.py's `--lines` now takes
   a line of several actions (a sale then the buy). **Queue mine 50 (from 18:47, snapshot frozen-mine50):** 300
   seeds, 4 reshuffles; logs/mine_decisions.log, runs/mine/m1/report.txt.
   **Result (20:02; trace 197/300, 65.7%, as the reference): close calls are not where games go.** 400 decisions,
   1,600 pairs: the runner-up against the choice in lost games −0.05 ± 0.13 blinds, −0.5 ± 1.3 points at ante 8; won
   games +0.12 ± 0.14 / +1.5 ± 1.5. By kind (~60 groups, so a few at 2 SE by chance): joker over a pack confirmed
   (the pack −16.7 ± 7.2, n 15); leaving over a reroll (−6.9 ± 4.4, n 18); a reroll over a Tarot used +16.7 ± 8.3
   (n 6) and a pack over a reroll +11.1 ± 6.1 (n 9) only hints. By ante, all level. Blind spot: the shop keeps one
   sale per buy (the best by its numbers), so "which joker to sell" never shows as a runner-up: the user's Brainstorm
   case (below) had Reroll as runner-up. Next for the miner: fork the other sales (each joker sold for the same buy),
   and the round's plays and discards.
   **The user's 6AWQ2FCT ante 8 shop ("should i sell chad for brainstorm or something else? i feel like abstract might
   be better option", 19:35):** the bot: sell Chad +0.49, Abstract +0.24, Steel +0.23 (Chad kept 0.17 by power: −0.16
   without it, Abstract −0.43). Fork (value bot to ante 12, 24 reshuffles, logs/fork_6awq2fct_brainstorm.log): past
   ante 10's boss: keep 83%, Steel→Brainstorm 79% (−0.03 ± 0.07 blinds), Abstract→Brainstorm 71% (−0.05 ± 0.06),
   **Chad→Brainstorm 17% (−0.29 ± 0.06)**. The user was right; the bot's worth for Chad is badly short. Not money:
   8 replays each (logs/chad_why.log) show the same rerolls (~15) and Flash Card Mult (~88), Chad +0.8 Lucky rolls a
   round; every line sells Chad within a few rounds. **Traced (21:19, logs/chad_gone.log, scratchpad chad_gone.py, 6
   reshuffles a line): not Chad.** Every line has lost Chad by ante 9 (the keep line sells it there itself, for The Trio
   from a Buffoon pack). The wall is ante 10's boss, The Flint (ante 8's Violet Vessel is beaten in all 18). Past The
   Flint: keep with The Trio held (Abstract sold for Bull at ante 10) 4/4; keep with The Trio sold for Bull 0/2 (0.60,
   0.91 of the target); sell Chad (Brainstorm, then Crafty; The Trio never taken) 1/6; sell Abstract 5/6 (mostly
   without The Trio). So the bot's mistake here is likelier selling The Trio (X3) for Bull at ante 10 than Chad's worth;
   no Chad fix. For the miner on sales.
   **The user's 6AWQ2FCT ante 6 shop ("check if i should replace something with steel joker", 18:34):** 1 Steel card
   in 55 (X1.2). Fork (value bot to ante 12, 30 reshuffles, logs/fork_6awq2fct_steel.log): every line beats ante 9;
   ante 10's boss is the wall: keep 10%, Chad for Steel 19% (+0.09 ± 0.06 blinds paired), Sly 16% (+0.05 ± 0.06),
   Abstract 23% but −0.43 ± 0.29 (lost before ante 9 in 2/31). Level; the bot's play-on sells Chad and Steel later
   anyway. What the build lacks is X Mult for ante 10.
   **Fixed and on (19:05), the user's 6AWQ2FCT ante 6 Big Blind, "how does it calculate garbage tag?": `SKIP_ROUND_INCOME`.**
   The Garbage Tag: $1 a discard left unused this run (35 → $35, 0.70); playing: reward $4 + interest $5 + $1 a hand
   left (0.20) + the flat shop (skip_shop 0.25). Playing left out what the round pays besides: Golden Joker's $4 and
   the other income jokers (modifiers.round_dollars, split from income(): the dollars, whatever the income rules'
   strength, 0 since 28 Oct, in a joker's worth), Gold cards held ($3, a hand's share of the deck, Red Seal and Mime
   counted) and Lucky rolls at the run's own rate (run.pay_seen["lucky"]: Lucky cards scored with retriggers; Chad not
   counted twice). Here +0.065 (25 rolls in 12 rounds: ~$2.8 a round, +$0.4 the Gold card): 0.52 against 0.70, still
   skip (the user took it: $35). In skip_blind, _double_lookahead's Big Blind, skip_parts (the Play tab's row). Test.
   **Written (off; in latest): `SKIP_SHOP_MEASURED`** (the user: "does it account for skipped shop as well?"): the
   shop given up worth GLYPH_SHOP_SHARE of the run's recent best offers (the reroll hope's memo, 3 sets at least), not
   0.25 in every run. Test. Measured after the round-income baseline (queue 51).
   **Fixed and on (19:25), the user's 6AWQ2FCT ante 8 shop, $77: "why not buy pluto while we are here? its like it
   rerolls for rerolling": `CARDS_BEFORE_REROLL`.** Reroll +0.057 against Pluto +0.040: one action a call, the best,
   and the reroll threw Pluto away though buying it first left the reroll as it was. Now a card used as it is bought
   (Planet, Tarot needing no cards) worth > 0 goes before the reroll while the reroll stays affordable; jokers and
   cards kept left out (a slot a reroll's find may want: a judgment, not done). Test; both bots now buy Pluto there.
   In queue 51's i-base with SKIP_ROUND_INCOME. At "worth > 0" it bought Jupiter at +0.002 next (the user, 19:33: "its
   almost of no use to me"): now at least BEFORE_REROLL_MIN 0.02, the Play tab's coin-flip margin.

5. **Next (proposed 30 Oct 21:20, the user: "what do we do next?"): the bosses, play or build.** Where the reference's
   games end (scratchpad boss_deaths.py, logs/boss_deaths.log; each ante's boss drawn from the seed, checked against a
   played game): **140 of 169 losses (i-base) and 131 of 148 (h777-base) at a boss.** A typical boss at antes 7-8 ends
   ~1 game in 10 that reaches it (i-base ante 7: 39/392, ante 8: 40/351). Six end 2-3x as many, 134 of the 317 losses:
   Violet Vessel 37 (27% of the 135 met), The Wall 25 (antes 5-8; 26-45% at ante 7), The Needle 21, Crimson Heart 21
   (15%), The Eye 17, The Water 13 (n 14-80 a boss, both sets agree). Two leaks fit: the round's play (Needle, Eye,
   Water, Crimson Heart change how a round must be played) or the build (Vessel, Wall need raw score; the boss is
   shown from the ante's start, the shops value an average boss). **Test:** each lost boss round replayed with the
   same cards, played by a 1-ply rollout player (the leading plays/discards each played out over redraws of the unseen
   cards, no peeking); won boss rounds as the control. Many losses won → fix the play at those bosses; few → value the
   ante 7-8 shops against the boss coming. After it: the miner on sales and confident calls (Chad's kind: sure and
   wrong; m1 forked only near-ties).
   **Written: `scripts/boss_rounds.py`** (Search wraps the bot: its pick, the top 3 plays by score and the top 3
   discards it weighs, each played out by the bot to the round's end over N redraws of the pile, chance re-seeded;
   the most wins taken, a tie the bot's). Probe (3I7DG4FM, ante 7 The Mouth): the replay matches the eval (0.608 of
   the target); Search changed 4 of 7 decisions and reached 0.987 (still lost), 110 s at 4 rollouts. **Run b1 (from
   21:23, alongside queue 51):** i-base's 140 lost boss rounds + 140 controls (same boss and ante, beaten), 6 rollouts,
   10 workers; logs/boss_rounds.log, runs/bossplay/b1/.
   **Read (the user: "cant you just read those?", 21:35; logs/read_bosses.log, scratchpad read_bosses.py):** 21 lost
   rounds, up to 3 a boss (Vessel, Wall, Needle, Crimson Heart, Eye, Water, Mouth), every play and discard written
   out, and a generous ceiling: the best hand from every card the round showed, times the hands. **12 unwinnable by
   any play (ceiling 0.62-0.93): Vessel 3/3, Needle 3/3, Wall 2, Eye 2, Water 1, Mouth 1**; 1 borderline (Mouth,
   1.08); 5 unclear (Crimson Heart 3/3: ceilings 1.4-6.0 are loose). **3 play mistakes:** (a) The Mouth (19CX3AR3,
   ante 5): Three of a Kind locked in first (7,412 of 22,000), then 0, 0, 0; Two Pair at level 3 repeats far more
   often: the first hand type is picked by its score, not by how often it can be made again in the hands left.
   (b) The Water (MTHIGJNT, ante 7): an Ace played as High Card (2,551) where a play of junk cards keeps it; the
   next hand drew the other Ace (a Pair: ~22,600). DEAD_PLAYS digs by playing only when nothing scores (best <= 0),
   not when the best is far below needed / hands left. (c) The Wall (KT5U5CJT, ante 7): three 10s discarded to keep
   A K Q (Scholar, Smiley Face), then High Card first; 0.82. So at these bosses the build is the bigger leak (the
   shops before a known boss); (a) and (b) are fixes to write behind switches after b1's count.
   **b1 at 80 rounds (22:10) overturns "build is the bigger leak":** lost 37, Search wins 16; won 43, Search loses 2.
   The ceiling read was wrong for EED2E7Z1 (The Mouth: Search won, 1.27; the ceiling used the cards the bot saw and the
   type it locked in); the other "unwinnable" reads held (Needle 3, Vessel 2, Wall 2, Eye 2, Water 1). The three
   "play mistakes" read weren't won by Search (19CX3AR3 0.34 → 0.86, MTHIGJNT same, KT5U5CJT worse). Most wins change
   1-2 decisions, most often a discard made a play. Caveat: lost rounds end near the target and a change of play
   changes later luck too; check against close won rounds (bot share < 1.2) at the end. Next: group Search's changes
   to find the rule (the discard/play call first: cheap), rather than Search in the bot (too slow for 480 games).

   **b1 final (22:54): lost 140, Search won 52 (37%); won 140, Search lost 4 (2.9%)**; of the 54 close won rounds
   (the bot under 1.2 of the target) 2 lost. Rescues at bosses hiding cards (b1's Search didn't redraw them): The
   Fish 2, The Mark 1, The Wheel 1, Amber Acorn 1, so at least 47 (34%) honest. Changes in rescued rounds: discard →
   play 36, play → other play 24, discard → other discard 12, play → discard 9 (at 114 lost). Chain estimate (the
   user: "cant you just run a rough approximation"): 37% of boss losses rescued alone 64.8% → ~74%; with won rounds
   lost at 2.5% at antes 5-8 ~67.5%, at 1.25% ~71%; at every boss of every ante ~61%. The won rounds lost decide it.
   **Written (off): `ROUND_SEARCH`** (balatro/search.py; ValueBot.round_action): Search in the bot, boss rounds only
   (SEARCH_BOSS_ONLY), skipped when the bot's play surely wins or its own 6 play-outs all win; face-down cards in hand
   swapped with cards they could be (under The Mark face cards), the game seed's streams set aside, Amber Acorn left
   alone (the jokers face down); a switch only when the other wins SEARCH_MARGIN 2 more of 18 (6 + 12 confirming, the
   same redraws). tests/test_search.py (3). 4 games: 29-108 s a game, about the baseline's. **Queue 52 (from 22:53):**
   j-base (BASE_CARD_EFFECTS) against i-base, j-search (ROUND_SEARCH) against j-base; 90210 then 777;
   logs/sweep_queue52.log. Then b1's 52 rescued rounds with ROUND_SEARCH (`--explain`, every decision weighed in
   runs/bossplay/b1/explain.jsonl), for a cheap rule.

   **Queued overnight:** queue 53 (after 52): j-searchall (ROUND_SEARCH in every round, SEARCH_BOSS_ONLY=0) against
   j-base, both sets. Queue 54 (after 53): **the miner on sales, written** (`mine_decisions.py sales` / `sales-report`):
   m1's 300 traced games, each sale that made room for a buy or pack pick (the last in each lost game at ante ≤ 8: 92;
   50 from won games) forked into every joker sold for the same item and "keep all" (leave / skip), 4 reshuffles,
   3,600 games; logs/mine_sales.log, runs/mine/m1/sales/report.txt. An independent agent is reviewing for the biggest
   win-rate gains (runs/agent-review-20261031/report.md). The explain run replays i-base's games with
   bots.BASE_CARD_EFFECTS off (i-base's code; with it on the replays drifted to other rounds: its first run crashed)
   and checks each replay ends as in b1.
   **Explain, first 23 rounds (23:40; scratchpad explain_report.py):** ROUND_SEARCH (honest, margin 2 of 18) still
   wins 17 of 23. Of 28 changed decisions, 18 are discard → play, mostly at the round's start (4 hands 4 discards: 6):
   Violet Vessel NXH5QKQN threw 5 hearts keeping a pair of 3s (9/18) where the pair played at once won 18/18; The Ox
   K26HHQN9 discarded 5 three times holding K K, Q Q, J J (1, 4, 15 of 18 against 9, 11, 18). Why: with no Banner,
   Mystic Summit or Green Joker the rule is SmartBot._worth_discarding (strategy.py:462): discard when the next hand
   after the draw is 1.2x better on average; a discard kept has no worth for the hands after, so it is spent on a hand
   that is already good. A cheap rule (a kept discard worth what it adds to a later hand) only if ROUND_SEARCH itself
   doesn't measure well or is too slow; it costs ~65 s a game, about the baseline.
   **j-search (00:46): ROUND_SEARCH 70.2%, +4.4 ± 1.3 points against j-base (progress +0.34 ± 0.12)**; 29 games
   won that j-base lost, 8 the other way. 146 s a game against 35 s (the machine loaded). To confirm on 777
   (j777-search, ~02:30); if it holds: on by default and in LATEST_SWITCHES. Queue 53 reshaped: j-searchall (every
   round) against j-search, 90210 only.
   **Overnight results (31 Oct):** ROUND_SEARCH adopted (j-search +4.4 ± 1.3, j777-search +2.3 ± 1.2; on by
   default since 02:15; references j-search 70.2% / j777-search 72.5%). k-search (+ LAST_DISCARD_ODDS) −0.2 ± 0.2:
   level, kept as a fix. **k-strict +1.2 ± 0.7, k-searchall +1.0 ± 0.8** against k-search (90210): to confirm in queue
   55 (k777-strict, k777-searchall against j777-search; k-both against k-search). **Sales miner:** another sale instead
   of the bot's did worse on average (lost games −5.3 ± 2.6 points, won −3.6 ± 2.1): the bot's choice of which joker to
   sell is not a systematic leak; the Chad / The Trio cases were single games. Not ported yet: the agent's capacity
   worths (discard vouchers ~3x high, joker capacity gains 0) and PLAY_AHEAD.
   **Fixed and on (31 Oct 22:15), the user's XRTTE7VX ante 1 (Anaglyph Deck; "why does it say to skip?", "same here"):**
   (1) `RANDOM_TRIALS` 32: The Wheel of Fortune's 1 in 4 missed in all 8 effect_worth copies (a 10% fluke the state's
   seeding always repeats) and measured 0 against +0.19 on 200: an effect that drew on chance and came out alike in every
   copy is now tried on 32 (deterministic effects cost nothing more). (2) `PICK_TIES`: Jupiter, Earth, Saturn all
   measured 0 (the 12 sample hands: 9 Pairs, 2 High Cards, a Three of a Kind) and the pack was skipped; a free pick worth
   what skipping is (and ≥ 0) is now taken. Now: the Wheel (+0.27), Jupiter. Tests; suite 758 passed; viewer restarted.
   Not fixed: a planet's worth is today's sample hands only (a level for a hand not made now is 0); The Sun weighed only
   with 3+ hearts held. Measured in the next combined baseline. Queue 55 still frozen (SIGSTOP) since 08:10.
   **The review agent's report (01:30; runs/agent-review-20261031/report.md; its round lab samples every contested
   round, lost or won, on seeds outside 90210/777).** (1) `BEHIND_STRICT` (written 01:50, off): behind, a discard needs
   the usual 1.2x, not any gain (strategy.py SmartBot._worth_discarding): +1.40 ± 0.68 round wins per contested round,
   flips +25 / −4; est. +1 to +1.5 points. (2) `LAST_DISCARD_ODDS` (a fix, written on): the last hand with one discard
   left, the discard reaching the target in more of 48 draws than the play's win_odds (ValueBot._round_choice /
   _last_discard); 22 refusals in the lab, all in lost rounds. (3) PLAY_AHEAD (small, shrank on replication: not
   ported). (4) Capacity worths: +1 discard is worth log 0.09 (Wasteful/Recyclomancy valued +0.27, ~3x high), +1 hand
   0.15, +1 hand size 0.127 (power right); joker capacity gains count 0 (strategy.py:2082). Not ported yet. Ruled out:
   BEHIND_DIG and LAST_HAND_ODDS (no round changed in 420 redraws each: drop them from the held list), dodging Violet
   Vessel (≤ 0.2 points), CRIMSON_CYCLE (≤ 0.5). Tests for both (test_strategy.py).
   **Queue 53 rebuilt (01:55):** after queue 52, reads j777-search; confirmed (gain > its SE): k-search (ROUND_SEARCH +
   LAST_DISCARD_ODDS) against j-search, k-strict (+ BEHIND_STRICT) against k-search, k-searchall against k-search
   (90210); not confirmed: k-base / k-strict without search, both sets. Queue 54 (sales miner) after it.
   **Explain done (00:34): ROUND_SEARCH wins 35 of b1's 52 rescued rounds** (all 52 replays checked against b1), so
   ~25% of lost boss rounds honestly (b1: 37%, with hidden cards known and no margin). 75 decisions changed of 123
   weighed: discard → play 37 (11 at 4 hands 4 discards), discard → other discard 16, play → other play 12, play →
   discard 10; by boss The Wall 13, Crimson Heart 8, The Ox 8, The Mouth 6, The Eye 6.

**Queue 51's shop switch (22:08): i-shop +1.2 ± 1.6, i777-shop −1.5 ± 1.5: level, SKIP_SHOP_MEASURED stays off.**

**Fixed and on (21:55), the user's 6AWQ2FCT ante 9 Small Blind: "why does it advise me go create a glass and
discard it?": `bots.BASE_CARD_EFFECTS`.** Justice on 3H, then 3H[Glass] discarded. The cheap ranking before full
scoring (bots.base_value; strategy._base_at / _base_at_level_1 for power's sample hands, _candidates) counted rank
chips only, so a lone low card's Glass X2 (and Mult, Bonus, Foil, Holographic, Polychrome) was never scored: the bot
couldn't see 3H[Glass] alone (46,368 over KS[Lucky]'s 41,349) and threw it away. Now all three count the scoring
cards' enhancements and editions (bots.base_at_level). Test. Measured in the next combined baseline.
**Not fixed (design):** Justice still goes on the 3, not J (J alone 53,130): deck_change_worth tries a change on the
cards of its rank in power's 12 sample hands of 9, and by chance they held 11 threes and 7 Jacks (0.018 against
0.007; logs/justice_why_fixed2.log, scratchpad justice_hits.py). Options for one card's target should be compared on
the same hands (the card put into each), not on which rank happened to turn up.

**The user's 6AWQ2FCT ante 9 shop, decision 255 ("does it consider that all 6 boost lucky cards chances?", 22:00;
scratchpad oops_why.py):** Flower Pot +0.406 (build +0.366) against Oops! All 6s +0.053 (build +0.011: the Lucky
cards' doubled +Mult in estimates; what it pays 0). Not counted: (a) the Lucky money doubled (88 rolls in 18 rounds,
$1.33 → $2.67 a roll: ~+$6.5 a round), as every joker's income is 0 in joker worth since 26 Oct (a judgment that was
measured; money buys Flash Card's rerolls in this build); (b) Glass breaking (1 in 4, 1 in 2 with Oops): never in any
worth. Flower Pot's +0.37 assumes four-suit plays the lone-card build doesn't make, and it sells Chad for it. A fork
test offered.

**Reference since queue 51 (21:19): i-base 64.8% (+0.0 ± 1.3 against h-base) / i777-base 71.0% (+1.9 ± 1.2)**:
SKIP_ROUND_INCOME, CARDS_BEFORE_REROLL (BEFORE_REROLL_MIN 0.02) and the Lucky counter stay on.

**Held tweaks** (queues stopped before they started, 30 Oct 14:50; re-run on the new reference afterwards): BEHIND_DIG
(queue 44), ODDS_CALIBRATED + ODDS_BY_ANTE (queue 45, likely overtaken by 1), NEGATIVE_LASTS with g-base (queue 47),
LAST_HAND_ODDS and skip_safety 0.8 / 1.0 (queue 46). Queue 43's MILK_LIKELY finishes (f-milk +0.6 ± 0.9).

## The replay review (29 Oct 20:40, `runs/review-20261029/report.md`): bot-play bugs, ahead of more plan work

An independent reviewer replayed 36 default games and made ~75 counterfactual replays (scripts in the scratchpad's
`review-bot-20261029/`). No Blocking finding: all 33 eval seeds reproduce n-base exactly, and there is no
hidden-information leak.

**Fixed and live (on by default), 29 Oct 21:10.** The user: no gate per plain bug. Measured together in queue 25
(z-base, z777-base against n-base, n777-base): a regression check, and the new baselines.
- **M1:** `SWAP_EXACT` on.
- **M2:** the top `RERANK` (3) discards re-ranked on `RERANK_DRAWS` (24) shared draws.
- **m1:** `card_add_worth` for pack and shop playing cards.
- **m2:** `scoring_power` as the shop's and packs' base.
- **m3:** the resale floor for free jokers only.
- **m4:** `final_round`: in-round money and cards made worth 0 in the run's last blind.
- **m6:** the draw pool sorted by uid; `probe_leaks.py` also shuffles the pile.
- **m7:** Orbital Tag's own hand.
- **m9:** Turtle Bean in `GROWTH`, rounded to whole cards.
- **n1:** `_keeps_best_play` on a seedless trial.
- **The user's catch (6X7SCM12, Zodiac Deck, ante 5 Mega Spectral pack):**
  - Medium put a Purple Seal on a Gold Queen, worth +0.1483 on every card in hand alike.
  - Only the highest unsealed card was offered, and `_card_economy` counted a Purple or Gold Seal on a Gold or Steel card
    (held, never thrown or played) in full.
  - Now those seals count nothing there, and a seal Spectral is offered the highest card, the lowest plain card
    (Medium's first) and a held one (for Blue and Red).
- **Tests:**
  - 2 new.
  - The Eye dead-play test relaxed to its intent: 4-6-7-8 against 6-7-8 is 25.0 against 24.5 on 1000 draws, a coin
    toss on 24.
- **Still open: m5** (face-down cards), **m8** (Luchador), **m10** (Celestial picks at 0; a 0-worth Planet is worth
  nothing either way).
- **The user's 6X7SCM12 (Zodiac Deck, the fixed bot in the viewer, 29 Oct 21:20). Lost at ante 7, The Mouth, 50,215
  of 70,000, holding $79.**
  - **The $79: explained, not a bug.** The bot bought Bull at ante 7 (+2 Chips a $1). In its last shop it knew it was
    in danger (boss_odds 0.378, margin 0.88), but its power was 9.71 holding $76 and 8.84 at $0: the money was its
    score (+152 chips). Nothing offered beat what spending would lose. The real weakness: a weak build with Satellite (an
    income joker) in a slot at ante 7.
    - The user's principle, "don't sit on money when you are losing", is right where money doesn't score. RISK_MONEY
      lost (−5.8, −9.4).
    - To try, a judgment call to measure: in the last shop before a boss with odds under ~0.5, money above the
      interest cap counted at the odds of surviving it.
  - **The fifth card (a 2♣ with a Purple Seal played beside Two Pair): padding, right.** It doesn't score either way,
    and played it is replaced by a new card.
  - **Fixed and live: dead plays chosen on rare draws.**
    - With Two Pair spent first and no discards left, the bot held three Jacks and a Glass Ace. The play was rightly a
      discard (nothing else scores), but it threw two Jacks, keeping J 7 10 (119 on 1000 draws) over J J A (1,036).
    - Why: the 6-draw screen dropped J J A before the 24-draw re-rank. A Two Pair coming is a rare draw.
    - Now `_ranked_discards(everything=True)` for dead plays re-ranks every option. On the replay the bot keeps J J A,
      draws Kings for a third Two Pair, and ends at 67,666 of 70,000 (was 50,215; the last hand held no Two Pair).
    - Not in queue 25's snapshot: in the next baseline.
  - **The opening hand type under The Mouth: considered.** Flush 44,051 against Two Pair 29,635 now. It chose Two
    Pair as the type that repeats (one Club left in hand after five played). With the dead-play fix the Two Pair line
    reaches 67,666 of 70,000.
- **Play for the odds when behind (the user, 29 Oct 21:30: "if it doesn't clear even playing two pairs all the time,
  shouldn't it have tried to find another joker, accepting the tradeoff in Bull?").** The bot chooses by mean log
  score, which is cautious; when behind a boss (its own odds 0.378 here), the chance of clearing rewards long shots.
  - The odds are logistic in the log margin, convex when behind, so variance is worth having.
  - Where:
    - the last shop before a boss (rerolls valued by Δodds over their outcomes, not their mean);
    - the hand type under The Mouth and The Eye (P(reaching the target) over sampled draws, not a capped mean);
    - the last hand (LAST_HAND_ODDS, queue 18).
  - A judgment call: a switch, measured.
- **Vouchers, flat weights (the user's NNVPEGNB, ante 1: Overstock $10 skipped for a $4 Buffoon Pack, -0.10 net).**
  - Overstock is 0.4 flat against a $10 price of 0.5 at $25 or less (the voucher check: a flat voucher clears its price
    only above ~$40).
  - Note: the ante's voucher stays for its shops (run.ante_voucher) and is replaced after the boss.
  - **Written 21:50: `VOUCHERS_MEASURED` (off).**
    - Overstock (Plus): OVERSTOCK_SHARE 0.2 of the run's recent best offer a shop (BEST_OFFER_PRIOR 0.3 before
      three), over rounds_left (survival-weighted). That is 0.76 at ante 1, 0.18 at ante 3+ for a jokerless deck.
      Counting every shop to 16 whole made it 2.8.
    - Reroll Surplus (Glut): $2 a reroll at the run's own rate.
    - Clearance Sale and Liquidation stay flat (the run doesn't track spend).
  - Queue 26: y-base and y777-base (today's code), then u-vouch and u777-vouch against them.
  - **Measured 23:40: level, not adopted.** u-vouch +1.2 ± 1.1 points (progress −0.03 ± 0.07), u777-vouch −1.5 ± 1.1
    (−0.02 ± 0.08). It stays off in the default and on in "Value bot, latest". The Overstock case the user raised
    (worth buying when it may be gone next round) isn't a win across seeds as written; the share 0.2 is untuned.
- **Milk a won round (the user's NNVPEGNB, ante 3 The Club, 29 Oct 21:52).**
  - The bot had a sure Two Pair (5,082 of 4,000), 5 hands, 4 discards, $0 and Business Card. It played the winner at
    once.
  - The user: play the face cards first for money, then one-shot it. Today, with a win in hand, only paid discards come
    first (PAID_WON); never paid plays.
  - The rule (`MILK_WON`, to write):
    - Use free discards to dig, then spare hands on plays that use none of the winning cards and pay more than the $1
      cash-out each hand used costs. The pay: Business Card, Reserved Parking held, Rough Gem, Golden Ticket, To Do
      List, and growth from hands played (Green Joker, Ride the Bus, Runner, Supernova...).
    - Only while the win stays sure: no boss that touches held cards or hand types (not The Hook, The Mouth, The Eye,
      The Psychic, The Tooth).
    - Here one face card is break-even ($1 expected against $1), and digging for more makes it pay.
  - A judgment call: a switch, measured.
- **Hieroglyph and Petroglyph (the user's NNVPEGNB, ante 5, 29 Oct 22:01: "doesn't like hieroglyph for some reason?").**
  - Flat: −0.381 = +0.10 for the ante back − 0.481 for a 6th hand (the log rule tuned on Grabber at 4 hands; the run used
    2.3 hands a round). With the price, −0.76: last on the list.
  - **Written 22:15: `GLYPH_MEASURED` (off).**
    - The ante back: 3 shops at GLYPH_SHOP_SHARE 0.5 of the recent best offer, plus 3 rounds of cash-out and interest.
    - The risk: DEATH × P(losing the replayed boss) × P(beating this ante's).
    - The lost hand (discard): the log rule times the share the run uses, plus $1 a round of cash-out over rounds_left.
  - That shop: +0.737 (net about +0.44 against the Jumbo Arcana Pack's +0.175).
  - Queue 28: x-base and x777-base (the newest code), then g-glyph and g777-glyph against them.
- **Threshold jokers are worth only what they do now (the user's NNVPEGNB, ante 4, 29 Oct 21:55: "negative license is
  excellent, why doesn't the bot prioritize it?").**
  - Driver's License (Negative, Rare, $12; ×3 Mult with 16 enhanced cards in the deck): joker_worth 0.683, of which
    0.55 is the flat Rare and Negative bonuses. The ×3 counts 0 with 0 of 52 enhanced. Afforded only by selling Even
    Steven: −0.138, left.
  - Growth is counted for jokers that grow a step at a time (GROWTH, FED_BY), not for those that switch on at a
    threshold.
  - Wanted: its worth weighted by the chance of reaching the threshold within the horizon, from the run's own rate of
    enhanced cards (Tarots used, Standard picks).
  - A Negative one holds no slot, so only its price weighs against it.
  - Mostly for antes 9-12: 0 → 16 enhanced takes about 10 Tarots.
  - A judgment call: a switch, measured.
- **ALEEB, the Soul seed (the user, 29 Oct 22:20; logs/aleeb_review.log, scratchpad aleeb_review.py).**
  - The Soul is in an Arcana Pack in 5 of the first 6 shops (projection; Red and Yellow alike).
  - Today's bot:
    - Yellow: Canio, Triboulet, Perkeo, Chicot; sold Triboulet at ante 3 for The Duo and Canio at ante 4 for Droll
      Joker; lost at ante 6 (best hand 27,555).
    - Red: Canio, Triboulet, Perkeo; sold Canio; lost at ante 8.
    - The latest switches change nothing on Yellow.
  - Wrong:
    1. Legendaries that need a deck are judged on today's: Triboulet (Kings/Queens), Canio (face cards destroyed). Their
       feeders were passed: Sock and Buskin and Smiley Face at ante 3; Trading Card in the first shop.
    2. The Soul passed with the slots full, for Temperance's $44 (Yellow ante 2; Red ante 3) and Death (Red ante 2). A
       random legendary valued on today's deck doesn't outweigh the joker sold for it.
    3. $58-86 at antes 3-4 on Yellow, yet two money jokers (Delayed Gratification, Satellite) of six at ante 6.
    4. A Buffoon Pack bought on its flat weight at ante 1 and both cards left ($4).
  - To build (judgment calls, switches, measured; ALEEB a showcase seed):
    - Legendary strategies for the plan:
      - Triboulet: Kings and Queens from Strength, Death, Cryptid, DNA and Standard packs; Blueprint/Brainstorm on it.
      - Canio: face cards destroyed by Trading Card, The Hanged Man and Glass.
      - Yorick: discards.
    - The Soul with full slots: worth what each legendary it may give can become.
- **The user's three questions (29 Oct 23:30):**
  - **Neuroevolution of the many numbers? Not now.**
    - Evolution ran on 25-26 Oct: champion 10.0% against 8.5%. Plain fixes since took the bot to 56.7%, and the reviews
      still find +1-2 points each. Tuning can't find bugs, and learns around them.
    - A measurement is ±2.3 points and ~20 min.
    - Later: CMA-ES (it learns how parameters depend on one another) on 10-20 continuous weights, paired seeds, checked on
      set 777 and on other decks.
  - **Overfitting to Red Deck / White Stake?**
    - The 27 Oct survey (160 seeds a cell; the bot at 44% then): decks from Black 38.8% to Checkered 67.5%, Red in the
      middle; stakes collapse (Red 32.5%, Green 10.6%, Blue 9.4%, Purple 2.5%, Orange 1.9%, Gold 1.2%): scaling, as at
      antes 10-12.
    - Queue 33 re-runs it on the newest code (runs/value/survey-20261030.json; the old one kept as
      survey-20261027.json).
    - From now on, adopted weights should also hold on a mixed check set (several decks plus Red Stake).
  - **Done: each bot option in the Play tab is a dropdown** of what its number is made of.
    - A play's scoring step by step: the base, each card, each joker, chips × Mult after each (`interactive.play_steps`;
      none for a play with face-down cards).
    - An offer's worth before its price, then the price. For a joker: what it adds to the build, its bonus, what it
      pays, what it destroys, the rest (`interactive.worth_parts`, `ValueBot.joker_parts`, `worth_parts` recorded in
      consider).
    - Server restarted 23:40.
- **The Play tab's decision list shows suit signs** (8♠ Q♥ 10♦ 2♣: interactive.card_text; Jev keeps its own text).

- **M1. Joker swaps ignore how jokers interact.** A swap scores `joker_worth(new | all held) − owned_worth(old | all
  held)` (strategy.py ~2615-2626; the same additive form in the Buffoon pack swap and `_funds`).
  - 7S5X1EZS: Baseball Card sold for a Rough Gem worth +0.83 only beside it (+0.18 without). Vetoing that sale turns
    the loss into a win.
  - ZLS2ZPBR: Turtle Bean swap scored +0.485, really +0.08.
  - Abstract Joker counts 6 jokers in `joker_worth` and 4 in `owned_worth`.
  - About 5 swaps a game. The swap re-scored as `power(J − X + Y)` on 18 replays: 4 of 13 losses became wins, 1 of 5
    wins a loss.
  - Fix: a switch that scores a swap as the lineup it makes, in the shop, Buffoon packs and `_funds`.
  - **Written 20:55: `SWAP_EXACT` (off)**, `swap_worth`, `_best_swap`, `_funds_exact`. Both sides are measured in
    `best_order`, which also covers m2 for swaps. In a Baseball Card lineup, selling it for Rough Gem scores 1.74 the
    old way and 0.52 as the lineup; with the switch it isn't the best sale.
  - The reviewer's Abstract Joker bias didn't reproduce: a twin swap reads −0.012 by the old score; the ±3 Mult cancel.
  - Queue 25: x-swap, x777-swap.
- **M2. Discards chosen on `DRAWS = 6` sampled draws, never swept.** 13% of 261 discard rankings were ≥0.1 worse than a
  32-draw pick, 6% ≥0.25.
  - RU1S6CBP: threw both pairs and a Flush draw; broke a made Full House.
  - Fix: sweep DRAWS 12 and 24 (a BOT= patch, no code change), or screen on 6 and re-rank the top 3 on 24.
- **Minor:**
  - **m1.** Standard Pack picks are always the first card (79 of 79): every card is worth the same flat
    `w.card + card_bonus`. Fix: rank by `effect_worth` of adding it; skip below 0.
  - **m2.** Ceremonial Dagger kept rightmost while `joker_worth` and `owned_worth` use `best_order`: ±0.22 on every
    joker, and churn (1R4CELJQ). Fix: the same order on both sides.
  - **m3.** The resale floor is at the full money weight while the price above the reserve is at 0.1×: bought an
    Invisible Joker worth −0.255 and sold it at once (14TWBQSA).
  - **m4.** In-round money is still priced in the run's last round (3I7DG4FM: Pair over Three of a Kind for a Gold
    King's $3).
  - **m5.** Face-down cards are never played (bots.py:146). The Fish lost 2 of the 6 runs that met it (9I3JYDW6).
  - **m6.** The discard sampler reads the draw pile in its true order: shuffling only the pile changes 16% of
    discards. No information in expectation, but `probe_leaks.py` doesn't test it. Fix: sort the pool by uid; shuffle
    the pile in the probe.
  - **m7.** Orbital Tag's hand is fixed and shown, but `tag_worth` averages over all hands.
  - **m8.** Luchador is never valued (no case; no selling in a round).
  - **m9.** Turtle Bean's −1 hand size a round isn't in `GROWTH`.
  - **m10.** 25 of 253 Celestial Packs bought then skipped: a pack pick needs a worth above 0, a use doesn't.
- **Nits:**
  - `_keeps_best_play` copies the run with its real seed streams (latent: it can't change a decision today).
  - A pack's "Bought" frame comes after the pack's own frames.
  - Three empty `logs/review_noise_a …` files with spaces in their names, left by the reviewer (to delete with the
    user's OK).
- **The plan (3 games):**
  - Flush ↔ held still flips 5 times in 8 rounds on E8G18YRT, despite `PLAN_MARGIN`.
  - The Flush suit locks on the first suit joker owned (7S5X1EZS declined Wrathful at ante 2 for a Clubs joker).
  - f-plan's logs show the same: Flush the final main strategy in 408 of 480 games, 1.9 switches a game.

## The second replay review (29 Oct 22:45; the agent's report, logs/review2_*.log, scratchpad review2-bot-20261029/)

The reviewer replayed 32 games and made about 180 counterfactuals, on (a) losses at antes 6-8 and (b) what stops antes
9-12.

- **Death profile:**
  - Deaths at antes 5-8 are mostly at bosses.
  - Worst regular bosses at antes 5-7: The Needle (0.74 beaten), The Wall (0.75), The Water (0.84).
  - Ante 8: Violet Vessel 0.61, Verdant Leaf 0.80.
  - In runs to 16: ante 9's boss 0.83 (The Needle, The Wall, The Fish and The Eye: 24 of ~40 losses), ante 10's
    Small Blind 0.62, ante 11's Small Blind 0.14.
- **Fixed and live (22:50):**
  - **B1, Amber Acorn:**
    - The jokers were shuffled but visible, and the bot reordered at once. Without reordering, 3 of 22 such rounds were
      lost: absolute rates are inflated by up to ~2 points, paired comparisons barely.
    - Now `AmberAcorn.noticed` keeps what each hand showed of each joker, and `known()` gives those whose effects are
      their own, plus the last by elimination. The user: deduced, not given; look-alikes stay unknown.
    - The bot weighs plays with the known jokers where they are and the rest in the order last seen, and doesn't
      reorder until all are known.
  - **M1, Verdant Leaf:** `VERDANT_SALE`, `_leaf_sale`. The joker whose loss costs least is sold when the build without
    it, cards scoring, beats the build debuffed; where the run goes on, only when the round looks lost. The review's 5
    lost seeds now win; the 3 Amber Acorn seeds stay won.
  - **m1, Boss Tag:** the Big Blind skip is tested against a random boss, not the one it removes.
  - **m2, Obelisk:** reset on a tie for most played, in the modifier and the growth projection.
- **Behind a switch:** m3 `SKIP_BOSS_SMALL` (a Small Blind skip also tested against the ante's boss): queue 29.
- **Written 23:10, behind switches (off), queue 30:**
  - `LASTING_HORIZON`: m4 and the audit's G1. `_antes_ahead` = rounds_left/3 for growth, vouchers' `late`,
    legend_worth and boss_reroll_worth. Measured in runs to 16 against w-base16, and to 8.
  - `MILK_WON`: `_milk_play` spends spare hands, a sure win kept in hand, on plays that pay more than the $1 cash-out.
    MILK_MARGIN 1.1; MILK_BOSSES excluded; not in the run's last round. Measured on both sets.
- **Written 23:15, behind a switch (off), queue 32: `MOUTH_ODDS`.** The Mouth's opening type is chosen by `_mouth_odds`:
  P(at least ceil(rest / s) of the later hands make it), with p the share of 24 draws that make it and s their mean
  score; a tie goes to the bigger score now. The Eye keeps the capped mean.
- **Written 23:20, behind a switch (off), queue 31: `BEHIND_GAMBLE`.** The user's 6X7SCM12 point: in the shop before a
  boss with boss_odds under 0.5:
  - money_scale times the odds;
  - a reroll's hope at least `_behind_hope`: REROLL_SHARE × DEATH × the mean Δodds of the recent best offers through
    m⁴/(1+m⁴), convex when behind.
  - Measured on both sets against w-base and w777-base.
- **Open:**
  - **m4:** growth, voucher, legend and reroll horizons stop at ante 8 in runs to 16. The audit's G1, the same issue.
  - **n1:** in-round power reads the boss's debuffs.
  - **n2:** Amber Acorn's shuffle isn't on the game's stream.
  - **n3:** skip money unscaled.
  - Late builds turn down scaling ×Mult jokers (Hologram, Vampire, Madness, Campfire, Obelisk) as swaps worth less than
    nothing.
- **Queue 29:** w-base, w777-base, then w-skipboss. Queues 17-19 re-chained onto it.

## The night of 29-30 Oct: measured (queues 27-36; the notes in runs/overnight-20261027.md)

Each baseline is against the one before, paired on 480 seeds:

| Baseline | What it adds | Set 90210 | Set 777 |
|---|---|---|---|
| x-base | face-down plays, Observatory, voucher sale | 57.5% (+0.8 ± 0.8) | 59.8% (+0.4 ± 0.9) |
| w-base | the second review's fixes | 57.7% (+0.2 ± 0.9) | 60.4% (+0.6 ± 0.9) |
| p-base | the EURSXV11 fixes | 59.6% (+1.9 ± 0.9) | 64.4% (+4.0 ± 0.9) |
| h-base | Hologram's floor, Celestial pack with Constellation, the third review's M1 and M2 | 62.9% (+3.3 ± 1.4) | 67.5% (+3.1 ± 1.2) |

In runs to 16, y-base16 beat ante 8 in 55.0%, reached ante 10 in 44.4% and ante 12 in 1.2%; w-base16: 55.8%, 44.8%,
1.5%.

The judgment calls stay off; none is shown better on both sets:

| Switch | Set 90210 | Set 777 | Decision |
|---|---|---|---|
| VOUCHERS_MEASURED | +1.2 ± 1.1 | −1.5 ± 1.1 | level |
| GLYPH_MEASURED | −0.6 ± 1.4 (progress −0.22 ± 0.09) | +0.8 ± 1.4 | out |
| SKIP_BOSS_SMALL | −1.2 ± 1.5 | | out |
| LASTING_HORIZON | +0.0 ± 1.7; to 16 +0.4 ± 1.5 | | level |
| MILK_WON | −1.7 ± 1.1 | +0.8 ± 0.9 | level |
| BEHIND_GAMBLE | +0.8 ± 1.6 | +0.4 ± 1.7 | level |
| MOUTH_ODDS | +0.0 | −0.2 ± 0.5 | level (few games) |
| GROWTH_HORIZON=18 | +1.7 ± 1.7 (progress −0.26 ± 0.15) | −1.2 ± 1.8 (−0.28 ± 0.15) | out |
| GROWTH_HORIZON=12 | +2.9 ± 1.7 on p-base; +4.0 ± 1.7 on h-base (progress +0.09 ± 0.14) | +0.2 ± 1.7 on h777-base (progress −0.08 ± 0.12) | not confirmed: off in the plain bot, on in "latest" |
| RIFF_MEASURED | +0.2 ± 0.8 | +0.2 ± 0.6 | level |
| REROLL_SHARE 0.15 / 0.4 | +1.7 ± 1.7 / −3.3 ± 2.0 | | level / out |
| sell_margin 0.05 / 0.2 | +0.0 (progress −0.16) / −2.1 ± 1.8 | | out |
| skip_shop 0.1 | +2.1 ± 2.0 | | level |

"Value bot, latest" carries the level ones, LAST_HAND_ODDS (not measured yet) and GROWTH_HORIZON 12.

**09:10, the user: "i feel like those are more correctness fixes?"** They are: each fixes a plainly wrong behaviour,
and level means it touches few games. By the protocol's own rule, a neutral correctness fix is kept. So seven are now on
by default in the value bot:
- VOUCHERS_MEASURED, SKIP_BOSS_SMALL, LASTING_HORIZON, MILK_WON, BEHIND_GAMBLE, RIFF_MEASURED;
- MOUTH_ODDS, for the value bot only (SmartBot keeps the capped mean).

GLYPH_MEASURED (progress −2.4 SE) and the GROWTH_HORIZON values stay off. **Queue 38:** one combined baseline, c-base and
c777-base against h-base and h777-base, after queue 37b. MILK_WON's −1.7 ± 1.1 is near the revert line: if c-base comes
out worse, test it first.
- **Measured 10:23:** c-base 62.3% (−0.6 ± 2.2), c777-base 64.4% (−3.1 ± 2.2); progress +0.05 and −0.09. Together −1.9 ±
  1.6, not clearly worse. Queue 40 turns MILK_WON, then SKIP_BOSS_SMALL, back off on c-base's code on both sets.

**"Value bot, latest" is the run viewer's default and the Play tab's advisor** (the user, 09:12). It is the plain value
bot plus `models.LATEST_SWITCHES`: LAST_HAND_ODDS, GROWTH_HORIZON 12, and the hint's own INCOME_STRENGTH 0.5,
DISCARD_INCOME and DISCOUNT_FIRST. The viewer remembers a choice under a new key, so it opens on the latest once.

**The deck and stake survey (30 Oct, queue 35's snapshot, 160 seeds a cell, against 27 Oct):**
- Every deck improved, by +2.5 to +17.5 points. Red improved most (+17.5, to 61.9%) and is 10th of 15 decks.
  - Best: Checkered 80.6%, Blue 72.5%, Ghost 71.9%.
  - Worst: Black 43.1% (one joker slot fewer), Plasma 52.5%, Nebula 53.1%.
- Stakes on the Red Deck:
  - Red Stake 54.4% (+21.9).
  - Green 19.4%, Black 16.2%, Blue 13.1%.
  - Purple, Orange and Gold 2% or less, unchanged since 27 Oct.
  - From Green Stake on, blind targets grow faster: the same scaling limit as the ante-12 wall.
- Open: a mixed-deck validation set; scaling (×Mult engines) is what stakes and antes 10-12 both need.

## The user's catches, 30 Oct morning (EURSXV11, ante 4, the new advisor)

- **"it still doesnt see vouchers worth?"** Reroll Surplus measured exactly 0. VOUCHERS_MEASURED counts $2 off each
  reroll at the run's own rate so far, and the bot hadn't rerolled by ante 4: it rarely rerolls early and often late.
  Fixed (live, for queue 38): the rate is at least `rerolls_ahead`, the bot's own rerolls a shop at the antes the run is
  likely to last (`REROLLS_A_SHOP`, measured on 48 seeds to 16: 0.03 a shop at ante 1, 1.06 at 4, 2.73 at 8). The
  dollars saved are worth what `dollars_worth` says: they fill the purse to the reserve at the money weight and count
  at spare_money beyond it, since the bot rerolls with money past the reserve. At the user's $32 shop it's 0.21
  against a $10 price of 0.30 (a skip); at $20, 0.43 against 0.40. Not counted: the behaviour change (cheaper rerolls,
  more of them, better offers found).
- **"doesnt it overvalue rocket?"** Yes: +0.82 in the advisor. Rocket's pay counted +1.46 over 19.5 rounds at the full
  money weight (the advisor's INCOME_STRENGTH 0.5), against −0.69 of Stencil's X1. Fixed (live, for queue 38):
  `earned` counts the dollars that fill the purse to the reserve at the money weight and the rest at spare_money,
  since the bot shops down to the reserve. Rocket is now −0.10, and the advisor takes Gros Michel (+0.15). The plain
  bot counts pure payers at 0 (modifiers.OFF).
- **"why doesnt it offer to sell stencil now that it gives only 1x?"** (ante 5: five jokers, Stencil X1, Obelisk on
  offer). The swap logic had it right: Stencil → Obelisk +0.711, Ice Cream → Obelisk +0.646. But the sale of a joker
  worth less kept than sold returned first. Ice Cream measured −0.58 kept, because its freed slot would raise Stencil
  to X2, so it was sold and Obelisk filled the slot. The final build is worse than selling Stencil, with $2 less.
  Fixed (live, for queue 39's baseline): that sale is weighed with the swaps and buys, not returned at once. The
  advisor now sells Stencil ($4), then buys Obelisk. The deeper Stencil lock-in (below) stays open. **Measured 10:51
  (queue 39):** d-base +0.6 ± 0.5, d777-base +0.0 ± 0.4: kept.
- **"i dont understand this reasoning, foil joker will bring us over the edge"** (CCU44VLE, Anaglyph Deck, ante 1's
  Small Blind, Foil Tag; it played). The Foil joker comes in the shop after the Big Blind, so it can't help there. But
  the skip is undervalued twice:
  - **The safety check is far too strict.** The bare deck's margin over the Big Blind read 0.68 against 1.25 needed,
    but such a deck beats ante 1's Big Blind in 98% of 200 Anaglyph seeds and 100% of 200 Red ones
    (logs/bare_big_blind.log). The third review saw the same: 35 of 36 early skips passed the next blind.
  - **boss_odds is miscalibrated early.** The bare deck against The Head (600) is margin 0.38, so odds 0.02.
    BEHIND_GAMBLE (on since 09:10) then counts money as next to worthless in early boss shops. It's queued off in queue
    41 against c-base.
  - **The Foil Tag counts $5 plus a flat 0.15.** +50 chips roughly doubles an ante-1 hand; an edition tag should be
    worth the power its edition adds.
  - **Calibration (running since 11:11, logs/odds_calib.log, runs/value/odds_calibration.json):** the margin before each
    blind against whether it was beaten, over 200 games. Next: fit odds(margin) per blind kind, then use it in the
    skip check and boss_odds, behind a switch (ODDS_CALIBRATED), and measure.
- **"why does it score incantation negatively?"** (CCU44VLE, ante 2: Misprint, Raised Fist, Blue Joker). Not a bug.
  It adds 4 random 2-10s that this build seldom plays (pairs of high cards), so their Bonus, Mult or Glass rarely
  fire. A held Steel adds only ~5%: its X1.5 lands on the mult before Raised Fist's and Misprint's +Mult, as the
  game orders it (a KK pair 2,242 → 2,360). Only Gold registers. Each card dilutes the deck by about −0.01 to −0.02,
  and the destroyed card is random. Mean −0.095 over 8 outcomes (−0.27 to +0.07).
- **"why burnt joker is negative here?"** Its effect wasn't counted in the shop: only its rarity (0.15) against $8.
  Fixed (live, for queue 42's e-base): `burnt_worth`, the most played hand's power with the levels it brings over
  the growth horizon (one a round in BURNT_SHARE 0.7 of them). Now 0.25 here, still under $8 at a $10 purse.
- **"why free pluto scores negatively?"** A level lowered power. The sets scored in full were the best three by poker
  hand at their levels plus each poker hand's best. A High Card level pushed out the Pair that played its low kicker,
  so Raised Fist read a higher card held: 8.03 → 7.65 on one sample hand, −0.025 in all. Fixed (live, for queue
  42's e-base): `_candidates` ranks at level 1 (`_base_at_level_1`), so a level never changes which sets are scored.
  The cache key drops the levels. test_a_level_never_lowers_a_hands_best_score. Pluto is now +0.012.
- **"if i do it now, i will get one planet card instead of two"** (The High Priestess with The World held, slots full).
  Keeping a card that acts on no cards was worth ~0 against its use, so a use cut short by full slots still won.
  Fixed (live, for queue 42's e-base): in `consumable_choice`, when full slots would cut what The High Priestess or The
  Emperor makes, keeping it is worth MAKER_WAIT (0.8) times the full output (tried with the room it needs). The
  advisor now leaves the shop holding it. test_the_high_priestess_waits_for_room_for_both_planets.
- **"weird to offer me to play a purple seal card when i can just discard it ... if i use World first"** (The Wheel,
  slots full). Playing the Purple Seal 4 as a kicker sheds the low card for Raised Fist, a real gain while a discard of
  it makes nothing (no room). The bot didn't see the line: use a consumable to free a slot, then discard the Purple
  Seal for a Tarot. Fixed (live, for queue 42's e-base):
  - `modifiers.purple_forfeit`: a Purple Seal card played costs its Tarot while the round has a discard and a free slot;
  - `consumable_choice`: in a round, with slots full, a Purple Seal card in hand and a discard left, a use that frees
    a slot earns that Tarot.
  After the user used The World, the advisor's plan was The High Priestess (two Planets), use them, then discard with
  the Purple Seal.
- **"doesnt make sense to do it here when i can skip negative tag and take two negative jokers"** (ante 5, two Double
  Tags held, Foil Tag on the Small Blind with the slots full, Negative Tag on the Big Blind). Each skip was weighed
  alone, so the Double Tags went on 3 × 0.22 of Foil, not 3 × 0.60 of Negative. Fixed (live): `_double_lookahead`
  weighs the whole line. Skip now: this tag with the copies, then the Big Blind played or skipped for one of its own.
  Play now: then the Big Blind played or skipped with the copies. Each skip is at its risk. Here 2.13 against 1.26:
  it plays. test_double_tags_are_kept_for_the_big_blinds_better_tag.
- **"fool gives me neptune that is useless" / "hermit gives me 1 dollar":** the bot agrees, both measure 0.02 (Neptune
  at its $1 resale, made_worth; $1 doubled), and labels the top four a coin flip. Nothing in that Jumbo Arcana Pack
  was worth much to the build; the $6 for it was the cost.
- **"if i clear in 1.5 hands, doesnt it make sense to spam face cards for a bit to get money?"** MILK_WON milks only
  with a sure win in hand. Here a Four of a Kind (14,168 of 20,000) needs a second hand from new draws. With only the
  J♣ to play, Business Card's E$1 (a scoring face, $2 at 1 in 2) equals the $1 a hand left over brings, so it was a
  wash. Two scoring faces (a pair of Jacks) pay $2. Written behind a switch (off), queue 43: `MILK_LIKELY`, a spare
  hand on pay when the best play, kept, plus the hands after it finish the round at MILK_LIKELY_ODDS (0.95) by
  margin_odds. test_milk_likely_spends_a_spare_hand_on_pay_when_the_round_is_all_but_won. In "latest".
- **"does advice hold even if all of my jokers are full?"** (ante 7, 8/8 with three Negatives, two Double Tags, a Rare
  Tag). Yes: a joker tag with no room already counted only what its joker adds over the weakest joker. But all three
  copies counted over that same weakest. Fixed (live, for queue 43's f-base): `tag_copies_worth`, each copy over the
  next weakest (Ice Cream 0.13, Raised Fist 0.21, Misprint 0.30): 0.48 + 0.40 + 0.32 = 1.19, not 1.45. The skip still
  wins: 1.09 after its risk, against 0.43.
  test_copies_of_a_joker_tag_with_the_slots_full_each_replace_the_next_weakest_joker.
- **e-base (queue 42, the morning's live fixes) against d-base:** 61.0%, −1.9 ± 1.4 (progress −0.08 ± 0.07); e777-base
  65.0%, +0.6 ± 1.4 (+0.05 ± 0.08). Level together. The user: don't switch fixes off, find why they cost.
  - **Investigation (12:20-12:40; scratchpad trace_game.py, diverge.py, traces/diverge.json):** the 61 changed seeds of
    90210 were traced under both snapshots, all 61 reproduced. At each seed's first differing decision, a bot following
    e's steps (its memory rebuilt) answered with each fix off in turn.
  - **Results:** LEVEL1_CANDIDATES split 38 games (e won where d lost 11, e lost where d won 19, same 8). MAKER_WAIT
    split 17 (6 and 6). PURPLE_ROOM split 5 (no outcome changed). BURNT_MEASURED split 1 (lost). DOUBLE_LOOKAHEAD 0.
  - **Why the level-1 ranking costs:** it kept a levelled hand's single best set, where its kicker variants matter
    (Raised Fist reads the lowest card held, Baron the Kings). So levelled builds saw slightly worse best plays.
    Confirmed: 17 of the 19 games it lost were in levelled builds at the split. Many held jokers for which the cards
    played with a hand matter: Splash, Hanging Chad, Card Sharp, Even Steven, Odd Todd, Seeing Double.
  - **Replaced (live, for queue 43's f-base):** the sets are ranked at the levels of the position judged, frozen at
    the levels a change is measured from (`_ranked_at`: level_worth, effect trials, burnt_worth, the Orbital Tag; the
    power cache keyed by it). A level still can't lower power; Pluto stays +0.012; a levelled Pair keeps three
    variants. LEVEL1_CANDIDATES now defaults off.
  - **MAKER_WAIT's 17 splits checked (logs/maker_splits.log):** each time The High Priestess or The Emperor waited
    beside a Tarot that needs cards in hand (The Star, The World, The Fool, Justice...), used mostly 2-7 decisions later.
    The few long waits (20-36 decisions) fell in won and lost games alike: neutral, nothing surfaced.
- **"bot seems to ignore that we wont win this round with his best hands so we might want to start discarding" ... "i
  mean right from the start of the round"** (ante 7's Big Blind, 52,500 in 5 hands, 3 discards).
  - At the start the best play (a Pair of 7s, 9,333) was under the 10,500 each hand had to average. Discarding 8 7 7 5
    reached 10,500 on the next hand in 20% of draws, playing in 0%; on average the two were about equal (9,410 against
    9,333). The round ended with all 3 discards unused.
  - The advisor's plan at the start was in fact "Use The Devil on K♠ → Discard 8♥ 7♣ 7♦ 5♦". The Play tab showed only
    its first step. **Fixed:** the hint shows the rest of the plan under it ("then: ..."; play.js, play.css).
  - Late in the round no line won: the build's best hands are 8.3k (a Pair with Half Joker), 10.9k (Five of a Kind)
    and 13.8k (Flush Five) against 23.7k in 2 hands.
  - **Behind a switch (off): `BEHIND_DIG`.** When the hand is short of needed / hands left and no joker pays for
    discards kept (DIG_KEEPERS), take the discard whose next hand reaches that in the most of 48 draws (ties: the mean
    log). A loss ends the run, so the chance counts, not the average. At the user's last hand it discards
    10♦ 9♥ 9♦ 7♥, not 7♥. In "latest"; queue 44 (f-dig, f777-dig against f-base) runs after queue 43.
    test_behind_dig_discards_toward_what_each_hand_must_make.
- **Queue 42's switches (on e-base):**
  - EDITION_TAGS_MEASURED: +0.8 ± 0.9 and +0.8 ± 1.1 points, progress +0.15 ± 0.06 and +0.13 ± 0.08. **On by default
    since 13:49** (in queue 43's f-base).
  - With it on, a test caught an imbalance: the measured Foil edition is worth 0.94 to a chip-starved build of +Mult
    jokers, while the Negative Tag kept its flat 0.5. Fixed 13:52 (live, not in f-base): under EDITION_TAGS_MEASURED
    the Negative Tag's joker is worth what a typical Common joker in a slot of its own adds (`common_joker_worth`, the
    mean over RIFF_SAMPLE). In that build: Negative 0.79, Foil 0.98.
  - ODDS_CALIBRATED: −0.8 ± 2.2 (progress −0.22 ± 0.20) and +4.2 ± 1.9 (+0.01 ± 0.20). The sets disagree; not adopted.
    ODDS_BY_ANTE (queue 45) refines it.
- **"negative joker is a bit more valuable than average one because there is no need to sell it at some point to make
  space ... it basically stays forever instead of median 7 rounds"** Measured (60 seeds, logs/hold_rounds.log): the bot
  keeps a joker 6.2 rounds on average (median 5). 59% are sold or destroyed, after 4.5 on average; the rest are held 8.6
  to the run's end. Written (off): `NEGATIVE_LASTS`, a Negative joker's worth times rounds_left / HOLD_ROUNDS (6.2) when
  more than one, in place of the flat w.negative 0.4. At ante 2 (rounds_left 11.8) a Negative Cavendish goes from 1.58
  (flat) to 2.24; at ante 5 on it gets no premium (rounds_left 3.0). When slots are full, a Negative joker already needs
  no sale. In "latest". Queue 47 (g-base against f-base, then g-neglasts on both sets) runs after 45, in place of 41,
  which was cancelled as overtaken. Queue 46 runs after 47.
- **"doesnt that mean that it shouldve predict that and reroll more or take some action? i dont think it should go
  straight to losing round unprepared"** (the same round). The bot's forecast at the round's start was a margin of
  0.79, and late rounds starting there are won about 86% of the time, so it wasn't lost from the start. But:
  1. **The skip's risk was undercounted.** The skip check read the Big Blind after skipping at 95%, from a curve pooled
     over antes that early rounds dominate. Late rounds are harder at the same margin (a Big Blind at 0.75-1.0: antes
     1-3 96%, antes 6-8 86%; a boss: 100% and 78%). Written (off): `ODDS_BY_ANTE`, the curve's centre by ante group
     (ODDS_CENTRE, the slopes kept). This skip now reads 88%, risk 0.24; the skip still wins, 0.95 against 0.43 (three
     Rare jokers, 1.19). In "latest"; queue 45 after 44.
  2. **Survival isn't in what the shop pays for (structural, open).** A purchase counts what it adds to the build, not
     what it adds to the odds of surviving the blinds ahead. A joker lifting a must-win round from 86% to 95% should
     count DEATH × 0.09 on top, which might also say whether three Rare jokers are worth a 12% risk. It went in holding
     $36, the interest reserve. BEHIND_GAMBLE weighs survival only in the shop before a boss and only below 50%.
     Next: odds of the blinds before the next shop (the boss, or the Big Blind after a planned skip) in what money,
     rerolls and purchases are worth. Needs a design.
  3. **The round's discards went unused:** BEHIND_DIG (above).
- **"it still is not able to pass this blind ... did you arm a new bot?"** (14:10, branch 7 from step 125, the skip).
  Yes; "latest" since 14:06, its dig showing. `scripts/fork_test.py` (new: a game's first steps as recorded, one step
  set to each line, the advisor playing on, 200 reshuffles plus the game's own; logs/fork_ccu44vle_125.log):
  **skip 0% past ante 7's Big Blind (0 of 201); playing the Small Blind 65% past it, 34% past the boss, 34% won.** On
  the game's own shuffle both lose (skip 69% of the target, Small Blind 93%: Celestial → Mercury, a Jumbo Standard,
  Ice Cream sold for Clever Joker [Foil]). The read at the skip (logs/typical_probe.log): typical 8,311, the 12
  sample hands' best scores 7.8k / 9.0k quartiles, best 10,731, 5 hands against 52,500: margin 0.79, which the pooled
  ante-6+ curve reads as 88%. **The curve is a population's: most builds beat their typical hand by far (discards find
  a flush; centre 0.48 at ante 7), a flat Pair build doesn't, and five of its best hands barely reach the target.**
  Next: odds from the build's own spread. Probe running (scratchpad odds_spread.py, logs/odds_spread.log,
  runs/value/odds_spread.json: each blind's margin, 12 sample scores, hands, discards and outcome over 200 games of
  "latest"); fit offline (resampling the sample scores over the round's hands and discards, and a logistic on margin
  and spread), compare log-loss with ODDS_CENTRE, then a switch, measured on both sets.
- **"are we hitting our ceiling?"** (30 Oct, evening). The references are flat since h-base (90210: 62.9, 62.3, 62.9,
  61.0, 62.3; 777: 67.5, 64.4, 64.4, 65.0, 64.2), but those were level-by-design fixes. Headroom, from the 85 honest
  variants on set 90210 since 27 Oct 12:45: 470/480 seeds won by at least one; of f-base's 181 losses, 171 won by some
  variant and 92 by a quarter or more (outcome spread is part luck: one changed decision redraws the rest). f-base's
  losses: 156 at bosses, 111 at antes 7-8; 83 reached 80%+ of the failed target (33 reached 95%+). The wall is late
  scaling and survival, not the seeds. Levers: odds from the build's spread (probe running), survival in shop and
  skip worth, valuing scaling toward ante 8's boss (the plan layer was +3.1 in runs to 16, level to 8).
- **Queue 40 (on c-base's code):** c-nomilk +1.0 ± 1.0, c-noskip +1.2 ± 1.4, c777-nomilk +0.0 ± 1.0, c777-noskip
  −0.6 ± 1.4. Neither switch explains c777-base's −3.1; both stay on.
- **Behind switches (off), queue 42:** `ODDS_CALIBRATED` (margin_odds from ODDS_FIT, used in boss_odds, Chicot, the
  gamble's hope and Hieroglyph's risk; a skip pays DEATH × (1 − the next blind's odds without the shop), and the
  Small Blind's boss gate goes, since playing's worth already holds the shop) and `EDITION_TAGS_MEASURED`
  (`edition_worth`: a plain Joker with the edition against one without; Foil 0.87 on a bare deck, 0.33 with three
  jokers). With both on, the user's ante-1 Foil Tag skip goes ahead: 0.79 against 0.33. Both are in "latest".
- **Queue 40 (on c-base's code), first half:** c777-nomilk +0.0 ± 1.0, c777-noskip −0.6 ± 1.4. Neither explains
  c777-base's −3.1; queue 41 (BEHIND_GAMBLE off) now runs after queue 42.
- **"it has to push me to use more planets to boost constellation?"** It does count it. Each Planet's X0.1 is worth
  0.064 (its level 0.039), so a Celestial pack is 0.104 against a $4 price of 0.080, and at $32 it said buy. After
  Reroll Surplus's $10 the purse sat below the reserve, where a pack also costs interest: −0.025. A close call, not
  a blind spot.

## The third replay review (30 Oct 09:00; 119 games; runs/review3-20261030/notification.txt, scratchpad review3-bot-20261029/)

- **Blocking:** none. Hidden information and determinism checked.
- **Fixed and live (00:02, before queue 36's 07:22 snapshot, so in h-base; the session then waited until 09:02 on an approval prompt):**
  - **M1:** a joker's lost hand counts, by voucher_worth's rule (`capacity_change`). Troubadour −0.656, so Card Sharp
    now beats it. What Drunkard, Merry Andy and Burglar add stays uncounted: counting it lost a win on 38 seeds. The
    review's check on the Troubadour seeds: 3 → 7 wins of 10.
  - **M2:** money a joker earns counts at spare_money once the purse is $10 or more past the reserve (`earned`), as
    price charges spending there. Satellite at $129 goes from 0.544 to 0.054. The review's check: +2 wins on 21 seeds.
- **Open:**
  - **m1:** card-making jokers are unvalued. Riff-Raff measured level (RIFF_MEASURED); Cartomancer (a Tarot a round),
    Hallucination, Certificate, Marble Joker and Séance aren't written.
  - **m2:** no rerolls at ante 1 (0 in 223 shops). `_reroll_hope` is 0 until three sets of shop cards are seen, and a
    weak build can reach the ante-1 boss holding $13-23. A judgment call: a prior for the hope, or cheaper money at
    antes 1-2 while no joker scores.
  - **m3:** Top-up Tag counts 0.12 a joker; a random Common joker measures 0.38-0.58.
  - **Scaling past ante 8:** builds grow 1.3-2.1x an ante, while targets grow 5.1x at ante 10 and 12.9x at ante 11.
    ×Mult scalers are taken when offered.
  - **n1:** live edits move replays; paired checks need a pinned snapshot (the queues have them).

## The user's EURSXV11 catches (29 Oct 23:20-23:30, Play tab; ante 2, Raised Fist, Shoot the Moon, Joker Stencil)

- **Fixed and live (23:38):**
  - **Mega Buffoon Pack skipped.** Each joker measured below 0, because each costs Stencil X1. A pack's joker is now
    worth at least its resale, as a free one in the shop is. The pick is Constellation ($3).
  - **The sale.** `_dead_sale` sells, before a round's first hand, a joker the shop would sell (kept worth + sell_margin
    < resale). It runs once a round and never against a boss: in-round power reads its debuffs (n1).
  - **Constellation never grew.** The rate was Planets used per round so far (0 in 4 rounds), so it projected X1 for
    good and the bot said sell. Owned, it makes every Planet worth buying (the user: "does our model account for
    behavior changes?"). The rate is now at least `planets_offered` (about 0.9: 2 × 1/7 shop cards + 2 × 0.31
    Celestial picks). Growth went from 0 to +0.24.
  - **Blind select.** It had no breakdown (`skip_parts`): play vs skip, each with its parts and the safety test.
- **Behind a switch: `GROWTH_HORIZON`** (a class attribute now; 6 by default, halfway = 3 rounds ahead).
  - At this shop, Constellation kept is worth −0.19 at 6, +0.01 at 12 and +0.17 at 18; it's sold below 0.095.
  - Queue 34: p-hor18 on both sets, then p-hor12, against p-base.
- **Open:**
  - **Behaviour-fed growth rates.** Hologram (cards added), Red Card (packs skipped), Flash Card (rerolls) and Campfire
    (cards sold) all read the run's rate before the joker is owned. Owning one changes the behaviour, so each needs
    the opportunity as a floor, as Constellation now has. Red Card and Flash Card cost money to feed, so the floor
    must count the price.
    - **Hologram fixed 23:45 (live, after queue 35's snapshot):** `offered(run, "Playing card")`, about 0.62 a round
      (Standard packs' picks, plus Magic Trick's cards). Growth from 0 to +0.37 with no card added. It goes into the
      next combined baseline (queue 36).
  - **The Stencil lock-in.** Every joker is valued one at a time against Stencil's X1 an empty slot, so the bot never
    sees "sell Stencil, fill its slots". With Raised Fist, Shoot the Moon and Stencil, Shoot the Moon measured below an
    empty slot on a plain deck, and `_dead_sale` would sell it (so would the shop). This needs a joint option: Stencil
    sold with the best offers taken, as `swap_worth` does with full slots.
  - ~~**Celestial packs with Constellation.**~~ Fixed 23:46 (live, for queue 36's baseline): `planet_growth_worth`, the
    build's power with each Constellation X0.1 higher, times the pack's picks. With Constellation a Normal Celestial
    pack is 0.315, against 0.23.
  - ~~**The Play tab: sales have no breakdown.**~~ Done 23:39: a shop sale lists the resale, the worth given up and
    that worth's parts (test_a_shop_sale_records_its_worth_and_parts_for_the_play_tab).
  - **Riff-Raff is worth only its rarity bonus (0.08).** The two Common jokers it makes at each blind, while there's
    room, aren't counted anywhere. On ALEEB, before the resale floor, the bot skipped a free Buffoon Pack with
    Riff-Raff in it while holding only Canio (4 slots empty). Now it takes Riff-Raff, which has Splash and Green Joker by
    the next shop. It should be worth what its jokers are expected to be worth (a mean over Commons, times the room),
    as JOKER_MAKERS are.
    - **Written 23:41, behind a switch (off): `RIFF_MEASURED`.** `riff_worth`: min(2, room) Commons at the next blind,
      each max(worth to the build, resale) as a mean over 10 Commons. Later blinds aren't counted (that's mostly resale,
      and pay counts at 0, modifiers.OFF). Beside Canio alone it's 1.60 (a plain Joker 1.11); 0 with no room.
    - Queue 35: r-riff and r777-riff against p-base and p777-base, after queue 34. The survey moved behind it.

## Measuring now (27 Oct)

- **Approaches: done, negative** (`TARGET`, `TARGET_ANTE`, `TARGET_LEVELS`, off; games in
  `runs/value/approaches_games.jsonl`, `python3 scripts/read_approaches.py`; full result in
  `runs/overnight-20261027.md`, 21:35). No fixed approach beats the bot; a perfect chooser gains +3.8 ± 3.5 beyond luck
  (ante 1), −1.9 ± 3.4 (ante 3); real choosers lose 5-11 points. Straight from ante 1 on 480 seeds: −0.4 ± 1.8, even
  (`logs/sweep_straight.log`). Closed as a shop-only nudge. That is not a test of approaches: the bot can't use what
  the nudge buys (no discards toward the hand, no Tarots shaping the deck, no rerolls for its jokers). Measured on 64
  seeds (`logs/straight_use.log`): Straights 6% → 14% of late plays and the main hand in 8 runs instead of 1, but
  runs holding a Straight joker 17 → 18, and 56 of 64 still end on Pair, Two Pair or High Card. A fair test needs the
  build layer below.
- **Is the bot better on its default sample hands? No.** On 480 seeds, other sample hands (s-salt1) did +1.5 ± 2.3
  points, progress +0.31 ± 0.19 against the default: the other way from the approach experiment's replays, so chance
  both times. s-salt2: −2.3 ± 2.4, progress −0.11 ± 0.19 (`logs/sweep_salt.log`). Done: the default is an ordinary
  draw; luck-only replays land within about ±2 points of it.
- **24 sample hands instead of 12: no better** (28 Oct 02:37, `logs/sweep_hands24.log`): +0.2 ± 2.3 points, progress
  −0.08 ± 0.19, 1.7x slower. Done; 12 stays.
- **KEEP_TRUST ×2: ADOPTED 28 Oct 01:03** (`logs/trust_confirm.log`; `runs/overnight-20261027.md`, 22:55). Ahead on
  every test: set 90210 +0.2 ± 1.4, set 777 +2.3 ± 1.6, Perkeo games +2.5 ± 4.0; both sets +1.1 ± 1.0 points, progress
  +0.12 ± 0.07. ×3 lost on Perkeo games (−1.7 ± 4.6). With HAND_INCOME (02:12) and MIME_HELD (03:20) also on, today's
  code was m-mime (set 90210, 48.5%) and m777-mime (set 777, 51.0%). Since END_MONEY and POWER_EXACT (28 Oct
  14:25) **the baselines for the next change are p-exact (set 90210, 48.8%) and p777-exact (set 777, 53.8%)**; the
  Balatro Lab server runs that code since its restart at 14:35.

## Pricing (switches written 27 Oct, off; measured 28 Oct 00:23, `logs/sweep_pricing.log`)

Found on a Plasma game: Reserved Parking Holographic at $9 scored −0.43, Paint Brush at $10 −0.32.
- `HAND_INCOME`: jokers that pay as hands are played (Reserved Parking, Business Card, Rough Gem, Golden Ticket)
  counted $0 when bought; now their typical takings a round (`modifiers.hand_pay`), like Golden Joker's $4.
  **Neutral, ADOPTED 28 Oct 02:12** (`logs/sweep_hand.log`): on KEEP_TRUST 2, set 90210 −0.8 ± 1.0, set 777
  +0.8 ± 0.9. Still worth measuring on seeds given Reserved Parking at the start. New baselines are no longer
  k-trust2 / k777-trust2 game for game: measure today's code fresh before the next change.
- `INTEREST_REFILL`: interest lost by spending was $1 per $5 at w.interest (0.1, five dollars' worth) as if lasting;
  now the dollars lost round by round until the purse is back at the cap ($32 → $22: $1 once). **−1.5 ± 2.1: not
  adopted.** It lets the bot spend more, against money and interest weights tuned with the old count; would need
  w.money and w.interest re-tuned with it to be a fair test (low priority).
- `MONEY_ONCE`: with Bull or Bootstraps, spending cost the money's worth plus the chips it held up; now the larger of
  the two. **−1.9 ± 1.0: wrong, dropped.** Money held with Bull gives chips now and is still there to spend later;
  spending it loses both.
- `DISCARD_INCOME` (written 28 Oct 15:25, off; queue 3, `logs/sweep_queue3.log`): jokers that pay for discards
  (Mail-In Rebate, Trading Card, Faceless Joker) counted 0 when bought, like Reserved Parking before HAND_INCOME. On
  C5X6MXUN (Abandoned Deck, ante 3) a Jumbo Buffoon Pack's Mail-In Rebate was 0.00 behind a dead Sock and Buskin
  (+0.05, the Uncommon bonus); with it, Mail-In Rebate +0.81 (`modifiers.discard_pay`: half of what the round's
  discards could take). Also seen there: **Burglar's effect (+3 hands, no discards) isn't measured at all** (+0.05,
  the flat bonus); and the Play tab now says "About equal" when the best two options are within 0.02.
  **Measured 28 Oct 20:44: not adopted.** Ante 8 level (+1.0 ± 1.4, +0.0 ± 1.4) but progress lower on both sets
  (−0.22 ± 0.11, −0.18 ± 0.12): losing runs die earlier. Half of what the discards could take is more than the bot
  collects, since its play doesn't go for the rank (no fishing, Banner's chips weighed against the $5): it buys these
  over scoring jokers it needed. Two ways to an honest number: **calibrate** `discard_pay` from bot games given the
  joker (what it really takes a round, as for Reserved Parking's $3.33 against $1.38), the cheap one; or **make the
  play earn it** (fishing, below), then re-measure. Still on in the Play tab's hint (HINT_SWITCHES, the user's ask).
  **First recorder data (16 games, 21:27) says otherwise:** Mail-In paid $5.00 a round against $4.08 (PAID_WON
  on): if 480 games agree, the loss is the discards it spends, not an overestimate. Full run in
  `logs/calibrate_pay.log`.
- `PAID_WON` (written 28 Oct 15:40, off; queue 4, `logs/sweep_queue4.log`): with the round won anyway, a paid discard
  (Mail-In Rebate's rank, Purple Seals...) no longer counts Banner's 30 chips lost. C5X6MXUN's Big Blind (5,610 to
  3,000) held Mail-In Rebate's 9: the $5 (+0.10) lost to Banner (−0.20), so the bot played at once; with it, the 9 is
  thrown first. Next after it: **fishing**, a won round's spare discards thrown to draw the rank (about 0.6 of a card
  a discard from 26 cards holding three 9s), worth it when a discard is left to throw what comes.
  **Measured: +0.2 ± 0.2 and −0.6 ± 0.4 (progress +0.02, −0.04): a fix, level, adopted 28 Oct 21:22** (the new
  baselines in queue 6 were frozen before it: they lack it, a few games).
- **Calibrate every estimated payment from the bot's own games (28 Oct 21:15, from DISCARD_INCOME's result).**
  hand_pay (Reserved Parking: $3.33 real against $1.38), discard_pay (too high), income (off since the 24% bot),
  held-card pay: none checked against what the bot collects. A recorder (scratchpad) plays the seeds with the
  paying jokers counted, logs each paying joker's takings a round and how long it is kept, against each formula's
  estimate; one factor per formula from that; the calibrated set measured as one switch. Then the play (fishing,
  faces kept for Reserved Parking) and recalibrate.
  **The user's point (28 Oct 22:10): make them dynamic.** The 1.00s (Satellite = Planet types used, Cloud 9 = 9s in
  the deck, To the Moon = money held) only say this round's figure is right: each is today's pay times the
  horizon, as if nothing changed. Satellite grows with each new Planet type, To the Moon with money, Cloud 9 with
  added 9s. To do: (1) project growth (Satellite: + the run's rate of new Planet types a round; To the Moon: money
  expected; the horizon from the measured stay, 6.6 rounds kept against 8.3); (2) scored-card payers (Business
  Card, Rough Gem 1.7x) from the run's own scored cards a hand, not SCORED_CARDS = 3; Faceless/Golden Ticket
  (0.45x) from the real trigger rate; (3) check the estimate at purchase against everything paid while kept
  (per joker kept: needs the recorder to log instances); (4) measure as one switch.
  **Written 29 Oct 02:00: `PAY_FROM_PLAY` (off; queue 12, `logs/sweep_queue12.log`).** The run counts, over its
  hands, the face cards, Diamonds and Gold cards scored and the face cards held (`run.pay_seen`); after 6 hands
  Business Card, Rough Gem, Golden Ticket and Reserved Parking are estimated from that, not the deck's share times 3
  scored cards; Satellite adds the new Planet types to come at the run's rate so far (capped at 9). Checked against
  real takings on 96 seeds of set 4242 (`logs/calibrate_own.log`, 02:39): paid/estimate a round Business Card 1.24
  (was 1.93), Reserved Parking 1.20 (1.65), Golden Ticket 1.26 (1.61), Rough Gem 1.46 (1.50); over a stay 1.11, 0.95,
  0.49, 1.15, Satellite 1.60 (early, when its rate is low). Not in it: the horizon (kept 6.7 rounds against
  8.3), Faceless and Golden Ticket trigger rates, To the Moon's money to come. **Lost (29 Oct 06:34): −2.5 ± 1.1
  (51.9%) and −3.1 ± 1.2 (54.2%) points, both −2.8 ± 0.8; progress −0.03 and −0.16. Off.** Closer to the real
  takings, payers are bought more and the slots they take score less: a dollar from a payer is worth less to winning
  than the money weight says (the opposite of MONEY_SCALE's win, which was money in the purse). Next if revisited:
  income times a share below 1 (HAND_INCOME at a fraction), not more accuracy.
- **Income jokers are still off (asked 28 Oct 19:26, C5X6MXUN ante 4 shop).** Golden Joker, Rocket, Cloud 9, To the
  Moon and Egg have strength 0 (`modifiers.OFF`), set when the bot won 24% and hoarded money (24.2% at 0, 23.8% at
  0.25, 22.5% at 1). Today's MONEY_SCALE win says money is now undervalued: retest on today's bot. On C5X6MXUN Cloud 9
  ($4 a round, four 9s) was worth 0.05 and Mail-In Rebate 0.00, so their swap missed the 0.1 margin and wasn't listed;
  after selling Mail-In, Cloud 9 +0.06 against Even Steven +0.28. **Switch `INCOME_STRENGTH`** (the OFF rules'
  strength), written 19:30, off; on for the Play tab's hint only (`interactive.HINT_SWITCHES`, with DISCARD_INCOME,
  asked 20:05: the hint sold Cloud 9 for Wily Joker): **when measured, adopt or drop them there too**; **queue 7**
  **measured 28 Oct 22:52 against p-money: 0.5 level (−0.2 ± 1.8, progress −0.07 ± 0.13); 1.0 lost (−3.3 ± 1.9,
  progress −0.62 ± 0.15)**: not adopted; the hint now uses 0.5. Counted in full, they still crowd out scoring
  jokers (each counted over 8.3 rounds, kept 6.7: the calibration). Retest with the horizon calibrated; (`logs/sweep_queue7.log`, after the new baselines): 0.5 and 1.0 against
  p-money. **Fixed directly 19:30:** `rounds_left` counted payments only to ante 8's boss, too few in a run to 12 or 16
  (now to the run's last boss; no change on the 8-ante sets); the shop list kept the last swap for a joker sold, not
  its best (`worths` keyed by the sell; now the max).
- **`hand_pay` is too low for play built around the joker.** In the user's Plasma game (Play tab, game
  20261027-171809-MLQUG157) Reserved Parking paid $10 in its first 3 rounds (5 hands: $1, $4, $3, $0, $2; one-card plays
  and non-face discards to keep faces held): $3.33 a round against the estimate's $1.38, and its $9 back in 3 rounds.
  Calibrate from bot games given the joker (what it really takes a round), or estimate for adapted play.
- **Discards ignore Reserved Parking** (`modifiers.discard_bonus` has no case for it; plays do, in `play_bonus`): with
  it held, face cards should be kept and others thrown. Business Card the same for faces played.

## Valuation

- **`MIME_HELD`: ADOPTED 28 Oct 03:20**: Mime's second payment in its income (`modifiers.mime_pay`), Red Seals and
  Mimes in a held card's worth (`_card_economy`) and in what playing it forfeits (`held_forfeit`). On the game below
  it keeps Mime (High Priestess first, no sale). Level on both sets (`logs/sweep_mime.log`): 8 and 1 of 480 games
  change, +0.2 ± 0.4 and −0.2 ± 0.2 points. Today's code is m-mime (set 90210, 48.5%) and m777-mime (set 777, 51.0%).
  Left from the list below: deliberate Gold holding; worth a test on seeds given Mime and Gold cards.
- **Mime doesn't count its Gold-card money (bug, found 28 Oct 01:20 on your Plasma game, MLQUG157, ante 9).** The deck
  holds 18 Gold cards; you play single cards and hold 6 Golds at each round's end ($18, $36 with Mime). The bot valued
  Mime only by its scoring (+0.016: it retriggers 3 Steel cards, and on Plasma x1.5 Mult barely moves ((chips +
  Mult)/2)² with ~800 chips) and suggested selling it for Satellite (+0.107). Three gaps:
  - `modifiers.income` has no case for Mime (or Red Seals on Gold cards in `_card_economy`): its doubling of held
    Gold cards ($3 each) and Blue Seals isn't counted. Even at the bot's random-holding estimate (Golds held in
    proportion to hand size / deck) that's +0.21, more than Satellite's +0.15 (5 Planets used): it would keep Mime.
  - `held_forfeit` (playing a Gold card loses its $3) doesn't double for Mime either, so in rounds the bot plays Golds
    for +10% score it doesn't need ([280]: JH[Gold] JD[Steel] 6H where 6H alone clears).
  - Golds are held on purpose: the random-holding estimate ($7 a round here) is far below what deliberate holding
    takes ($18).
- **Horizon in endless play.** `rounds_left` counts to ante 8 (`9 - ante`, at least 1): at ante 9 of a game to 16,
  every lasting payment counts 1.5 rounds. Not simply `run.max_ante` (tried and reverted 28 Oct): `Run` defaults to
  16 and Play-tab games use 16, so that would double every lasting value from ante 1 in those games, away from what
  was tuned and measured (evals stop at 8). Needs a rule for past ante 8 only, e.g. the antes a run that has won
  typically survives in endless (measure: bots played to 16 from won positions).

- **Hieroglyph's ante back is a flat 0.1 (asked 28 Oct on MLQUG157, ante 10 of 16, $193).** The bot scores it −0.565:
  the hand it takes −0.601 (`CAPACITY_WEIGHT` 3.6 × log(5.5/6.5), 5 hands and 3 discards), the ante back +0.1
  (`VOUCHER_WORTH`, never measured), $10 −0.063. The ante back should be worth what an extra ante of rounds and shops
  is: little at ante 2, a lot past ante 8 in a game to 16 (Plasma Small Blinds: ante 9 220k, 10 1.12M, 11 14.4M, 12
  600M). Value it from the
  targets (the ante it returns to against the next) and the shops it adds; same horizon question as the next item.
  Petroglyph the same with a discard.
- **No consumable swap in the shop (asked 28 Oct, MLQUG157).** With the consumable slots full, a Tarot that must be
  held (one needing cards: The Chariot, Justice...) isn't weighed at all (`_shop_action`: `consumable_room` or
  nothing). Jokers have the swap (the weakest sold for room); consumables need the same: sell the held card worth least
  (keep_worth) when the offer's keep worth beats it by the net price. On MLQUG157 it wouldn't change the move (Strength
  and Justice +0.020, The Chariot +0.021, $1 each: Plasma with ~1,000 chips makes xMult cards near nothing).
  **Written 28 Oct 15:00:** `CONSUMABLE_SWAP` (the held card worth least sold for an offer worth `w.sell_margin`
  more; not with Perkeo), off; queued after the pack sweep. **Set 90210: +0.0 ± 0.3 (28 Oct 17:41), set 777: +0.2 ±
  0.2 (18:58)**: almost never changes a game; a fix, level, **adopted 28 Oct 19:00**.
- **Longevity.** Everything is valued as a change to today's power, as if it lasted the run: a joker likely replaced
  in two antes counts like a voucher that stays, and Bull's chips lost by spending as if Bull stayed. Value per round
  times the rounds it is expected to last: the run for vouchers, levels and cards; fewer for jokers (the weakest of a
  full row soonest). Same pattern as today's finding that measured values for lasting things (Tarot enhancements,
  levels) come out low against the tuned flat weights.
- **Surplus.** Power counts the same whether the build clears blinds with room to spare or barely. With room, money
  and scaling should win over scoring now (the user's point on Reserved Parking: "by the time it matters I'll have the
  profit"). The skip rule already has a margin (`boss_margin`, `skip_safety`); shop values don't. **Measuring the
  other side first (28 Oct, `logs/sweep_money.log`)**: losses die holding the $35 interest reserve (81 of 92 with
  $20+, `runs/analysis/losses.txt`); `RISK_MONEY` (money worth less the likelier the next boss ends the run) and
  `END_MONEY` (nothing in the run's last shop, interest only over the shops left), off. **RISK_MONEY lost (11:35)**:
  0.25 −5.8 ± 2.2 and −3.1 ± 2.4 points on the two sets, 0.5 −9.4 ± 2.3: the less money counts in danger, the worse.
  Money looks worth more than the weights, not less: next test the safe side, money and interest weights raised
  (everywhere, then only with room to spare). END_MONEY level on both sets (+0.6 ± 0.7, +0.6 ± 0.8): adopted 28 Oct.
  **`MONEY_SCALE` (money and interest weights times it, everywhere): 1.25 +4.8 ± 2.2 on set 90210 (28 Oct 18:00,
  53.5% against 48.8%)**, the first gain of the day; **1.5 +4.6 ± 2.4 (53.3%, progress +0.14)**: a plateau. **1.25
  on set 777: +4.2 ± 2.3 (57.9% against 53.8%, progress +0.28): adopted 28 Oct 19:20** (both sets +4.5 ± 1.6). 1.5
  on set 777: +1.5 ± 2.5 (55.2%; both sets about +3.0 ± 1.7): 1.25 stays. 2.0 on set 90210: −2.3 ± 2.6, progress
  −1.35 ± 0.30: too much, 1.25 is the peak. Next: new baselines with everything adopted; then money
  worth more only with room to spare (Surplus), and money and interest scaled apart. **`SURPLUS` written 29 Oct
  04:55 (strategy.py, off):** money and interest times 1 + SURPLUS × (2 × odds − 1) where the odds of beating the
  next boss (as RISK_MONEY reads them) are better than even. First a probe of those odds at each shop (48 seeds of
  set 4242, `logs/probe_surplus.log`): if nearly every shop is safe it is only a bigger MONEY_SCALE. **Probe (06:02,
  96 seeds, 42 won):** winners' shops are mostly safe from ante 3 (median odds 0.88-0.98 at antes 3-5, 0.67-0.74
  after), losers' at ante 3 only (0.78; 0.33 and less from ante 6): SURPLUS would mostly raise money for runs that win
  anyway, and to ×1.4-1.7 at antes 3-5, where 1.5 everywhere was a plateau. Low priority. Both arrive at shops with
  $42-67 from ante 4 and spend down to the $35 reserve (`probe_reserve.py`, 11 games: cap 5 throughout, 4-7 rerolls
  in a rich shop). **`RESERVE_EXTRA` (the reserve's $10 beyond what earns the most interest, never measured):
  queue 15, 0 and 20 on set 90210.** **Done 29 Oct 11:37: 0 -2.7 ± 2.0 (52.5%), 20 -2.3 ± 1.9 (52.9%), progress
  level: 10 kept.**
  **`INTEREST_SCALE` written the same hour (off: None, as MONEY_SCALE):** interest alone at its own share, to try
  1.0 and 1.5 with money at 1.25 (losses die holding the interest reserve: is it interest or spending that's mis-weighed?).
  **Queue 14 (29 Oct 09:45), set 90210 against l-luck: 1.0 -5.0 ± 1.8 points (50.2%), 1.5 -2.7 ± 1.9 (52.5%),
  progress level. Rejected: interest at money's 1.25 is the peak.** Lowering interest alone loses about all of the 28
  Oct MONEY_SCALE gain (+4.5), so that gain was interest's; the reserve that losers die holding is not interest
  over-weighed. Seed Money and Money Tree (interest cap $10, $20) are still a flat 0.25, about Seed Money's $10 price
  at the shop's $0.025; by the bot's own interest weight (0.1 a $ a round, ×1.25) its $5 more a round is worth up to
  ~0.6 while the purse holds $50 (shops from ante 4 see $42-67). Owning it lifts the reserve to $60, so it also
  changes the spending. **Queue 19 (after queue 18, ~22:25): Seed Money 0.6, then 1.2, set 90210 against g-guard.**
  Money Tree after, if it gains; if a flat weight helps, make it dynamic (the interest the purse would add).
- **Invisible Joker.** Buy values ignore its copy: a strong or Polychrome joker is worth more as its target, every
  extra joker dilutes the draw, and a player sells the others first to force the copy. Same fix shape as Perkeo.
- **Packs are flat weights** (Celestial 0.20, Arcana 0.25, Spectral 0.35, Buffoon 0.30, Standard 0.05). Measured
  Celestial (`CELESTIAL_MEASURED`) was even on the pre-honesty bot; retest now, with a trust factor like KEEP_TRUST.
  **Next, raised 28 Oct (ALEEB, to ante 16):** since KEEP_TRUST 2 a single Tarot outbids a pack of three. Ante 1's
  first shop, $5: The Empress $3 +0.250 against the Arcana Pack $4 +0.070 (with KEEP_TRUST 1: +0.045, the pack
  bought; it held The Soul, Triboulet, the run won to ante 10; today's bot dies at ante 8's boss). Only KEEP_TRUST
  changes ALEEB (each 28 Oct switch toggled alone, scratch `aleeb.py`). An Arcana or Spectral pack: the best of its
  cards' keep worths (KEEP_TRUST and all), estimated over the pack's possible contents. **Written 28 Oct 14:45:**
  `PACK_MEASURED` (that; `pack_worth`, 6 of the pack's possible cards a shop) and `PACK_TRUST` (the flat weight times
  KEEP_TRUST), off. Measured at ALEEB's shop the pack is 0.233 to The Empress's 0.41: today's bot was right and the
  27 Oct win was The Soul's luck; PACK_TRUST buys the pack (+0.32). **Both lost (28 Oct 17:02,
  `logs/sweep_packs.log`)**: PACK_MEASURED +0.4 ± 2.2 and −5.0 ± 2.3 (both sets −2.3 ± 1.6; 88 s a game against 40),
  PACK_TRUST +0.8 ± 2.2 and −5.2 ± 2.3 (−2.2 ± 1.6); each changes about half the games. Packs valued higher than the
  tuned flat weights make the bot worse; the weights stay. Closed.

## Strategy

- **Depth, and the run's length changing the bot (the user asked how changes affect max ante, 29 Oct 14:00).**
  Depth check, the first 96 seeds of set 90210 played to ante 16 (`logs/depth_check.log`): before-money 37.5% beat
  ante 8, mean ante 7.74, 29% reach ante 10, none 12; 27 Oct 51.0%, 8.25, 33%, none; today's 37.5%, 7.60, 25%, 1%
  reach 12. Nobody gets past ~ante 11. **Today's bot beats ante 8 in 51% of these seeds in runs to 8, 37.5% in runs
  to 16** (16 games won only in the short runs, 3 only in the long): rounds_left counted to the run's last boss, so a
  run to 16 values income, growth and keeps twice over from ante 1 and plays the long game early. The 27 Oct bot
  isn't hurt (51% both): the 28 Oct valuations are what scale with it. The run viewer and Play tab run to 12 by
  default, so the bot the user watches (and the hints) played this weaker game. **`HORIZON_CAP` written 14:45**
  (modifiers.last_ante: to ante 8, or 4 antes ahead past ante 4; a run to 8 plays as before), off. Quick check on the
  96 seeds (`logs/depth_cap.log`): 45.8% beat ante 8, mean ante 8.02, 32% reach 10 (uncapped 37.5%, 7.60, 25%).
  **Controls (15:01):** today's code with every new switch off, runs to 8, both harnesses: the same 96 games as
  g-guard, 49 won: the drop is the run's length alone. **The user (14:50): don't make it play only to ante 8, prepare
  for the hardest antes.** So the fix is **`SURVIVAL_HORIZON`** (ValueBot.survival_rounds, off): each ante ahead
  counted by the chance the run gets there, from the build's margin over a random boss growing 1.6x an ante against
  each ante's real target (calibrated on 24 games' shop margins, `logs/margin_probe.log`: scale 1.4; antes 1-2 at 97%
  from the median ante-3 margin 2.4), discounted 0.85 an ante. Ante 1 of a run to 16 counts 13.1 rounds (old 24, a
  run to 8 12.7); at ante 5 a build at margin 3 counts 12.7, at 1.0 7.4. The cap stays a control. **Queue 22** (after
  21): h-surv16 and h-cap16 against d-off16, h-surv8 and h777-surv8 against g-guard and g777-guard.
  **Queue 22 (16:14-17:00): SURVIVAL_HORIZON to 16 237/480 (49.4%), +8.1 ± 1.9 points against d-off16, progress
  +1.28 ± 0.22, 38.5% reach ante 10 (29.6%), 0.6% reach 12; the cap (control) 50.2%, +9.0 ± 1.9, 39.0%, 1.2%; to 8:
  -0.2 ± 1.3 (54.6%) and -1.9 ± 1.3 (55.2%), progress +0.05 and -0.10. A fix, level in runs to 8: adopted 17:05**
  (default on; three tests that use the old rule's arithmetic pinned to it). Queue 23: new baselines on today's
  defaults (n-base, n777-base, n-base16), then the plan on them (n-plan, n-plan-w3, n777-plan, n-plan16); queues
  17-19 moved to that code and those baselines after it (k-rr15 had just started on the old code: stopped).
  **The plan bot to 16 (same 96 seeds, 15:10):** 33.3% beat ante 8, mean ante 7.40, 21.9% reach 10 (today's 37.5%,
  7.60, 25.0%); 28 seeds deeper, 32 shallower, 36 the same: no better in long runs, and it carries the same long
  horizon. Its runs to 8 are queue 21's b-plan and b777-plan; with SURVIVAL_HORIZON, a combined run after queue 22.
- **LUCK_EXPECTED, why level (the user asked, 29 Oct 10:15).** 373 and 371 of 480 games play the same with it; the
  rest flipped 39 to wins and 41 to losses over both sets. A replay of the flipped games to their first differing
  decision (`logs/lucky_diverge.log`; 76 of 80 done, every replay matching the measured result; hung at 0% CPU at
  152/160 and stopped 13:22): first difference (to win / to loss) a play with a Lucky card, Bloodstone or Misprint in
  hand 14/12, a discard with one 8/11, a shop 6/8, a pack 3/2, other discards 3/2, uses 1/3, other plays 1/1. No
  part clearly helps: averages are no better than ignoring chance. What should help is playing for the odds of
  reaching the target (LAST_HAND_ODDS, queue 18); discards might keep LUCK_EXPECTED off (8/11, not significant).
- **Consumable room (the user's catch, 29 Oct 10:20, RZ364T64 Abandoned Deck).** Cards that make cards make only
  what fits: The Emperor used with The Moon held made 1 Tarot of 2 (antes 2, 3, 5), and Cartomancer made nothing at
  ante 1's boss and ante 2's Small Blind (both slots full). The Moon sat in a slot from ante 1 to 3, then was sold.
  Wanted: a creator's use worth only what fits (and using or selling a held card first when what it makes is worth
  more), and a held card charged for what it blocks (Cartomancer, 8 Ball, Purple Seal, Hallucination,
  Superposition, Séance, Vagabond, Sixth Sense). **Paused 10:40 for the build layer (the user's priority).** Where
  it stands: a use is weighed by `effect_worth` on a copy of the run, so The Emperor with one slot free is worth one
  Tarot; nothing tries selling (`sell_consumable` exists in run.py) or using the held card first. Next: in `_use`
  and the pack picks, for a creator short of room, the held card worth least (keep_worth) sold or used first when
  one more created card is worth more; in the shop before leaving, the same with Cartomancer owned.
- **Engine planning (the user's E8G18YRT, Ghost Deck, to ante 14 on their phone; 29 Oct 10:24).** Their build:
  DNA + Brainstorm (copying DNA) on one-card plays, Steel Red Seal Kings held with Mime, Blue Seal Steel Queens
  making Plutos (High Card level 75), Cavendish, Baseball Card. The bot on the same seed (gameseed.py: the game's
  shops, packs and deck order) dies at ante 6 with Wee Joker, Satellite, Mime, Jolly Joker, Card Sharp
  (`logs/user_run_worths.log`): DNA ($8, ante 6) under every joker it owned, Pluto 0 in every pack (it never plays
  High Card), The Chariot and Mime only at ante 6. Each piece is worth little alone; a player buys toward the
  engine. A build layer: known engines (held Steel/Kings + Mime + Red Seals; DNA + one-card hands; Blue Seal + Mime
  into Planets for one hand) valued by what the run becomes with the next pieces. **Top priority (the user, 10:40).
  Design approved 11:00: `docs/superpowers/specs/2026-10-29-build-planning-layer-design.md`** (an engine library:
  held Steel/Kings, DNA, levels, Flush; plan worth from projected runs at the shops' odds, no peeking; steering of
  buys, rerolls, Tarots, Planets, discards, plays). Step 1 (framework + held + dna) measured ahead of queues 17-19.
  **Plan: docs/superpowers/plans/2026-10-29-build-planning-layer.md (two reviews; the second applied it to a scratch
  copy and ran it). Built 29 Oct 11:45-12:30:** step 0 `POWER_PAIRED` (queue 20 measures it after queue 16); step 1:
  `balatro/engines.py` (odds from the shop's rates, the held and dna engines), the plan in ValueBot (joint
  projection, V with each chance once, choice with PLAN_MIN/PLAN_SWITCH, plan_worth beyond today where today is
  measured, the whole gain where it is flat, plans only for the live run), hooks (adjust: jokers bought/sold, packs,
  Paint Brush; consumable uses and keeps with preferred targets; playing cards; rerolls; discards keep held cards;
  plan_hold_cost in play_bonus), eval_value `--max-ante` and the per-game plan log. 19 tests in
  tests/test_engines.py. **Speed (Task 9):** first 7x a game (70 s against 10 s, 16 seeds), the plan flickering on
  and off. Profiled: card-by-card measures on 36/24 hands and a thrashing candidates cache. Fixed: PLAN_HANDS 12
  and PLAN_CARD_HANDS 8 (shared caches), candidates cache 512 -> 4096 (a memo: decisions unchanged), a missing piece's
  expected gain never below 0 and a plan kept at the floor (no flicker), plan worth for sells only on plan pieces and
  for buys only on pieces, starters or when a piece would be pushed out, one more projected change measured once a
  decision (deck_change_worth adds cards one by one), the replaced joker remembered per row. Now 2.2-2.5x (7.9 s
  against 3.1, 23 s against 10.5; same games). Queue 21 (b-plan, b777-plan, d-off16, d-plan16) queued after queue
  20 if the suite passes. **Queue 21 (15:05-15:42): b-plan 265/480 (55.2%) +0.4 ± 1.5 points against g-guard,
  b777-plan 272/480 (56.7%) -0.4 ± 1.5 against g777-guard, progress -0.04 both: level, not adopted (stays off).**
  The plan logs: held+dna the final plan in 341 and 334 games, held alone 124 and 132: it commits to held nearly
  always (scores small but positive, PLAN_MIN 0) and plan worth at that size seldom changes a decision. Next: PLAN_WEIGHT
  2 and 4, PLAN_MIN above 0 (commit only when an engine is near), then the levels and flush engines. d-off16 (today's
  bot to 16): 41.2% beat ante 8, -13.5 ± 2.0 against the same seeds to 8; 29.6% reach ante 10, 0.8% reach 12.
  **d-plan16 (16:14): 213/480 (44.4%), +3.1 ± 1.6 points against d-off16, progress +0.11 ± 0.16; 31.2% reach 10,
  0.4% reach 12; 87 seeds deeper, 69 shallower.** In long runs the plan helps (about 2 SE), where the long horizon
  weakens the base bot; in runs to 8 it is level. Re-measure with SURVIVAL_HORIZON once queue 22 says whether it
  fixes the base.
  **Queue 23 (17:14-18:37): new baselines n-base 256/480 (53.3%), -1.5 ± 2.3 against g-guard, n777-base 264/480
  (55.0%), -2.1 ± 2.4 against g777-guard (the two adoptions together, level); n-base16 (to 16) 244/480 (50.8%), +1.5 ±
  2.3 against h-surv16: runs to 16 now 2.5 points under runs to 8 (13.5 this morning). n-plan 251/480 (52.3%), -1.0
  ± 1.5 against n-base; n-plan-w3 (PLAN_WEIGHT 3) 250/480 (52.1%), -1.2 ± 2.0: level, the plan stays off.** The
  per-game plan logs (runs/value/eval_n-plan*.json): held is the first plan in all 480 games (the starting deck's
  Kings count a third of it; dna starts at 0); held completed in 13 (14 at x3), dna in 8 (14); 255 games never add a
  held piece (Baron rare, Mime uncommon). Tripling the pull changes 92 games' result against n-base, not 49, and
  they cancel. So the weight is not the lever: step 1's engines are too rare to matter by ante 8. Next: step 2
  (levels: one hand with Planets) and step 3 (Flush), the engines most runs can reach; n777-plan and n-plan16 (does
  the plan help long runs on top of SURVIVAL_HORIZON) still to come.
  **The user (18:50): DNA is a deckbuilding tool, an element of a strategy, not a strategy.** In E8G18YRT it copied
  Steel Red Seal Kings (held) and Blue Seal Queens (Plutos): one joker, two strategies. Step 1 half-treats it so
  (fits held and levels, projected last) but scores it as an engine of its own, lets it start a plan, and copies a
  fixed guess (`_copy_rank`: Steel or Glass, Red Seal, Polychrome, King, rank), not the strategy's card. Redesign:
  **strategies** (what wins rounds: held, levels, Flush; later face cards, Glass, retriggers) are scored and chosen;
  **tools** (DNA; later Cryptid, Death, The Hanged Man, Trading Card, Strength, Sigil, Ouija) have no score of their
  own, join the plan of whichever strategy is main, and are worth what they add to it: each strategy names its key
  card (held: a Steel Red Seal King; levels: a Blue Seal card; Flush: the best card of its suit), the card a tool
  copies. Also: held's progress counts the starting deck's Kings (a third of it in every run). The choice itself is by
  score, not progress, so this skews only which fitting engines join and the log's finish rate: progress to count what
  the run has added. Spec section 5 revised.
  **n777-plan (19:04): 257/480 (53.5%), -1.5 ± 1.5 against n777-base: step 1 level on both sets.**
  **Step 2 measured (queue 24):**
  - f-plan −0.4 ± 1.8 (52.9%) and f777-plan −0.4 ± 1.7 (54.6%).
  - f-plan-noflush (held, with DNA as a tool) +0.8 ± 1.5 (54.2%), progress +0.03 ± 0.09.
  - All level: Flush adds nothing, and the restructure alone is level too. f-plan16 skipped at the user's word.
  - **The plan pauses here** (off): the bot-play fixes pay more (z-base +3.3).
  - When it resumes:
    - Flush's choice: 85% of games, its score inflated by the suit's Tarot and Hanged Man projections in any deck.
    - The suit locking on the first suit joker.
    - Levels.
  **n-plan16 (19:41): 237/480 (49.4%), -1.5 ± 1.5 against n-base16, progress -0.20 ± 0.15; 37.5% reach ante 10
  (n-base16 40.6%), 0.8% reach 12 (0.8%).** Step 1's +3.1 in runs to 16 (d-plan16) was making up for the old horizon:
  with SURVIVAL_HORIZON it adds nothing to long runs either.
  **Step 2 built (29 Oct 18:55-19:25; Flush ahead of levels):** a levels strategy would mostly count twice what
  level_worth already counts (a Planet is valued by today's power; a plan expecting more levels would even rate the
  next one lower, log power being concave in levels); Flush needs commitment across decisions (suit jokers, the
  suit's Tarot on off-suit cards with fewer than 3 of the suit in hand, The Hanged Man on off-suit cards). Built:
  Engine.kind (strategy or tool) and key (the card a tool copies), DNA a tool, held's progress without the starting
  Kings, `FLUSH` (suit from the first suit joker owned, else the deck's most common; its Tarot and The Hanged Man
  projected; prefers off-suit targets), `_plan_after` switching to a strategy that doesn't fit the main one only when
  it would score PLAN_SWITCH more. Found on the way:
  - **A large group wins for being likely, not good.** Flush's 11 jokers (0.61 over 2 antes against held's 0.25)
    scored 0.66-0.72 against held's 0.02-0.18 in every test setup, Baron + Mime + 3 Steel Red Seal Kings included:
    the best one (Onyx Agate, +7 Mult a Club) is a strong joker on its own. A plain Joker as yardstick didn't help
    (Onyx Agate beats it by 0.4 power). `PLAN_SYNERGY`: a missing joker counts only for what the projection adds to it
    beyond what it adds today; its own worth comes either way. Held then wins there 0.075 to 0.029, and the two are close
    with Baron alone on a plain deck (fair: 4 plain Kings).
  - **Flicker:** scores of 0.005-0.07 flipped the main strategy flush/held 6 times a game on the 25% share alone.
    `PLAN_MARGIN` 0.02: a switch needs that much more too, and a plan is dropped only below PLAN_MIN less it.
  - **Speed:** 95.8 s a game against 19.0 off (55.2 without Flush), 12 seeds: `_best_of` tried Flush's 11 jokers for
    every option (now once a decision), Flush's projected changes were new closures each call so `_one_change`'s memo
    never hit (now one function a suit), and a plan_worth asked the same V up to 3 times (now remembered within it).
    `_one_change` and `_best_of` also keyed their memos on the previous decision while `_plan` scored (stale; fixed:
    `_decision` set first).
  - **deck_change_worth is additive** (scratchpad suit_bias.py, dcw_bias.py; logs/dcw_bias.log). On single changes it
    is unbiased within its spread against 3000 paired hands (Mult on 3 low cards +0.081 against +0.073; Mult on 3
    Kings +0.120 against +0.087; Bonus, Glass, Steel, Steel with Baron, one suit Tarot, The Sun with Lusty all within
    noise; spread 0.006-0.13 a decision): no bug in the bot's own Tarot decisions. Changes made together are not:
    3 Tarots to Spades -0.010 against +0.125 ± 0.009, 6 Tarots -0.19 against +0.58 ± 0.04 (a suit's concentration
    is worth what no single card's change shows). Over the plan's 2-ante horizon the projection holds ~0.4 of a suit's
    Tarot, so it hardly matters now; **a joint measure (paired hands over the projection's in-place changes) is
    needed for a longer horizon or for scoring a whole Flush build** (cost: ~1.7 ms a hand, sd ~0.5 a hand for 3
    Tarots: 100+ hands for a useful answer).
- **Two-step wins that keep what pays held (the user's catch, 29 Oct 10:30, RZ364T64 ante 5 Big Blind).** The bot
  takes any one-hand win: Two Pair with the Gold 8 it had just made with The Devil (22,470 of 16,500, the only
  one-hand win) over the Flush that kept it (14,525) and a small hand after, with 5 hands left ($3 lost; the card
  isn't, it is played, not destroyed). And a Glass card's 1 in 4 break is priced nowhere (play_bonus): among plays
  that win, one without the Glass card should come first. Repro: scratchpad `gold_play.py`.
- **`INCOME_AT_MARGIN` (the user's "there has to be balance", 29 Oct 10:15; to write).** Income is counted at the
  full money weight for every round left (modifiers.income), spending at spare_money (0.1) above the reserve
  (price): the bot's two rates for one dollar. From ante 4 it arrives at $42-67, so most of a payer's money lands
  above the reserve. Count income at the bot's own margin (full while below the reserve, spare above); then
  PAY_FROM_PLAY on top (its estimates are closer to what payers pay; they lost only at the full rate).
- **Voucher choices (the user: "skips a lot of good vouchers for mediocre jokers", 29 Oct 10:28). Checked 11:20**
  (RZ364T64 to ante 12 and 16 eval seeds; scratchpad `voucher_probe.json`, `voucher_analyze.py`): of 123 voucher
  offers (one voucher for an ante), 50 bought, 12 never affordable, 47 never worth their price when affordable, 14
  worth it at some point and not bought; a joker came first while a voucher was worth buying 16 times (8 bought later
  in the ante). **All 41 games (11:50, 19 won):** 306 offers, 125 bought, 119 never worth their price when
  affordable, 40 worth it at some point and not bought; another buy beat a voucher worth buying in 121 decisions (44
  bought later in the ante). Avg net at first sight: Grabber +0.49 (14 of 15 bought: measured), Overstock +0.08,
  Seed Money +0.05, Clearance Sale +0.04, Crystal Ball -0.02, Paint Brush -0.19 (gross +0.05: the noise), Director's
  Cut -0.16 (0 of 28), Hieroglyph -0.75 (0 of 17). Causes:
  1. Flat `VOUCHER_WORTH` (0.05-0.4, never measured) against today's prices: `price()` charges a $10 buy 0.500 at
     $25 or less, 0.375 at $30, 0.250 at $35, 0.138 at $40, 0.025 from $45 (interest lost at 0.125 a dollar since
     27-28 Oct), so a flat voucher clears its price only above ~$40; jokers bought have a median net of 0.47.
     KWD6CFXZ a4 $33: Grabber +0.27 lost to Baseball Card 0.76; QPNVXV9M a3: Seed Money +0.10-0.17 lost to Banner,
     Chaos the Clown, Supernova.
  2. **Paint Brush and Palette measured on noise:** `power`'s sample positions are keyed by hand size, so n and n+1
     cards are different hands (12 salts on 11 states: mean +0.02 to +0.32, sd 0.06-0.31, single readings -0.42 to
     +0.96). Likely the same for jokers that change hand size (Juggler, Turtle Bean, Troubadour, Merry Andy,
     Stuntman). **`POWER_PAIRED` (positions drawn once for the largest hand, smaller hands the first n of each): step
     0 of the build layer**, a correctness fix. **Queue 20 (29 Oct 14:30): +1.7 ± 2.1 and -1.5 ± 2.3 points, progress
     +0.19 and -0.21 ± 0.20: level, adopted** (it reshuffles every decision's sample hands a little, so many games move).
  3. Past ante 8 every voucher counts 0.25 of its weight (`late`, VOUCHER_ANTES), Antimatter 0.8 -> 0.2.
  4. Crystal Ball's flat 0.2 ignores what full slots block (The Emperor, Cartomancer; see Consumable room).
  Proposed after the build layer's first steps: `VOUCHER_SCALE` (the flat part x1.5, x2) on set 90210, then
  `VOUCHERS_MEASURED` (Clearance Sale and Liquidation from the run's spend a shop, Reroll Surplus/Glut from its
  rerolls a shop, Overstock from `_reroll_hope`, Crystal Ball from cards blocked, Antimatter from the weakest joker).

- **`USE_GUARD` (written 28 Oct 23:20, off; queue 10, `logs/sweep_queue10.log`; asked by the user).** In a round
  the value bot weighs a Tarot's use by the deck's change over power's sample hands (the long run) against a flat
  keep weight, never by the hand held: on C5X6MXUN it used Strength on a 9-8-7-6 straight's 9s (60,750 lost to a
  +1 chip a card). Now a use that lowers the hand's best play waits (weighed again next decision). On in the hint.
  Deeper: weigh using now against using after this hand, and Strength's targets for what they complete.
  **Set 90210: −1.7 ± 0.9 points, progress +0.00 ± 0.07 (29 Oct 02:29); set 777: −0.2 ± 1.0, progress +0.07 ± 0.04
  (03:17). Both sets −1.0 ± 0.7: not adopted.** It held back Tarots
  whenever the hand's best play dropped, also with the round won either way. **`GUARD_AT_RISK` (written 02:50;
  queue 13, `logs/sweep_queue13.log`):** only when the use costs the round (the best play won it and no longer does,
  or every hand left at the best play got there and no longer does). **Measured with USE_GUARD, against p-money:
  −0.2 ± 0.7 and +0.8 ± 0.7 points (both sets +0.3 ± 0.5), progress +0.05 ± 0.05 and +0.09 ± 0.04 (29 Oct 08:09).
  Level, a fix: both on for every bot since 29 Oct 08:10** (value-27oct pins USE_GUARD off). It was measured without
  LUCK_EXPECTED; queue 16 (`logs/sweep_queue16.log`) plays the two together against l-luck and l777-luck, and those
  runs (g-guard, g777-guard) are the baselines from then on. Still open: using now against using after this hand,
  and Strength's targets for what they complete.
- **`DISCOUNT_FIRST` (written 28 Oct 23:20, off; queue 9, `logs/sweep_queue9.log`; the user's point).** The shop
  picks one buy at a time by worth, so a pack (+0.19) went before Liquidation (+0.13) and paid full price. Now a
  discount voucher (Clearance Sale, Liquidation) the bot would buy here goes before the cards, packs or rerolls
  it would buy. On in the hint. Next: count the voucher's saving on this shop's offers in its worth too.
  **Measured (29 Oct 01:33): −0.2 ± 0.8 and −0.8 ± 0.8, progress +0.05 and +0.00 ± 0.04: level, both a shade down;
  not adopted for the bot, stays in the hint** (for a person it is pure order). Likely why: it checks the voucher's
  worth, not that the money covers both, so when it doesn't the voucher replaces the better buy. If retried: only
  when the money covers the voucher and the discounted buy. Low priority (it changes few games: ±0.8).
- **`GROWN_FROM_NOW` (written 28 Oct 23:10, off; queue 8, `logs/sweep_queue8.log`).** Ride the Bus and Obelisk were
  projected at their steady state from scratch (`_grown_value`: p/(1−p), capped at the hands ahead), whatever they
  had built: C5X6MXUN's Bus at +24 (2 face cards in 41) counted as heading for +6, its growth worth negative, owned
  +0.14, and the hint sold it for a Runner at 0. Now p^N of what it built is kept over the N hands ahead, plus the
  growth: owned +0.53, no sale. On in the Play tab's hint at once (HINT_SWITCHES). **Measured: +0.0 ± 0.5 and +0.6 ±
  0.5 (progress +0.04, +0.08 ± 0.04): a fix, level, adopted 29 Oct 00:00.**
- **Lucky cards in play (asked 28 Oct 22:50).** The hint picks a plain pair over a pair holding a Lucky card (1 in 5
  +20 Mult, 1 in 15 $20). **Cause (29 Oct 01:50):** estimates roll chances with NO_LUCK, so a Lucky card never
  comes off: it counts for nothing in play (Bloodstone's Hearts too; only consumables' deck valuation, `_as_scored`,
  counted it as a Mult card). Reproduced: one hand left, 1,000 to go, it plays a Flush (296, can't win) over a
  Straight holding two Lucky cards (260, 780 on average, wins 36%). **`LUCK_EXPECTED` (bots.py; queue 11,
  `logs/sweep_queue11.log`):** a chance that scores counts as its expectation (Lucky +4 Mult, Bloodstone X1.25,
  doubled by Oops! All 6s); a play only counts as winning if it wins with no luck (`surely_wins`). **Measured: +0.8 ±
  1.3 and −0.6 ± 1.4 points (both +0.1 ± 1.0), progress +0.04 and +0.13 (+0.08 ± 0.07): a fix, level, adopted 29 Oct
  04:55** (on for every bot; a run's own `expect_luck` overrides it). New baselines: l-luck (55.2%) and l777-luck
  (56.7%). Not yet: the Lucky $20 (1 in 15) in the play's worth. **`LAST_HAND_ODDS` (written 29 Oct 08:18, off;
  queue 18, `logs/sweep_queue18.log`, after queue 17):** on the round's last hand with no play sure to win, the
  play likeliest to reach the target (`bots.win_odds`: its Lucky cards, Bloodstone and Misprint rolled 200 times),
  not the best on average: a sure Flush of 296 never makes 500, a pair of Kings with a Lucky one (180 on average)
  does 1 in 5. Against g-guard and g777-guard.
- **Bug, first: the bot's round play depends on its history (28 Oct 12:26).** RZ364T64: after the whole game it
  throws a pair of Kings and loses the round (65,932 of 70,000); fresh on a copy of the round's start it wins
  (74,436). Held two Mercury. **Cause: power's cache** (Blue Joker reads the draw pile, jokers grow in place; the key
  sees neither). Fix `POWER_EXACT`: level (−0.4 ± 1.3, +2.1 ± 1.4), no slower, **adopted 28 Oct 14:25**. Then: power itself depends on
  when it is called (the shop's leftover pile for Blue Joker, the round's hands and discards left): it should be
  "as a round starts" everywhere (`_as_round_starts`: a full pile less a hand). **Written 28 Oct 15:00:** `POWER_PILE`
  (out of a round, the pile a round starts with), off; queued after the pack sweep. **Set 90210: +0.6 ± 0.6 (28 Oct
  17:23), set 777: −0.6 ± 0.6 (18:38): level, adopted 28 Oct 18:40** (server restart waits for the money result).
  `fair_rounds.py`'s `bot_again` counts the lost rounds a fresh bot wins.
- **Play of the deciding round: measured 28 Oct 14:03, a small lever** (`scripts/fair_rounds.py`,
  `runs/analysis/fair_rounds.json`): fair play (each move over 32 shuffles of the unseen cards) won 37 of the 92 lost
  rounds, but the bot's own odds there averaged 0.33 (30 expected with fresh draws: a third of the losses are the last
  round's luck; 28 lost as the favourite); the best first move 0.39 (35.4). Real gain ~5-7 rounds of 92, 5 of them the
  cache bug (a fresh bot alone wins); 24 hopeless whatever the play. Maybe +1-3 points of games at 15-60 min a round:
  not worth building now. The build (antes 7-8, xMult, Violet Vessel) is the bigger share. Was proposed as: In the loss analysis (`runs/analysis/losses.txt`, 92
  losses) the primary causes are: misplayed the deciding round 37, build too weak 32, the boss's effect 23 (Violet
  Vessel 13). The 37 come from `analyze_losses.search`, a beam search that sees the cards to come in order, which the
  bot can't: an upper bound. First a fair version (the cards left in the deck known, as in the game's deck view, their
  order not: decide each step over sampled shuffles of them; face-down cards unseen, `scripts/probe_leaks.py`), replayed on those rounds. If it wins a real share, a search for tight
  rounds in the bot. Also count winners with no xMult joker by ante 5 (the losses: 53 of 92), never measured.
- **Winners against losers, by ante (29 Oct, `logs/probe_surplus.log`, `runs/analysis/probe_surplus.json`).** At
  each ante's first shop, losers still alive own as many jokers and as many xMult jokers as winners (more at antes
  2-3 and 6-7: 0.21 vs 0.14, 0.81 vs 0.60), the same levels and about the same money; winners' power is ahead by
  0.3-0.6 from ante 2 on. Not xMult missing: which jokers, and how they fit, differ. (The "no xMult by ante 5" item
  above: winners 48%, losers 61% at ante 5, but the reverse at 6-7.)
- **Weights set before 27 Oct, never retuned (queue 17, `logs/sweep_queue17.log`, after queue 16).** MONEY_SCALE
  (+4.5) showed a weight tuned before the honesty changes can be off by a quarter. One at a time on set 90210
  against g-guard, from queue 16's snapshot (the same code): REROLL_SHARE 0.15 and 0.4 (0.25), sell_margin 0.05 and
  0.2 (0.1, the margin a joker swap needs), skip_shop 0.1 and 0.5 (0.25, the shop a skip gives up), skip_safety
  1.0 and 1.6 (1.25). Any gain confirmed on set 777 before adoption. Noted on the way: MONEY_SCALE reaches the shop
  only (`shop_action`); the skip rule weighs the blind's money and a money tag both at the raw weight (consistent).
  Not patchable from the harness yet: rarity (a tuple), the voucher weights (Seed Money and Money Tree a flat 0.25,
  never measured: the cap stayed 5 in every shop of the reserve probe).
- **A build layer.** Triboulet sold at ante 5 for Swashbuckler (ALEEB): a joker is valued on today's deck, not the
  deck it could make. High Card runs only happen by accident (6 of 64 runs, 4 won). A chosen hand has to steer
  everything at once: shop values (done, `TARGET`), discards toward it (Straight: keep connected ranks, throw
  duplicates), Tarots shaping the deck for it (Strength, Hanged Man, suit Tarots for Flush), Planets, and rerolls for
  its key jokers (Four Fingers, Shortcut). Only then is "does choosing an approach win?" a fair question.
- **Higher stakes.** Green Stake and up beat ante 8 about 10% of the time or less (survey, 27 Oct): the next big
  target after White Stake.
- Earlier list: level undervaluation, Fool/Planet planning (lookahead), Violet Vessel.

## Cleanup

Done 28 Oct on the user's go-ahead: the `frozen*` snapshots (measure.sh makes new ones per run),
`runs/analysis-20261026-1852` and `-20261027-0001`, `straight_use.broken.*`, the idle workers from 25 Oct and the
Sunday waiter shell. Probe scripts stay in the session scratchpad (small; `perkeo_eval.py` is cited above). The Balatro
Lab server was restarted on today's defaults.

## The board (Play tab and run viewer)

- **Odd-shaped jokers' cards and shadows (the user, 30 Oct 15:10): fixed.** Footage (Roffle Lite's "Stop Doubting
  Square Joker" at 15:00; a Half Joker short): Square Joker and Half Joker sit centred where a card would be, their
  shadow their own card's shape. Ours drew their art at the top of a full card with a full card's shadow. Now
  (cards.js JOKER_SHAPES, cards.css, style.css #shades): Half Joker, Square Joker and Photograph's art moved down by
  half the height it lacks, the debuffed cross on the card alone, and the shadow in the joker row sized and placed to
  the card; Wee Joker's shadow 0.7 of a card's, centred. Half Joker's card is torn across (its lower edge runs from 93
  to 121 of 190 px), so its shadow is a mask of its art ("in the shape of him", the user); Square Joker's and
  Photograph's edges are straight. Shop offers already used a drop-shadow on the art.
- **Seed Finder (the user, 29 Oct 11:50-12:40): done.** The table (built 00:52, 893 M chains) checked: 6 of 8 seeds'
  openings found in ~2 s each (`logs/seed_table_check.log`; the 75% it is built for). A search without the voucher
  went straight to the 1h40m scan (table_lookup needed it): now it tries the 16 ante-1 vouchers (~30 s; the user's
  6X7SCM12 found that way in 29 s). **Projection** of a found seed (`balatro/projection.py`, GET
  /api/seed/projection, a Projection button per seed in seed.js): per ante the boss, tags, voucher; per blind the first
  hand and the draw order; per shop the cards, voucher and both packs' contents; under the path "every blind played,
  no skips, nothing bought, no rerolls", packs as if opened in order, Standard packs from the Lab's own draws, decks
  without the standard 52 flagged. Ante 1 matches `opening()` on three seeds; tests/test_projection.py. Server
  restarted 12:40. The seedfinder reads openings as the standard deck deals them: an Abandoned Deck's first hand won't
  match (left as is).

- **A pack a skip's tag opens (the user's catch, 29 Oct 10:19): done 10:27.** It opened behind the blind panels (the
  pack's cards, its panel and the hand under them, RZ364T64 frame 24): `mark` counted every pack as the shop's, and
  packMove cleared the shop, not the blinds. Now `_tagged`: the blinds drop away, the pack and hand come up, the
  blinds rise again after; the hand count hides under an open pack ("8/8" sat on "Choose 2"). Checked in the browser.
- **Animation pass from the gameplay video: done 28 Oct 23:30** (ANIMATION.md: flames, the cash-out typing in, the
  hand back into the deck, +1 / -$N popups, the table's colours, pack bursts and stars, GAME OVER with Jimbo, thin
  shared card shadows). **The boss's announcement across the table: done 29 Oct 07:30** (ANIMATION.md; with it the
  sidebar's boss line wraps to two lines and every boss has a short line, data/bosses.json `short`: The Mouth's
  was cut off at "Only the first hand type played t"). **The shop's "Improve your run!" typing in: done 29 Oct
  08:35** (from the footage frame by frame; checked in the page: 0.33 s for the line, a jump mid-line restores it).
  Left: a win screen from footage (the video has none:
  YOU WIN! is the GAME OVER panel with a gold title); Celestial, Buffoon and Standard packs' table colours (guessed).
- **Flames played back from the footage (29 Oct 00:00)**: the game makes its flames up as it goes (no pattern repeats
  across the three episodes), so flame-data.json holds the footage's own outlines, frame by frame (ANIMATION.md).
  Left: the peak's rule rests on three hands (by score: ~42 px a tenfold); check it against more footage with bigger
  scores. The darker wisps inside are drawn, not recorded.
