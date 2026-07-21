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

## Campaign 1 result (5 techniques, n=25 each, directional)

| technique | class | cost/solved vs opus-solo | quality | mechanism of failure |
|---|---|---|---|---|
| prewalk-sonnet | model swap | 1.35× [0.97,2.42] | ~flat | executor turn-inflation (19→25 median turns) |
| prewalk-haiku | model swap | 0.86× [0.60,1.62] | −8% (lost 2 solves) | capability pays for the discount |
| sliding-window masking | context, per-turn | ~28× (killed at smoke) | — | perpetual cache re-writes (cc/cr 0.39 vs 0.05) |
| whale-capping @16k chars | context, at-source | inert (fired 2/25 runs) | preserved | >16k observations too rare |
| whale-capping @4k chars | context, at-source | 1.59× [0.89,3.01] | preserved | capped tokens were 0.1× cache reads — nothing to save |
| epoch clearing (50k trigger) | context, batched | 1.99× [1.16,4.98] | worst point est. | treated runs flailed: 2.5× turns, one lost solve |

**Conclusion: on a prompt-cached, API-priced coding agent, context-size
reduction does not reduce cost-per-solved.** Caching already collapsed the
context term (reads at 0.1×); the binding terms are TURNS and OUTPUT tokens.
Independently replicated at 40× scale by
["Token Reduction Is Not Cost Reduction" (arXiv:2607.12161)](https://arxiv.org/abs/2607.12161).
Full findings (F1–F5), anomaly log, and the clearing break-even derivation:
`docs/SWEBENCH_LIVE_ANALYSIS.md`. All results directional (n=25, small
solve-denominators, wide CIs); the negative directions are consistent and
mechanism-backed.

## Next — round 3

`docs/TOKEN_REDUCTION_CANDIDATES.md` (v3) ranks the round-3 slate, aimed at
the binding terms and cache-safe by construction: repo-instruction +
thinking-budget tuning (output tokens), experience-driven early termination
(turns AND output), diagnostic front-loading, course-correction feedback.
