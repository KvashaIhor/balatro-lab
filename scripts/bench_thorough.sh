#!/bin/zsh
# Thorough-mode planner benchmarks (no time limit), one setting after another: evolved weights against the
# hand-set ones, then a wider beam, a longer look-ahead and more options per decision.
# Log: logs/bench_planner.log (each plan and each benchmark's mean); this script's own lines: logs/bench_thorough.log
cd "$(dirname "$0")/.."
LOG=logs/bench_thorough.log
run() {
  echo "$(date '+%F %T')  start $1" >> $LOG
  "${@:2}" > /dev/null 2>&1
  echo "$(date '+%F %T')  done $1 (exit $?): $(grep "bench $1: mean" logs/bench_planner.log | tail -1 | cut -c22-)" >> $LOG
}
run thorough-evolved python3 -u scripts/bench_planner.py --label thorough-evolved --time 0
run thorough-hand env VALUEBOT_WEIGHTS=hand python3 -u scripts/bench_planner.py --label thorough-hand --time 0
run thorough-beam12 python3 -u scripts/bench_planner.py --label thorough-beam12 --time 0 --beam 12
run thorough-h4 python3 -u scripts/bench_planner.py --label thorough-h4 --time 0 --horizon 4
run thorough-branch4 python3 -u scripts/bench_planner.py --label thorough-branch4 --time 0 --branch 4
echo "$(date '+%F %T')  all done; exit 0" >> $LOG
