# How the Lab animates, and where the numbers come from

The run viewer (`app/static/app.js`, `motion.js`) moves the board the way the game does. Every number below
was measured from a 1920 x 1080, 60 fps recording of a first Balatro run (a YouTube video kept locally, not
in the repo), mostly the Big Blind at 7:36-8:59 and The Hook at 9:41-11:10: contact sheets at 5 to 30 fps
for the order of events, and template matching of single cards at every frame (position, tilt and scale)
for the curves. Times are at the game speed of that recording, the Lab's 1x; ½x, 2x and 4x scale all of it.

## Motion

| What | Measured | In the Lab |
|---|---|---|
| Any move (a card lifting 46 px) | 0, 4, 18, 38, 46, 50, 50, 50, 48, 46 px on successive frames: ~10% overshoot, settled in ~0.15 s | Damped spring per frame: `v = 0.435 v + 0.33 (target - x)`, `x += v` (predicts 0, 15, 32, 44, 50, 51, 50, 48, 47, 46) |
| Long flights (deck to hand, hand to played row) | a dealt card's edge moves 1744, 1672, 1568, 1470, 1370, 1274, 1214 px: ~100 px per frame | Speed capped at 100 px per frame |
| The hand rising or dropping 160 px (buttons in or out) | 158, 144, 120, 94, 80, 50, 36, 26, 20, 16, 12, 10, 8, 6, 4, 2, 0 px to go: a slow start, no overshoot, ~0.3 s | The hand's cards follow an anchor that is itself a softer spring, `v = 0.38 v + 0.12 (target - x)` (predicts 154, 139, 117, 93, 71, 52, 38, 28, 21, 16, 12, 9, 7, 6, 4, 3, 2) |
| Cards in flight | tilt up to 25-30 deg toward their sideways motion | Tilt 0.3 deg per px/frame of sideways speed, at most 25 deg |
| Juice (a card scoring, a joker firing, a number changing) | scale 1.28, 1.20, 1.00, 0.96, ..., 1.08 at 0.14 s, flat by 0.25 s; tilt about ±3 deg | `1 + 0.32 sin(51t)(1 - t/0.4)^3`, tilt `3.5 sin(54t)(1 - t/0.4)^2` deg |
| Idle | a joker at rest tilts -2 to +0.5 deg and drifts ±2 px over ~3 s | sway of 1.2 deg and 2 px, period ~3 s, per card phase |

## Layout found on the way

- While the player chooses, the hand sits 160 px higher, over the Play Hand / Sort Hand / Discard buttons
  (grey until a card is selected). Pressing a button drops the buttons and lowers the hand.
- Selected cards rise 44 px. Hand cards are spaced the hand's width over the hand size (98 px apart at
  size 10, ~122 at 8); the fan's tilt is ~3.2 deg per card with few cards, ~1.6 with eight.
- Played cards rest with their tops at 503; scoring cards rise 43 px (to 460). Non-scoring cards stay down
  at full brightness.

## The order of events (seconds at 1x)

**Play a hand.** Selected cards lift one at a time (0.12 s apart) and the hand name with its base chips and
mult shows. Play: buttons drop, hand lowers (~0.25 s). After 0.45 s the cards fly to the played row one at a
time, 0.07 s apart; the row stays centred, so earlier cards shift as later ones land, and the hand closes
up. After 0.45 s the scoring cards rise one at a time, 0.1 s apart. After ~0.6 s scoring starts: each effect
is 0.8 s apart; its card (or joker) juices, a popup grows in a letter at a time ("+11" over a blue badge above
a card, "+4 Mult" over a red one below a joker), the chips or mult number juices to its new value, and the
popup breaks up after ~0.6 s. About 1 s after the last effect (1.6-2 s in the footage) the total replaces
the hand name with a juice and chips and mult go to 0; 0.85 s later it counts into the round score,
linearly, in 0.5 s. 0.3 s later the played cards go off the right edge one at a time (0.08 s apart), turning
face down on the way.

**Draw.** Cards leave the deck face down 0.12-0.13 s apart, tilted, and turn over in flight (edge on ~0.07 s
out, face up as they land ~0.1 s out). Each goes straight to its sorted place in the hand, which is held open
while it flies, so the cards already there shift over. Then the buttons rise and the hand lifts.

**Discard.** As a play up to the button; then the selected cards go off the right edge one at a time.

**Blind starts.** The background's colours fade over ~0.5 s while the hand is dealt as above: to a boss blind's
colour; Small and Big Blinds play on the shop's green (their colour tints the sidebar only), and so does the
blind select screen, whatever blind is next (28 Oct pass, from a 50-minute gameplay video, 2 fps around each
moment). Selecting a blind pops an orange "+1" on Round; beating a boss pops one on Ante.

**A boss's announcement** (The Hook, 9:43-9:46, every frame at 30 fps; 29 Oct). As the last card of the hand lands,
the boss's line comes in across the table, centred over the hand (x ~1035, y ~528; 980 px wide for 39 letters, the
sidebar's font at ~1.9x), white with the usual drop shadow: a few letters a frame, all of it in ~0.15 s, while a swell
runs along it from the left, each letter growing to ~1.9x with a slight tilt and back (~0.15 s each, 4-6 letters
swollen at once, ~0.8 s end to end). It holds while the player looks at the hand (no play needed), and ~2.85 s after
it came every letter shrinks to nothing where it stands, all at once, in ~0.25 s (board.js `announce`). The line is
the short one the sidebar shows (data/bosses.json `short`, our own words; the full rule stays for Run Info); a long
one wraps to two lines, as the sidebar's does.

**Flames.** They come on the moment the hand being scored reaches the blind's whole target on its own (chips x mult
>= the blind's chips, whatever the round score: three episodes in the footage, 10:50, 29:02 and 45:01; a Big Blind of
450 with 316 scored had none at 55x8 = 440 and caught at 63x8 = 504; The Hook's 600 caught exactly at 75x8 = 600).
Measured from every frame of the three (28-29 Oct; the footage is 1:1 with the board): flame pixels 2 px; the outline
moves ~1-2 px a frame (75-90% alike from one frame to the next, a shape lives ~4-8 frames), no sideways drift; tongues
~10 px wide ~26 px apart; chips and mult flicker independently; ~12% of columns throw a piece off the top in a big
flare; inside, each box's colour rising into a lighter tip, brighter in a bigger flame, a faint darker wisp or two.
No repeating pattern between the episodes (the game makes them up as it goes), so the Lab plays the footage itself:
flame-data.json holds every clean frame's outline (body and pieces, scaled by the frame's mean height), a low set
(~20 px flames) and a high set (~58 px), played at 60 fps and drawn to the size wanted (flames.js). The size: a
flare to a peak set by the hand's score (~42 px a tenfold: 900 and 608 peaked at ~20 px, 6,072 at 58), reached in
~0.8 s, sinking back over ~2 s to ~10 px while the hand goes on, out as its total counts into the round score.

**Round won.** While a hand that reaches the blind's target is scored, flames burn on the score boxes
(flames.js, fitted to 60 fps footage frame by frame): each box's own colour rising off its whole top edge into a
lighter tip (blue #0092ff to cyan #08d6f9, red #ff4b40 to orange #f58c3a and yellow), one ragged mound per box,
highest in the middle, whose broad licks rise and throw off small blobs, in ~3 px pixels, over the hand's name. They
flare up in ~0.15 s to ~75 px (higher the further the hand beats the blind), settle to ~45 px once the total
shows (the total drawn over them), and die away as it counts into the round score. The rest of the hand closes up
and slides back into the deck (its count climbing); ~0.3 s later the discard pile streams back into the deck from
the right. The cash-out panel springs up empty and types itself in (28 Oct pass): the blind's row a letter at a
time ("Score at least N"), its dollars ticking in one by one (~0.15 s each); the blind's chip in the sidebar burns
away, the blind's panel leaves the sidebar and the table fades from a boss's colour to green; a dotted rule draws
across; each payout row types in with its count ("4 Remaining Hands ($1 each)", "5 1 interest per $5 (5 max)") and
ticks its dollars; last, "Cash Out: $N" pops up at the top. The panel drops away, the round score counts to 0
(0.35 s), "+$N" pops on the money and it counts up.

**Run lost.** The table turns red and a red wash (~70%) covers everything; the GAME OVER panel comes up in the
middle right (Best Hand, Most Played Hand, Cards Played, Discarded, Purchased, Times Rerolled, Seed; Ante, Round,
Defeated By with the blind's chip; New Run, Main Menu), and Jimbo tumbles in from the left to beside it, bobbing,
with a speech bubble and blue and orange sparks. The footage has no win; the Lab's YOU WIN! is the same panel with
a gold title over the table as it is.

**Shop.** The SHOP sign drops into the sidebar, the panel springs up empty, and the offers materialise one
after another. "Improve your run!" under the sign types itself in once the sign has landed (11:05.9, every frame at
60 fps; 29 Oct): the first letter ~0.57 s after the sign starts to drop, then about one a frame (17 characters in
~0.32 s), each popping in small and full size two frames later; no swell after (board.js `typeImprove`). A bought card flies from its slot to its tray; a voucher or pack juices and dissolves where it
is; a reroll dissolves the cards and new ones materialise. Opening a pack drops the shop and brings up the
pack's panel and cards. Opening one (28 Oct pass): the money pops "-$N" in red, the pack flies to the middle of
the table, shakes, and bursts into white squares as the table takes the pack's colour (Arcana a dark purple,
Spectral a deep blue, both with small white stars drifting; Celestial, Buffoon and Standard not in the footage:
guessed); then the cards appear. Back to the shop's green after.

**Shadows.** A card's shadow is a thin strip ~10 px below it (hand, jokers), and where cards overlap the shadows
don't darken twice: one shared shadow layer, see-through once (motion.js SHADOW). It was a 36 px drop shadow per
card, which banded under the hand (the user's catch, 28 Oct).

## Drawing

The springs step at a fixed 60 per game second; every display frame draws the sprites part of the way
between the last two steps, and juice, turns and sway run on continuous time, so motion is even at 60 or
120 Hz and at ½x. Moving cards are placed with transforms on their own layers (no layout, and their shadows
aren't redrawn each frame), and a card far from its place draws above cards at rest. Scene snapshots
(`#scene=`) keep plain left/top placement so they still match the screenshots pixel for pixel.

Not reproduced: the game's dissolve shader (cards fade and shrink instead), and a win.
