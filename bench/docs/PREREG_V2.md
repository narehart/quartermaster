# Preregistration — instruction-block v2 sweep (trust-tools / no-re-read)

Locked before data. Attacks the campaign's central remaining waste mechanism
— RE-VERIFICATION — using the only technique family with a certified win
(behavioral instructions, F9). Each arm = the certified v1 block + ONE
targeted addition (single-variable). Control = pooled opus-tuned (n=75) plus
two bonus tuned replications (F12/A7 arms) available for sensitivity checks.

## Motivation & prior art

- Our ledger: front-loaded info failed twice (F8 roust, F11 diag) because
  the agent RE-VERIFIES everything it is given — the additive-info pattern.
- Causal anchor: arXiv:2608.01347 (4,644 runs, in Claude Code) shows the
  verification dial is instruction-steerable at up to 18× cost in the
  waste-increasing direction. **The trust-increasing direction is untested
  in the literature** — this sweep is novel.
- File re-reads are the measured largest avoidable-spend category
  (industry ~42% of avoidable tokens; CORVUS −37% reasoning cycles via a
  cache-hostile architecture — v2b is the cache-safe behavioral cousin).
- Scope condition (arXiv:2608.02645, 2607.07405): trust applies to
  deterministic read-only results only; the v2a text says so explicitly.

## Arms (n=25 each, standard subset, exact pin claude-opus-4-8)

- **opus-v2a "trust-tools"**: v1 block + act on tool results/provided
  context without re-verification (scoped to deterministic read-only
  results); verify the fix exactly once at the end via the narrowest test.
- **opus-v2b "no-re-read"**: v1 block + never re-read an already-read file;
  an edit's success result IS the confirmation (no re-open after edit).

## Metrics & gates

- Primary: cost/solved ratio vs pooled tuned (bootstrap over instances,
  arm runs paired against all 3 control reps; 10k resamples, seeded).
- Mechanism gates (per arm): re-read/verification behavior must actually
  drop — measured as (a) Read-tool calls per run and (b) reads of
  already-read paths per run, both vs pooled tuned. An arm whose re-read
  count does not drop is inert regardless of cost.
- Turn gate: median turns should drop; inflation >+50% = kill.
- Quality bar: pass-rate diff CI vs pooled tuned not entirely below zero.
  RISK NOTE (pre-declared): trust instructions could plausibly HURT quality
  (acting on a misread). The quality bar is the primary safety check; a
  cost win with quality below bar is a REJECTION, per the standing rule.

## Kill criteria

- (a) quality CI entirely below tuned → stop, record.
- (b) mechanism inert (re-reads don't drop) → record inert.
- Budget: ~$26 expected (2×25 runs); abort gate $45 on jobs_v2.

## Verdict rules

Cost ratio median <1 + mechanism engaged + quality bar met → directional
pass → powered confirmation → block update ships in v0.10.0. Both-arms-null
→ evidence the tuned config is at the instruction-level floor (a citable
ending for the writeup).
