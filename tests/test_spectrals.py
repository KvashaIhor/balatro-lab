from collections import Counter

import pytest

from balatro.agent import Agent
from balatro.hands import HAND_ORDER
from balatro.items import CONSUMABLES
from balatro.jokers import CATALOG, Joker
from balatro.run import Run
from balatro.shop import PACKS, OpenPack, Shop


def make_run(seed=0):
    run = Run(Agent(), seed=seed)
    run.start_ante()
    run.hand = run.deck[:8]
    return run


def use(run, name, targets=(), **kw):
    """Put the card in the consumable area and use it on hand positions `targets`."""
    run.consumables.append(CONSUMABLES[name](**kw))
    return run.use_consumable(len(run.consumables) - 1, list(targets))


class Counting(Joker):
    """A joker with state that `on_added` would reset."""
    name = "Counting"

    def on_added(self, run):
        self.count = 0


def test_all_spectrals_are_registered():
    assert sum(c.kind == "Spectral" for c in CONSUMABLES.values()) == 18


@pytest.mark.parametrize("name, ranks, count", [
    ("Familiar", {11, 12, 13}, 3), ("Grim", {14}, 2), ("Incantation", set(range(2, 11)), 4),
])
def test_destroy_one_then_add_enhanced_cards(name, ranks, count):
    for seed in range(20):
        run = make_run(seed)
        before = list(run.hand)
        assert use(run, name)
        new = [c for c in run.hand if c not in before]
        assert len(run.hand) == 8 - 1 + count and len(run.deck) == 52 - 1 + count
        assert sum(c in run.hand for c in before) == 7
        assert len(new) == count and all(c.rank in ranks for c in new)
        assert all(c.enhancement not in (None, "Stone") and c.edition is None and c.seal is None for c in new)
        assert all(any(c is d for d in run.deck) for c in new)
        assert len({c.uid for c in run.deck}) == len(run.deck)


@pytest.mark.parametrize("name", ["Familiar", "Grim", "Incantation", "Sigil", "Ouija", "Immolate"])
def test_hand_cards_need_two_cards_in_hand(name):
    run = make_run()
    run.hand = run.deck[:1]
    assert not use(run, name)
    run.hand = run.deck[:2]
    assert CONSUMABLES[name]().can_use(run, [])


@pytest.mark.parametrize("name, seal", [("Talisman", "Gold"), ("Deja Vu", "Red"), ("Trance", "Blue"), ("Medium", "Purple")])
def test_seal_spectrals_seal_exactly_one_card(name, seal):
    run = make_run()
    run.hand[0].seal = "Gold"
    assert not use(run, name, [0, 1])
    run.consumables.clear()
    assert use(run, name, [0])
    assert run.hand[0].seal == seal and run.hand[1].seal is None


def test_aura_gives_an_edition_only_to_an_editionless_card():
    run = make_run()
    run.hand[0].edition = "Foil"
    assert not use(run, "Aura", [0])
    run.consumables.clear()
    editions = Counter()
    for _ in range(2000):
        run.hand[1].edition = None
        assert use(run, "Aura", [1])
        editions[run.hand[1].edition] += 1
    assert set(editions) == {"Foil", "Holographic", "Polychrome"}
    assert abs(editions["Foil"] / 2000 - 0.5) < 0.04 and abs(editions["Polychrome"] / 2000 - 0.15) < 0.03


def test_wraith_makes_a_rare_joker_and_wipes_money_and_debt():
    for money in (37, -8):
        run = make_run()
        run.money = money
        assert use(run, "Wraith")
        assert run.money == 0 and [j.rarity for j in run.jokers] == ["Rare"]
    run.joker_slots = 1
    run.money = 10
    assert not use(run, "Wraith") and run.money == 10


def test_sigil_and_ouija_convert_the_whole_hand():
    run = make_run(3)
    assert use(run, "Sigil")
    assert len({c.suit for c in run.hand}) == 1 and len({c.suit for c in run.deck}) == 4
    hand_size = run.hand_size
    assert use(run, "Ouija")
    assert len({c.rank for c in run.hand}) == 1 and run.hand_size == hand_size - 1


def test_ectoplasm_hand_size_cost_grows_with_each_use():
    run = make_run()
    assert not use(run, "Ectoplasm")  # no jokers
    run.consumables.clear()
    run.jokers = [CATALOG["Joker"]("Foil")] + [CATALOG["Joker"]() for _ in range(3)]
    for n, size in ((1, 7), (2, 5), (3, 2)):
        assert use(run, "Ectoplasm")
        assert run.ectoplasm_uses == n and run.hand_size == size
        assert sum(j.edition == "Negative" for j in run.jokers) == n
    assert run.jokers[0].edition == "Foil"
    assert not use(run, "Ectoplasm")  # every joker has an edition


def test_immolate_destroys_five_random_cards_for_twenty_dollars():
    run = make_run()
    run.money = 0
    before = list(run.hand)
    assert use(run, "Immolate")
    assert len(run.hand) == 3 and len(run.deck) == 47 and run.money == 20
    assert all(c in before for c in run.hand)
    run.hand = run.deck[:3]
    assert use(run, "Immolate")
    assert run.hand == [] and len(run.deck) == 44 and run.money == 40


def test_ankh_copies_one_joker_and_destroys_the_others_but_not_eternals():
    for seed in range(20):
        run = make_run(seed)
        keep = CATALOG["Jolly Joker"]()
        keep.eternal = True
        run.jokers = [keep, CATALOG["Joker"](), CATALOG["Greedy Joker"]("Holographic")]
        assert use(run, "Ankh")
        twin = run.jokers[-1]
        original = next(j for j in run.jokers[:-1] if j.name == twin.name)
        assert keep in run.jokers and twin is not original and twin.edition == original.edition
        assert len(run.jokers) == (2 if original is keep else 3)
        assert twin.eternal == original.eternal


def test_ankh_copy_keeps_state_and_stickers_but_not_negative():
    run = make_run()
    j = Counting("Negative")
    j.count, j.rental, j.perishable, j.perish_rounds = 9, True, True, 2
    run.jokers = [j]
    assert use(run, "Ankh")
    twin = run.jokers[1]
    assert run.jokers[0] is j and twin is not j
    assert (twin.count, twin.rental, twin.perishable, twin.perish_rounds, twin.edition) == (9, True, True, 2, None)
    twin.count += 1
    assert j.count == 9


def test_ankh_needs_a_joker_and_a_free_slot():
    run = make_run()
    assert not use(run, "Ankh")
    run.consumables.clear()
    run.jokers = [CATALOG["Joker"]() for _ in range(5)]
    assert not use(run, "Ankh")
    run.jokers[0].edition = "Negative"
    assert use(run, "Ankh")


def test_hex_polychromes_an_editionless_joker_and_destroys_the_rest_but_eternals():
    run = make_run()
    assert not use(run, "Hex")
    run.consumables.clear()
    eternal = CATALOG["Jolly Joker"]("Foil")
    eternal.eternal = True
    plain, foil = CATALOG["Joker"](), CATALOG["Greedy Joker"]("Foil")
    run.jokers = [eternal, plain, foil]
    assert use(run, "Hex")
    assert run.jokers == [eternal, plain] and plain.edition == "Polychrome" and eternal.edition == "Foil"
    assert not use(run, "Hex")  # nothing edition-less left


def test_cryptid_adds_two_exact_copies_with_their_own_uids():
    run = make_run()
    card = run.hand[2]
    card.enhancement, card.edition, card.seal, card.bonus_chips = "Glass", "Polychrome", "Red", 10
    assert not use(run, "Cryptid", [0, 1])
    run.consumables.clear()
    assert use(run, "Cryptid", [2])
    copies = run.hand[-2:]
    assert len(run.hand) == 10 and len(run.deck) == 54
    assert all(c == card and c is not card for c in copies)
    assert all(any(c is d for d in run.deck) for c in copies)
    assert len({c.uid for c in run.deck}) == 54


def test_the_soul_makes_a_legendary_joker():
    if not any(cls.rarity == "Legendary" for cls in CATALOG.values()):
        pytest.skip("no Legendary joker registered yet")
    run = make_run()
    assert use(run, "The Soul")
    assert [j.rarity for j in run.jokers] == ["Legendary"]
    run.joker_slots = 1
    assert not use(run, "The Soul")


def test_black_hole_levels_every_hand():
    run = make_run()
    run.hand_levels["Flush"] = 3
    assert use(run, "Black Hole")
    assert run.hand_levels["Flush"] == 4
    assert all(run.hand_levels[h] == 2 for h in HAND_ORDER if h != "Flush")
    assert run.last_tarot_planet is None and run.consumables_used["Spectral"] == 1


def test_spectrals_on_the_hand_work_in_a_spectral_pack_but_not_in_the_shop():
    run = make_run()
    run.current_shop = Shop(run)
    assert not CONSUMABLES["Familiar"]().can_use(run, [])
    assert not CONSUMABLES["Talisman"]().can_use(run, run.hand[:1])
    assert CONSUMABLES["Black Hole"]().can_use(run, [])
    run.open_pack_state = OpenPack(PACKS["Spectral Pack"], [], 1)
    assert CONSUMABLES["Familiar"]().can_use(run, [])
    run.consumables = [CONSUMABLES["Pluto"](), CONSUMABLES["Mars"]()]
    assert CONSUMABLES["Cryptid"]().can_use(run, run.hand[:1])  # creates cards, not consumables


class PickFirstUsable(Agent):
    def pack_action(self, run, pack):
        for i, item in enumerate(pack.cards):
            for targets in ([0], []):
                if item.can_use(run, run.cards_at(targets)):
                    return ("pick", i, targets)
        return ("skip",)


def test_a_spectral_pack_deals_a_hand_and_keeps_the_deck_consistent():
    for seed in range(10):
        run = Run(PickFirstUsable(), seed=seed)
        run.start_ante()
        run.jokers = [CATALOG["Joker"]()]
        run.open_pack(PACKS["Spectral Pack"])
        assert run.consumables_used["Spectral"] == 1
        assert run.hand == [] and len({c.uid for c in run.deck}) == len(run.deck)
