# Preregistration — held-out generalization of the shipped output tuning

Locked before data. The certified result (F9: cost/solved ratio 0.66
[0.55, 0.77], quality identical, n=150) was developed AND certified on one
25-instance subset. This campaign tests whether it generalizes to a
**held-out subset** the technique has never touched — the standard
subset-overfit check, and the strongest remaining threat to the product
claim. (A fresher-in-time subset was the preferred axis, but upstream
SWE-bench Live has published nothing newer than 2025-09; recorded here for
transparency.)

## Design

- **Subset:** `swebench_live_holdout.json` — 25 instances selected by the
  same recency-ordered, image-verified, test-count-bounded procedure as the
  original, with the original 25 EXCLUDED (`--exclude`).
- **Arms (contemporaneous, per the A8 drift rule):**
  - `opus-solo` (n=25) — untuned control
  - `opus-tuned` (n=25) — the shipped configuration, byte-identical block
- Exact pin `claude-opus-4-8` both arms; standard harness; ~$35 expected;
  abort gate $60 on jobs_holdout.

## Hypotheses

- H1 (replication): tuned/solo cost-per-solved ratio median < 1 on the
  held-out subset, with the certified 0.66 inside the CI.
- H2 (quality): pass-rate diff CI not entirely below zero.
- Mechanism expectations: output-token ratio ≈ 0.6, turns ratio ≈ 0.6–0.7
  (the certified signatures). Mechanism replication matters more than the
  point estimate — A4-scale variance at n=25×1 is expected.

## Verdict rules (pre-committed)

- Ratio median <1 + quality bar met → **generalization supported**; README
  claim gains "replicates on a held-out subset" (directional; the n=150
  certification remains the strength claim).
- Ratio ≥1 or quality bar failed → **scope warning recorded in README and
  writeup**: the certified claim is subset-specific until shown otherwise.
  No spin.
- Baseline sanity: if opus-solo resolve on the held-out subset is <10% or
  >60% (subset difficulty far from the original's ~24–32%), note that the
  comparison crosses a difficulty regime and interpret conservatively.
