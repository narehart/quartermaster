# Preregistration — round 3, Arm A: output-token tuning (opus-tuned)

Locked before data. Attacks a BINDING cost term (output tokens, never
cache-discounted) per the campaign-1 conclusion, using the two levers with
published controlled evidence:

- **Repo-instruction efficiency block** (fixed `CLAUDE.md` written untracked
  into the task repo; auto-loaded by the agent CLI). Evidence:
  arXiv:2601.20404 — median −16.6% output tokens, −28.6% runtime,
  completion preserved, across 10 repos / 124 PRs.
- **Thinking-budget cap** (`MAX_THINKING_TOKENS=8000`). Evidence:
  arXiv:2512.10398 — SWE-bench Verified resolve 68.7% @32k vs 67.3% @8k
  (≈ −1.4pp for the full cap).

Both are cache-safe by construction: the instruction text is a constant
(stable prefix content), and the thinking cap changes only output volume.
No context is ever mutated; no proxy in the path.

## Arm & control

- **opus-tuned** (n=25, the standard subset): opus-solo scaffold + the two
  levers. Exact pin `claude-opus-4-8` verified per run.
- **Control:** existing opus-solo baseline (n=25). Same A4 caveat: same-day
  trajectory variance dominates; paired bootstrap over the intersection.

## Hypothesis (directional)

Output tokens per run drop materially (mechanism gate), driving
cost-per-solved down, with resolve rate not statistically below baseline.

## Metrics & gates

- Primary: paired cost-per-solved vs opus-solo (10k bootstrap, seeded).
- **Mechanism gate: completion (output) tokens per run must drop.** If output
  tokens do not drop, the levers did nothing (inert arm) regardless of the
  cost number.
- Quality bar: pass-rate diff CI not entirely below zero.
- Turn gate: median turns must not inflate >+50% (an agent told to be terse
  might compensate with more turns — watch for it).
- cc/cr sanity ≤0.15 median (nothing here should touch the cache).

## Kill criteria

- (a) resolve CI entirely below baseline → quality broken; stop.
- (b) output tokens NOT lower (median per-run) → inert; record and stop.
- Budget: ~$19 expected; abort gate $30 for jobs_round3.

## Pre-experiment screen recorded (EET-style Arm B: NOT RUN)

Corpus mining (103 opus-scaffold runs) shows simple early-termination
features do not discriminate doomed from slow-but-solvable runs on this
distribution: runs past 40 turns resolve at 29% (≥ the 27% base rate) and
"no edit by turn N" sits at base rate for all N tested. An abort@40 rule
would kill ~4 of 28 solves to save ~8% of spend — a guaranteed quality-bar
failure. EET's published discrimination evidently needs richer features
than turn/edit-timing; the simple-rule arm is screened out WITHOUT spending
its budget. (Recorded as finding F6 in SWEBENCH_LIVE_ANALYSIS.md.)
