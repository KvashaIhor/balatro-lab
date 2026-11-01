from balatro.bots import GreedyBot
from balatro.run import Run
from balatro.shop import Shop


def test_the_shop_after_a_boss_belongs_to_the_next_ante():
    # KH77XUG6 with both ante-1 blinds skipped (a player's report, seedfinder/REPORT.md section 5): the first
    # shop, after The Pillar, offers Walkie Talkie and the Telescope voucher, both from ante 2's streams.
    run = Run(GreedyBot(), game_seed="KH77XUG6")
    run.start_ante()
    assert run.ante_boss.name == "The Pillar" and run.ante_voucher == "Clearance Sale"
    run.boss_defeated()
    shop = Shop(run)
    assert run.ante == 2
    assert shop.cards[0].name == "Walkie Talkie"
    assert [o.name for o in shop.vouchers] == ["Telescope"]


def test_an_extinct_gros_michel_never_returns_to_a_seeded_shop_and_cavendish_comes_after_it():
    run = Run(GreedyBot(), game_seed="ZZ8E3KJS")
    run.seedrng.sync(run)
    assert "Gros Michel" not in run.seedrng.model.gated and "Cavendish" in run.seedrng.model.gated
    run.extinct.add("Gros Michel")                     # (it died at the end of a round)
    run.seedrng.sync(run)
    assert "Gros Michel" in run.seedrng.model.gated and "Cavendish" not in run.seedrng.model.gated
    offered = {run.seedrng.shop_card(run, [])["name"] for _ in range(400)}
    assert "Gros Michel" not in offered
