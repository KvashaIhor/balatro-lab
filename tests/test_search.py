"""Round search (balatro/search.py, ValueBot.ROUND_SEARCH)."""
import pytest

from balatro import search
from balatro.cards import Card
from balatro.run import Run
from balatro.strategy import ValueBot


def _round(bot, hand, pile, needed, hands=4, discards=3):
    run = Run(bot, game_seed="DD8JI5Y5", deck="Red Deck")
    run.blind = run.make_blind(0)
    run.in_round, run.round_score = True, run.blind.chips - needed
    run.hands_left, run.discards_left = hands, discards
    run.hand, run.draw_pile = hand, pile
    return run


def _searching():
    bot = ValueBot()
    bot.ROUND_SEARCH, bot.SEARCH_BOSS_ONLY = True, False
    bot.SEARCH_ROLLOUTS, bot.SEARCH_CONFIRM, bot.SEARCH_MARGIN = 3, 3, 1
    return bot


def test_the_search_decides_the_same_whatever_a_face_down_card_really_is():
    """The play-outs swap each face-down card for a card it could be: which of the unseen cards it really is must not
    change the choice (the boss-round test's first version kept them as they were: The Fish, The House, The Wheel,
    The Mark). The face-down card and a card of the pile trade places; what is unseen stays the same."""
    def hand():
        return [Card(13, "Hearts"), Card(13, "Spades"), Card(9, "Clubs"), Card(7, "Diamonds"), Card(5, "Hearts"),
                Card(4, "Clubs"), Card(3, "Spades")]

    def pile(other):
        return [Card(r, s) for r, s in [(2, "Hearts"), (6, "Clubs"), (8, "Diamonds"), (10, "Spades"), (11, "Hearts"),
                                        (12, "Clubs"), (14, "Diamonds")]] + [other]
    picks = []
    for hidden, other in ((Card(2, "Clubs"), Card(13, "Diamonds")), (Card(13, "Diamonds"), Card(2, "Clubs"))):
        hidden.face_down = True                                     # a 2, or a third King
        bot = _searching()
        run = _round(bot, hand() + [hidden], pile(other), needed=400)
        a = search.choose(bot, run, ("play", [0, 1]))
        picks.append((a[0], sorted(a[1])))                        # by position: the face-down card's is the same
    assert picks[0] == picks[1]


def test_a_play_that_surely_wins_is_kept_without_playing_anything_out(monkeypatch):
    bot = _searching()
    hand = [Card(13, "Hearts"), Card(13, "Spades"), Card(9, "Clubs"), Card(7, "Diamonds"), Card(5, "Hearts")]
    run = _round(bot, hand, [Card(2, "Clubs"), Card(3, "Clubs")], needed=20)    # a Pair of Kings: 2 x (10 + 20) = 60
    monkeypatch.setattr(search, "play_out", lambda *a: pytest.fail("played out"))
    assert search.choose(bot, run, ("play", [0, 1])) == ("play", [0, 1])


def test_on_by_default_and_only_in_boss_rounds():
    """Adopted 31 Oct (j-search +4.4 ± 1.3, j777-search +2.3 ± 1.2 points)."""
    assert ValueBot.ROUND_SEARCH is True and ValueBot.SEARCH_BOSS_ONLY is True
