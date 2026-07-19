#!/usr/bin/env bash
# SWE-bench Live opus-solo re-baseline runner. Mirrors run_prewalk_prereg.sh's
# structure: N waves of tasks from swebench_live_subset.json, a per-run
# budget cap ($15/run, enforced by `claude --max-budget-usd` inside each
# agent invocation), and a cumulative-cost abort gate checked BETWEEN waves
# (not mid-wave) so a partial dataset stays balanced/analyzable if aborted.
#
# Usage:
#   ANTHROPIC_API_KEY=... ./run_swebench_live.sh <arm> [n_waves] [wave_size] [budget_limit_usd]
#     arm: opus-solo | prewalk
#
# Launch detached, e.g.:
#   nohup env ANTHROPIC_API_KEY=... ./run_swebench_live.sh opus-solo 5 5 150 \
#       > swebench_live_opus_solo.log 2>&1 &
set -euo pipefail

HERE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE_DIR"

ARM="${1:?usage: run_swebench_live.sh <arm> [n_waves] [wave_size] [budget_limit_usd]}"
N_WAVES="${2:-5}"
WAVE_SIZE="${3:-5}"
BUDGET_LIMIT_USD="${4:-150}"
SUBSET_FILE="$HERE_DIR/swebench_live_subset.json"
RESULTS_ROOT="$HERE_DIR/results"
RESULTS_CSV="$HERE_DIR/swebench_live_results.csv"
PY="$HERE_DIR/.venv/bin/python3"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "FATAL: ANTHROPIC_API_KEY is not set in the environment" >&2
  exit 1
fi

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

# NOTE: `mapfile` (bash 4+) is deliberately NOT used here -- this host's
# /usr/bin/env resolves to macOS system /bin/bash 3.2 (no bash 4+ installed),
# which lacks the `mapfile` builtin. Portable read-loop instead.
ALL_INSTANCE_IDS=()
while IFS= read -r _instance_id; do
  ALL_INSTANCE_IDS+=("$_instance_id")
done < <("$PY" -c "
import json
d = json.load(open('$SUBSET_FILE'))
for i in d['instances']:
    print(i['instance_id'])
")
N_TOTAL="${#ALL_INSTANCE_IDS[@]}"
log "Loaded $N_TOTAL instances from $SUBSET_FILE"

cumulative_cost() {
  "$PY" build_results_csv.py "$RESULTS_ROOT" --out "$RESULTS_CSV" >/dev/null 2>&1 || true
  "$PY" -c "
import csv
total = 0.0
try:
    with open('$RESULTS_CSV') as f:
        for row in csv.DictReader(f):
            if row.get('arm') == '$ARM':
                try:
                    total += float(row.get('total_cost_usd') or 0)
                except ValueError:
                    pass
except FileNotFoundError:
    pass
print(round(total, 4))
"
}

# Sets globals WAVE_N_TOTAL/WAVE_N_ERRORED rather than returning via stdout
# capture -- `run_instance.py` itself prints its own live progress markers
# (INSTANCE_START, AGENT_RUN_DONE, ...) to stdout, so wrapping this call in
# `$(run_wave ...)` would silently swallow BOTH this function's own log()
# lines AND run_instance.py's entire console output into a single captured
# string (and corrupt the n_total/n_errored parse downstream). Calling this
# directly (no command substitution) lets everything flow straight through
# to the driver's own stdout/stderr (both already redirected to the log file
# by the launch command), and the caller reads the globals afterward.
run_wave() {
  local wave="$1"
  shift
  local instance_ids=("$@")
  WAVE_N_ERRORED=0
  WAVE_N_TOTAL=0
  for instance_id in "${instance_ids[@]}"; do
    WAVE_N_TOTAL=$((WAVE_N_TOTAL + 1))
    log "WAVE $wave RUN instance_id=$instance_id arm=$ARM"
    if "$PY" run_instance.py --instance-id "$instance_id" --arm "$ARM" --wave "$wave" --results-root "$RESULTS_ROOT"; then
      log "WAVE $wave RUN_OK instance_id=$instance_id"
    else
      WAVE_N_ERRORED=$((WAVE_N_ERRORED + 1))
      log "WAVE $wave RUN_FAILED instance_id=$instance_id"
    fi
  done
}

finalize_and_exit() {
  local exit_code="$1"
  "$PY" build_results_csv.py "$RESULTS_ROOT" --out "$RESULTS_CSV"
  local rows
  rows=$(($(wc -l <"$RESULTS_CSV") - 1))
  local final_cost
  final_cost=$(cumulative_cost)
  log "ALL_DONE arm=$ARM rows=${rows} total_cost_usd=${final_cost}"
  exit "$exit_code"
}

idx=0
for wave in $(seq 1 "$N_WAVES"); do
  wave_instances=()
  for ((i = 0; i < WAVE_SIZE && idx < N_TOTAL; i++)); do
    wave_instances+=("${ALL_INSTANCE_IDS[$idx]}")
    idx=$((idx + 1))
  done
  if [ "${#wave_instances[@]}" -eq 0 ]; then
    log "NO_MORE_INSTANCES wave=${wave}"
    break
  fi

  run_wave "$wave" "${wave_instances[@]}"
  n_total="$WAVE_N_TOTAL"
  n_errored="$WAVE_N_ERRORED"
  cost=$(cumulative_cost)
  log "WAVE_DONE w=${wave} errored=${n_errored}/${n_total} cumulative_cost_usd=${cost}"

  if [ "$n_total" -gt 0 ] && [ "$n_errored" -eq "$n_total" ]; then
    log "ABORT_ALL_ERRORED w=${wave}"
    finalize_and_exit 1
  fi

  if "$PY" -c "import sys; sys.exit(0 if $cost > $BUDGET_LIMIT_USD else 1)"; then
    log "ABORT_BUDGET cumulative=${cost} limit=${BUDGET_LIMIT_USD}"
    finalize_and_exit 1
  fi

  if [ "$idx" -ge "$N_TOTAL" ]; then
    log "ALL_INSTANCES_CONSUMED after wave=${wave}"
    break
  fi
done

finalize_and_exit 0
