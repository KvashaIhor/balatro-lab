import os
import subprocess
import time

from balatro.cards import Card
from balatro.jokers import CATALOG
from balatro.planner import PlanAgent, _hand_step, beam_plan, rollout, settled_steps
from balatro.run import Run
from balatro.shop import Offer, Shop

SEED = "DD8JI5Y5"


def test_a_sale_to_make_room_and_the_buy_it_is_for_are_one_move():
    agent = PlanAgent()
    run = Run(agent, game_seed=SEED, deck="Red Deck")
    run.money = 50
    run.jokers = [CATALOG[n]() for n in ("Joker", "Jolly Joker", "Zany Joker", "Mad Joker", "Crazy Joker")]
    shop = Shop(run)
    shop.cards, shop.packs, shop.vouchers = [Offer("Joker", CATALOG["Cavendish"]())], [], []
    action = agent.shop_action(run, shop)
    decision = agent.trace[-1]                       # the sale was a decision of the search, offered with the buy
    assert action[0] == "sell_joker" and decision["options"][decision["choice"]].endswith("and buy Cavendish for $4")
    assert run.sell_joker(action[1])
    assert agent.shop_action(run, shop) == ("buy", "card", 0)      # and the buy follows at once


def _group_processes() -> set[int]:
    out = subprocess.run(["pgrep", "-g", str(os.getpgrp())], capture_output=True, text=True).stdout
    return {int(pid) for pid in out.split()}


def test_hands_follow_the_games_sort_and_face_down_cards_go_by_position():
    # The House: the first hand is face down, so the plan names positions in the game's sorted hand
    # (rank high to low, then spades, hearts, clubs, diamonds; Stone cards last)
    before = [Card(3, "Hearts", face_down=True), Card(14, "Clubs", face_down=True), Card(9, "Spades", enhancement="Stone"),
              Card(3, "Spades", face_down=True), Card(12, "Diamonds", face_down=True)]
    f = {"before": [c.to_dict() for c in before], "picked": [0, 3], "hand_name": "Pair", "level": 1, "chips": 16,
         "mult": 2, "total": 32, "round_score": 32, "blind": {"chips": 300}}
    st = _hand_step("play", f)
    assert [c["label"] for c in st["hand"]] == ["AC", "QD", "3S", "3H", "Stone"]
    assert st["picked"] == [2, 3]
    assert st["text"] == "Play cards 3, 4 from the left (face down: 3♠ 3♥): Pair for 32"
    f["before"] = [c.to_dict() for c in (Card(3, "Hearts"), Card(14, "Clubs"), Card(3, "Spades"))]
    f["picked"] = [0, 2]
    assert _hand_step("play", f)["text"] == "Play 3♠ 3♥: Pair for 32"


def test_beam_plan_beats_the_base_strategy_and_replays():
    before = _group_processes()
    reports = []
    res = beam_plan(SEED, max_ante=2, width=2, horizon=1, time_limit=20, on_progress=reports.append)
    assert res["progress"] >= res["base"]["progress"]
    assert res["steps"] and res["frames"]
    choices = [d["choice"] for d in res["decisions"]]
    replay = rollout(SEED, "Red Deck", choices, 2)
    assert (replay.progress, replay.ante, replay.won) == (res["progress"], res["ante"], res["won"])
    # what was reported settled during the search is where the plan starts, unless the search's lines all fell
    # behind the base strategy's own run and the plan says it left them
    assert reports
    kept = not res["left_settled"]
    assert not kept or all(choices[:len(p["settled"])] == p["settled"] for p in reports)
    # and the steps shown for it are where the plan's steps start: steps are only ever appended
    for p in reports if kept else []:
        early = settled_steps(SEED, "Red Deck", 2, p["settled"])
        if not early:
            continue
        *whole, last = early
        assert whole == res["steps"][:len(whole)]
        same = res["steps"][len(whole)]
        assert last["steps"] == same["steps"][:len(last["steps"])]
        # (the last section is still open: its steps and the round's running score come as it is played)
        assert ({k: v for k, v in last.items() if k not in ("steps", "scored")}
                == {k: v for k, v in same.items() if k not in ("steps", "scored")})
    # every forked line is gone once the plan is back
    for _ in range(20):
        left = _group_processes() - before - {os.getpid()}
        if not left:
            break
        time.sleep(0.1)
    assert not left
