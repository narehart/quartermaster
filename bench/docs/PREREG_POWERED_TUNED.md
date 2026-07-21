# Preregistration — powered confirmation of output tuning

Locked before data. Purpose: convert F7's **directional pass** into a
certified verdict (or refute it), per the project rule that "shipped" status
requires statistical power, not direction.

## Design — reps over subset expansion

**3 reps × 25 instances × 2 arms = 150 runs.**

- **Arms:** `opus-tuned` (identical configuration to F7: fixed efficiency
  CLAUDE.md + MAX_THINKING_TOKENS=8000) and `opus-solo` (FRESH control reps —
  not the original baseline run).
- Why reps, not more instances: (a) run-to-run trajectory variance (A4) is
  the dominant noise source and reps measure it directly; (b) fresh control
  reps eliminate the "original baseline drew lucky on flaky instances"
  asymmetry F7's quality read had to argue around; (c) the existing subset's
  eval images are already on disk — no new-image pulls.
- Per-rep isolated work roots (a repo checkout is DIRTY after a run;
  reps must never share a checkout).
- Exact pin `claude-opus-4-8` both arms, verified per run.

## Primary endpoint

Paired cost-per-solved ratio (tuned/control), bootstrap over instances with
reps pooled within instance (resample instances, keep all reps of a sampled
instance). **Certification bar: 95% CI upper bound < 1.**

## Quality bar

Pass-rate difference (tuned − control), pooled reps, same bootstrap.
**Bar: CI not entirely below zero.** With ~150 runs the solve denominators
should be ~18–24 per arm — enough to see a real 8% quality drop if it exists.

## Secondary / mechanism

- Output-token ratio (expect ≈0.53, must be <0.8 or the mechanism regressed)
- Median turns ratio (expect ≈0.56)
- Per-instance resolve stability: for each instance, resolve fraction across
  3 reps per arm — identifies the flaky set explicitly (pre-named suspects:
  openai-1601, SDV-2658, django-guardian-899).
- cc/cr sanity ≤0.15.

## Kill criteria

- (a) tuned resolve CI entirely below control → quality broken; stop, record.
- (b) output-token ratio >0.8 → mechanism regressed (config error); abort.
- Budget: ~$90 expected (150 runs; tuned ≈$0.43/run, control ≈$0.75/run);
  abort gate **$120** on jobs_powered.

## Verdict rules (pre-committed)

- CI_upper(cost/solved ratio) < 1 AND quality bar passes → **CONFIRMED**:
  output tuning gets "shipped" status, README ledger goes ✅ shipped.
- CI includes 1 but median <1 and quality passes → remains directional;
  report honestly, consider one further powering round only if the CI
  narrowed materially (else accept indeterminate).
- Quality bar fails → REVOKE the directional pass; README updated.
