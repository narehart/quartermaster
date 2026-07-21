#!/usr/bin/env bash
# Powered confirmation of output tuning (bench/docs/PREREG_POWERED_TUNED.md):
# 3 reps x 25 instances x {opus-tuned, opus-solo}. Per-rep isolated
# results/work roots (repo checkouts are dirty after a run). Resume-safe at
# the (rep, arm, instance) level.
set -euo pipefail

HERE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE_DIR"

PER_RUN_BUDGET_USD="${1:-15}"
CUMULATIVE_BUDGET_USD="${2:-120}"
N_REPS="${3:-3}"
SUBSET_FILE="$HERE_DIR/swebench_live_subset.json"
BASE="$HERE_DIR/jobs_powered"
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
log "POWERED start: $N_TOTAL instances x $N_REPS reps x 2 arms; budgets per-run=\$$PER_RUN_BUDGET_USD cum=\$$CUMULATIVE_BUDGET_USD"

cumulative_cost() {
  "$PY" - <<'PYEOF'
import csv, glob, subprocess, sys, os
total = 0.0
for rep_results in glob.glob(os.path.join(os.environ["BASE"], "rep*", "results")):
    out = rep_results + "/../results.csv"
    subprocess.run([os.environ["PY"], "build_results_csv.py", rep_results, "--out", out],
                   capture_output=True)
    try:
        with open(out) as f:
            for row in csv.DictReader(f):
                try:
                    total += float(row.get("total_cost_usd") or 0)
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
print(round(total, 4))
PYEOF
}
export BASE PY

count=0
for REP in $(seq 1 "$N_REPS"); do
  for ARM in opus-tuned opus-solo; do
    log "PHASE_START rep=$REP arm=$ARM"
    n_err=0
    for instance_id in "${ALL_INSTANCE_IDS[@]}"; do
      RR="$BASE/rep$REP/results"
      if [ -f "$RR/$ARM/$instance_id/eval/$instance_id/report.json" ]; then
        log "SKIP_DONE rep=$REP arm=$ARM instance_id=$instance_id"
        continue
      fi
      log "RUN rep=$REP arm=$ARM instance_id=$instance_id"
      if "$PY" run_instance.py --instance-id "$instance_id" --arm "$ARM" \
        --results-root "$RR" --work-root "$BASE/rep$REP/work" \
        --max-budget-usd "$PER_RUN_BUDGET_USD"; then
        log "RUN_OK rep=$REP arm=$ARM instance_id=$instance_id"
      else
        n_err=$((n_err + 1))
        log "RUN_FAILED rep=$REP arm=$ARM instance_id=$instance_id"
      fi
      count=$((count + 1))
      if [ $((count % 10)) -eq 0 ]; then
        cost=$(cumulative_cost)
        log "WAVE_DONE total_runs=$count cumulative_cost_usd=$cost"
        if "$PY" -c "import sys; sys.exit(0 if $cost > $CUMULATIVE_BUDGET_USD else 1)"; then
          log "ABORT_BUDGET cumulative=$cost limit=$CUMULATIVE_BUDGET_USD"
          exit 1
        fi
      fi
    done
    log "PHASE_DONE rep=$REP arm=$ARM errored=$n_err"
  done
done
log "ALL_DONE total_runs=$count cumulative_cost_usd=$(cumulative_cost)"
