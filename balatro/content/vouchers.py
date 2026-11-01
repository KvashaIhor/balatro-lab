"""The 32 vouchers. Those the run checks by name (Telescope, Observatory, Omen Globe, Magic Trick,
Illusion, the Merchants and Tycoons, Director's Cut, Retcon, Blank) need no code beyond registering.
Source: data/vouchers.json."""
from ..items import Voucher, entries, voucher


def _set(**changes):
    """A voucher that sets run attributes."""
    def apply(self, run):
        for attr, value in changes.items():
            setattr(run, attr, value)
    return apply


def _add(**changes):
    """A voucher that adds to run attributes."""
    def apply(self, run):
        for attr, value in changes.items():
            setattr(run, attr, getattr(run, attr) + value)
    return apply


def _overstock(self, run):
    run.shop_card_slots += 1
    if run.current_shop is not None:
        run.current_shop.add_card_slot()


def _glyph(attr):
    def apply(self, run):
        run.ante -= 1
        setattr(run, attr, getattr(run, attr) - 1)
    return apply


EFFECTS = {
    "Overstock": _overstock, "Overstock Plus": _overstock,
    "Clearance Sale": _set(discount_percent=25), "Liquidation": _set(discount_percent=50),
    "Hone": _set(edition_rate=2), "Glow Up": _set(edition_rate=4),
    "Reroll Surplus": _set(reroll_base=3), "Reroll Glut": _set(reroll_base=1),
    "Crystal Ball": _add(consumable_slots=1), "Antimatter": _add(joker_slots=1),
    "Grabber": _add(base_hands=1), "Nacho Tong": _add(base_hands=1),
    "Wasteful": _add(base_discards=1), "Recyclomancy": _add(base_discards=1),
    "Seed Money": _set(interest_cap=10), "Money Tree": _set(interest_cap=20),
    "Paint Brush": _add(base_hand_size=1), "Palette": _add(base_hand_size=1),
    "Hieroglyph": _glyph("base_hands"), "Petroglyph": _glyph("base_discards"),
}

for _entry in entries("voucher"):
    _name = _entry["name"]
    _body = {"name": _name}
    if _name in EFFECTS:
        _body["apply"] = EFFECTS[_name]
    voucher(type(_name.replace(" ", "").replace("'", ""), (Voucher,), _body))
