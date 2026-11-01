"""Validate rng.py / opening.py against everything we could find.

    python3 -u validate.py                 # ~5 s, log: logs/validate.log
    python3 -u validate.py --erratic-all   # also stream all 26,803 rows of dlew's result.txt (~40 s)

Sections
  A. RNG test vectors published with dlew/balatro-erratic-generator (MIT).
  B. Erratic Deck facts: the blog's named seeds, the 35 "all 10 of Spades" seeds (a NaN in the
     hash -- only reproducible if pseudohash is bit exact) and a sample of dlew's result.txt.
  C. Seed claims published by players (articles, Steam, Reddit via articles), each modelled as the
     scenario the player describes.  Claims from before Balatro 1.0.1 are run in 1.0.0 mode.
  D. Cross-check with another independent implementation (Motely's analyzer snapshots).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from opening import DECK_ORDER, Run
from rng import GameRNG, LuaRandom, pseudohash

HERE = Path(__file__).resolve().parent
LOG = HERE / "logs" / "validate.log"
T0 = time.time()
_log_fh = None


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} +{time.time() - T0:6.1f}s  {msg}"
    print(line, flush=True)
    _log_fh.write(line + "\n")
    _log_fh.flush()


RESULTS: list[tuple[str, str, str]] = []      # (section, item, PASS/FAIL/PARTIAL/INFO)


def record(section: str, item: str, status: str, detail: str = "") -> None:
    RESULTS.append((section, item, status))
    log(f"[{section}] {status:8s} {item}" + (f"  -- {detail}" if detail else ""))


# ----------------------------------------------------------------------------------------------
# A. RNG vectors (from dlew/balatro-erratic-generator src/main.rs tests, MIT licence)
# ----------------------------------------------------------------------------------------------
def section_a():
    vec = [
        ("pseudohash('erratic')", pseudohash("erratic"), 0.45752552206801056),
        ("pseudohash('erratic11153DRU')", pseudohash("erratic11153DRU"), 0.8218377909411174),
        ("pseudohash('11153DRU')", pseudohash("11153DRU"), 0.6472053688891037),
        ("pseudohash('7LB2WVPK')", pseudohash("7LB2WVPK"), 0.17691054639954018),
        ("random(1.0)", LuaRandom(1.0).random(), 0.3238105623786367),
        ("random(0.15252152112567)", LuaRandom(0.15252152112567).random(), 0.9092652238207108),
        ("random(0.5993819212141018)", LuaRandom(0.5993819212141018).random(), 0.02339323168160301),
    ]
    for name, got, want in vec:
        record("A", name, "PASS" if got == want else "FAIL", f"got {got!r} want {want!r}")
    g = GameRNG("11153DRU")
    ps = g.pseudoseed("erratic")
    ok = ps == 0.5993819212141018 and g.state["erratic"] == 0.5515584735391
    record("A", "pseudoseed('erratic') for 11153DRU", "PASS" if ok else "FAIL", f"{ps!r}")
    nan = pseudohash("erratic7LB2WVPK")
    record("A", "pseudohash('erratic7LB2WVPK') is NaN", "PASS" if nan != nan else "FAIL")


# ----------------------------------------------------------------------------------------------
# B. Erratic Deck
# ----------------------------------------------------------------------------------------------
DECK_RANKS = "23456789AJKQT"


def erratic_counts(seed: str):
    g = GameRNG(seed)
    ranks, suits = [0] * 13, [0] * 4
    for _ in range(52):
        c = DECK_ORDER[g.element_index("erratic", 52)]
        suits["CDHS".index(c[0])] += 1
        ranks[DECK_RANKS.index(c[1])] += 1
    rk = max(range(13), key=lambda i: (ranks[i], -i))
    sk = max(range(4), key=lambda i: (suits[i], -i))
    return ranks[rk], DECK_RANKS[rk], suits[sk], "CDHS"[sk]


# Blog post (https://blog.danlew.net/2025/11/03/balatros-least-erratic-decks/): named results.
ERRATIC_NAMED = [("I3EFEF17", 25, "T", None, None), ("RGJO14OZ", 24, "4", None, None),
                 ("8778L6US", None, None, 39, "H"), ("77XX2TEK", 20, "4", 38, "S"),
                 ("11153DRU", 17, "K", 19, "D")]
ERRATIC_NAN_SEEDS = """BGY5SDS 1V3UQ6AP 36756M6I 3WBV4FSC 627SP6LE 6WG44S7Z 7LB2WVPK 81N7QMOM 9PCOBR2D
B9A4IA7S CJFU1DL1 DHHHTLKL ENNGZMF2 FAH3Y3S9 HOWRQJVZ I4N2BX1E IU2LKGT8 N9ER1XLW NSPURPAH NWMELXAM
O6BRINCY O7CMD6K7 PHLSY9F4 Q6SEQZLP QIB7UA76 RDNCZ58P S4DM5V37 S4TMWWAE S793AULP SNML7XC8 SS44ACWE
SSU4L34S TO7WNQA5 XEQH7CP9 ZZFHQFDG""".split()
# 25 rows of https://github.com/dlew/balatro-erratic-generator/blob/main/result.txt (MIT).
ERRATIC_SAMPLE = """54KOIP 7 8 34 C|5699DT 6 2 34 D|5YUIMA 20 5 18 H|69DVL8 9 J 34 D|6GJQKU 20 7 16 H
6GY4BD 20 T 16 C|6GYRBQ 6 3 35 S|AMNSLF 21 5 16 H|B64VT5 20 6 15 S|DTS5ET 20 5 17 S|FGHEHV 9 J 34 H
HMJVD4 21 Q 16 S|K5N7XB 20 T 15 D|M6YG9Z 20 J 15 C|O2P9K4 20 Q 15 C|QNDAJE 20 6 16 C|R3G7WT 8 2 34 H
RXN1VZ 7 A 35 C|SJ6Q1M 7 K 34 H|SK4TEB 20 3 18 H|W2SKCZ 8 Q 34 C|XH2YOF 20 9 14 H|XY61PD 20 Q 18 C
12CWMHG 6 T 34 S|1435GLA 20 7 17 C""".replace("\n", "|").split("|")


def section_b(all_rows: bool):
    for seed, rc, r, sc, s in ERRATIC_NAMED:
        got = erratic_counts(seed)
        ok = (rc is None or (got[0], got[1]) == (rc, r)) and (sc is None or (got[2], got[3]) == (sc, s))
        record("B", f"Erratic {seed}", "PASS" if ok else "FAIL", f"got {got}")
    bad = [s for s in ERRATIC_NAN_SEEDS if erratic_counts(s) != (52, "T", 52, "S")]
    record("B", f"all {len(ERRATIC_NAN_SEEDS)} NaN seeds give 52 x 10 of Spades",
           "PASS" if not bad else "FAIL", f"mismatches: {bad}")
    bad = []
    for row in ERRATIC_SAMPLE:
        seed, rc, r, sc, s = row.split()
        if erratic_counts(seed) != (int(rc), r, int(sc), s):
            bad.append(seed)
    record("B", f"{len(ERRATIC_SAMPLE)} sampled rows of dlew result.txt",
           "PASS" if not bad else "FAIL", f"mismatches: {bad}")
    if all_rows:
        url = "https://raw.githubusercontent.com/dlew/balatro-erratic-generator/main/result.txt"
        log(f"[B] downloading {url} into memory (data only, not saved)")
        try:
            text = urllib.request.urlopen(url, timeout=60).read().decode()
        except Exception as e:          # python.org builds on macOS often lack CA certificates
            log(f"[B]   urllib failed ({e.__class__.__name__}); using curl")
            text = subprocess.run(["curl", "-sL", "--max-time", "120", url], check=True,
                                  capture_output=True, text=True).stdout
        pat = re.compile(r"seed: (\w+), Rank Count: (\d+), Rank: (\w), Suit Count: (\d+), Suit: (\w)")
        rows = sorted({m.groups() for m in pat.finditer(text)})
        n, bad, t = len(rows), [], time.time()
        for i, (seed, rc, r, sc, s) in enumerate(rows, 1):
            if erratic_counts(seed) != (int(rc), r, int(sc), s):
                bad.append(seed)
            if i % 5000 == 0 or i == n:
                el = time.time() - t
                log(f"[B]   {i}/{n} rows, {i / el:.0f} rows/s, ETA {(n - i) / (i / el):.0f}s, mismatches {len(bad)}")
        # dlew rounds with (x*1e13).round()/1e13; the game uses string.format("%.13f") (exact).
        # Re-run the mismatches with dlew's approximation to see whether that explains them all.
        import rng as rng_mod
        exact = rng_mod.round13

        def approx13(x):
            return x if x != x else abs(float(int(x * 1e13 + 0.5)) / 1e13)
        rng_mod.round13 = approx13
        try:
            rows_by_seed = {row[0]: row for row in rows}
            unexplained = [s for s in bad if erratic_counts(s) != (int(rows_by_seed[s][1]), rows_by_seed[s][2],
                                                                    int(rows_by_seed[s][3]), rows_by_seed[s][4])]
        finally:
            rng_mod.round13 = exact
        record("B", f"all {n} unique rows of dlew result.txt",
               "PASS" if not unexplained else "FAIL",
               f"{n - len(bad)} identical; {len(bad)} differ and ALL {len(bad) - len(unexplained)} are explained "
               f"by dlew's approximate 13-digit rounding (with it we match {n - len(unexplained)}/{n}); "
               f"in-game tie-breakers: {bad[:3]}")
        for s in bad[:3]:
            rng_mod.round13 = approx13
            alt = erratic_counts(s)
            rng_mod.round13 = exact
            log(f"[B]   {s}: exact rounding -> {erratic_counts(s)}, approximate rounding -> {alt}")


# ----------------------------------------------------------------------------------------------
# C. Published seed claims
# ----------------------------------------------------------------------------------------------
def names(cards):
    return [c["name"] for c in cards]


def soul_legendary(run: Run, pack_cards, ante):
    return run.legendary(ante)["name"] if "The Soul" in names(pack_cards) else None


def skip_both_shop(run: Run, held):
    """Player skips Small and Big: the first shop is the one after the ante-1 Boss (ante 2)."""
    return run.shop(2, tags=list(held))


def claim(item, src, cond: dict, version="1.0.1"):
    """cond: name -> (ok: bool, shown) ; overall PASS if all ok, PARTIAL if some, FAIL if none."""
    oks = [v[0] for v in cond.values()]
    status = "PASS" if all(oks) else ("PARTIAL" if any(oks) else "FAIL")
    detail = "; ".join(f"{k}={'ok' if v[0] else 'NO'} ({v[1]})" for k, v in cond.items())
    record("C", f"{item} [{version}] <{src}>", status, detail)


def section_c():
    IG = "insider-gaming.com/best-balatro-seeds (2025-01-09)"
    CB = "comicbook.com best-balatro-seeds-strategy (2025-02-14)"
    DS = "destructoid.com/best-balatro-seeds (2024-03-29)"
    ST = "steamcommunity 4346607305576903701 (2024-02-26)"

    # KH77XUG6: skip both -> Double + Investment; "a Telescope and a Walkie Talkie are offered early"
    for ver in ("1.0.1", "1.0.0"):
        r = Run("KH77XUG6", version=ver)
        tags = {r.tag(1), r.tag(1)}
        v2 = r.voucher(2)
        sh = skip_both_shop(r, [])
        claim("KH77XUG6 tags Double+Investment, Telescope & Walkie Talkie early", ST, {
            "tags": (tags == {"Double Tag", "Investment Tag"}, sorted(tags)),
            "ante-2 voucher Telescope": (v2 == "Telescope", v2),
            "Walkie Talkie in first (ante-2) shop": ("Walkie Talkie" in names(sh["cards"]), names(sh["cards"])),
        }, ver)

    # 11EVFRPQ: voucher chain when every voucher is bought
    r = Run("11EVFRPQ")
    chain = {}
    for a in range(1, 13):
        v = r.voucher(a)
        chain[a] = v
        r.vouchers_bought.add(v)
    want = {1: "Telescope", 2: "Director's Cut", 3: "Retcon", 4: "Observatory", 7: "Overstock",
            10: "Blank", 12: "Antimatter"}
    claim("11EVFRPQ voucher per ante (all bought)", IG,
          {f"ante {a} {v}": (chain[a] == v, chain[a]) for a, v in want.items()})

    # 8Q47WV6K: skip both -> Double Tag + Charm Tag (Mega Arcana) twice; Triboulet and Perkeo;
    # "the second pack has Temperance"
    r = Run("8Q47WV6K")
    tags = [r.tag(1), r.tag(1)]
    p1 = r.open_pack("Mega Arcana Pack", 1)
    l1 = soul_legendary(r, p1, 1)
    p2 = r.open_pack("Mega Arcana Pack", 1)
    l2 = soul_legendary(r, p2, 1)
    claim("8Q47WV6K Double+Charm, two Mega Arcana -> Triboulet & Perkeo, Temperance in 2nd", IG, {
        "tags": (sorted(tags) == ["Charm Tag", "Double Tag"], tags),
        "legendaries": ({l1, l2} == {"Triboulet", "Perkeo"}, [l1, l2]),
        "Temperance in pack 2": ("Temperance" in names(p2), names(p2)),
    })

    # PKF1939A: skip both -> two Rare Tags, then the Buffoon pack: Burnt Joker, Brainstorm, Blueprint
    r = Run("PKF1939A")
    tags = [r.tag(1), r.tag(1)]
    sh = skip_both_shop(r, tags)
    buf = r.open_pack(sh["packs"][0], 2) if "Buffoon" in sh["packs"][0] else []
    got = set(names(sh["cards"])) | set(names(buf))
    claim("PKF1939A two Rare Tags + Buffoon Pack -> Burnt Joker, Brainstorm, Blueprint", CB, {
        "tags": (tags == ["Rare Tag", "Rare Tag"], tags),
        "jokers": ({"Burnt Joker", "Brainstorm", "Blueprint"} <= got,
                   f"shop {names(sh['cards'])}, {sh['packs'][0]} {names(buf)}"),
    })

    # RBPTDL2H: skip both -> Perkeo in the first Arcana pack + Polychrome Fortune Teller
    r = Run("RBPTDL2H")
    tags = [r.tag(1), r.tag(1)]
    sh = skip_both_shop(r, tags)
    arc = [p for p in sh["packs"] if "Arcana" in p]
    leg = soul_legendary(r, r.open_pack(arc[0], 2), 2) if arc else None
    first_joker = next((c["name"] for c in sh["cards"] if c["type"] == "Joker"), None)
    claim("RBPTDL2H skip both -> Perkeo in first Arcana pack, Polychrome Fortune Teller", CB, {
        "Polychrome Tag held": ("Polychrome Tag" in tags, tags),
        "first shop joker Fortune Teller": (first_joker == "Fortune Teller", names(sh["cards"])),
        "Arcana pack -> Perkeo": (leg == "Perkeo", f"{sh['packs']} -> {leg}"),
    })

    # 99K6IUBD: "Shop 1 contains a Negative Blueprint Joker and a Brainstorm"
    r = Run("99K6IUBD")
    r.tag(1), r.tag(1)
    sh = r.shop(1)
    buf = r.open_pack(sh["packs"][0], 1)
    c0 = sh["cards"][0]
    claim("99K6IUBD first shop: Negative Blueprint and Brainstorm", CB, {
        "Negative Blueprint": (c0["name"] == "Blueprint" and c0["edition"] == "Negative", c0),
        "Brainstorm (in the shop's Buffoon Pack)": ("Brainstorm" in names(buf), names(buf)),
    })

    # AYU7KNQ7: "Skip the first blind for a Polychrome Stencil Joker"
    r = Run("AYU7KNQ7")
    small = r.tag(1)
    r.tag(1)
    sh = r.shop(1)
    claim("AYU7KNQ7 skip small -> Polychrome Joker Stencil", CB, {
        "small tag Polychrome": (small == "Polychrome Tag", small),
        "first shop joker Joker Stencil": (sh["cards"][0]["name"] == "Joker Stencil", names(sh["cards"])),
    })

    # D97FB8XS / 86GRJT3C: "Skip the first Small Blind for Triboulet" (Charm Tag -> Mega Arcana)
    for seed in ("D97FB8XS", "86GRJT3C"):
        r = Run(seed)
        small = r.tag(1)
        r.tag(1)
        leg = soul_legendary(r, r.open_pack("Mega Arcana Pack", 1), 1)
        claim(f"{seed} skip small -> Triboulet", IG, {
            "small tag Charm": (small == "Charm Tag", small),
            "Mega Arcana -> Triboulet": (leg == "Triboulet", leg),
        })

    # Pre-1.0.1 claims (Destructoid, credited to Reddit users) -> run in 1.0.0 mode
    for ver in ("1.0.0", "1.0.1"):
        r = Run("LH28B6PF", version=ver)
        small, big = r.tag(1), r.tag(1)
        leg = soul_legendary(r, r.open_pack("Mega Arcana Pack", 1), 1)
        sh = skip_both_shop(r, [big])
        claim("LH28B6PF skip small -> Perkeo; skip big -> Invisible Joker", DS, {
            "tags Charm, Rare": ((small, big) == ("Charm Tag", "Rare Tag"), (small, big)),
            "Charm pack -> Perkeo": (leg == "Perkeo", leg),
            "Rare Tag joker Invisible Joker": (sh["cards"][0]["name"] == "Invisible Joker", names(sh["cards"])),
        }, ver)

        r = Run("V14NKYRB", version=ver)
        tags = [r.tag(1), r.tag(1)]
        sh = skip_both_shop(r, tags)
        arc = [p for p in sh["packs"] if "Arcana" in p]
        leg = soul_legendary(r, r.open_pack(arc[0], 2), 2) if arc else None
        claim("V14NKYRB skip both -> Blueprint & The Duo in shop, Triboulet in Arcana pack", DS, {
            "shop": (set(names(sh["cards"])) == {"Blueprint", "The Duo"}, names(sh["cards"])),
            "Arcana -> Triboulet": (leg == "Triboulet", f"{sh['packs']} -> {leg}"),
        }, ver)

        r = Run("6FCKWFSZ", version=ver)
        small = r.tag(1)
        r.tag(1)
        sh = r.shop(1)
        arc = [p for p in sh["packs"] if "Arcana" in p]
        leg = soul_legendary(r, r.open_pack(arc[0], 1), 1) if arc else None
        claim("6FCKWFSZ skip small: Polychrome Credit Card, Sock and Buskin, Arcana -> Triboulet", DS, {
            "small tag Polychrome": (small == "Polychrome Tag", small),
            "shop": (names(sh["cards"]) == ["Credit Card", "Sock and Buskin"], names(sh["cards"])),
            "Arcana -> Triboulet": (leg == "Triboulet", f"{sh['packs']} -> {leg}"),
        }, ver)

    # Remaining Destructoid entries (not credited to anyone in the article)
    r = Run("5IVQ8I9Y")
    v1 = r.voucher(1)
    v2 = r.voucher(2)
    r.tag(1), r.tag(1)
    sh = r.shop(1)
    claim("5IVQ8I9Y 'Golden Joker and Discount Voucher in the first shop'", DS, {
        "Golden Joker": ("Golden Joker" in names(sh["cards"]), names(sh["cards"])),
        "Clearance Sale voucher": (v1 == "Clearance Sale", f"ante1 {v1}, ante2 {v2}"),
    })
    for ver in ("1.0.1", "1.0.0"):
        for seed, joker in (("477S1AMK", "Splash"), ("X4WH84AX", "Ride the Bus")):
            r = Run(seed, version=ver)
            r.tag(1), r.tag(1)
            sh = r.shop(1)
            claim(f"{seed} '{joker} in the first shop'", DS,
                  {joker: (joker in names(sh["cards"]), names(sh["cards"]))}, ver)
        r = Run("VGSCB3QZ", version=ver)
        small = r.tag(1)
        r.tag(1)
        sh = r.shop(1, tags=[small])
        souls = [p for p in sh["packs"] if "Arcana" in p and "The Soul" in names(r.open_pack(p, 1))]
        claim("VGSCB3QZ 'Soul from the Arcana pack in the store after skipping Small'", DS,
              {"Arcana with Soul": (bool(souls), sh["packs"])}, ver)
        r = Run("BZBZBXCB", version=ver)
        tags = [r.tag(1), r.tag(1)]
        sh = skip_both_shop(r, tags)
        souls = [p for p in sh["packs"] if "Arcana" in p and "The Soul" in names(r.open_pack(p, 2))]
        claim("BZBZBXCB 'Soul from the Arcana pack after skipping Small and Big'", DS,
              {"Arcana with Soul": (bool(souls), sh["packs"])}, ver)
        r = Run("JXLYA4I8", version=ver)
        r.tag(1), r.tag(1)
        sh = r.shop(1)
        legs = []
        for p in sh["packs"]:
            if "Arcana" in p or "Spectral" in p:
                legs.append(soul_legendary(r, r.open_pack(p, 1), 1))
        claim("JXLYA4I8 'Canio in the first pack'", DS, {"Canio": ("Canio" in legs, f"{sh['packs']} -> {legs}")}, ver)
        r = Run("ZURCAMOS", version=ver)
        small = r.tag(1)
        r.tag(1)
        sh = r.shop(1, tags=[small])
        ouija = [p for p in sh["packs"] if "Spectral" in p and "Ouija" in names(r.open_pack(p, 1))]
        claim("ZURCAMOS 'Spectral Pack with Ouija after skipping the first Blind'", DS,
              {"Spectral pack with Ouija": (bool(ouija), sh["packs"])}, ver)


# ----------------------------------------------------------------------------------------------
# D. Motely (independent C# implementation) analyzer snapshots, ante 1, Red Deck, White Stake.
#    https://github.com/Tacodiva/Motely/tree/master/Motely.Tests/seeds  (facts transcribed)
# ----------------------------------------------------------------------------------------------
MOTELY = {
    "1234567": ("The Psychic", "Crystal Ball", ("Juggle Tag", "Rare Tag"), ("The Sun", "Mad Joker"),
                ("Buffoon Pack", "Celestial Pack"), ("Wrathful Joker", "Greedy Joker"), ("Earth", "Jupiter", "Ceres")),
    "12345678": ("The Pillar", "Blank", ("Investment Tag", "Boss Tag"), ("Neptune", "Pareidolia"),
                 ("Buffoon Pack", "Jumbo Arcana Pack"), ("Ice Cream", "Spare Trousers"),
                 ("The Magician", "The Hanged Man", "Strength", "The Fool", "The Wheel of Fortune")),
    "ALEEB": ("The Window", "Magic Trick", ("Speed Tag", "Speed Tag"), ("Trading Card", "Rocket"),
              ("Buffoon Pack", "Arcana Pack"), ("Red Card", "Riff-Raff"), ("Temperance", "The Empress", "The Soul")),
    "ALEEBOOO": ("The Goad", "Grabber", ("Holographic Tag", "Juggle Tag"), ("Ceres", "Drunkard"),
                 ("Buffoon Pack", "Jumbo Standard Pack"), ("Burglar", "Madness"), None),
    "UNITTES": ("The Club", "Telescope", ("Economy Tag", "Juggle Tag"), ("Hanging Chad", "The Wheel of Fortune"),
                ("Buffoon Pack", "Jumbo Arcana Pack"), ("Egg", "Joker"),
                ("The Hierophant", "The Tower", "The Magician", "Death", "The Lovers")),
    "UNITTEST": ("The Window", "Tarot Merchant", ("Speed Tag", "Speed Tag"), ("Hallucination", "Stone Joker"),
                 ("Buffoon Pack", "Mega Standard Pack"), ("Constellation", "Cloud 9"), None),
}
GATED = {"Ceres", "Planet X", "Eris", "Stone Joker", "Steel Joker", "Glass Joker", "Golden Ticket",
         "Lucky Cat", "Cavendish"}


def section_d():
    for seed, (boss, vch, tags, cards, packs, buf, pack2) in MOTELY.items():
        r = Run(seed)
        got = {"boss": r.boss_ante1(), "voucher": r.voucher(1), "tags": (r.tag(1), r.tag(1))}
        sh = r.shop(1)
        got["cards"] = tuple(names(sh["cards"]))
        got["packs"] = tuple(sh["packs"])
        got["buf"] = tuple(names(r.open_pack(sh["packs"][0], 1)))
        got["pack2"] = None if "Standard" in sh["packs"][1] else tuple(names(r.open_pack(sh["packs"][1], 1)))
        for k, want in (("boss", boss), ("voucher", vch), ("tags", tags), ("packs", packs), ("buf", buf)):
            record("D", f"Motely {seed} {k}", "PASS" if got[k] == want else "FAIL", f"{got[k]}")
        for k, want in (("cards", cards), ("pack2", pack2)):
            if want is None:
                continue
            diff = [(w, g) for w, g in zip(want, got[k]) if w != g]
            if not diff:
                record("D", f"Motely {seed} {k}", "PASS", f"{got[k]}")
            elif all(w in GATED for w, _ in diff):
                record("D", f"Motely {seed} {k}", "INFO", f"differs only where Motely shows a card the "
                       f"game soft-locks at run start ({diff}); ours resamples")
            else:
                record("D", f"Motely {seed} {k}", "FAIL", f"{got[k]} vs {want}")


def section_e():
    """Pool contents and order vs the project's own sourced rules data (../data/*.json)."""
    import json
    import opening as op
    data = HERE.parent / "data"
    if not data.exists():
        record("E", "../data not found", "INFO")
        return
    js = sorted(json.load(open(data / "jokers.json")), key=lambda j: j["n"])
    for rar, pool in (("Common", op.COMMON_JOKERS), ("Uncommon", op.UNCOMMON_JOKERS),
                      ("Rare", op.RARE_JOKERS), ("Legendary", op.LEGENDARY_JOKERS)):
        want = [j["name"] for j in js if j["rarity"] == rar]
        record("E", f"{rar} joker pool = jokers.json collection order", "PASS" if want == pool else "FAIL",
               f"{len(pool)} jokers")
    vs = [v["name"] for v in json.load(open(data / "vouchers.json"))["vouchers"]]
    record("E", "voucher pool order = vouchers.json", "PASS" if vs == op.VOUCHERS else "FAIL")
    tg = json.load(open(data / "tags.json"))["tags"]
    ok = [t["name"] for t in tg] == op.TAGS and {t["name"] for t in tg if t["min_ante"] == 2} == op.TAGS_MIN_ANTE_2
    record("E", "tag pool order and min-ante-2 set = tags.json", "PASS" if ok else "FAIL")
    bs = json.load(open(data / "bosses.json"))["bosses"]
    a1 = sorted((b["key"], b["name"]) for b in bs if b["min_ante"] <= 1 and not b["showdown"])
    record("E", "ante-1 boss set sorted by key = bosses.json", "PASS" if [n for _, n in a1] == op.BOSSES_ANTE1 else "FAIL",
           f"{[n for _, n in a1]}")
    cons = json.load(open(data / "consumables.json"))
    names_ = [c["name"] for c in cons["tarots"]]
    record("E", "tarots order = consumables.json", "PASS" if names_ == op.TAROTS else "FAIL", f"{names_[:3]}...")
    names_ = [c["name"] for c in cons["planets"]]
    same_set = set(names_) == set(op.PLANETS)
    record("E", "planets: same 12 cards as consumables.json", "PASS" if same_set else "FAIL")
    record("E", "planets order", "INFO", "consumables.json lists planets by poker hand (wiki table), not by "
           "the game's pool order; opening.py uses Mercury..Pluto, Planet X, Ceres, Eris (Immolate) -- "
           "not independently confirmed; ask for a seed whose first shop shows a planet")
    sp = [c["name"] for c in cons["spectrals"]]
    record("E", "spectral order = consumables.json", "PASS" if sp == op.SPECTRALS else "FAIL", f"{sp}")


def main():
    global _log_fh
    ap = argparse.ArgumentParser()
    ap.add_argument("--erratic-all", action="store_true")
    args = ap.parse_args()
    LOG.parent.mkdir(exist_ok=True)
    _log_fh = open(LOG, "w")
    log(f"validate.py start (python {sys.version.split()[0]})")
    for name, fn in (("A RNG vectors", section_a), ("B Erratic deck", lambda: section_b(args.erratic_all)),
                     ("C published claims", section_c), ("D Motely cross-check", section_d),
                     ("E pools vs ../data", section_e)):
        log(f"== section {name}")
        fn()
    summary = {}
    for sec, _, st in RESULTS:
        summary.setdefault(sec, {}).setdefault(st, 0)
        summary[sec][st] += 1
    log(f"SUMMARY {summary}")
    log(f"done in {time.time() - T0:.1f}s, exit 0")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        if _log_fh:
            _log_fh.write(traceback.format_exc())
        raise
