# Contributing

Thanks for looking. The most useful things you can do, roughly in order:

## 1. Play against the bot and catch its mistakes

Open the Play tab (`python3 app/server.py`, then http://127.0.0.1:8643/play.html), tick "Show what the value bot
would do", and play. When the bot suggests something that looks wrong, that's a find. Many of the bot's biggest gains
came from exactly this: a player asking "why does it want to do that?" and the answer being a bug.

Open an issue with:

- the game's file from `runs/played/` (or its seed, deck and the decision number), and
- what the bot suggested, what you'd do instead, and why.

## 2. Run the measurements on your machine

```bash
python3 -m pytest
python3 -u scripts/eval_value.py --bot base --label mine --rng 90210
```

Results that differ from the README's (70.2% on set 90210) are worth an issue too.

## 3. Improve the bot or the simulator

Pull requests are welcome. A change to how the bot plays needs a number:

- **Measure it on 480 seeds against the version before it**, paired seed by seed:
  `scripts/eval_value.py`, then `scripts/compare_evals.py <before> <after>`. Use set 90210 (`--rng 90210`) first and
  confirm on set 777 (`--rng 777`).
- **Put judgment calls behind a switch, off by default** (a class attribute on `ValueBot` in `balatro/strategy.py`),
  so they can be measured on and off. Plain bug fixes can go straight in.
- **Never use what a player can't see**: the deck order, face-down cards or future rolls.
  `scripts/probe_leaks.py` checks this.
- **Add a test** for the behaviour you change (`tests/`).

Simulator fixes (a joker, boss or rule that behaves differently from the game) are just as welcome: say what the game
does, ideally with a source, and add a test. Rules data and its sources live in `data/`.

`BACKLOG.md` lists what's being worked on, what was tried and measured, and ideas not yet built.
