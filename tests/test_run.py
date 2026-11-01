import pytest

from balatro.bots import GreedyBot
from balatro.jokers import CATALOG
from balatro.run import Run


@pytest.mark.parametrize("seed", range(5))
def test_a_run_plays_through_and_keeps_its_books(seed):
    run = Run(GreedyBot(), seed=seed, max_ante=3, record=True)
    result = run.play()
    assert result.blinds_beaten >= 1  # a plain deck clears ante 1's Small Blind
    assert result.blinds_beaten <= result.progress < result.blinds_beaten + 1 or result.ante > 3
    assert len(run.deck) == 52 and run.money >= 0
    plays = [e for e in run.log if e[2] == "play"]
    assert plays and all(1 <= len(e[3]) <= 5 for e in plays)


def test_same_seed_same_run():
    def go():
        return Run(GreedyBot(), seed=7, max_ante=2).play()
    assert go() == go()


def test_jokers_change_the_outcome():
    plain = Run(GreedyBot(), seed=3, max_ante=4)
    boosted = Run(GreedyBot(), seed=3, max_ante=4)
    boosted.jokers = [CATALOG["Joker"](), CATALOG["The Duo"](), CATALOG["Jolly Joker"]()]
    assert boosted.play().progress > plain.play().progress


def test_a_hand_used_up_mid_blind_is_dealt_again_without_spending_a_hand_or_discard():
    from balatro.agent import Agent
    from balatro.items import CONSUMABLES
    seen = []

    class Immolator(Agent):
        def round_action(self, run):
            if run.consumables:
                return ("use", 0, [])                  # Immolate destroys all 5 cards in hand
            seen.append((len(run.hand), run.hands_left, run.discards_left))
            return ("play", [0])

    run = Run(Immolator(), seed=1, max_ante=1)
    run.base_hand_size = 5
    run.consumables = [CONSUMABLES["Immolate"]()]
    run.blind = run.make_blind(0)
    run.play_round()
    assert seen[0] == (5, 4, 3) and len(run.deck) == 47 and run.money >= 20


def test_with_a_sort_mode_the_hand_stays_sorted_after_every_draw_as_in_the_game():
    from balatro.cards import Card
    run = Run(GreedyBot(), seed=2)
    run.blind = run.make_blind(0)
    run.hand_sort = "rank"
    run.draw_pile = [Card(4, "Hearts"), Card(12, "Spades")] + [
        Card(r, s) for r, s in ((3, "Clubs"), (14, "Hearts"), (9, "Spades"), (9, "Hearts"), (2, "Diamonds"),
                                (13, "Clubs"), (5, "Spades"), (9, "Diamonds"))]
    run.hand = []
    run.draw("start")
    label = lambda: [f"{c.rank}{c.suit[0]}" for c in run.hand]
    assert label() == ["14H", "13C", "9S", "9H", "9D", "5S", "3C", "2D"]
    run.free_action(("sort_hand", "suit"))
    assert label() == ["9S", "5S", "14H", "9H", "13C", "3C", "9D", "2D"]
    run.hand = run.hand[2:]                                   # two cards gone: the next draw sorts in by suit
    run.draw("discard")
    assert label() == ["12S", "14H", "9H", "4H", "13C", "3C", "9D", "2D"]


def test_cash_out_pays_reward_remaining_hands_and_interest():
    run = Run(GreedyBot(), seed=1)
    run.blind = run.make_blind(0)
    run.money, run.hands_left = 23, 2
    run.cash_out()
    assert run.money == 23 + 3 + 2 + 4  # $3 Small Blind, $1 per hand left, $1 per $5 held (cap $5)
