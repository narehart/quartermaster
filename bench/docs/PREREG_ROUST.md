# Preregistration — round 3, Arm B: roust-only retrieval (opus-roust)

Locked before data. Tests whether recall-first code retrieval
([narehart/roust](https://github.com/narehart/roust), pinned at
`52b23059ace88dd4cd8bfb4e3efc12c6d55439e4`) reduces cost-per-solved by
attacking the TURNS term: one ranked, token-budgeted bundle per query instead
of the iterative grep→read→grep-again exploration loop. roust's own
validation is recall-side (92.1% all-gold-files on 407 held-out SWE-bench
Verified instances); this experiment measures the live cost/quality effect.

## Arm

- **opus-roust** (n=25, standard subset): opus-solo scaffold, exact pin
  `claude-opus-4-8`, with:
  1. roust binary in the sandbox image (`Dockerfile.agent-roust`, multi-stage
     build from the pinned commit);
  2. usage instructions via untracked CLAUDE.md, following roust's
     README-recommended block (raw query text, verbatim error strings,
     `--files-only` for localization) adapted for the hard block below;
  3. **enforcement**: Grep tool and grep-family Bash commands
     (grep/egrep/fgrep/rg/ag/ack) DENIED by a PreToolUse hook that returns a
     redirect-to-roust reason. Instruction-only routing measures ~60%
     compliance (context-mode's own data), so we enforce. Read/Glob/LS stay
     available: known-file reading is fine, content DISCOVERY goes through
     roust. This is the strictest variant (no grep fallback at all).
- **Control:** existing opus-solo baseline (n=25), paired bootstrap, usual
  A4 trajectory-variance caveat.

## Hypothesis (directional)

Fewer exploration turns (and fewer/larger-grained context reads) →
cost-per-solved down, resolve rate not statistically below baseline.
Secondary hypothesis: localization-driven solves may IMPROVE resolve rate
(SHERLOC-style effect — agents spend ~half their budget locating faults).

## Metrics & gates

- Primary: paired cost-per-solved vs opus-solo (10k bootstrap, seeded).
- **Mechanism gates:**
  - roust actually used: count Bash `roust` invocations per transcript;
    if the median run has 0, the arm is inert (instructions failed).
  - enforcement fired-or-unneeded: count hook denials per transcript
    (denials are evidence the block works; ~0 denials with high roust use
    is the ideal — the agent went to roust directly).
  - n_turns vs paired baseline (the hypothesis says DOWN; >+50% median
    inflation = kill (b)).
- Quality bar: pass-rate diff CI not entirely below zero.
- cc/cr sanity ≤0.15 median (nothing here touches cached history; the
  bundle is a normal tool_result, append-only).

## Kill criteria

- (a) median roust invocations = 0 → inert; record and stop.
- (b) median turns inflation > +50% → the tool is hurting navigation; stop.
- (c) resolve CI entirely below baseline → quality broken; record and stop.
- Budget: ~$19 expected; abort gate $30 for jobs_roust.

## Confounds / notes

- roust's first call per repo builds an index (sub-second to seconds) —
  wall-clock only, no token cost. `.roust/` cache is untracked → cannot leak
  into patches (`extract_patch` is tracked-only diff).
- The roust image differs from the baseline image only by the added binary
  (same node/claude-code/toolchain layers), so scaffold parity holds.
- Single-variable discipline: this arm does NOT include the opus-tuned
  efficiency instructions; if both arms pass independently, a stacked arm
  is a separate future prereg.
