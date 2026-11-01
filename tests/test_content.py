from balatro import content
from balatro.items import BOSSES, CONSUMABLES, DECKS, TAGS, VOUCHERS, entries
from balatro.jokers import CATALOG, JOKER_DATA


def test_every_content_module_loads():
    assert not content.FAILED, "\n".join(content.FAILED.values())


def test_registered_names_exist_in_the_data():
    assert set(CATALOG) <= set(JOKER_DATA)
    for registry, kinds in ((CONSUMABLES, ("tarot", "planet", "spectral")), (BOSSES, ("boss",)),
                            (TAGS, ("tag",)), (VOUCHERS, ("voucher",)), (DECKS, ("deck",))):
        names = {e["name"] for k in kinds for e in entries(k)}
        assert set(registry) <= names


def test_planets_and_vouchers_are_complete():
    assert sum(c.kind == "Planet" for c in CONSUMABLES.values()) == 12
    assert len(VOUCHERS) == 32
