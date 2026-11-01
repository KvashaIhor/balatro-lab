"""Play seeds as scripts/eval_value.py does (ValueBot, hand-set weights, Red Deck to ante 8) in the code at ROOT, and
record every decision as a step the Play tab replays ({"kind", "action"}): to find where two versions of the bot part.
Usage: ROOT=<snapshot> python3 scripts/trace_game.py OUT_DIR SEED [SEED ...]   (ROOT: a frozen copy of the code)"""
import json, os, sys, time
ROOT = os.environ["ROOT"]
sys.path.insert(0, ROOT)
os.environ.setdefault("VALUEBOT_WEIGHTS", "hand")
from multiprocessing import Pool
from balatro.run import Run
from balatro.strategy import ValueBot

def plain(a):
    return [list(x) if isinstance(x, (list, tuple)) else x for x in a]

class Traced(ValueBot):
    def __init__(self):
        super().__init__()
        self.trace = []
    def skip_blind(self, run, blind, tag):
        a = super().skip_blind(run, blind, tag)
        self.trace.append({"kind": "select", "action": ["skip" if a else "select"], "ante": run.ante})
        return a
    def reroll_boss(self, run, boss):
        a = super().reroll_boss(run, boss)
        self.trace.append({"kind": "boss", "action": ["reroll" if a else "keep"], "ante": run.ante})
        return a
    def round_action(self, run):
        a = super().round_action(run)
        self.trace.append({"kind": "round", "action": plain(a), "ante": run.ante})
        return a
    def shop_action(self, run, shop):
        a = super().shop_action(run, shop)
        self.trace.append({"kind": "shop", "action": plain(a), "ante": run.ante})
        return a
    def pack_action(self, run, pack):
        a = super().pack_action(run, pack)
        self.trace.append({"kind": "pack", "action": plain(a), "ante": run.ante})
        return a

def one(args):
    out, seed = args
    bot = Traced()
    res = Run(bot, game_seed=seed, deck="Red Deck", max_ante=8).play()
    json.dump({"seed": seed, "won": res.won, "ante": res.ante, "steps": bot.trace}, open(f"{out}/{seed}.json", "w"))
    return seed, res.won, res.ante, len(bot.trace)

if __name__ == "__main__":
    out, seeds = sys.argv[1], sys.argv[2:]
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    with Pool(8) as pool:
        for i, r in enumerate(pool.imap_unordered(one, [(out, s) for s in seeds]), 1):
            print(f"{time.strftime('%T')} {i}/{len(seeds)} {r} {time.time() - t0:.0f}s", flush=True)
