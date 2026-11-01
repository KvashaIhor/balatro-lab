import pytest

from balatro.interactive import Games, PlayError, plain, replay
from balatro.run import Run
from balatro.strategy import ValueBot, Weights

SPEC = {"seed": "DD8JI5Y5", "deck": "Red Deck", "stake": "White Stake", "max_ante": 2}


class Recorder(ValueBot):
    """The value bot, writing down every decision as the Play tab records a person's."""

    def __init__(self):
        super().__init__()
        self.w, self.net, self.steps = Weights(), None, []

    def skip_blind(self, run, blind, tag):
        skip = super().skip_blind(run, blind, tag)
        self.steps.append({"kind": "select", "action": ["skip" if skip else "select"]})
        return skip

    def reroll_boss(self, run, boss):
        self.steps.append({"kind": "boss", "action": ["keep"]})
        return False

    def round_action(self, run):
        a = super().round_action(run)
        self.steps.append({"kind": "round", "action": plain(a)})
        return a

    def shop_action(self, run, shop):
        a = super().shop_action(run, shop)
        self.steps.append({"kind": "shop", "action": plain(a)})
        return a

    def pack_action(self, run, pack):
        a = super().pack_action(run, pack)
        self.steps.append({"kind": "pack", "action": plain(a)})
        return a


def test_replaying_the_recorded_actions_plays_the_same_run():
    bot = Recorder()
    res = Run(bot, game_seed=SPEC["seed"], deck=SPEC["deck"], stake=SPEC["stake"], max_ante=SPEC["max_ante"]).play()
    assert len(bot.steps) > 20
    pos = replay(SPEC, bot.steps)
    assert pos.need is None and pos.agent.i == len(bot.steps)
    again = pos.result
    assert (again.won, again.ante, again.blinds_beaten, again.progress, again.best_hand, again.money) == \
        (res.won, res.ante, res.blinds_beaten, res.progress, res.best_hand, res.money)
    cut = replay(SPEC, bot.steps[:7])                     # stops at the 8th decision, as recorded
    assert cut.need is not None and cut.kind == bot.steps[7]["kind"]


def test_a_game_plays_rewinds_to_a_new_branch_and_switches_back(tmp_path):
    games = Games(tmp_path)
    s = games.new("DD8JI5Y5", "Red Deck", "White Stake")
    gid = s["id"]
    assert s["decision"] == "select" and s["bot_pending"]                  # a worker works the hint out
    assert games.hint(gid)["bot"]["action"] in (["select"], ["skip"])
    s = games.act(gid, ["select"])
    assert s["decision"] == "round" and len(s["view"]["hand"]) == 8
    s = games.act(gid, ["play", [0, 1]])
    assert s["step"] == 2 and s["view"]["round_score"] > 0 and s["events"]
    first = s["timeline"]
    s = games.rewind(gid, 1)                              # back to the first hand: a new branch
    assert s["branch"] == 1 and s["step"] == 1 and s["decision"] == "round" and s["view"]["round_score"] == 0
    s = games.act(gid, ["discard", [0, 1, 2]])
    assert s["view"]["discards_left"] == 3 and len(s["branches"]) == 2
    s = games.switch(gid, 0)
    assert s["timeline"] == first
    assert (tmp_path / f"{gid}.json").exists() and "## ROUND ante 1" in (tmp_path / f"{gid}.txt").read_text()
    assert [g["id"] for g in games.listing()] == [gid]


def test_each_action_brings_the_frames_it_recorded_which_continue_the_run(tmp_path):
    games = Games(tmp_path)
    s = games.new("DD8JI5Y5", "Red Deck", "White Stake")
    frames = s["frames"]
    assert s["frames_from"] == 0 and frames[-1]["kind"] == "select"
    for action in (["select"], ["play", [0, 1]], ["discard", [0]]):
        s = games.act(s["id"], action)
        assert s["frames_from"] == len(frames) and s["frames"]
        frames = frames + s["frames"]
    assert frames == games.state(s["id"])["frames"]         # the same as all of them at once
    assert {"play", "discard", "draw", "blind"} <= {f["kind"] for f in frames}
    assert "affordable" not in str(s["view"]["hand"]) and "controls" in s["view"]


def test_a_hand_the_boss_wont_score_says_why():
    from balatro.cards import Card
    from balatro.hands import evaluate
    from balatro.interactive import why_not
    from balatro.items import BOSSES
    run = Run(ValueBot(), game_seed="DD8JI5Y5", deck="Red Deck")
    run.blind = run.make_blind(0)                          # (each boss is put on it below)
    pair, high = [Card(8, "Spades"), Card(8, "Hearts")], [Card(14, "Clubs")]
    assert why_not(run, high, evaluate(high, run.rules)) is None
    for name, played, reason in (("The Mouth", high, "The Mouth: only Pair scores this round"),
                                 ("The Eye", pair, "The Eye: Pair already played this round"),
                                 ("The Psychic", pair, "The Psychic: must play 5 cards")):
        run.blind.boss = BOSSES[name]()
        run.round_hand_types.clear()
        run.round_hand_types["Pair"] += 1
        assert why_not(run, played, evaluate(played, run.rules)) == reason
    run.blind.boss = BOSSES["The Plant"]()
    faces = [Card(13, "Spades"), Card(13, "Hearts")]
    for c in faces:
        c.debuffed = True
    assert why_not(run, faces, evaluate(faces, run.rules)) == "The Plant: every scoring card is debuffed"


def test_going_back_keeps_the_line_and_only_a_different_action_branches(tmp_path):
    games = Games(tmp_path)
    gid = games.new("DD8JI5Y5", "Red Deck", "White Stake")["id"]
    games.act(gid, ["select"])
    games.act(gid, ["play", [0, 1]])
    s = games.act(gid, ["discard", [0]])
    assert s["cursor"] == 3 and len(s["timeline"]) == 3
    back = games.state(gid, cursor=1)                      # back to the first hand: the later steps stay
    assert back["cursor"] == 1 and back["decision"] == "round" and back["view"]["round_score"] == 0
    assert len(back["timeline"]) == 3 and len(back["branches"]) == 1
    s = games.act(gid, ["play", [0, 1]], cursor=1)         # what the line did next: just on along it
    assert s["cursor"] == 2 and len(s["branches"]) == 1 and s["branch"] == 0
    assert s["frames_from"] == len(back["frames"]) and s["frames"]
    s = games.act(gid, ["discard", [0, 1]], cursor=2)      # something else: a new branch from there, switched to
    assert len(s["branches"]) == 2 and s["branch"] == 1 and s["cursor"] == 3 and len(s["timeline"]) == 3
    assert s["timeline"][2]["text"] != back["timeline"][2]["text"]
    old = games.switch(gid, 0)                             # the old line, whole, the cursor at its end
    assert old["cursor"] == 3 and old["timeline"] == back["timeline"]
    with pytest.raises(PlayError):
        games.state(gid, cursor=9)


def test_sorting_the_hand_is_not_held_against_the_bot(tmp_path):
    games = Games(tmp_path)
    gid = games.new("DD8JI5Y5", "Red Deck", "White Stake")["id"]
    games.act(gid, ["select"])
    s = games.act(gid, ["sort_hand", "suit"])
    t = s["timeline"][-1]
    assert t["aside"] and t["agree"] is None and t["bot"] is None
    line = next(x for x in (tmp_path / f"{gid}.txt").read_text().splitlines() if "Sort" in x)
    assert "differs" not in line and "bot ->" not in line


def test_actions_the_game_cant_take_are_refused(tmp_path):
    games = Games(tmp_path)
    gid = games.new("DD8JI5Y5", "Red Deck", "White Stake")["id"]
    with pytest.raises(PlayError):
        games.act(gid, ["play", []])                      # not a select decision, and no cards
    games.act(gid, ["select"])
    for bad in (["play", [0, 0]], ["play", [0, 1, 2, 3, 4, 5]], ["play", [9]], ["buy", "card", 0], ["use", 0, []],
                ["sell_joker", 0], ["order_hand", [0, 1]]):
        with pytest.raises(PlayError):
            games.act(gid, bad)
    s = games.act(gid, ["order_hand", [7, 6, 5, 4, 3, 2, 1, 0]])
    assert s["step"] == 2 and s["decision"] == "round"
    with pytest.raises(PlayError):                        # keeping the order as it is changes nothing
        games.act(gid, ["order_hand", list(range(8))])
