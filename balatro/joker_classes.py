"""Joker classes from Jev's labels (scripts/classify_jokers.py, runs/classes/): for each joker, the weight Jev gives
each class of six facets (how its value changes, what it does with money, what it makes, which rule it changes, what
the build needs, what it risks), for the value bot's class genes (Weights.classes: 0 by default, so nothing changes
until evolution sets them). Growth is from the second version of the question and the rest from the first: the
versions that agree best with hand labels. Without the labels files there are no classes."""
from __future__ import annotations

import json
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "runs" / "classes"
# facet -> its classes; each facet's "nothing" class (fixed, none, nothing) is left out: it is the baseline
FACETS = {"growth": ("grows", "resets", "shrinks", "follows"),
          "money": ("every_round", "on_event", "sell", "uses", "cheaper"),
          "makes": ("tarot", "planet", "spectral", "joker", "cards"),
          "rules": ("hands", "limits", "slots", "chance", "shop", "boss"),
          "wants": ("hand_type", "suit", "rank", "enhanced", "deck", "jokers", "timing"),
          "risk": ("self", "destroys", "drawback")}
CLASSES = [f"{f}:{c}" for f, cs in FACETS.items() for c in cs]


def _load() -> dict[str, dict[str, float]]:
    """joker -> {"facet:class": Jev's weight}, leaving out weights under 0.05."""
    try:
        v1 = json.loads((DIR / "jokers.json").read_text())["jokers"]
        v2 = json.loads((DIR / "jokers_v2.json").read_text())["jokers"]
    except (OSError, ValueError, KeyError):
        return {}
    out = {}
    for name, facets in v1.items():
        out[name] = {f"{f}:{c}": p for f in FACETS
                     for c, p in (v2.get(name, {}) if f == "growth" else facets).get(f, {}).get("probs", {}).items()
                     if c in FACETS[f] and p >= 0.05}
    return out


JOKER_CLASSES = _load()
