#!/bin/zsh
# What the background jobs are doing, refreshed every 10 s (Ctrl-C stops it):
#   scripts/watch_jobs.sh          (or --once for a single look)
# The game being played now, the line-up of queues in the order they run (scripts/job_lineup.py: each run done, playing
# or waiting, with rough finish times), side probes still going, today's latest results, a payment calibration of the
# last 2 h, and any Play-tab rollout in the last hour. Short columns, long lines wrapped (fits an 80-column terminal).
cd "${0:A:h}/.." || exit 1
once=${1:-}
result='s/^[0-9-]+ ([0-9:]+) +\[[^]]*\] +([^:]+): beat ante 8 in [^ ]+ \(([0-9.]+%)\).*progress ([-+][0-9.]+) ± ([0-9.]+), ante 8 beaten ([-+][0-9.]+) ± ([0-9.]+) points/\1 \2|\3|\6 ± \7|\4 ± \5/'
while true; do
  w=$(tput cols 2>/dev/null || echo 80)
  out=$(
    echo "BALATRO LAB JOBS  $(date '+%H:%M:%S')"
    echo
    echo "PLAYING NOW"
    tail -n 1 logs/value_eval.log | sed -E 's/^[0-9-]+ ([0-9:]+) +/  \1  /; s/; so far beat ante 8 in/, so far won/'
    echo
    python3 scripts/job_lineup.py 2>&1                  # each queue in the order it runs, with rough finish times
    echo
    for f in $(find logs -name 'lucky_diverge.log' -mmin -180); do   # side probes still going
      echo "LUCKY CARDS REPLAY  $(grep 'games, ' $f | tail -n 1 | sed -E 's/^[0-9-]+ ([0-9:]+) +([0-9]+\/[0-9]+) games, [^,]*, ETA ([0-9.]+ min).*/\2 games at \1, ETA \3/')"
      grep 'games, ' $f | tail -n 1 | sed -E 's/.*first difference \(to win, to loss\): /  first difference (to win\/to loss): /'
      echo
    done
    echo "LATEST RESULTS (change against its baseline, points of games past ante 8)"
    printf "  %-24s %6s  %-12s %s\n" "time and label" "won" "ante 8" "progress"
    grep -h "^$(date '+%F').*beat ante 8 in .*against" logs/sweep_*.log 2>/dev/null | sort | tail -n 10 |
      sed -E "$result" | awk -F'|' '{printf "  %-24s %6s  %-12s %s\n", $1, $2, $3, $4}'
    cal=$(find logs -name 'calibrate_*.log' -mmin -120 2>/dev/null | head -n 1)   # a calibration run of the last 2 h
    if [ -n "$cal" ]; then
      echo
      n=$(grep -n 'games, beat ante 8' $cal | tail -1 | cut -d: -f1)
      if [ -n "$n" ]; then
        tail -n +$n $cal | head -n 1 |
          sed -E 's/^[0-9-]+ ([0-9:]+) +([0-9]+\/[0-9]+) games, beat ante 8 in ([0-9]+), ETA (.*)/PAYMENT CALIBRATION  \2 games at \1, ETA \4/' | sed "s/\$/  ($(basename $cal .log))/"
        printf "  %-18s %6s %7s %9s %6s\n" "joker" "rounds" "paid" "estimate" "ratio"
        tail -n +$((n + 1)) $cal | head -n 20 | grep 'rounds held' |
          sed -E 's/^[0-9-]+ [0-9:]+ +(.+): ([0-9]+) rounds held, paid \$([0-9.]+) a round, estimate \$?([0-9.]+).*ratio ([0-9.]+).*/\1|\2|\3|\4|\5/' |
          awk -F'|' '{printf "  %-18s %6s %7s %9s %6s\n", $1, $2, "$" $3, "$" $4, $5}'
        tail -n +$((n + 1)) $cal | head -n 20 | grep 'stays' |
          sed -E 's/^[0-9-]+ [0-9:]+ +stays: ([0-9]+) jokers, held ([0-9.]+) rounds against a horizon of ([0-9.]+).*/  jokers kept \2 rounds on average; the formulas assume \3/; s/^[0-9-]+ [0-9:]+ +stays of paying jokers: ([0-9]+), held ([0-9.]+) rounds against ([0-9.]+)/  paying jokers kept \2 rounds/'
      fi
      tail -n 1 $cal | grep -E 'done in|exit' | sed -E 's/^[0-9-]+ ([0-9:]+) +/  \1  /; s#/Users/[^ ]*/balatro/##'
    fi
    for f in $(find logs -name 'shop_*.log' -mmin -60); do
      echo
      echo "ROLLOUT ${f:t:r}"
      tail -n 1 "$f" | sed -E 's/^[0-9-]+ ([0-9:]+) +/  \1  /; s/ \| /\n  /g'
    done
  )
  [ -z "$once" ] && clear
  print -r -- "$out" | fold -s -w $w
  [ -n "$once" ] && break
  sleep 10
done
