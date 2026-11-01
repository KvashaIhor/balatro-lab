# Writing content: jokers, consumables, bosses, tags, decks

Every joker, Tarot, Spectral, boss blind, tag and deck is a small class in `balatro/content/<file>.py`.
Each module in `balatro/content/` is imported automatically; a decorator registers the class and fills its
numbers from `data/*.json`. Rules come from the data files (paraphrased from balatrowiki.org, sources in
`data/SOURCES.md`), not memory. If the data is unclear, follow the wiki and note the call in
`data/OPEN_QUESTIONS.md` under a heading for your file.

Already done (don't redo): Planets (`content/planets.py`), vouchers (`content/vouchers.py`), stakes (read
from data by the run), the jokers Joker, Greedy Joker, Jolly Joker, Hanging Chad, The Duo, Baseball Card,
Blueprint, Brainstorm (`balatro/jokers.py`).

## Jokers (`balatro/jokers.py`)

```python
from ..jokers import Joker, joker

@joker
class RideTheBus(Joker):
    name = "Ride the Bus"  # must match data/jokers.json; rarity, cost, copyable, sticker flags come from there

    def __init__(self, edition=None):
        super().__init__(edition)
        self.mult = 0

    def before(self, ctx):
        if ctx.live:  # own state: not while copied by Blueprint, not while a bot estimates
            faces = any(c.is_face(ctx.run.pareidolia) for c in ctx.scoring_cards)
            self.mult = 0 if faces else self.mult + 1

    def independent(self, ctx, score):
        score.add_mult(self.name, self.mult)
```

Hooks, in the order the game reaches them (see the docstrings in `jokers.py`):

| Hook | When | Examples |
|---|---|---|
| `on_blind_select(run, blind)` | blind chosen, after hands/discards are set, before the draw | Burglar, Riff-raff, Marble Joker, Madness, Ceremonial Dagger, Cartomancer, Chicot |
| `on_round_start(run)` | first hand of the round drawn | Certificate |
| `before(ctx)` | hand chosen, before scoring | Space Joker, Midas Mask, Vampire, DNA, Ride the Bus, Runner, Square Joker, Green Joker |
| `retriggers(ctx, card, position)` -> int | per scoring card | Sock and Buskin, Hack, Dusk, Seltzer, Hanging Chad |
| `on_scored(ctx, card, score)` | per scoring card trigger, after its own chips/enhancement/edition/seal | suit jokers, Fibonacci, Scholar, Photograph, Hiker, Business Card, Wee Joker |
| `held_retriggers(ctx, card)` -> int, `on_held(ctx, card, score)` | per card held in hand | Mime; Baron, Shoot the Moon, Raised Fist, Reserved Parking |
| `independent(ctx, score)` | the joker's main effect, left to right | most +mult / xmult jokers |
| `on_joker(ctx, other, score)` | after each joker's effect | Baseball Card |
| `after(ctx, score)` | hand scored | Ice Cream, Seltzer, Loyalty Card count |
| `on_discard(run, cards, first)` | a discard (all discarded cards at once) | Castle, Faceless, Mail-In Rebate, Trading Card, Burnt Joker, Hit the Road, Yorick, Ramen, Green Joker |
| `end_of_round(run, blind)` -> dollars | blind beaten, before cash out | Golden Joker, Rocket, Cloud 9, Satellite, Delayed Gratification, Egg, Gift Card, Gros Michel, Popcorn, Turtle Bean, To Do List |
| `on_boss_defeated(run)` | after a boss's cash out | Rocket, Campfire reset |
| `on_shop_open/on_reroll/on_shop_close(run, shop)` | shop | Flash Card, Perkeo |
| `on_sell(run, item)` / `on_sold(run)` | something else sold / this one sold | Campfire / Luchador, Diet Cola, Invisible Joker |
| `on_pack_open/on_pack_skip(run, pack)` | booster pack | Hallucination / Red Card |
| `on_consumable_used(run, c)` | Tarot/Planet/Spectral used | Fortune Teller, Constellation |
| `on_cards_added(run, cards)` / `on_cards_destroyed(run, cards)` | playing cards join / leave the deck | Hologram / Glass Joker, Canio |
| `on_added(run)` | it joins your jokers | record a baseline (Lucky Cat), pick a starting card (The Idol) |
| `on_fail(run)` -> bool | round about to be lost | Mr. Bones |
| `can_spawn(run)` classmethod -> bool | may it appear in shop/packs now | Cavendish, Steel Joker, Stone Joker, Golden Ticket, Lucky Cat, Glass Joker |

Passives: `hand_size_bonus`, `hands_bonus`, `discards_bonus`, `debt` (Credit Card 20), `rules` dict with
`four_fingers`, `shortcut`, `smeared`, `splash`, `pareidolia`, `showman`. The run checks Chaos the Clown,
Astronomer and Oops! All 6s by name; they still need a class.

**Copies and estimates.** Blueprint and Brainstorm forward every hook above except `end_of_round`,
`on_added`, `on_sold`, `on_fail` and passives. So:
- own state (scaling counters, chosen card/suit): change only when `ctx.live` (hand hooks) or
  `not run.copying` (run hooks);
- effects on the run (money, creating/destroying cards, levelling hands, adding chips to a card): a copy
  does them too; in hand hooks only when `not ctx.estimating` (bots score hypothetical hands).
- chances: `ctx.chance(n)` in hand hooks, `run.chance(n)` elsewhere (both honour Oops! All 6s).

Hand state during hand hooks: `ctx.played`, `ctx.held`, `ctx.result.name`, `ctx.result.contains`,
`ctx.scoring_cards`, `ctx.destroyed` (append cards to destroy after scoring). The run's counters already
include the hand being scored: `run.hand_plays[name]` (run), `run.round_hand_types[name]` (round),
`run.round_hands_played` (1 on the first hand), `run.hands_left` (0 on the final hand).

## Consumables (`balatro/items.py`)

```python
from ..items import Consumable, consumable

@consumable
class TheEmpress(Consumable):
    name = "The Empress"  # kind and cost come from data/consumables.json
    min_targets, max_targets = 1, 2

    def use(self, run, targets):
        for c in targets:
            c.enhancement = "Mult"
```
`can_use(run, targets)` defaults to the target count; override for extra conditions (Ankh needs a joker,
cards that create things need room). `run.hand` holds the cards (the round's hand, or the hand an
Arcana/Spectral pack deals). Leave The Soul and Black Hole to `use` like any other card: the pool only
offers them from packs.

## Bosses, tags, decks (`balatro/items.py`)

`Boss` hooks: `on_select`, `on_disable`, `debuffs(run, card)`, `face_down(run, card, when)`,
`draw_count(run, default, when)`, `after_draw`, `press_play`, `allows` (pure check), `before_score`,
`modify_base` (pure), `after_hand`, `forced_selection`, `on_sell`. Set `self.triggered = True` when the
ability actually affected a hand (Matador pays for that). Chip multiple, reward and showdown come from data.

`Tag` hooks return True when used up: `setup` (when rolled), `on_gain`, `on_blind_select`, `on_shop_open`,
`on_shop_offer` (each joker put on sale), `on_boss_defeated`. Double Tag needs only an empty class (the run
handles copying).

`Deck.apply(run)` changes run attributes before the run starts.

## The run API for content (`balatro/run.py`)

State: `run.money`, `run.ante`, `run.deck` (full deck), `run.hand`, `run.draw_pile`, `run.jokers`,
`run.consumables`, `run.vouchers`, `run.tags`, `run.hand_levels`, `run.hand_plays`, `run.round_hand_types`,
`run.blind` (`.chips`, `.kind`, `.boss`), `run.round_score`, `run.hands_left`, `run.discards_left`,
`run.discards_used`, `run.skips`, `run.hands_played`, `run.unused_discards`, `run.consumables_used`
(Counter by kind), `run.planets_used`, `run.last_tarot_planet`, `run.extinct`, `run.played_this_ante`
(uids), `run.lucky_triggers`, `run.starting_deck_size`, `run.joker_slots`, `run.consumable_slots`,
`run.base_hands`, `run.base_discards`, `run.base_hand_size`, `run.hand_size_delta` (this round),
`run.interest_cap`, `run.interest_enabled`, `run.money_per_hand`, `run.money_per_discard`,
`run.spectral_weight`, `run.blind_scale`, `run.plasma`, `run.double_tag_after_boss`, `run.rng[stream]`
(use `"misc"` for content rolls, `"luck"` is the hand-scoring stream).

Derived: `run.active_jokers()`, `run.hand_size`, `run.smeared`, `run.pareidolia`, `run.showman`,
`run.active_boss`, `run.has_joker(name)`, `run.has_voucher(name)`, `run.joker_room(j=None)`,
`run.consumable_room(c=None)`, `run.sell_value(item)`, `run.most_played_hand()`.

Actions: `run.chance(n)`, `run.level_up(hand, n)`, `run.add_joker(j)`, `run.create_joker(rarity=None,
name=None, edition=None)`, `run.remove_joker(j)` (refuses Eternal), `run.create_consumable(kind=None,
name=None, edition=None)`, `run.add_cards(cards, to_hand=False)`, `run.destroy_cards(cards)`,
`run.copy_card(card)`, `run.set_deck(cards)`, `run.redeem_voucher(name)`, `run.gain_tag(tag)`,
`run.reroll_boss(paid=False)`, `run.disable_boss()`, `run.open_pack(PACKS[name])` (`balatro/shop.py`).
Pools (`balatro/pool.py`): `random_joker`, `random_consumable`, `random_playing_card`, `random_voucher`,
`random_tag`, `pick_edition` (guaranteed Foil/Holo/Poly), `roll_edition`, `planet_for(hand)`.
Shop (`balatro/shop.py`): `shop.cards`, `shop.packs`, `shop.vouchers` (lists of `Offer(kind, item, free)`),
`shop.joker_offer(rarity=None, free=False)`, `shop.reroll_base`, `Offer("Voucher", name)`.

Cards (`balatro/cards.py`): `rank` 2-14, `suit`, `enhancement`, `edition`, `seal`, `bonus_chips`,
`debuffed`, `face_down`, `uid`; `is_face(pareidolia)`, `has_suit(suit, smeared)`, `is_stone`.

## Tests

One test file per content file (`tests/test_<file>.py`). Test the effects that are easy to get wrong:
numbers from the data, scaling and its reset, copy behaviour, interaction with debuffs, chance effects
with a seeded rng. Score hands with `HandContext` + `score_hand` as in `tests/test_scoring.py`, on a real
`Run(Agent(), seed=...)` after `run.start_ante()`. Run `python3 -m pytest -q` from `balatro/`; all tests
must pass, including other people's.
