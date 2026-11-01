"""The 12 Planet cards; each levels up its poker hand (hand and cost from data/consumables.json)."""
from ..items import Planet, consumable, entries

for _entry in entries("planet"):
    consumable(type(_entry["name"].replace(" ", ""), (Planet,), {"name": _entry["name"]}))
