#!/usr/bin/env bash
# 3-arm SWE-bench Live baseline experiment driver: opus-solo, prewalk-sonnet,
# prewalk-haiku, each run over the SAME 25-instance swebench_live_subset.json
# (1 rep each = 75 runs total). Generalizes run_swebench_live.sh's per-arm
# wave + per-run-budget + cumulative-abort-between-waves shape to loop over
# all 3 arms in one detached process, so the cumulative abort gate can be
# scoped to the WHOLE experiment (jobs_baseline/ only) rather than per-arm --
# see PREREG_SWEBENCH_LIVE.md.
#
# Usage:
#   ANTHROPIC_API_KEY=... ./run_baseline_experiment.sh \
#       [n_waves] [wave_size] [per_run_budget_usd] [cumulative_budget_usd]
#
# Launch detached, e.g.:
#   nohup env ANTHROPIC_API_KEY=... ./run_baseline_experiment.sh 5 5 15 80 \
#       > swebench_live_baseline.log 2>&1 &
set -euo pipefail

HERE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE_DIR"

ARMS=(opus-solo prewalk-sonnet prewalk-haiku)
N_WAVES="${1:-5}"
WAVE_SIZE="${2:-5}"
PER_RUN_BUDGET_USD="${3:-15}"
CUMULATIVE_BUDGET_USD="${4:-80}"
SUBSET_FILE="$HERE_DIR/swebench_live_subset.json"
RESULTS_ROOT="$HERE_DIR/jobs_baseline/results"
WORK_ROOT="$HERE_DIR/jobs_baseline/work"
RESULTS_CSV="$HERE_DIR/swebench_live_baseline_results.csv"
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
log "Loaded $N_TOTAL instances from $SUBSET_FILE; arms=${ARMS[*]}; total_runs=$((N_TOTAL * ${#ARMS[@]}))"

cumulative_cost() {
  # Cumulative TRUE cost across ALL 3 arms combined, scoped to
  # jobs_baseline/results only (never the smoke/prior results/ dir).
  "$PY" build_results_csv.py "$RESULTS_ROOT" --out "$RESULTS_CSV" >/dev/null 2>&1 || true
  "$PY" -c "
import csv
total = 0.0
try:
    with open('$RESULTS_CSV') as f:
        for row in csv.DictReader(f):
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
  local arm="$1" wave="$2"
  shift 2
  local instance_ids=("$@")
  WAVE_N_ERRORED=0
  WAVE_N_TOTAL=0
  for instance_id in "${instance_ids[@]}"; do
    # Crash-resume skip: if this (arm,instance) already produced a scored
    # report.json in a prior run, skip it (don't re-spend). A run that errored
    # before scoring has no report.json, so it is correctly re-run.
    if [ -f "$RESULTS_ROOT/$arm/$instance_id/eval/$instance_id/report.json" ]; then
      log "WAVE $wave SKIP_DONE instance_id=$instance_id arm=$arm (already scored)"
      continue
    fi
    WAVE_N_TOTAL=$((WAVE_N_TOTAL + 1))
    log "WAVE $wave RUN instance_id=$instance_id arm=$arm"
    if "$PY" run_instance.py --instance-id "$instance_id" --arm "$arm" --wave "$wave" \
      --results-root "$RESULTS_ROOT" --work-root "$WORK_ROOT" --max-budget-usd "$PER_RUN_BUDGET_USD"; then
      log "WAVE $wave RUN_OK instance_id=$instance_id arm=$arm"
    else
      WAVE_N_ERRORED=$((WAVE_N_ERRORED + 1))
      log "WAVE $wave RUN_FAILED instance_id=$instance_id arm=$arm"
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
  log "ALL_DONE rows=${rows} total_cost_usd=${final_cost}"
  exit "$exit_code"
}

for ARM in "${ARMS[@]}"; do
  log "ARM_START arm=$ARM"
  idx=0
  for wave in $(seq 1 "$N_WAVES"); do
    wave_instances=()
    for ((i = 0; i < WAVE_SIZE && idx < N_TOTAL; i++)); do
      wave_instances+=("${ALL_INSTANCE_IDS[$idx]}")
      idx=$((idx + 1))
    done
    if [ "${#wave_instances[@]}" -eq 0 ]; then
      log "NO_MORE_INSTANCES arm=$ARM wave=${wave}"
      break
    fi

    run_wave "$ARM" "$wave" "${wave_instances[@]}"
    n_total="$WAVE_N_TOTAL"
    n_errored="$WAVE_N_ERRORED"
    cost=$(cumulative_cost)
    log "WAVE_DONE arm=${ARM} w=${wave} errored=${n_errored}/${n_total} cumulative_cost_usd=${cost}"

    if [ "$n_total" -gt 0 ] && [ "$n_errored" -eq "$n_total" ]; then
      log "ABORT_ALL_ERRORED arm=${ARM} w=${wave}"
      finalize_and_exit 1
    fi

    if "$PY" -c "import sys; sys.exit(0 if $cost > $CUMULATIVE_BUDGET_USD else 1)"; then
      log "ABORT_BUDGET cumulative=${cost} limit=${CUMULATIVE_BUDGET_USD}"
      finalize_and_exit 1
    fi

    if [ "$idx" -ge "$N_TOTAL" ]; then
      log "ALL_INSTANCES_CONSUMED arm=${ARM} after wave=${wave}"
      break
    fi
  done
  log "ARM_DONE arm=$ARM"
done

finalize_and_exit 0
