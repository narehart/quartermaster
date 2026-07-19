# Preregistration — deterministic whale-capping (SWE-bench Live)

Locked before data collection. Supersedes PREREG_MASKING.md's experiment: the
sliding-window technique it preregistered was killed at smoke by finding F2
(cache-hostile; see SWEBENCH_LIVE_ANALYSIS.md) — its kill-criterion (b) fired
exactly as designed. This experiment tests the cache-safe successor.

## Hypothesis (directional, one-sided)

Capping only the LARGEST tool observations (>16k chars ≈ 4k tokens) with a
deterministic, frozen, content-keyed transform (head 8k + tail 4k + overflow
note pointing at a re-fetchable file) reduces **cost-per-solved** vs the
unmasked opus-solo baseline, without a statistically significant drop in
resolve rate.

Grounding: our 25 opus-solo trajectories show the top-3 observations hold
~71% of tool-output bytes (ORIGINAL_IDEAS.md) — the compressible mass is a
few whales, so capping only them buys most of the reduction at minimal
quality risk; the re-fetch path (Read /meta/obs/<hash>.txt with offset/limit)
makes nothing unrecoverable.

## Arms

- **Control: existing opus-solo baseline** (n=25, already run, committed in
  results CSV). Valid because the proxy is scaffold-preserving; validated
  further by the parity arm.
- **opus-capped** (n=25, same subset): opus-solo scaffold + egress proxy in
  cap mode. Params fixed: cap_chars=16000, head=8000, tail=4000.
- **opus-passthru parity check** (n=3, first 3 subset instances): identical
  proxy path, transform off. Confirms the proxy adds ~0 tokens; if parity
  fails materially, escalate to a full fresh control arm.

Model pinned exactly `claude-opus-4-8`, verified per run via model_sequence.

## Primary metric

cost-per-solved (total true USD / resolved), paired bootstrap vs opus-solo
over the instance intersection, 10k resamples, seeded.

## Mechanism gates (any failure = technique did not do what it claims)

- **Cache-safety (the F2 gate):** per-run cache_creation/cache_read ratio in
  the capped arm must stay ≈ baseline (~0.05), NOT the F2 pathology (0.39).
  This is the proof the frozen transform preserves prefix stability.
- **Turn discipline (the F1 gate):** n_turns must not materially inflate vs
  the same instance's opus-solo run (re-fetch flailing would show here).
- **Capping actually fired:** report per-run capped-part counts; runs with 0
  caps are diluting (expected on small-context runs — report the split).
- **Re-fetch accounting:** count agent Reads of /meta/obs/* as a mechanism
  metric (frequent re-fetching = the cap threshold is too aggressive).

## Quality bar (identical to prior campaigns)

Capped arm "preserves quality" iff the bootstrap CI on the pass-rate
difference (capped − opus-solo) is NOT entirely below zero.

## Cost-win criterion

Directional: paired cost-per-solved ratio median < 1. Statistical: 95% CI
upper < 1. Report both; n=25 with small solve-denominators is likely
underpowered for the statistical bar — this is a directional read feeding a
powered confirmation, same as the baseline campaign.

## Kill criteria (pre-committed)

- (a) cc/cr ratio > 0.15 median in capped arm → transform is not
  cache-stable in practice; abort and diagnose.
- (b) median n_turns inflation > +50% vs paired baseline → re-fetch flailing;
  abort.
- (c) parity arm deviates > 10% in per-run total tokens from its paired
  opus-solo runs → proxy itself confounds; escalate to fresh full control.
- (d) resolve rate CI entirely below baseline → quality broken; record and
  stop.

## Budget

~$18 (25 capped runs at opus-solo-like ~$0.75/run) + ~$2 parity + smoke.
Abort gate at $35 cumulative for this experiment's jobs dir.
