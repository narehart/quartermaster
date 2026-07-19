# Quartermaster bench

The evidence gate for Quartermaster's pivoted mission: **reduce token cost on
long-horizon agentic software-engineering tasks without compromising quality.**
A technique earns a place in the plugin only if this bench shows it clears that
bar. Nothing is grandfathered.

## Why this bench

Real daily dev work is long-horizon and contamination-sensitive. We use
**SWE-bench Live** (fresh, continuously-updated GitHub issues) rather than the
deprecated SWE-bench Verified split, whose fixes are widely memorized — on
fresh tasks one-shot Opus resolves ~32%, versus ~70% on Verified, which is the
contamination-resistance we want.

The core metric is **cost-per-solved** (total true USD ÷ tasks resolved), never
raw token count — a technique that halves tokens but also halves solves is not
a win. Every run captures per-model `cache_read`/`cache_creation` tokens,
because prompt caching (and its model-scoped cold-start cost) dominates
long-horizon spend and is exactly what naive token-counting misses.

## Discipline

- **Preregister** metrics + kill-criteria before collecting data
  (`docs/PREREG_SWEBENCH_LIVE.md`), locked by commit hash.
- **Exact model pins**, no floating aliases — planner `claude-opus-4-8`,
  executor `claude-sonnet-5` / `claude-haiku-4-5-20251001`; verified per run
  against the observed `model_sequence` (`validate_arm.py`).
- **Treat every suspicious result as a bug until proven** — see the anomaly log
  in `docs/SWEBENCH_LIVE_ANALYSIS.md` (background-Haiku confound, pin-form
  nuance, etc.).
- **Report underpowered results as directional**, never as certifying.

## Layout

```
bench/
  swebench_live/          harness (patch-in / verdict-out over per-task Docker)
    run_baseline_experiment.sh   3-arm driver (opus-solo, prewalk-sonnet, prewalk-haiku)
    run_instance.py              one task: agent run -> patch -> SWE-bench eval -> result.json
    agent_runner.py              opus-solo + prewalk (opus-until-first-edit, then --resume --model)
    metrics.py                   true cost/tokens from stream-json; exact-pin verification
    analyze_baseline.py          paired bootstrap: cost-per-solved + pass-rate quality bar
    validate_arm.py              per-run health (swap fired, pins, patch, drift)
    build_subset.py / dataset_cache.py   fixed recency-ordered instance subset
    swebench_live_subset.json    the committed 25-instance subset
    agent/Dockerfile.agent       sandbox: node:20 + @anthropic-ai/claude-code
  results/swebench_live_baseline_results.csv   committed record of the baseline run
  docs/                   prereg, running analysis, and the candidate pipeline
```

Heavy per-run outputs (`jobs_*/`, Docker eval dirs, transcripts, `.venv/`) are
gitignored — only the harness, the fixed subset, and the results CSV are tracked.

## Setup

Requires Docker, a Python venv, and the SWE-bench-Live evaluation code:

```bash
cd bench/swebench_live
python3 -m venv .venv && . .venv/bin/activate
pip install datasets           # + the SWE-bench-Live eval deps
git clone https://github.com/microsoft/SWE-bench-Live vendor/SWE-bench-Live
# ANTHROPIC_API_KEY must be in the environment (never on argv); the driver
# passes it to the sandbox via a 0600 --env-file, never echoed.
```

## Run

```bash
# 3-arm baseline (opus-solo + prewalk-sonnet + prewalk-haiku) over the subset
export ANTHROPIC_API_KEY=...        # exported into env, never on an argv
nohup ./run_baseline_experiment.sh 5 5 15 80 >> swebench_live_baseline.log 2>&1 &
# args: n_waves wave_size per_run_budget_usd cumulative_budget_usd
# resume-safe: already-scored (arm,instance) pairs are skipped, not re-spent

.venv/bin/python3 validate_arm.py prewalk-sonnet   # per-run health
.venv/bin/python3 analyze_baseline.py              # cost-per-solved + quality bar
```

## Current result (directional, n=25, underpowered)

First campaign tested the incumbent cost technique, **prewalk** (run Opus until
the first edit, then swap to a cheaper executor via session resume):

| arm | resolved | cost/solved | vs opus (paired) |
|---|---|---|---|
| opus-solo | 8/25 (32%) | $2.35 | baseline |
| prewalk-sonnet | 7/25 (28%) | $3.25 | **1.35×** cost, −4% quality |
| prewalk-haiku | 6/25 (24%) | $2.04 | **0.86×** cost, −8% quality |

**Neither prewalk variant clears "cheaper without quality loss" on real-repo
work.** Sonnet's modest per-token discount is erased by executor turn-inflation
(25 vs 19 turns); Haiku's larger discount does cut total cost 35% but trades
away 2 of Opus's 8 solves. Terminal-Bench's clean 40.9% prewalk saving does not
generalize to large-context dev tasks. Full analysis + mechanism:
`docs/SWEBENCH_LIVE_ANALYSIS.md`. This is directional (tiny solve-denominators,
wide CIs) — a powered confirmation is required before any published claim.

## Next

`docs/TOKEN_REDUCTION_CANDIDATES.md` ranks the techniques to test next. The
literature's quality-neutral cost wins are **per-turn context reduction**
(tail-only observation masking, trajectory pruning, cache-aware prompt
ordering) — not model-swap — and this harness already captures the cache tokens
needed to evaluate them honestly.
