# Token Reduction Is Mostly Dead: a preregistered campaign on the real cost of coding agents

*Quartermaster campaign writeup — July 2026. Status: complete through F9;
delivery-vehicle re-bench (PREREG_VEHICLE.md) pending §7 update.*

## Abstract

We ran a preregistered, cache-priced, quality-gated benchmark campaign to
find techniques that reduce the cost of long-horizon agentic coding
(SWE-bench Live, real Claude Code, per-task Docker, exact model pins).
Across ten techniques and ~$350 of measured spend, **every context-reduction
and model-substitution technique failed** — several catastrophically — and
the failures share one arithmetic cause: **prompt caching has already
collapsed the context term of agent cost.** Cached re-reads are billed at
0.1×; removing such tokens saves almost nothing (whale-capping: fully
engaged, cost-neutral-at-best), while *mutating* already-sent context
re-triggers 1.25× cache writes every turn (sliding-window masking: **~28×**
cost). What binds instead are the full-price terms: **turn count** and
**output tokens**. The one technique aimed at those terms — a fixed
efficiency instruction block plus a thinking-budget cap — **certified at
n=150: cost-per-solved ratio 0.66 (95% CI [0.55, 0.77]) at an identical
resolve rate (24.0% vs 24.0%)**, and now ships as a Claude Code plugin. Our
central negative finding was independently replicated at 40× our scale
within days (arXiv:2607.12161). The broader claim: most published "token
savings" numbers are cache-blind, and under real cache-tier pricing they can
invert into cost increases.

## 1. Motivation

The project began as a plugin premised on a plausible idea: delegate an
expensive model's tool-work to cheaper models and cost falls. A preregistered
A/B killed that premise (cost-neutral at Sonnet, 1.39× at Opus — delegation
overhead doubles token volume). Rather than patch the story, we pivoted the
project to the general question — *what actually reduces the cost of
long-horizon agentic coding?* — governed by one rule: **a technique ships
only if a preregistered benchmark shows it cuts cost-per-solved without a
statistically significant quality drop, under real cache pricing.** Nothing
grandfathered, including the founding mechanism.

## 2. Instrument

- **Task distribution:** SWE-bench Live — continuously refreshed GitHub
  issues. Contamination matters: one-shot Opus resolves ~32% here vs ~70% on
  the memorized SWE-bench Verified, so Verified-based savings claims ride on
  recall, not work. Fixed 25-instance recency-ordered subset.
- **Agent:** unmodified Claude Code, headless, per-task Docker sandbox,
  non-root; patches scored by the official SWE-bench Live evaluator
  (FAIL_TO_PASS / PASS_TO_PASS in per-instance images).
- **Metric:** **cost-per-solved** — billed USD ÷ resolved tasks — never raw
  token counts. Per-model, per-tier token accounting (`input`, `output`,
  `cache_read` at 0.1×, `cache_creation` at 1.25×) parsed from the billing
  stream of every run.
- **Discipline:** preregistration (metrics, arms, kill criteria) locked by
  pushed commit before data; exact model-ID pins verified per run against
  the observed model sequence; paired bootstrap over instances (10k
  resamples, seeded); every anomaly logged with root cause (A1–A5);
  interventions delivered through mechanisms proven byte-transparent when
  inactive (an egress proxy on `ANTHROPIC_BASE_URL`, validated end-to-end).

## 3. The cost model (what the failures taught)

Per task, a cached API agent costs approximately:

```
cost ≈ Σ over turns ( 0.1 × cached-context reads + 1.25 × new-token cache writes )
       + ~5 × output tokens
```

Three consequences, each learned the expensive way:

1. **Context volume is nearly free to keep** — and therefore nearly
   worthless to remove. A 5k-token observation in a 30-turn run costs one
   1.25× write plus 29 re-reads at 0.1× ≈ 2% of the run.
2. **Context is expensive to *change*.** Anthropic (and now OpenAI) cache on
   strict prefixes: mutate anything already sent and everything after it
   re-writes at 1.25× — every turn, if the mutation moves.
3. **Turns and output tokens are full price.** Each turn re-reads the whole
   context and emits ~5×-rate output; nothing discounts either.

## 4. Findings

### 4.1 Model substitution fails via turn-inflation (F1)

*prewalk* — plan with Opus until the first edit, then resume the session on
a cheaper executor — looked spectacular on Terminal-Bench (40.9% cheaper,
CI excluding zero). On real-repo work it inverts: the Sonnet executor takes
more turns (median 19→25), and each extra turn re-reads everything.
Net **1.35×** cost/solved. The Haiku executor's larger per-token discount
survives its (absent) turn-inflation — 0.86× — but pays in capability (−8%
resolve). Neither clears "cheaper without quality loss." The general law:
**net = per-token discount ÷ turn-inflation**, and turn-inflation usually
wins. (The same law later re-killed delegation-shaped ideas: SWE-Edit-style
sub-agent editing was adopted for its retry-loop ingredients only.)

### 4.2 Mutating context is catastrophic (F2)

Tail-only observation masking — keep the last N tool results, placeholder
the rest — is the literature's headline context technique (~52% claimed
savings). Delivered faithfully through a validated egress proxy, it cost
**~28×** baseline on its smoke instance: the sliding window mutates the
cached prefix every turn, so cache_creation/cache_read hit 0.39 (baseline
~0.05) and the agent, robbed of observations, ballooned 6→34 turns. Killed
at smoke for $3.63 — the preregistered kill-criterion fired exactly as
designed. The claimed savings exist only under cache-blind token counting.

### 4.3 Shrinking context at source saves nothing (F3, F4)

The cache-safe variant — cap each oversized observation ONCE at first entry
(pure content-keyed transform, byte-stable thereafter, overflow re-fetchable
in-sandbox) — was mechanically flawless: cache untouched (cc/cr 0.026),
quality preserved, and at a 4k-char threshold it engaged on 19/25 runs
(1,882 caps). Cost effect: **none** (1.59× point estimate, noise-dominated,
CI spanning 1). The capped tokens were 0.1×-rate cache reads; per §3.1 there
was nothing to save. At 16k chars it simply never fired (2/25 runs) —
observation whales are rarer than the top-3-hold-71%-of-bytes concentration
suggested once context accounting is done properly.

### 4.4 Batched clearing hurts the runs it touches (F5)

The cache-*correct* version of context editing — threshold-gated, batched,
fire-once-and-freeze clearing, tuned by a break-even derivation (below) —
fired on exactly the 2/25 tail runs it was designed for, and both blew up:
2.5× turns, one lost a solve the control had. Cleared observations were
still needed; the re-fetch net did not compensate. Anthropic's own "+29%
with context editing" (their agentic evals) did not transfer to this coding
workload. Clearing's break-even (novel, as far as we know): removing D
tokens from context S above stable prefix P pays only after
**n\* ≈ [1.25·(S−D−P) − 0.1·(S−P)] / (0.1·D)** further turns — which median
runs never reach.

### 4.5 Simple early-termination cannot find doomed runs (F6)

Mined from 103 completed trajectories before spending: runs past 40 turns
resolve at ≥ the base rate; "no edit by turn N" carries no signal. A simple
abort rule would kill ~4 of 28 solves to save ~8% of spend. Screened out for
$0 — the published EET result evidently requires richer features than
turn/edit-timing.

### 4.6 Better retrieval, worse bill (F8)

roust — recall-first code retrieval (92.1% gold-file recall on held-out
SWE-bench Verified), enforced via hard-denied grep and README-faithful
instructions — was fully adopted (median 3 calls/run) and quality-neutral,
yet cost **1.37× [1.14, 1.94]**: turns did not drop (18 vs 18); the agent
used the ~8k-token bundles *in addition to* its normal reading. Diagnostic:
on this workload recall is not the bottleneck — **turn conversion** is.

### 4.7 The technique that worked (F7 → F9)

Aim at the full-price terms directly: a fixed ~150-word efficiency
instruction block (be concise; read the minimum; batch independent reads;
smallest change; stop when done) plus `MAX_THINKING_TOKENS=8000`.
Directional pass at n=25 (cheaper on 24/25 instances), then **certified in a
powered replication** — 3 reps × 25 instances × both arms, fresh controls,
150 runs:

| | tuned | control |
|---|---|---|
| resolved | 18/75 (**24.0%**) | 18/75 (**24.0%**) |
| output tokens/run | 5,172 | 8,230 (**0.63×**) |
| median turns | 11 | 16 (**0.69×**) |
| cost/solved | $2.07 | $3.16 — **ratio 0.66, 95% CI [0.55, 0.77]** |

Instructions alone moved BOTH binding terms: less narration (output) and
less re-exploration (turns), at zero measured quality cost. It ships as a
Claude Code plugin (v0.9.0): the certified block auto-injected at session
start, the cap set once user-level.

## 5. External corroboration

- **arXiv:2607.12161** (*Token Reduction Is Not Cost Reduction*, 2,848
  Claude Code runs, published within days of our campaign): cache traffic
  ≈87% of billed cost; token-reduction↔cost correlation r=0.15; removing
  38% of tool-output tokens *increased* paired cost 6.8%. Independent
  replication of §4.2–4.4 at 40× our scale.
- **arXiv:2601.06007** (*Don't Break the Cache*): caching alone cuts agent
  cost 41–80%; stable-prefix/dynamic-suffix discipline dominates.
- **arXiv:2606.17016 (TokenPilot)** and **arXiv:2606.11213 (CWL)**
  independently name the pathology of §4.2 (the "perpetual cache-write
  regime").
- **Pricing convergence:** OpenAI's GPT-5.6+ adopted the write-charged
  strict-prefix cache model; no commercial API exposes non-prefix KV reuse
  (that exists only in self-hosted serving). The constraint is industry-wide
  and, with read prices trending down, strengthening.

## 6. Methodology notes (what made this cheap)

Total campaign spend ≈ $350 for ten adjudicated techniques. The economics of
honesty: preregistered kill criteria stopped the worst technique at $3.63
instead of $18 (§4.2); corpus mining screened one arm for $0 (§4.5);
resume-safe drivers survived a machine crash and a Docker-daemon wedge with
zero lost spend (A5); byte-transparent instrumentation kept controls free.
The anomaly log (A1–A5) is part of the result: background-model housekeeping
(A1), same-instance trajectory variance ~2× (A4 — the dominant noise source,
and the reason the certification used fresh controls and reps), and
infrastructure failure modes (A5) would each have manufactured false
findings if unlogged.

## 7. Limitations & open work

- One scaffold (Claude Code), one model family (Opus 4.8 work-loop), one
  25-instance Python-heavy subset; certification is distribution-specific.
- Negative results are directional (n=25, wide CIs); their *mechanisms* are
  the durable contribution, and each is arithmetic-backed rather than
  merely sampled.
- Cost-per-solved with small solve denominators is noisy; the certified
  result is the only claim made at certification strength.
- Delivery-vehicle re-bench (hook-injection vs repo CLAUDE.md; identical
  text): **resolved — vehicles equivalent** (PREREG_VEHICLE.md, F10; n=25
  vs the powered campaign's pooled arms). Hook-injected delivery reproduced
  the certified mechanism in full: output-token ratio 0.61 vs control
  (mechanism bar <0.8), shipped/tuned output ratio 0.97, cost/run ratio
  0.96, identical median turns (11), quality bar met. The v0.9.0 plugin
  delivers what was certified.
- Untested candidates remain (diagnostic front-loading, course-correction
  feedback, batched recon, context-mode as a live arm, LSP navigation).

## 8. Conclusion

"Reduce token usage" was the wrong objective. Under real cache pricing the
right objective is **reduce turns and output tokens without reducing resolve
rate** — and the cheapest certified way we found to do that is to *tell the
agent to work that way*, in ~150 words, and cap its thinking budget. Every
fancier mechanism we tested either attacked already-discounted tokens, paid
the prefix-mutation tax, or destabilized the agent into extra turns that
cost more than the mechanism saved. Benchmarks that count tokens without
pricing cache tiers are measuring the wrong thing, and quality-ungated cost
claims are not cost claims at all.

## Appendix: experiment ledger

| # | technique | class | verdict | key number |
|---|---|---|---|---|
| 0 | tool-tier delegation | model routing | ❌ | 1.39× at Opus |
| 1 | prewalk-sonnet | model swap | ❌ | 1.35×; turns 19→25 |
| 2 | prewalk-haiku | model swap | ❌ | 0.86× but −8% quality |
| 3 | sliding-window masking | context/per-turn | ❌ killed at smoke | ~28×; cc/cr 0.39 |
| 4 | whale-capping @16k | context/at-source | ⚪ inert | fired 2/25 |
| 5 | whale-capping @4k | context/at-source | ❌ | engaged 19/25, no cost effect |
| 6 | epoch clearing | context/batched | ❌ | treated runs 2.5× turns, lost solve |
| 7 | simple early termination | turns | ⚪ screened, $0 | no doomed-run signal |
| 8 | roust-only retrieval | turns | ❌ | 1.37× [1.14,1.94]; turns flat |
| 9 | **output tuning** | output+turns | **✅ SHIPPED** | **0.66 [0.55, 0.77], quality identical, n=150** |

Full findings: SWEBENCH_LIVE_ANALYSIS.md (F1–F9, A1–A5). Preregistrations:
PREREG_*.md. Raw records: ../results/*.csv.
