"""The measurement line-up for scripts/watch_jobs.sh: each queue in the order it runs, each of its runs done (with its
result), playing (how far) or waiting (a rough finish time: the pace of the last plain runs, build-plan runs 2.3x as
long, runs to ante 16 1.5x). Edit LINEUP when queues are added or reordered."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

LOGS = Path(__file__).resolve().parent.parent / "logs"
# (queue, what it measures, its runs in order): today's order, 29 Oct (the build plan's runs, 23 and 24, ahead of 17-19)
LINEUP = [
    ("16", "new baselines (Lucky cards + Tarot guard)", ["g-guard", "g777-guard"]),
    ("20", "POWER_PAIRED (paired sample hands)", ["p-paired", "p777-paired"]),
    ("21", "build plan, step 1 (held + DNA)", ["b-plan", "b777-plan", "d-off16", "d-plan16"]),
    ("22", "survival-weighted horizon (and the cap)", ["h-surv16", "h-cap16", "h-surv8", "h777-surv8"]),
    ("23", "new baselines, then the plan on them", ["n-base", "n777-base", "n-base16", "n-plan", "n-plan-w3",
                                                    "n777-plan", "n-plan16"]),
    ("24", "build plan, step 2 (DNA a tool, Flush, synergy)", ["f-plan", "f777-plan", "f-plan-noflush"]),
    ("25", "the review's fixes together: new baselines (alongside 24)", ["z-base", "z777-base"]),
    ("26", "today's code (+ dead plays), then measured vouchers", ["y-base", "y777-base", "u-vouch", "u777-vouch"]),
    ("27", "today's code to ante 16: antes 10 and 12 reached", ["y-base16"]),
    ("28", "newest code (+ face-down plays...), then measured Hieroglyph", ["x-base", "x777-base", "g-glyph", "g777-glyph"]),
    ("29", "the second review's fixes together, then Small Blind skips by the boss", ["w-base", "w777-base", "w-skipboss"]),
    ("30", "LASTING_HORIZON (to 16 and 8) and MILK_WON", ["w-base16", "l-hor16", "l-hor", "m-milk", "m777-milk"]),
    ("31", "BEHIND_GAMBLE (money and rerolls before a likely-lost boss)", ["b-behind", "b777-behind"]),
    ("32", "MOUTH_ODDS (The Mouth's opening by its odds)", ["mo-odds", "mo777-odds"]),
    # queue 33: the deck and stake survey (scripts/survey_decks.py, not an eval_value run; logs/survey_decks.log)
    ("17", "weights re-tune", ["k-rr15", "k-rr40", "k-sell05", "k-sell20", "k-shop10", "k-shop50", "k-safe10",
                                "k-safe16"]),
    ("18", "last hand by its odds", ["o-odds", "o777-odds"]),
    ("19", "Seed Money's worth", ["v-seed06", "v-seed12"]),
]
DONE = re.compile(r"^(\S+) (\S+)  (\S+): beat ante 8 in \d+/\d+ \(([\d.]+)%\).*?([\d.]+) min; exit (\d+)")
PLAYING = re.compile(r"^(\S+ \S+)  (\S+): (\d+)/(\d+) games, ETA ([\d.]+) min")
VERDICT = re.compile(r"\] +(\S+): beat ante 8 in .*?progress ([-+][\d.]+) ± ([\d.]+), ante 8 beaten ([-+][\d.]+) ± ([\d.]+)")


def factor(label: str) -> float:
    """A run's length against a plain run's: the plan's runs (step 1 2.3x; step 2, labels f-, 4x with Flush, 2.8x
    without), runs to ante 16 1.5x."""
    plan = 1.0 if "plan" not in label else 2.8 if "noflush" in label else 4.0 if label.startswith("f") else 2.3
    return plan * (1.5 if label.startswith("d-") or label.endswith("16") else 1.0)


def main() -> None:
    lines = (LOGS / "value_eval.log").read_text(errors="replace").splitlines()
    done, minutes = {}, []
    for line in lines:
        m = DONE.match(line)
        if m:
            label = m[3]
            done[label] = (m[2][:5], float(m[4]), int(m[6]))
            if factor(label) == 1.0:
                minutes.append(float(m[5]))
    pace = sum(minutes[-3:]) / len(minutes[-3:]) if minutes else 50.0
    verdicts = {}
    for f in LOGS.glob("sweep_queue*.log"):
        for line in f.read_text(errors="replace").splitlines():
            m = VERDICT.search(line)
            if m:
                verdicts[m[1]] = f"ante 8 {m[4]} ± {m[5]}, progress {m[2]}"
    playing = None
    for line in reversed(lines[-50:]):
        m = PLAYING.match(line)
        if m:
            if m[2] not in done:                         # (its ETA counts from the line's own time: logged every 48 games)
                at = dt.datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S") + dt.timedelta(minutes=float(m[5]))
                playing = (m[2], int(m[3]), int(m[4]), at)
            break
    clock = dt.datetime.now()
    if playing:
        clock = max(clock, playing[3])
    print(f"LINE-UP  (in the order they run; a run takes ~{pace:.0f} min now, plan runs 2.3x, to ante 16 1.5x)")
    for queue, what, runs in LINEUP:
        print(f"  queue {queue}  {what}")
        for label in runs:
            if label in done:
                end, won, code = done[label]
                note = f"won {won:.1f}%" + (f", {verdicts[label]}" if label in verdicts else "")
                print(f"     {label:12s} done {end}  {note}" + ("" if code == 0 else f"  EXIT {code}"))
            elif playing and playing[0] == label:
                print(f"     {label:12s} playing {playing[1]}/{playing[2]}, done ~{clock:%H:%M}")
            else:
                clock += dt.timedelta(minutes=pace * factor(label))
                print(f"     {label:12s} waiting, done ~{clock:%H:%M}")


if __name__ == "__main__":
    main()
