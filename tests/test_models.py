import pytest

from balatro.models import listing, make
from balatro.run import Run
from balatro.strategy import ValueBot


def test_every_listed_model_plays_a_run():
    from balatro.models import NEEDS_NETWORK
    ids = [m["id"] for m in listing()]
    assert ids[:3] == ["greedy", "smart", "value"]
    for model_id in ids:
        if model_id in NEEDS_NETWORK:                         # played offline below
            continue
        result = Run(make(model_id), seed=3, max_ante=1, record=True).play()
        assert result.frames, model_id


@pytest.mark.parametrize("model_id", ["jev", "jev-shop", "jev-ties"])
def test_jev_plays_legal_moves_from_what_the_value_bot_weighs(model_id, monkeypatch):
    import random
    from balatro.jev import Client
    rng = random.Random(7)
    asked = []

    def fake_choose(self, state, options):                    # no network: a random pick each time
        asked.append((state, options))
        return [rng.random() for _ in options]
    monkeypatch.setattr(Client, "choose", fake_choose)
    result = Run(make(model_id), game_seed="DD8JI5Y5", deck="Red Deck", max_ante=4).play()
    assert result.progress > 0 and asked
    assert all("Ante" in s and len(o) >= 2 for s, o in asked)


def test_the_jev_bot_replaces_only_the_value_bots_decisions():
    from balatro.jev import JevBot
    overridden = {n for n in vars(JevBot) if not n.startswith("__") and hasattr(ValueBot, n)}
    assert overridden == {"round_action", "shop_action", "pack_action"}     # no helper of its own hides the bot's


def test_a_model_keeps_its_weights_to_itself():
    before = (ValueBot.w, ValueBot.net)
    for m in listing():
        make(m["id"])
    assert (ValueBot.w, ValueBot.net) == before


def test_the_hand_set_value_bots_play_with_the_hand_set_weights_and_their_rules():
    from balatro.strategy import Weights
    full, first = make("value"), make("value-first-rules")
    assert full.w == Weights() and full.net is None              # not the planner's weights
    assert first.w.mods["Supernova"] == 0.0 and first.w.mods["Runner"] == 1.0


@pytest.mark.parametrize("bad", ["nope", "saved:../x", "saved:planner", "evolve:123", "evolve:../../etc"])
def test_unknown_models_are_refused(bad):
    with pytest.raises(KeyError):
        make(bad)
