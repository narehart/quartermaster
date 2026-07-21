#!/usr/bin/env bash
# Context-reduction round 2 driver (bench/docs/PREREG_CONTEXT2.md):
#   arm opus-cap4k  -- at-source capping, 4000-char threshold (dose-response)
#   arm opus-epoch  -- tail-targeted fire-once clearing (trigger 50k tokens)
# Control = existing opus-solo baseline (not re-run). Resume-safe.
#
# Usage: ANTHROPIC_API_KEY=... ./run_context2_experiment.sh [per_run_budget] [cumulative_budget]
set -euo pipefail

HERE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE_DIR"

PER_RUN_BUDGET_USD="${1:-15}"
CUMULATIVE_BUDGET_USD="${2:-55}"
SUBSET_FILE="$HERE_DIR/swebench_live_subset.json"
RESULTS_ROOT="$HERE_DIR/jobs_context2/results"
WORK_ROOT="$HERE_DIR/jobs_context2/work"
RESULTS_CSV="$HERE_DIR/swebench_live_context2_results.csv"
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
log "Loaded $N_TOTAL instances; budgets: per-run=\$$PER_RUN_BUDGET_USD cumulative=\$$CUMULATIVE_BUDGET_USD"

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

check_budget() {
  local cost
  cost=$(cumulative_cost)
  log "CUMULATIVE cost_usd=$cost"
  if "$PY" -c "import sys; sys.exit(0 if $cost > $CUMULATIVE_BUDGET_USD else 1)"; then
    log "ABORT_BUDGET cumulative=$cost limit=$CUMULATIVE_BUDGET_USD"
    exit 1
  fi
}

run_arm() {
  # $1 = arm; remaining args are passed through to run_instance.py via "$@".
  # NOTE: deliberately NOT captured into a local array -- expanding an EMPTY
  # array under `set -u` on macOS bash 3.2 is an "unbound variable" error
  # (this killed the epoch phase on 2026-07-20; "$@" itself is exempt).
  local arm="$1"
  shift
  log "PHASE_START arm=$arm n=$N_TOTAL"
  local n_err=0 count=0
  for instance_id in "${ALL_INSTANCE_IDS[@]}"; do
    if [ -f "$RESULTS_ROOT/$arm/$instance_id/eval/$instance_id/report.json" ]; then
      log "SKIP_DONE arm=$arm instance_id=$instance_id (already scored)"
      continue
    fi
    log "RUN arm=$arm instance_id=$instance_id"
    if "$PY" run_instance.py --instance-id "$instance_id" --arm "$arm" \
      --results-root "$RESULTS_ROOT" --work-root "$WORK_ROOT" \
      --max-budget-usd "$PER_RUN_BUDGET_USD" "$@"; then
      log "RUN_OK arm=$arm instance_id=$instance_id"
    else
      n_err=$((n_err + 1))
      log "RUN_FAILED arm=$arm instance_id=$instance_id"
    fi
    count=$((count + 1))
    if [ $((count % 5)) -eq 0 ]; then
      log "WAVE_DONE arm=$arm done=$count/$N_TOTAL errored=$n_err"
      check_budget
      if [ "$n_err" -ge 5 ] && [ "$n_err" -eq "$count" ]; then
        log "ABORT_ALL_ERRORED arm=$arm"
        exit 1
      fi
    fi
  done
  log "PHASE_DONE arm=$arm errored=$n_err"
}

run_arm opus-cap4k --cap-chars 4000
check_budget
run_arm opus-epoch

"$PY" build_results_csv.py "$RESULTS_ROOT" --out "$RESULTS_CSV"
log "ALL_DONE total_cost_usd=$(cumulative_cost)"
