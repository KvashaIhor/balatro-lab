"""Copy the user's Balatro art into the app: named card images, plus pieces cut from sprite sheets.

The art is the game's (copyright LocalThunk / Playstack) and stays local: app/static/img is git-ignored
and nothing here is published.

Usage:  python3 scripts/import_assets.py <extracted balatro.zip folder> <folder with the sprite sheets>
        e.g. python3 scripts/import_assets.py /tmp/x/balatro ~/Downloads
Output: app/static/img/<kind>/<slug>.png and app/static/img/manifest.json (game name -> image path)
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "static" / "img"
CELL = (71, 95)  # one card on the 1x sprite sheets
SHEET_PREFIX = "PC _ Computer - Balatro - "
FOLDERS = {"jokers": "jokers", "tarot": "tarots", "planets": "planets", "spectral": "spectrals", "vouchers": "vouchers",
           "boosters": "boosters", "tags": "tags", "decks": "decks", "enhancers": "enhancers"}
RENAMED = {"driver": "Driver's License", "caino": "Canio", "director": "Director's Cut",  # file names that differ
           "skip tag": "Speed Tag"}  # from the game's names
SEAL_CELLS = {"Gold": (2, 0), "Purple": (4, 4), "Red": (5, 4), "Blue": (6, 4)}
# Floating figures on the Jokers sheet (column, row): row 9, under the legendaries' cards in row 8.
SOUL_CELLS = {"Hologram": (2, 9), "Canio": (3, 9), "Triboulet": (4, 9), "Yorick": (5, 9), "Chicot": (6, 9), "Perkeo": (7, 9)}
FACE_SUITS = ("Hearts", "Spades", "Clubs", "Diamonds")  # column groups on the Friends of Jimbo sheet
# Rows of the Blind Chips sheet (each row is one blind's animation), matched by colour and glyph.
BLIND_CHIP_ROWS = {"Small Blind": 0, "Big Blind": 1, "The Ox": 2, "The House": 3, "The Club": 4, "The Fish": 5,
                   "The Window": 6, "The Hook": 7, "The Manacle": 8, "The Wall": 9, "The Wheel": 10, "The Arm": 11,
                   "The Psychic": 12, "The Goad": 13, "The Water": 14, "The Serpent": 15, "The Pillar": 16, "The Eye": 17,
                   "The Mouth": 18, "The Plant": 19, "The Needle": 20, "The Head": 21, "The Tooth": 22, "The Mark": 23,
                   "The Flint": 24, "Crimson Heart": 25, "Cerulean Bell": 26, "Amber Acorn": 27, "Verdant Leaf": 28,
                   "Violet Vessel": 29}


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def title(file_stem: str, canonical: dict[str, str]) -> str:
    """The game's name for an image file: the exact name from our data when the slugs match
    (jokers: data/jokers_list.tsv), else title case with small words lowered after the first."""
    name = RENAMED.get(file_stem.split(" · ")[0], file_stem.split(" · ")[0])
    if slug(name) in canonical:
        return canonical[slug(name)]
    words = name.split()
    return " ".join(w[:1].upper() + w[1:] if k == 0 or w not in ("of", "the", "and") else w for k, w in enumerate(words))


def cut(sheet: Image.Image, x: int, y: int) -> Image.Image:
    w, h = CELL
    return sheet.crop((x * w, y * h, (x + 1) * w, (y + 1) * h)).resize((w * 2, h * 2), Image.NEAREST)


def main_colour(img: Image.Image) -> str:
    """The most common opaque colour of a sprite (a blind chip's face colour)."""
    counts: dict[tuple, int] = {}
    for r, g, b, a in img.getdata():
        if a > 200:
            counts[(r, g, b)] = counts.get((r, g, b), 0) + 1
    r, g, b = max(counts, key=counts.get)
    return f"#{r:02x}{g:02x}{b:02x}"


def main() -> int:
    named, sheets = Path(sys.argv[1]), Path(sys.argv[2])
    manifest: dict[str, dict[str, str]] = {}
    tsv = ROOT / "data" / "jokers_list.tsv"
    canonical = {slug(line.split("\t")[1]): line.split("\t")[1]
                 for line in tsv.read_text().splitlines() if line and not line.startswith("#")}
    for folder, kind in FOLDERS.items():
        (OUT / kind).mkdir(parents=True, exist_ok=True)
        entries = manifest.setdefault(kind, {})
        for f in sorted((named / folder).glob("*.png")):
            name = title(f.stem, canonical)
            target = OUT / kind / f"{slug(name)}.png"
            Image.open(f).save(target)  # re-encode: only pixels come across
            entries[name] = f"img/{kind}/{target.name}"
    manifest["jokers"]["Wee Joker"] = manifest["jokers"]["Joker"]  # the game draws Wee Joker as a small Joker

    cards = Image.open(sheets / f"{SHEET_PREFIX}Playing Cards - Card Backs, Enhancers and Seals.png").convert("RGBA")
    (OUT / "cards").mkdir(exist_ok=True)
    cut(cards, 1, 0).save(OUT / "cards" / "base.png")
    manifest["cards"] = {"base": "img/cards/base.png"}
    manifest["seals"] = {}
    for seal, (x, y) in SEAL_CELLS.items():
        cut(cards, x, y).save(OUT / "cards" / f"seal-{slug(seal)}.png")
        manifest["seals"][seal] = f"img/cards/seal-{slug(seal)}.png"

    faces = Image.open(sheets / f"{SHEET_PREFIX}Playing Cards - _Friends of Jimbo 1_ Playing Cards.png").convert("RGBA")
    manifest["faces"], manifest["faces_hc"] = {}, {}
    for s, suit in enumerate(FACE_SUITS):
        for r, rank in enumerate(("J", "Q", "K")):
            name = f"{rank}{suit[0]}"
            for row, key, suffix in ((0, "faces", ""), (1, "faces_hc", "-hc")):  # row 1: high-contrast colours
                cut(faces, s * 3 + r, row).save(OUT / "cards" / f"face-{name.lower()}{suffix}.png")
                manifest[key][name] = f"img/cards/face-{name.lower()}{suffix}.png"

    # The figures that float above the legendary jokers' cards, and Hologram's face: separate cells of the
    # Jokers sheet (the game draws them over the card, bobbing).
    jokers = sheets / f"{SHEET_PREFIX}Jokers and Consumables - Jokers.png"
    if jokers.exists():
        sheet = Image.open(jokers).convert("RGBA")
        manifest["souls"] = {}
        for name, (x, y) in SOUL_CELLS.items():
            cut(sheet, x, y).save(OUT / "jokers" / f"soul-{slug(name)}.png")
            manifest["souls"][name] = f"img/jokers/soul-{slug(name)}.png"

    sign = sheets / f"{SHEET_PREFIX}Miscellaneous - Shop Sign.png"  # 4 animation frames of 113 x 57
    if sign.exists():
        (OUT / "ui").mkdir(exist_ok=True)
        Image.open(sign).convert("RGBA").save(OUT / "ui" / "shop-sign.png")
        manifest["ui"] = {"shop_sign": "img/ui/shop-sign.png"}

    chips = Image.open(sheets / f"{SHEET_PREFIX}Blinds - Blind Chips.png").convert("RGBA")
    (OUT / "chips").mkdir(exist_ok=True)
    manifest["chips"], manifest["chip_colours"] = {}, {}
    for name, row in BLIND_CHIP_ROWS.items():  # first animation frame, 34 x 34 at 1x
        chip = chips.crop((0, row * 34, 34, row * 34 + 34))
        chip.resize((68, 68), Image.NEAREST).save(OUT / "chips" / f"{slug(name)}.png")
        manifest["chips"][name] = f"img/chips/{slug(name)}.png"
        manifest["chip_colours"][name] = main_colour(chip)

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print({kind: len(entries) for kind, entries in manifest.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
