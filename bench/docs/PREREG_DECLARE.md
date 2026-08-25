# Preregistration — budget-declaration isolation arm (opus-declare)

Locked before data. F16 (opus-budget) produced a directional pass (cost/solved
0.62 [0.32, 1.05] vs the August band, quality up) in which the PREREGISTERED
mechanism (live countdown) demonstrably never fired (0/25 runs crossed a
threshold). The only other active component was the static CLAUDE.md
declaration: "This task has a cost budget of $1.00... prefer the cheapest
action that makes progress." This arm isolates it.

## Design
- opus-declare (n=25, original subset): certified block + the declaration
  line ONLY — no hook, no countdown, nothing else. Single variable.
- Control: the same August band (F12 lint + A7 quarantined, n=50) used for
  F16, PLUS opus-budget's own 25 runs as a should-be-equivalent comparison
  (if declaration is the driver, declare ≈ budget).
- ~$8; abort $20 on jobs_declare. Pin claude-opus-4-8.

## Hypotheses & verdict rules
- H1: cost/run and output/turns reproduce opus-budget's drop (≈0.7× band).
- H2: quality bar vs band met.
- Reproduces → the economic-framing effect is real → powered confirmation
  (fresh contemporaneous controls) → candidate one-line addition to the
  shipped block (v0.10.0). Fails to reproduce → F16's effect was noise or
  countdown-dependent in some unseen way; record and stop.
