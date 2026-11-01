"""Label every joker on a few facets (how it scores, how it grows, what it does with money, what it makes, which
rule it changes, what the build needs, what it risks), each a question Jev answers with a probability per option;
then compare the labels with the value bot's word-matched groups (strategy._joker_groups) and with what the engine
pays at the end of a round.

    python3 -u scripts/classify_jokers.py [--v2] >> logs/classify_jokers.log 2>&1

Writes runs/classes/jokers.json: per joker and facet, the label Jev gives most weight, that weight, and every
option's. Answers are cached (runs/jev/cache.sqlite), so a rerun costs nothing. --v2 asks again on growth and money
with clearer options and labelled examples (FACETS_V2) and writes runs/classes/jokers_v2.json (the other facets as
in jokers.json). Both are scored against GOLD, hand-labelled clear cases none of the examples are drawn from."""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from balatro.items import data  # noqa: E402
from balatro.jev import MODEL, PRICE_IN, Client  # noqa: E402

OUT = ROOT / "runs" / "classes" / "jokers.json"
INSTRUCTIONS = ("You are labelling the jokers of the game Balatro so that a bot can value them. A hand scores chips x "
                "mult; jokers add Chips or Mult, multiply Mult, pay money, make cards or change rules. Read this joker's "
                "effect and pick the one option that describes it best. {question}")
# facet -> (question, {label: option text}); each facet's options are exclusive, and each has a 'none' of some kind
FACETS = {
    "scoring": ("When it acts, how does it add to a hand's score?", {
        "chips": "It adds Chips",
        "mult": "It adds Mult",
        "xmult": "It multiplies Mult (xMult)",
        "retrigger": "It retriggers played or held cards",
        "copy": "It copies another joker's ability",
        "mixed": "It adds to the score in more than one of these ways",
        "none": "It never adds to a hand's score itself"}),
    "growth": ("Over a run, how does what it adds to the score change? Money it pays does not count here.", {
        "play": "It grows for good when something happens as hands are played (a hand type, cards scored)",
        "discard": "It grows for good from discards",
        "items": "It grows for good from shop or item actions (buying, selling, using consumables, skipping blinds "
                 "or packs, rerolling, adding or destroying cards)",
        "rounds": "It grows for good with every round or blind",
        "round_only": "It builds up within a round or an ante and then resets",
        "shrinks": "It shrinks or runs out as the run goes on",
        "deck": "It follows what the deck or the run holds right now (deck size, card types, money, jokers)",
        "fixed": "It never changes, or it adds nothing to the score"}),
    "money": ("What does it do with money?", {
        "every_round": "It pays money at the end of every round",
        "on_event": "It pays money when something happens in play, in discards or at a blind",
        "sell": "It raises sell values",
        "uses": "Its score depends on the money held",
        "cheaper": "It makes things cheaper or free, or lets money go below zero",
        "none": "Nothing to do with money"}),
    "makes": ("What does it create?", {
        "tarot": "Tarot cards",
        "planet": "Planet cards",
        "spectral": "Spectral cards",
        "joker": "Jokers",
        "cards": "Playing cards added to the deck",
        "none": "Nothing"}),
    "rules": ("Which rule of the game does it change?", {
        "hands": "How poker hands are formed or which cards count as what (suits, faces, straights, flushes)",
        "limits": "The number of hands, discards or cards in hand",
        "slots": "Joker or consumable slots",
        "chance": "The odds of random effects",
        "shop": "The shop, booster packs or rerolls",
        "boss": "Boss blinds",
        "none": "It changes no rule"}),
    "wants": ("What does the build need for it to work well?", {
        "hand_type": "A particular poker hand type",
        "suit": "Cards of a particular suit",
        "rank": "Particular ranks or face cards",
        "enhanced": "Enhanced cards, seals or editions",
        "deck": "A particular deck size or deck makeup",
        "jokers": "Few jokers, empty slots, or other particular jokers",
        "timing": "Playing at a particular moment (first or last hand, no discards used)",
        "nothing": "Nothing in particular"}),
    "risk": ("Does it carry a risk or a cost?", {
        "self": "It may destroy itself",
        "destroys": "It destroys cards or other jokers",
        "drawback": "It has a lasting drawback (fewer hands or discards, rising costs, debuffs)",
        "none": "No risk"}),
}

# Version 2 of the two facets the value bot's groups come from: one question per idea (a value the joker remembers,
# money it pays), and examples (none of them in GOLD).
FACETS_V2 = {
    "growth": ("Does the joker remember a value (Chips, Mult or xMult) that changes as the run goes on? Judge the "
               "joker, not the cards: a joker that gives the same bonus every time a card scores never changes. "
               "Examples: Green Joker grows (+1 Mult per hand, kept); Canio grows (X1 Mult per face card destroyed); "
               "Turtle Bean shrinks; Seltzer shrinks (used up after 10 hands); Lusty Joker is fixed (+3 Mult per "
               "scoring Heart, every time); Gros Michel is fixed (+15 Mult, though it may destroy itself); Banner "
               "follows (Chips from the discards left now); Driver's License follows (the deck's Enhanced cards now); "
               "Matador is fixed (it only pays money).", {
                   "grows": "It grows: its value rises and is kept for the rest of the run (until something resets it)",
                   "resets": "It builds up within a round and resets when the round ends",
                   "shrinks": "It shrinks: its value falls over time, or it is used up",
                   "follows": "Its value is worked out from what the run holds right now (deck, money, jokers, "
                              "discards), not remembered",
                   "fixed": "It is fixed: it gives the same thing every time, or adds nothing to the score"}),
    "money": ("Does the joker itself put money in your pocket, and how? Examples: Satellite pays every round ($1 per "
              "Planet used); Matador pays on an event ($8 when the boss's ability triggers); Astronomer makes things "
              "free (Planets); Ceremonial Dagger has nothing to do with money (it reads a sell value but pays nothing); "
              "Cavendish has nothing to do with money.", {
                  "every_round": "It pays money at the end of every round (a fixed amount, or an amount set by the "
                                 "deck, the run or the interest)",
                  "on_event": "It pays money only when particular cards are scored, held or discarded, or at a "
                              "particular blind",
                  "sell": "It raises sell values",
                  "uses": "It pays nothing; it turns money held into Chips or Mult",
                  "cheaper": "It pays nothing; it makes things cheaper or free, or lets money go below zero",
                  "none": "Nothing to do with money"}),
}
# Hand-labelled clear cases (growth, money); the debatable ones (Obelisk, Supernova, Campfire, Throwback, Delayed
# Gratification, Midas Mask...) are left out.
GOLD = {
    "Joker": ("fixed", "none"), "Arrowhead": ("fixed", "none"), "Fibonacci": ("fixed", "none"),
    "Scholar": ("fixed", "none"), "Smiley Face": ("fixed", "none"), "Walkie Talkie": ("fixed", "none"),
    "Runner": ("grows", "none"), "Square Joker": ("grows", "none"), "Wee Joker": ("grows", "none"),
    "Vampire": ("grows", "none"), "Spare Trousers": ("grows", "none"), "Constellation": ("grows", "none"),
    "Ride the Bus": ("grows", "none"), "Lucky Cat": ("grows", "none"), "Madness": ("grows", "none"),
    "Hologram": ("grows", "none"), "Red Card": ("grows", "none"), "Flash Card": ("grows", "none"),
    "Yorick": ("grows", "none"), "Castle": ("grows", "none"), "Glass Joker": ("grows", "none"),
    "Hit the Road": ("resets", "none"),
    "Ice Cream": ("shrinks", "none"), "Popcorn": ("shrinks", "none"), "Ramen": ("shrinks", "none"),
    "Steel Joker": ("follows", "none"), "Abstract Joker": ("follows", "none"), "Blue Joker": ("follows", "none"),
    "Stone Joker": ("follows", "none"), "Erosion": ("follows", "none"), "Swashbuckler": ("follows", "none"),
    "Bull": ("follows", "uses"), "Bootstraps": ("follows", "uses"),
    "Golden Joker": ("fixed", "every_round"), "Rocket": ("fixed", "every_round"), "Cloud 9": ("fixed", "every_round"),
    "To the Moon": ("fixed", "every_round"),
    "Business Card": ("fixed", "on_event"), "Rough Gem": ("fixed", "on_event"), "Reserved Parking": ("fixed", "on_event"),
    "Golden Ticket": ("fixed", "on_event"), "Faceless Joker": ("fixed", "on_event"), "Mail-In Rebate": ("fixed", "on_event"),
    "Trading Card": ("fixed", "on_event"),
    "Egg": ("fixed", "sell"), "Gift Card": ("fixed", "sell"),
    "Credit Card": ("fixed", "cheaper"), "Chaos the Clown": ("fixed", "cheaper"),
}
# version 1's labels in version 2's terms (growth; money keeps its names)
V1_GROWTH = {"play": "grows", "discard": "grows", "items": "grows", "rounds": "grows", "round_only": "resets",
             "shrinks": "shrinks", "deck": "follows", "fixed": "fixed"}

_local = threading.local()


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def describe(j: dict) -> str:
    notes = " ".join(j.get("notes") or [])
    return (f"Joker: {j['name']} ({j['rarity']}). Effect: {j['effect']}"
            + (f" When: {j['condition']}" if j.get("condition") else "") + (f" Notes: {notes}" if notes else ""))


def ask(j: dict, facet: str, facets: dict = FACETS) -> tuple:
    client = getattr(_local, "client", None) or Client()
    _local.client = client
    question, options = facets[facet]
    before = client.usage["input_tokens"]
    probs = client.choose(describe(j), list(options.values()), INSTRUCTIONS.format(question=question))
    return j["name"], facet, dict(zip(options, probs)), client.usage["input_tokens"] - before


def compare(labels: dict) -> list[str]:
    """Where the labels and the word-matched groups disagree, and the engine's end-of-round payers."""
    import balatro.content  # noqa: F401  (registers the jokers)
    from balatro.jokers import CATALOG, Joker
    from balatro.strategy import _joker_groups
    grows, pays, rules = _joker_groups()
    top = {n: {f: v["label"] for f, v in fs.items()} for n, fs in labels.items()}
    checks = [("grows (words) vs growth for good", grows,
               {n for n, t in top.items() if t["growth"] in ("play", "discard", "items", "rounds")}),
              ("pays (words) vs pays money", pays,
               {n for n, t in top.items() if t["money"] in ("every_round", "on_event", "sell")}),
              ("rules (wiki: passive) vs changes a rule", rules, {n for n, t in top.items() if t["rules"] != "none"}),
              ("engine pays at round end vs pays every round",
               {n for n, c in CATALOG.items() if c.end_of_round is not Joker.end_of_round},
               {n for n, t in top.items() if t["money"] == "every_round"})]
    lines = []
    for title, words, jev in checks:
        lines.append(f"{title}: both {len(words & jev)}, only the first {sorted(words - jev)}, only Jev {sorted(jev - words)}")
    return lines


def score(labels: dict, version: int) -> list[str]:
    """Agreement with GOLD per facet, and the misses."""
    lines = []
    for k, facet in enumerate(("growth", "money")):
        got = {n: labels[n][facet]["label"] for n in GOLD}
        if version == 1 and facet == "growth":
            got = {n: V1_GROWTH[g] for n, g in got.items()}
        miss = [f"{n} {got[n]} (not {GOLD[n][k]})" for n in GOLD if got[n] != GOLD[n][k]]
        lines.append(f"v{version} {facet}: {len(GOLD) - len(miss)}/{len(GOLD)} agree with the hand labels; misses: "
                     + "; ".join(miss))
    return lines


def main() -> int:
    v2 = "--v2" in sys.argv
    facets = FACETS_V2 if v2 else FACETS
    jokers = data("jokers.json")
    tasks = [(j, f) for j in jokers for f in facets]
    log(f"labelling {len(jokers)} jokers on {len(facets)} facets{' (v2)' if v2 else ''}: {len(tasks)} questions to Jev ({MODEL})")
    labels, tokens, t0 = ({n: dict(fs) for n, fs in json.loads(OUT.read_text())["jokers"].items()} if v2 else {}), 0, time.time()
    with ThreadPoolExecutor(6) as pool:
        futures = [pool.submit(ask, j, f, facets) for j, f in tasks]
        for n, fut in enumerate(as_completed(futures), 1):
            name, facet, probs, used = fut.result()
            tokens += used
            label = max(probs, key=probs.get)
            labels.setdefault(name, {})[facet] = {"label": label, "p": round(probs[label], 3),
                                                  "probs": {k: round(v, 3) for k, v in probs.items()}}
            if n % 70 == 0 or n == len(tasks):
                rate = n / max(1e-9, time.time() - t0)
                log(f"{n}/{len(tasks)} answers, {rate:.1f} a second, ETA {(len(tasks) - n) / rate / 60:.1f} min, "
                    f"${tokens * PRICE_IN:.4f} so far")
    out = OUT.with_name("jokers_v2.json") if v2 else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    order = [j["name"] for j in jokers]
    out.write_text(json.dumps({"model": MODEL, "facets": {f: list(o) for f, (_, o) in {**FACETS, **facets}.items()},
                               "jokers": {n: labels[n] for n in order}}, indent=1))
    log(f"wrote {out.relative_to(ROOT)}; {tokens:,} new input tokens, ${tokens * PRICE_IN:.4f}")
    if v2:
        for line in score(json.loads(OUT.read_text())["jokers"], 1) + score(labels, 2):
            log(line)
        return 0
    unsure = sorted(((v["p"], n, f) for n, fs in labels.items() for f, v in fs.items()))[:15]
    log("least sure: " + "; ".join(f"{n} {f} {p:.2f}" for p, n, f in unsure))
    for line in compare(labels):
        log(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
