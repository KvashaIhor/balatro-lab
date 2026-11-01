"""Game content: every module in this folder registers its jokers, consumables, bosses, tags, vouchers or
decks when imported. Importing the package imports them all, so a new module needs no registration.

A module that fails to import is recorded in FAILED instead of breaking every other module;
tests/test_content.py fails while FAILED is not empty."""
import importlib
import pkgutil
import traceback

FAILED: dict[str, str] = {}

for _module in pkgutil.iter_modules(__path__):
    try:
        importlib.import_module(f"{__name__}.{_module.name}")
    except Exception:  # noqa: BLE001  reported by tests/test_content.py
        FAILED[_module.name] = traceback.format_exc()
