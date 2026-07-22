# Preregistration — delivery-vehicle re-bench (opus-shipped)

Locked before data. Closes the honesty caveat on the shipped v0.9.0 package:
certification (F9) delivered the instruction block via **repo CLAUDE.md**;
the plugin delivers the IDENTICAL text via **SessionStart-hook
additionalContext**. Does the shipped vehicle reproduce the certified effect?

## Arm & controls

- **opus-shipped** (n=25, standard subset): certified text injected via a
  SessionStart hook inside the sandbox (exactly the plugin's mechanism),
  `MAX_THINKING_TOKENS=8000` via env, NO repo CLAUDE.md. Exact pin
  `claude-opus-4-8`.
- **Controls (no new runs)**: the powered campaign's 75 fresh opus-solo
  control runs (days old, same subset) and, for effect-size comparison, its
  75 certified opus-tuned runs.

## Hypothesis (directional)

The shipped vehicle reproduces the certified effect: output tokens and
cost/solved drop comparably to the CLAUDE.md vehicle, quality preserved.

## Metrics & gates

- **Mechanism gate: output-token ratio vs pooled controls < 0.8.** If output
  tokens do NOT drop, the hook-injected block is not landing with equivalent
  force — the vehicle matters and shipping must be revisited.
- cost/solved ratio vs pooled controls (bootstrap: resample instances;
  shipped runs paired against all control reps of the same instance).
- Quality bar: pass-rate diff CI not entirely below zero.
- Effect-size comparison vs pooled opus-tuned: shipped/tuned output-token
  and cost ratios ≈ 1 (the two vehicles should be indistinguishable).

## Verdict rules (pre-committed)

- Mechanism gate met + quality bar met → **vehicle validated**; caveat
  removed from README.
- Mechanism gate FAILED (output ratio ≥ 0.8) → the shipped delivery is
  materially weaker than certified: ship a repo-CLAUDE.md-based delivery
  instead (e.g. /tune writes the block to the project) and re-bench THAT.
- Quality bar failed → investigate before any release change; record.

## Budget

n=25 ≈ $13 expected; abort gate $25 on jobs_vehicle.
