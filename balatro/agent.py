"""What a player decides, as the run asks it. Subclass Agent and override the decisions you make; the
defaults never skip, never reroll the boss, play the first card, buy nothing and skip packs.

Actions are tuples. Card positions are indexes into `run.hand`; at most 5 cards per play or discard.

Any time (round, shop, open pack) - these don't end the decision, the run asks again:
    ("use", i, [cards])          use consumable i on the given hand cards ([] when it needs none)
    ("sell_joker", i)            ("sell_consumable", i)
    ("order_jokers", [perm])     ("order_hand", [perm])    rearrange (perm lists every old index once)
    ("sort_hand", "rank" | "suit")    sort the hand, and keep it sorted after every draw (as the game does)
Round:  ("play", [cards])        ("discard", [cards])
Shop:   ("buy", "card" | "pack" | "voucher", i)    ("buy_use", i, [cards])  buy consumable i and use it now
        ("reroll",)              ("leave",)
Pack:   ("pick", i, [cards])     ("skip",)
"""
from __future__ import annotations


class Agent:
    def skip_blind(self, run, blind, tag) -> bool:
        """Skip this Small or Big Blind for its tag?"""
        return False

    def reroll_boss(self, run, boss) -> bool:
        """Pay $10 to reroll the ante's boss (needs Director's Cut or Retcon)?"""
        return False

    def round_action(self, run) -> tuple:
        return ("play", [0])

    def shop_action(self, run, shop) -> tuple:
        return ("leave",)

    def pack_action(self, run, pack) -> tuple:
        return ("skip",)
