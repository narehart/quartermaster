# Preregistration — round 4: marginal value over the shipped baseline

Locked before data. **The baseline has moved:** with output tuning shipped
(F9/F10), new techniques must beat the TUNED configuration, not untuned
control. Control = the powered campaign's 75 pooled opus-tuned runs (fresh,
same subset).

## Arm A — opus-diag (diagnostic front-loading, SHERLOC-style)

Tuned config (certified block + MAX_THINKING_TOKENS=8000) plus a
**diagnosis pre-phase**: one `claude-sonnet-5` call in the same sandbox
produces a structured diagnosis (likely root cause; ranked files/functions
to inspect; fix strategy; affected tests — explicitly NO edits), which is
appended to the main run's task prompt. The opus main run starts localized.

- Motivation: agents spend a large share of turns locating the fault
  (arXiv:2606.24820 claims −23% tokens AND +6pp resolve from structured
  localization). Tuned cut narration; diag attacks the exploration turns
  that remain (tuned median is 11 — the floor is not reached).
- Cost accounting: the diag phase writes to the SAME stream log (the prewalk
  multi-invocation pattern), so its tokens/cost are counted in the arm
  total. Expected pins: [claude-opus-4-8, claude-sonnet-5], exact.
- Mechanism gate: median turns < tuned's 11 (the arm exists to cut turns;
  if turns don't drop, the diagnosis isn't landing).

## Arm B — opus-lint (edit-retry-loop elimination)

Tuned config plus a **PostToolUse lint hook**: after every Edit/Write to a
`*.py` file, run pyflakes on that file and return any errors as
additionalContext. Kills failed-edit → test-fail → re-edit cycles at the
earliest possible moment.

- Motivation: ~half of SWE trajectories contain failed-edit retry loops
  (SWE-agent data); SWE-Edit attributes its −17.9% cost to edit
  reliability. We adopt the feedback ingredient WITHOUT sub-agent
  delegation (which F1 killed).
- Append-only (hook feedback is a new message) — cache-safe.
- Mechanism gates: lint hook fires (count feedback events; 0 median =
  inert); turns not inflated (>+50% = kill).

## Shared design

- n=25 each, standard subset, per-arm work/results roots (jobs_round4).
- Primary: cost-per-solved ratio vs pooled tuned control (bootstrap over
  instances; arm runs paired against all 3 control reps per instance).
- Quality bar: pass-rate diff CI vs pooled tuned not entirely below zero.
  SECONDARY upside hypothesis (both arms): resolve rate IMPROVES (both
  papers claim quality gains) — report the CI either way.
- cc/cr sanity ≤0.15. Exact pins verified per run.

## Kill criteria

- (a) quality CI entirely below tuned control → stop arm, record.
- (b) opus-diag: diag pre-phase cost > 25% of run cost (overhead swamp) →
  flag; if ALSO no turn reduction, arm fails on mechanism.
- (c) opus-lint: median lint events = 0 → inert; record and stop.
- Budget: ~$30 expected for both arms; abort gate $45 on jobs_round4.

## Verdict rules

Per arm: cost ratio median < 1 with quality bar met → directional pass →
candidate for powered confirmation (and for stacking into the shipped
config). Cost ≥ 1 but resolve UP with cost/solved ≤ 1 → report as a
quality-technique candidate (different product decision). Otherwise reject.
