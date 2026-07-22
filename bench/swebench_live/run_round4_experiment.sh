#!/usr/bin/env bash
# Round-3 Arm A driver (bench/docs/PREREG_ROUND4.md): __ARM__ over the
# standard subset. Control = existing opus-solo baseline (not re-run).
# Resume-safe; explicit DRIVER_EXIT logging is added by the launch wrapper.
set -euo pipefail

HERE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE_DIR"

PER_RUN_BUDGET_USD="${1:-15}"
CUMULATIVE_BUDGET_USD="${2:-30}"
SUBSET_FILE="$HERE_DIR/swebench_live_subset.json"
RESULTS_ROOT="$HERE_DIR/jobs_round4/results"
WORK_ROOT="$HERE_DIR/jobs_round4/work"
RESULTS_CSV="$HERE_DIR/swebench_live_round4_results.csv"
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

for ARM in opus-diag opus-lint; do
log "PHASE_START arm=$ARM n=$N_TOTAL"
n_err=0
count=0
for instance_id in "${ALL_INSTANCE_IDS[@]}"; do
  if [ -f "$RESULTS_ROOT/$ARM/$instance_id/eval/$instance_id/report.json" ]; then
    log "SKIP_DONE arm=$ARM instance_id=$instance_id (already scored)"
    continue
  fi
  log "RUN arm=$ARM instance_id=$instance_id"
  if "$PY" run_instance.py --instance-id "$instance_id" --arm "$ARM" \
    --results-root "$RESULTS_ROOT" --work-root "$WORK_ROOT" \
    --max-budget-usd "$PER_RUN_BUDGET_USD"; then
    log "RUN_OK arm=$ARM instance_id=$instance_id"
  else
    n_err=$((n_err + 1))
    log "RUN_FAILED arm=$ARM instance_id=$instance_id"
  fi
  count=$((count + 1))
  if [ $((count % 5)) -eq 0 ]; then
    log "WAVE_DONE arm=$ARM done=$count/$N_TOTAL errored=$n_err"
    cost=$(cumulative_cost)
    log "CUMULATIVE cost_usd=$cost"
    if "$PY" -c "import sys; sys.exit(0 if $cost > $CUMULATIVE_BUDGET_USD else 1)"; then
      log "ABORT_BUDGET cumulative=$cost limit=$CUMULATIVE_BUDGET_USD"
      exit 1
    fi
    if [ "$n_err" -ge 5 ] && [ "$n_err" -eq "$count" ]; then
      log "ABORT_ALL_ERRORED arm=$ARM"
      exit 1
    fi
  fi
done

"$PY" build_results_csv.py "$RESULTS_ROOT" --out "$RESULTS_CSV"
log "PHASE_DONE arm=$ARM"
done

log "ALL_DONE errored=$n_err total_cost_usd=$(cumulative_cost)"
