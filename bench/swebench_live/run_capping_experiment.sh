#!/usr/bin/env bash
# Whale-capping experiment driver (see bench/docs/PREREG_CAPPING.md):
#   1. opus-passthru parity check over the first PARITY_N subset instances
#   2. opus-capped over the full subset
# Control is the ALREADY-RUN opus-solo baseline (committed CSV) -- not re-run.
# Resume-safe: any (arm, instance) with a scored report.json is skipped.
#
# Usage:
#   ANTHROPIC_API_KEY=... ./run_capping_experiment.sh [per_run_budget] [cumulative_budget]
set -euo pipefail

HERE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE_DIR"

PER_RUN_BUDGET_USD="${1:-15}"
CUMULATIVE_BUDGET_USD="${2:-35}"
PARITY_N=3
SUBSET_FILE="$HERE_DIR/swebench_live_subset.json"
RESULTS_ROOT="$HERE_DIR/jobs_capping/results"
WORK_ROOT="$HERE_DIR/jobs_capping/work"
RESULTS_CSV="$HERE_DIR/swebench_live_capping_results.csv"
PY="$HERE_DIR/.venv/bin/python3"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "FATAL: ANTHROPIC_API_KEY is not set in the environment" >&2
  exit 1
fi

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

ALL_INSTANCE_IDS=()
while IFS= read -r _iid; do
  ALL_INSTANCE_IDS+=("$_iid")
done < <("$PY" -c "
import json
d = json.load(open('$SUBSET_FILE'))
for i in d['instances']:
    print(i['instance_id'])
")
N_TOTAL="${#ALL_INSTANCE_IDS[@]}"
log "Loaded $N_TOTAL instances; parity_n=$PARITY_N budgets: per-run=\$$PER_RUN_BUDGET_USD cumulative=\$$CUMULATIVE_BUDGET_USD"

cumulative_cost() {
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

run_one() {
  local arm="$1" instance_id="$2"
  if [ -f "$RESULTS_ROOT/$arm/$instance_id/eval/$instance_id/report.json" ]; then
    log "SKIP_DONE arm=$arm instance_id=$instance_id (already scored)"
    return 0
  fi
  log "RUN arm=$arm instance_id=$instance_id"
  if "$PY" run_instance.py --instance-id "$instance_id" --arm "$arm" \
    --results-root "$RESULTS_ROOT" --work-root "$WORK_ROOT" \
    --max-budget-usd "$PER_RUN_BUDGET_USD"; then
    log "RUN_OK arm=$arm instance_id=$instance_id"
  else
    log "RUN_FAILED arm=$arm instance_id=$instance_id"
    return 1
  fi
}

check_budget() {
  local cost
  cost=$(cumulative_cost)
  log "CUMULATIVE cost_usd=$cost"
  if "$PY" -c "import sys; sys.exit(0 if $cost > $CUMULATIVE_BUDGET_USD else 1)"; then
    log "ABORT_BUDGET cumulative=$cost limit=$CUMULATIVE_BUDGET_USD"
    exit 1
  fi
}

log "PHASE_START phase=parity arm=opus-passthru n=$PARITY_N"
n_err=0
for ((i = 0; i < PARITY_N; i++)); do
  run_one opus-passthru "${ALL_INSTANCE_IDS[$i]}" || n_err=$((n_err + 1))
done
check_budget
if [ "$n_err" -eq "$PARITY_N" ]; then
  log "ABORT_ALL_ERRORED phase=parity"
  exit 1
fi
log "PHASE_DONE phase=parity errored=$n_err/$PARITY_N"

log "PHASE_START phase=capped arm=opus-capped n=$N_TOTAL"
wave_err=0
count=0
for instance_id in "${ALL_INSTANCE_IDS[@]}"; do
  run_one opus-capped "$instance_id" || wave_err=$((wave_err + 1))
  count=$((count + 1))
  if [ $((count % 5)) -eq 0 ]; then
    log "WAVE_DONE arm=opus-capped done=$count/$N_TOTAL errored=$wave_err"
    check_budget
    if [ "$wave_err" -ge 5 ] && [ "$wave_err" -eq "$count" ]; then
      log "ABORT_ALL_ERRORED phase=capped"
      exit 1
    fi
  fi
done

"$PY" build_results_csv.py "$RESULTS_ROOT" --out "$RESULTS_CSV"
log "ALL_DONE errored=$wave_err total_cost_usd=$(cumulative_cost)"
