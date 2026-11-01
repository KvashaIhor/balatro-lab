"""The 18 Spectral cards. Counts, seals, money and hand-size changes come from data/consumables.json; the
edition split from data/modifiers.json (via `pool.pick_edition`).

Calls where the data is thin (checked on balatrowiki.org, 2026-10-25):
- Familiar, Grim, Incantation, Sigil, Ouija and Immolate need at least 2 cards in hand; random destruction
  picks from the whole hand. Added cards are uniform in suit and in rank within their set, with one of the 7
  enhancements other than Stone, and no edition or seal. Immolate destroys the whole hand when it holds 5
  or fewer cards.
- Ectoplasm's hand-size cost grows each use in a run (1st -1, 2nd -2, ...): `run.ectoplasm_uses` counts them.
- Ankh needs a joker and a free joker slot (wiki: "No Space!" when full). It picks any joker, Eternal ones
  included, destroys the other non-Eternal jokers and adds a copy that keeps edition (not Negative),
  stickers and state; the copy's `on_added` doesn't reset that state.
- Hex picks an edition-less joker; Eternal jokers survive.
- Aura, like The Wheel of Fortune, Ectoplasm and Hex, never touches a card or joker that has an edition.
- Wraith sets money to $0, wiping debt too.
- The Soul makes a random Legendary joker; Black Hole levels every hand, secret ones included, by 1.
"""
from __future__ import annotations

import copy

from .. import pool
from ..cards import ENHANCEMENTS, FACE_RANKS, RANKS, SUITS, Card
from ..items import Consumable
from .tarots import OnCards, editionless_jokers, has_hand, recheck_debuffs, register

spectral = register("spectral")

RANK_SETS = {"face": FACE_RANKS, "Ace": (14,), "2-10": tuple(range(2, 11))}
SPECTRAL_ENHANCEMENTS = tuple(e for e in ENHANCEMENTS if e != "Stone")


def destroy_random(run, n: int) -> None:
    run.destroy_cards(run.rng["misc"].sample(run.hand, min(n, len(run.hand))))


class OnHand(Consumable):
    """Acts on the whole hand, which must hold enough cards."""

    def can_use(self, run, targets):
        return (super().can_use(run, targets) and has_hand(run)
                and len(run.hand) >= self.spec.get("min_cards_in_hand", 1))


class AddCards(OnHand):
    """Familiar, Grim, Incantation: destroy a random card in hand, then add Enhanced cards to the hand."""

    def use(self, run, targets):
        destroy_random(run, self.spec["destroy_random"])
        add, rng = self.spec["add_cards"], run.rng["misc"]
        ranks = RANK_SETS[add["ranks"]]
        cards = [Card(rng.choice(ranks), rng.choice(SUITS), rng.choice(SPECTRAL_ENHANCEMENTS))
                 for _ in range(add["count"])]
        run.add_cards(cards, to_hand=True)
        recheck_debuffs(run)


class AddSeal(OnCards):
    def use(self, run, targets):
        for c in targets:
            c.seal = self.spec["seal"]


class CreateJoker(Consumable):
    rarity: str | None = None

    def can_use(self, run, targets):
        return super().can_use(run, targets) and run.joker_room()

    def use(self, run, targets):
        run.create_joker(self.rarity, source="wra" if self.rarity == "Rare" else None)


@spectral
class Familiar(AddCards):
    name = "Familiar"


@spectral
class Grim(AddCards):
    name = "Grim"


@spectral
class Incantation(AddCards):
    name = "Incantation"


@spectral
class Talisman(AddSeal):
    name = "Talisman"


@spectral
class Aura(OnCards):
    name = "Aura"

    def can_use(self, run, targets):
        return super().can_use(run, targets) and all(c.edition is None for c in targets)

    def use(self, run, targets):
        for c in targets:
            c.edition = pool.pick_edition(run.rng["misc"])


@spectral
class Wraith(CreateJoker):
    name = "Wraith"
    rarity = "Rare"

    def use(self, run, targets):
        super().use(run, targets)
        run.money = 0


@spectral
class Sigil(OnHand):
    name = "Sigil"

    def use(self, run, targets):
        suit = run.rng["misc"].choice(SUITS)
        for c in run.hand:
            c.suit = suit
        recheck_debuffs(run)


@spectral
class Ouija(OnHand):
    name = "Ouija"

    def use(self, run, targets):
        rank = run.rng["misc"].choice(RANKS)
        for c in run.hand:
            c.rank = rank
        run.base_hand_size += self.spec["hand_size"]
        recheck_debuffs(run)


@spectral
class Ectoplasm(Consumable):
    name = "Ectoplasm"

    def can_use(self, run, targets):
        return super().can_use(run, targets) and bool(editionless_jokers(run))

    def use(self, run, targets):
        run.rng["misc"].choice(editionless_jokers(run)).edition = "Negative"
        run.ectoplasm_uses = getattr(run, "ectoplasm_uses", 0) + 1
        run.base_hand_size -= run.ectoplasm_uses


@spectral
class Immolate(OnHand):
    name = "Immolate"

    def use(self, run, targets):
        destroy_random(run, self.spec["destroy_random"])
        run.money += self.spec["dollars"]


@spectral
class Ankh(Consumable):
    name = "Ankh"

    def can_use(self, run, targets):
        return super().can_use(run, targets) and bool(run.jokers) and run.joker_room()

    def use(self, run, targets):
        chosen = run.rng["misc"].choice(run.jokers)
        for j in list(run.jokers):
            if j is not chosen:
                run.remove_joker(j)
        twin = copy.deepcopy(chosen, {id(run): run})
        if twin.edition == "Negative":
            twin.edition = None
        state = dict(vars(twin))
        # TODO(engine): add_joker runs on_added, which may reset a copy's state; a way to add a copy without it
        run.add_joker(twin)
        vars(twin).update(state)


@spectral
class DejaVu(AddSeal):
    name = "Deja Vu"


@spectral
class Hex(Consumable):
    name = "Hex"

    def can_use(self, run, targets):
        return super().can_use(run, targets) and bool(editionless_jokers(run))

    def use(self, run, targets):
        chosen = run.rng["misc"].choice(editionless_jokers(run))
        chosen.edition = "Polychrome"
        for j in list(run.jokers):
            if j is not chosen:
                run.remove_joker(j)


@spectral
class Trance(AddSeal):
    name = "Trance"


@spectral
class Medium(AddSeal):
    name = "Medium"


@spectral
class Cryptid(OnCards):
    name = "Cryptid"

    def use(self, run, targets):
        run.add_cards([run.copy_card(targets[0]) for _ in range(self.spec["copies"])], to_hand=True)
        recheck_debuffs(run)


@spectral
class TheSoul(CreateJoker):
    name = "The Soul"
    rarity = "Legendary"


@spectral
class BlackHole(Consumable):
    name = "Black Hole"

    def use(self, run, targets):
        for hand in run.hand_levels:
            run.level_up(hand, 1)
