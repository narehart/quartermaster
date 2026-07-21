# Preregistration: SWE-bench Live 3-Arm Prewalk Experiment (First Real Run)

Written and locked before any real SWE-bench Live baseline data exists.
Reuses the bootstrap/CI/decision-rule conventions of `PREREG_OPUS.md`/
`PREREG_EXP1.md`/`PREREG_EXP2.md`/`PREREG_EXP3.md`/`PREREG_PREWALK.md`/
`PREREG_PREWALK_SONNET.md`, applied for the first time to the
`swebench_live/` harness (`swebench_live/README.md`) instead of the
Terminal-Bench harness those documents used. Does not modify or supersede
those documents. The `swebench_live/` harness itself was smoke-validated
(not preregistered data) for ~$2.50 prior to this document: gold-patch
sanity check resolved=True, an opus-solo run and a prewalk(opus-4-8→sonnet-5)
run each produced a real diff/tokens/cost/verdict, and model pins were exact
with no drift on both. This document locks the design for the first *real*
measurement run.

## Goal

First real measurement, on long-horizon software-engineering tasks (SWE-bench
Live: fresh, post-training-cutoff GitHub issues with verified Docker scoring
images — contamination-resistant relative to the original SWE-bench), of
whether a mid-session planner→cheaper-builder swap (`claude-opus-4-8` plans
until the first successful edit, then a cheaper model finishes the same
session) reduces cost-per-solved relative to an opus-solo baseline **without
compromising quality**. This generalizes the Terminal-Bench-only prewalk
result (`PREWALK_PREREG_ANALYSIS.md`) to a different, harder task
distribution and, for the first time, runs a haiku-executor arm and a
sonnet-executor arm side by side against the SAME task set in the SAME
experiment (the Terminal-Bench prewalk/prewalk-sonnet documents ran these as
two separate, sequential preregistrations).

## Arms (pin exactly; 3 arms × 25 instances × 1 rep = 75 runs)

All three arms run the SAME 25 recency-ordered SWE-bench Live instances
(`swebench_live/swebench_live_subset.json` — verified-image, test-count-
filtered, most-recent-`created_at`-first subset), one rep each.

1. **opus-solo (baseline).** ONE `claude` process, `--model claude-opus-4-8`
   start to finish. Ground truth this experiment measures the other two arms
   against.
2. **prewalk-sonnet.** `claude-opus-4-8` plans/explores in a normal agentic
   tool-use loop until the FIRST successful `Edit`/`Write`/`MultiEdit` tool
   result (detected event-driven via a `PostToolUse` hook marker file, not
   log-polling), at which point the opus process is killed and
   `claude --resume <session-id> --model claude-sonnet-5` continues the SAME
   session unsupervised to completion.
3. **prewalk-haiku.** Identical mechanism to prewalk-sonnet, except the
   resumed executor is `claude-haiku-4-5` instead of `claude-sonnet-5`.

Model IDs are EXACT pins, never floating aliases (`claude-opus-4-8`,
`claude-sonnet-5`, `claude-haiku-4-5` only) — verified per run against the
real `modelUsage` block Claude Code itself emits (`metrics.verify_model_pins`
in `swebench_live/metrics.py`), not assumed from the `--model` flag we
passed. Swap point is the first successful edit tool result in every prewalk
run, identically defined for both executor tiers.

## Primary metric

**Cost-per-solved** (`sum(total_cost_usd) over all valid runs in the arm /
n_resolved`) for prewalk-sonnet and prewalk-haiku, each vs opus-solo. Point
estimate + 95% CI of both the **difference** (arm − opus-solo) and the
**ratio** (arm / opus-solo), via bootstrap: 10,000 resamples, seed = 20260718
(numpy `default_rng`, same seeding convention as `analyze_opus.py`/
`analyze_exp1.py`/`analyze_exp2.py`), resampling runs *within* each arm's set
of the 25 tasks (task-level resample, not rep-level — n=1 rep here) and
recomputing cost-per-solved for each bootstrap draw.

**Null rule (verbatim, same form as every prior PREREG in this repo): if the
bootstrap CI on the primary metric (cost-per-solved difference, arm vs
opus-solo) straddles zero, the result is null — regardless of which point
estimate looks lower.** No post-hoc rationalization of a point estimate not
backed by a CI excluding zero.

## QUALITY BAR (the definitional gate — stated verbatim before data)

A technique arm **"preserves quality"** iff its pass rate
(`n_resolved / n_valid`) is **NOT statistically below** opus-solo's — i.e.
the bootstrap CI on the pass-rate difference (arm − opus-solo) **includes
zero or is positive**.

An arm that is **BOTH** cheaper per solve **AND** not-statistically-worse on
pass rate **QUALIFIES as a shippable token-reducer**. An arm that is cheaper
but statistically worse on pass rate **does NOT qualify** — it compromises
quality, full stop, regardless of the cost savings. Qualify/not-qualify is
reported per arm (prewalk-sonnet, prewalk-haiku), each independently against
opus-solo, using the same 10,000-resample bootstrap (seed = 20260719, i.e.
`SEED + 1`, same offset convention as prior PREREGs' pass-rate-diff CIs) on
the pass-rate difference.

## Swap audit (built in — state before data)

Every prewalk run (both executor tiers) is classified:

- **SWAPPED** — the `PostToolUse` hook marker fired (an
  `Edit`/`Write`/`MultiEdit` tool result was observed) and the kill+`--resume
  --model <executor>` sequence executed (`run_result.swap_fired = True` from
  `agent_runner.run_prewalk`).
- **NEVER-SWAPPED** — no qualifying edit occurred before the opus process
  either completed on its own or the marker-wait timed out
  (`run_result.swap_fired = False`), with `never_swapped_reason` recorded
  (`opus_completed_without_edit` or `marker_wait_timeout`).

**NEVER-SWAPPED runs are EXCLUDED from that arm's primary-metric and
quality-bar verdict, and reported separately** (count, task IDs, reasons) —
never silently folded into the SWAPPED numbers, and never dropped from the
CSV. Model-pin verification (`claude-opus-4-8` alone expected for
NEVER-SWAPPED prewalk runs and for opus-solo; `claude-opus-4-8` +
`claude-sonnet-5`/`claude-haiku-4-5` expected for SWAPPED prewalk runs) is
asserted per run via `metrics.verify_model_pins` against the real
`modelUsage` in the stream-json log; **any drift is flagged and invalidates
the affected run** for the primary-metric/quality-bar computation (still
reported in the raw CSV with `model_pin_ok=False`).

## Secondary metrics

- **Pass rate per arm** vs opus-solo, reported as opus-solo's actual
  observed rate (not assumed 100% — SWE-bench Live is a harder, fresher
  benchmark than the Terminal-Bench suite the earlier PREREGs used, so
  opus-solo is not assumed to solve everything).
- **Edit→swap delay** (`marker_epoch` minus process-launch time, from
  `agent_runner.run_prewalk`'s poll loop) distribution across all SWAPPED
  runs in both prewalk arms.
- **Opus-portion vs executor-portion cost split** per SWAPPED run
  (`opus_cost_usd` vs `sonnet_cost_usd`/`haiku_cost_usd` columns in
  `swebench_live_baseline_results.csv`, derived authoritatively from
  per-model `modelUsage` — see `metrics.analyze_log`'s docstring for why
  this, not the single final `result` line, is used for a 2-process prewalk
  log).
- **Post-swap turns** (total turns in the run minus turns before the swap
  marker fired) per SWAPPED run, both prewalk arms.

## Kill/flag criteria (stated before data)

- **(a) Swap reliability.** If **>30% of a prewalk arm's runs fail to
  swap** (NEVER-SWAPPED, of that arm's 25 attempted runs), the harness is
  flagged unreliable for that arm — its SWAPPED-only verdict is still
  reported, but caveated, and the NEVER-SWAPPED count/reasons are reported
  prominently rather than buried.
- **(b) Model-pin drift.** Any observed model-pin drift (a run's
  `modelUsage` shows a model ID outside the expected exact set for its arm)
  **invalidates the affected run** for primary-metric/quality-bar purposes;
  reported as a flagged anomaly, not silently excluded without mention.
- **(c) Baseline difficulty.** If opus-solo's baseline pass rate on this
  25-task subset comes in **too low (<~40%)**, the subset is flagged as too
  hard for this experiment's purposes — cost-per-solved denominators
  (`n_resolved`) become small and unstable at n=25, and any arm comparison
  is reported with that instability explicitly caveated rather than
  presented as a clean result.

## Caveat (flagged, not resolved)

n=25 tasks × 1 rep per arm (task-diversity design, not rep-averaging — no
per-task repeated-measures noise estimate is available, unlike the
Terminal-Bench PREREGs' 5-rep designs). This is the **first** baseline
measurement on SWE-bench Live with this harness — no prior real (non-smoke)
data exists to compare against or sanity-check outliers. The subset is
recency-ordered and verified-image-filtered (`build_subset.py`), which
biases toward tasks whose Docker scoring image exists and whose test suite
is under the configured size cap — this is a tractability filter, not a
representativeness claim about SWE-bench Live as a whole. Single first
baseline: treat point estimates from this run as informative but not yet a
stable reference the way `opus_results.csv`'s Terminal-Bench baseline is
after multiple confirmatory reps.

## Execution parameters (pin exactly)

- **Budget:** `$15` max per single run (`claude --max-budget-usd`,
  harness-enforced) — `--max-budget-usd` passed explicitly by
  `run_baseline_experiment.sh` to every `run_instance.py` invocation.
- **Cumulative abort:** `$80`, checked **between waves** (never mid-wave),
  summed across **all 3 arms combined**, scoped strictly to
  `swebench_live/jobs_baseline/results/` — never `swebench_live/results/`
  (the pre-existing $2.50 smoke-test dir, untouched by this experiment) or
  any Terminal-Bench `jobs*/` dir elsewhere in this repo.
- **Waves:** 5 waves × 5 tasks per arm, arms run sequentially
  (opus-solo → prewalk-sonnet → prewalk-haiku), each arm covering all 25
  subset instances once.
- **Jobs directory:** `~/qm-bench-spike/swebench_live/jobs_baseline/`
  (`results/<arm>/<instance_id>/` + `work/<arm>/<instance_id>/repo/`).
  Greppable `WAVE_DONE`/`ARM_START`/`ARM_DONE`/`ABORT_BUDGET`/
  `ABORT_ALL_ERRORED`/`ALL_DONE` markers in the driver's log output
  (`run_baseline_experiment.sh`).
- **Results:** `swebench_live/swebench_live_baseline_results.csv`
  (`build_results_csv.py`, rebuilt after every wave and at exit), one row
  per run: `instance_id`, `arm`, `model` (planner→executor label),
  `model_ids_observed` (raw distinct models seen in `modelUsage`),
  `resolved` (0/1), `total_cost_usd`, per-model (opus/sonnet/haiku)
  prompt+completion token and cost split, `n_turns`, `wall_clock_s`,
  `status`, `swap_fired`, `model_pin_ok`, `model_pin_drift`,
  `resolved_verdict_source`, `patch_empty`.

## Decision rule

Same form as every prior PREREG in this repo: if the bootstrap CI on
cost-per-solved (arm vs opus-solo) straddles zero, the result is null,
regardless of which point estimate looks lower. The quality bar (pass-rate
CI) is evaluated independently and BOTH conditions (cheaper AND
not-statistically-worse pass rate) must hold for an arm to qualify as a
shippable token-reducer. Kill/flag criteria (a)–(c) above are checked and
reported regardless of what the primary metric shows — a "cost win" that
trips (a), (b), or (c) is not reported as a clean greenlight.
