# Preregistration — tail-only observation masking (SWE-bench Live)

DRAFT — to be LOCKED by commit hash before any data is collected. The
"Arms & implementation" section is pending the mechanism decision (CLI hook
vs Claude Agent SDK); everything else is fixed now.

## Motivation

The baseline campaign established cost ≈ Σ_turns(context × rate), with the
growing re-read context as the dominant driver. The research sweep
(TOKEN_REDUCTION_CANDIDATES.md) ranks **tail-only observation masking**
("The Complexity Trap", arXiv:2508.21433) as the highest-leverage,
lowest-effort, quality-neutral candidate: ~52.7% cost cut at neutral resolve
rate on SWE-bench Verified, a pure prompt/harness transform.

## Hypothesis (directional, one-sided)

Replacing OLDER tool observations in-context with short placeholders (keeping
the last N at full fidelity, and the stable prefix untouched) **reduces
cost-per-solved** on SWE-bench Live versus an otherwise-identical unmasked
agent, **without** a statistically-significant reduction in resolve rate.

## Primary metric

**cost-per-solved** = total true USD (summed per-model, from stream-json
`modelUsage`) ÷ tasks resolved. Same instrument as the baseline.

## Secondary / mechanism metrics (must move the right way, or the technique
did not do what it claims)

- **cache_read tokens per run** — MUST drop materially in the masked arm; if
  it doesn't, masking isn't actually shrinking the re-read context (broken
  implementation or cache-invalidation, see below).
- **cache_creation tokens** — MUST NOT balloon; if masking mutates content
  below a cache breakpoint it will force cold re-prefill and can COST more
  (the exact failure the "tail-only, prefix-preserved" design must avoid).
- n_turns, patch_empty rate, wall-clock.

## Quality bar (identical to the baseline campaign)

The masked arm "preserves quality" iff the bootstrap CI on the pass-rate
difference (masked − unmasked) is NOT entirely below zero (includes zero or
positive). Paired bootstrap over the instance intersection (each instance run
in both arms).

## Cost-win criterion

- **Directional win:** paired cost-per-solved ratio (masked/unmasked) median
  < 1.
- **Statistical win:** its bootstrap 95% CI upper bound < 1.
Report both honestly; n may be too small for the statistical bar (as in the
baseline).

## Preregistered masking parameters (fixed before data)

- **Keep-window N = 3**: the most recent 3 tool observations retained at full
  fidelity; all older tool observations replaced by a fixed placeholder.
- **Placeholder**: a constant short string, e.g.
  `[observation masked to save context — re-run the tool if needed]`, with the
  tool name + a byte-count retained so the agent knows what was there.
- **Prefix preserved**: system prompt, tool definitions, and the task
  statement are never masked (kept in the cacheable prefix).
- **Only tool RESULTS are masked**, never the agent's own reasoning/messages
  or the final assistant turns.

## Kill criteria (pre-committed)

- (a) cache_read does not drop in the masked arm → implementation broken,
  abort and fix.
- (b) cache_creation balloons (cache-invalidation) → masking is hitting the
  cached prefix; abort and fix the breakpoint placement.
- (c) resolve rate craters (masked pass rate CI entirely below unmasked) →
  masking is dropping info the agent needs at N=3; record and stop (a
  larger N might recover, but that is a new prereg).
- (d) patch_empty rate materially higher in masked arm → the agent is losing
  the thread; record and stop.

## Confounds to control

- **Claude Code's own background compaction / background-Haiku** (baseline
  anomaly A1): both arms run the SAME model and SAME scaffold so this applies
  equally; report per-arm background-Haiku share to confirm it didn't diverge.
- **Scaffold parity:** unmasked and masked arms MUST use the identical
  scaffold (CLI-vs-CLI or SDK-vs-SDK) — masking must be the ONLY difference.
  This is why the implementation mechanism (pending) determines whether we can
  reuse the existing opus-solo run as the control or must run a fresh
  same-scaffold unmasked control.

## Arms & implementation — PENDING MECHANISM DECISION

Two candidate designs, chosen once the Claude Code mechanism is known:

- **If a CLI PostToolUse-style hook can rewrite tool-result content
  in-context:** arms = existing opus-solo (unmasked, CLI) vs opus-masked
  (CLI + masking hook), same 25-instance subset, paired. Reuses the baseline
  as control — no re-spend on the control arm.
- **If masking requires the Claude Agent SDK message loop:** arms =
  unmasked-SDK vs masked-SDK, BOTH freshly run on the subset (the CLI
  opus-solo data is NOT a valid control — different scaffold). More runs, but
  isolates masking.

Model held constant across arms (Opus, matching the existing baseline's
long-trajectory regime where masking should help most). Exact model pin
`claude-opus-4-8`, verified per run.
