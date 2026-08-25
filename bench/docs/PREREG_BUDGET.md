# Preregistration — budget-visibility arm (opus-budget)

Locked before data. The last live candidate from the cross-disciplinary
sweep: a **budget-visibility information channel** — the one lever the F13
instruction-floor result does not cover, because it adds live per-run
information (remaining spend), not a style directive.

## Mechanism

Certified tuned config + (a) a CLAUDE.md line declaring a $1.00 task budget,
(b) a PostToolUse hook that estimates spend from the run's own transcript
(usage × opus prices) and injects "[budget] $X spent; $Y remaining" at
50/75/90% threshold crossings (append-only → cache-safe; ≤3 messages/run).

Precedent: TALE (arXiv:2412.18547, −68% output from budget prompts, untuned
models) vs BAGEN (arXiv:2606.00198, prompting-only budget effects weak on
frontier agents). This arm adjudicates which applies to a frontier agent
ALREADY at the instruction floor.

## Design

- **Arm:** opus-budget, n=25, ORIGINAL subset, pin claude-opus-4-8.
- **Control (A8-compliant):** the August tuned replication band — the two
  no-op-hook arms (F12 lint + A7 quarantined, 50 runs, run 2026-08-23,
  same subset, same block, hook-bearing like this arm). July pooled tuned
  reported for reference only.
- ~$13 expected; abort gate $25 on jobs_budget.

## Metrics & gates

- Primary: cost/solved ratio vs the August control band (bootstrap over
  instances, pooled band runs per instance).
- **Mechanism gate:** budget messages must actually fire — median ≥1 per
  run given the $1.00 budget vs ~$0.45 mean spend... NOTE: at $1.00, most
  runs never cross 50% ($0.50). This is INTENTIONAL: the arm tests whether
  visibility changes behavior on the expensive tail (the runs that cross
  thresholds) plus any ambient effect of the budget declaration. Report
  fired-message distribution; if 0 runs fire any message AND cost is
  unchanged, the arm is inert-by-generosity (record; a tighter budget would
  be a NEW prereg, not a peek-and-tweak).
- Quality bar: pass-rate diff CI vs the band not entirely below zero.
  Pre-declared risk: scarcity pressure could truncate patches (quality
  down); the bar is the safety check.

## Kill criteria

- (a) quality CI entirely below the band → stop, record.
- (b) inert-by-generosity (no messages fire, cost unchanged) → record ⚪.

## Verdict rules

Cost median <1 vs band + quality met → directional pass → powered
confirmation candidate. Null/inert → the information-channel family joins
the floor finding, and the campaign's live pipeline is empty pending new
scaffolds/models.
