import sys
from pathlib import Path

from balatro.agent import Agent
from balatro.bots import GreedyBot
from balatro.projection import card_code, project
from balatro.run import Run

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "seedfinder"))
import opening  # noqa: E402  (seedfinder/opening.py)


def test_ante_1_agrees_with_the_seed_finders_opening():
    for seed in ("DD8JI5Y5", "E8G18YRT", "4Z7TWAWF"):          # DD8JI5Y5: the user's run, confirmed in the game
        p, o = project(seed, "Red Deck", 1), opening.opening(seed)
        a = p["antes"][0]
        first = a["blinds"][0]
        assert (a["boss"], a["tags"], a["voucher"]) == (o["boss"], [o["small_tag"], o["big_tag"]], o["voucher"])
        assert sorted(first["hand"]) == sorted(o["first_hand"])
        assert [(c["name"], c["edition"]) for c in first["shop"]["cards"]] == [(c["name"], c.get("edition"))
                                                                              for c in o["shop_cards"]]
        assert [pk["name"] for pk in first["shop"]["packs"]] == o["packs"]


def test_each_blind_deals_the_whole_deck_its_first_hand_first_and_repeats_exactly():
    p = project("DD8JI5Y5", "Red Deck", 3)
    assert p == project("DD8JI5Y5", "Red Deck", 3)                 # nothing random of its own, nothing kept
    assert p["exact_deck_order"]
    for a in p["antes"]:
        assert len(a["blinds"]) == 3
        for b in a["blinds"]:
            assert len(b["hand"]) + len(b["draws"]) == 52 and len(set(b["hand"] + b["draws"])) == 52
            assert len(b["shop"]["cards"]) == 2 and len(b["shop"]["packs"]) == 2
    assert p["antes"][0]["blinds"][2]["name"] == p["antes"][0]["boss"]
    assert p["antes"][0]["blinds"][2]["shop"]["voucher"] == p["antes"][1]["voucher"]   # a boss's shop: the next ante's


class _Leaves(GreedyBot):
    """Plays its best hands, skips nothing, buys nothing, leaves every shop."""

    def skip_blind(self, run, blind, tag):
        return False

    def shop_action(self, run, shop):
        return ("leave",)


def test_it_matches_a_lab_run_that_plays_every_blind_and_buys_nothing_until_that_run_falls():
    seed = "E8G18YRT"
    res = Run(_Leaves(), game_seed=seed, deck="Red Deck", max_ante=8, record=True).play()
    p = project(seed, "Red Deck", 8)
    blinds = [b for a in p["antes"] for b in a["blinds"]]
    dealt = [f for f in res.frames if f["kind"] == "blind"]
    shops = [f for f in res.frames if f["kind"] == "shop"]
    assert dealt and shops
    for f, b in zip(dealt, blinds):
        assert sorted(card_code_of(c) for c in f["hand"]) == sorted(b["hand"])
    for f, b in zip(shops, blinds):
        assert [c["name"] for c in f["shop"]["cards"]] == [c["name"] for c in b["shop"]["cards"]]
        assert [p_["name"] for p_ in f["shop"]["packs"]] == [pk["name"] for pk in b["shop"]["packs"]]


def card_code_of(d) -> str:
    """A recorded frame's card (Card.to_dict) as the Seed Finder writes it."""
    return d["suit"][0] + {10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}.get(d["rank"], str(d["rank"]))


def test_a_deck_without_the_52_standard_cards_says_its_order_is_unchecked():
    p = project("DD8JI5Y5", "Abandoned Deck", 1)
    assert not p["exact_deck_order"] and "isn't checked" in p["note"]
    assert len(p["antes"][0]["blinds"][0]["hand"]) + len(p["antes"][0]["blinds"][0]["draws"]) == 40
    assert card_code(type("C", (), {"suit": "Hearts", "rank": 10})()) == "HT"
    assert isinstance(Agent(), Agent)


def test_the_servers_endpoint_checks_what_it_is_asked():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
    import server
    body, status = server.seed_projection("seed=dd8ji5y5&antes=2")
    assert status == 200 and body["seed"] == "DD8JI5Y5" and len(body["antes"]) == 2
    assert server.seed_projection("seed=!!")[1] == 400
    assert server.seed_projection("seed=DD8JI5Y5&deck=Nope")[1] == 400
    assert server.seed_projection("seed=DD8JI5Y5&antes=x")[1] == 400
