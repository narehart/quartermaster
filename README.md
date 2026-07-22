# Quartermaster

## The goal

Find techniques that **reduce the token cost of long-horizon agentic
software-engineering work** — the kind a coding agent like Claude Code does
all day — **without sacrificing task success.** One rule governs the project:
a technique ships only if the preregistered benchmark in [`bench/`](bench/)
shows it reduces **cost-per-solved** without a statistically significant drop
in resolve rate, under real cache-tier pricing. Nothing is grandfathered —
including this project's own original mechanism (ledger row 0).

## The answer so far

The per-task cost of a cached API agent is approximately:

```
cost ≈ Σ over turns ( 0.1× cached-context reads  +  1.25× new-token cache writes )
       + 5× output tokens
```

**Prompt caching has already collapsed the context term.** Re-read context
costs 0.1× of the input rate, so removing context tokens saves almost
nothing — and *mutating* already-sent context is actively catastrophic (it
re-triggers 1.25× cache writes every turn). After eight preregistered
experiments, every context-reduction and model-swap technique we tested
either did nothing or made cost worse. The terms that actually bind are
**turn count** (each turn re-reads everything and emits full-price output)
and **output tokens** (5× rate, never discounted). That is where the search
now points — and the one arm aimed there is the first to trend cheaper on
every instance.

This is not just our result: it was independently replicated at 40× our
scale, within days, by
["Token Reduction Is Not Cost Reduction" (arXiv:2607.12161)](https://arxiv.org/abs/2607.12161)
(2,848 Claude Code runs — cache traffic ≈87% of billed cost;
token-reduction↔cost correlation r=0.15).

## Install the shipped technique

The certified **output tuning** configuration (~34% cheaper per solved task,
identical resolve rate — [certification](bench/docs/SWEBENCH_LIVE_ANALYSIS.md))
ships as this plugin:

```bash
claude plugin marketplace add narehart/quartermaster
claude plugin install quartermaster@quartermaster-marketplace
# then, once, in any session:
/quartermaster:tune     # sets MAX_THINKING_TOKENS=8000 in your user settings
```

Installing the plugin auto-injects the certified instruction block
([tuned/EFFICIENCY-CLAUDE-MD.md](tuned/EFFICIENCY-CLAUDE-MD.md) — the exact
text that was benchmarked; the text IS the technique) into every session via
a SessionStart hook — zero per-project setup. `/quartermaster:tune` performs
the one step a hook can't: writing the certified thinking-budget cap to your
user-level settings. Undo: remove that env key and disable the plugin.
The delivery vehicle itself is benchmarked: hook injection reproduces the
certified effect (output ratio 0.97 vs the certified arm, identical turns —
finding F10).

**The full campaign writeup — abstract to ledger, findings F1–F10 —
lives at [bench/docs/CAMPAIGN_WRITEUP.md](bench/docs/CAMPAIGN_WRITEUP.md).**

## How we measure

[`bench/`](bench/) runs **SWE-bench Live** (fresh, contamination-resistant
GitHub issues; one-shot Opus resolves ~32% here vs ~70% on the memorized
SWE-bench Verified) through real Claude Code in per-task Docker sandboxes:

- **Metric: cost-per-solved** (billed USD ÷ tasks resolved) — never raw token
  counts, which barely correlate with cost under caching.
- **Cache-tier accounting**: per-model `cache_read` / `cache_creation` /
  output tokens from the billing stream, per run.
- **Preregistration**: metrics, arms, and kill criteria locked by commit
  before data; every anomaly logged with root cause
  ([bench/docs/SWEBENCH_LIVE_ANALYSIS.md](bench/docs/SWEBENCH_LIVE_ANALYSIS.md)).
- **Exact model pins** (`claude-opus-4-8` etc.) verified per run against the
  observed model sequence.
- All results to date are **directional** (n=25, small solve-denominators):
  anything that passes gets a powered confirmation before "shipped" status.

## The ledger — grouped by the cost term attacked

### Attacking the model rate — dead end: *cheap-model substitution induces turn-inflation*

A cheaper executor pays less per token but takes more turns, and each extra
turn re-reads the whole context and emits full-price output.

| technique | verdict | why |
|---|---|---|
| **Tool-tier delegation** (the original Quartermaster plugin: restricted orchestrator delegating to cheap sub-agents) | ❌ rejected | Cost-neutral at Sonnet, **1.39×** at Opus — delegation overhead ~doubles token volume. Real governance value, no cost value. [Result](docs/benchmarks/2026-07-cost-ab.md) · [legacy docs](docs/legacy-plugin.md) |
| **prewalk-sonnet** (Opus plans → Sonnet executes after first edit) | ❌ rejected | **1.35×** cost/solved: executor turn-inflation (median 19→25 turns) eats the ~4× per-token discount |
| **prewalk-haiku** (same, Haiku executor) | ❌ rejected | 0.86× cost but **−8% quality** (lost 2 of 8 solves) — a cost↔quality trade, not a win |

### Attacking the context term — dead end ×2: *mutating cached context pays a write tax; shrinking it removes already-cheap tokens*

| technique | verdict | why |
|---|---|---|
| **Sliding-window observation masking** (keep last N tool results, mask older) | ❌ killed at smoke | **~28×** cost: the mask window slides every turn, mutating cached history → perpetual 1.25× cache re-writes (write/read ratio 0.39 vs 0.05 baseline) |
| **Whale-capping @16k chars** (cap huge tool outputs at first entry, frozen, re-fetchable) | ⚪ inert | Mechanically clean but fired on only 2/25 runs — >16k observations are rare here |
| **Whale-capping @4k chars** (dose-response) | ❌ rejected | Fully engaged (19/25 runs, 1,882 caps), zero cache damage, quality held — and still **1.59×**: the capped tokens were 0.1×-rate cache reads. There was nothing to save |
| **Epoch clearing** (batched, threshold-gated clearing — the cache-correct version of context editing) | ❌ rejected | **1.99×** and the campaign's worst quality point-estimate: both runs where it fired flailed (2.5× turns, one lost a solve the baseline had). Cleared observations were still needed |

### Attacking turn count — one dead end so far: *simple stop rules can't tell doomed from slow*

| technique | verdict | why |
|---|---|---|
| **Simple early termination** (abort long or edit-less runs) | ⚪ screened out, $0 spent | Mining our 103-run corpus: runs past 40 turns resolve at ≥ the base rate — an abort rule would kill ~4 of 28 solves for ~8% savings. Killed by data before spending its budget |

### Attacking output tokens — the live frontier

| technique | verdict | why |
|---|---|---|
| **Output tuning** (efficiency repo-instructions + thinking-budget cap) | ✅ **SHIPPED — certified at n=150** | Powered confirmation (3 reps × 25 instances × both arms, fresh controls): cost/solved ratio **0.66, 95% CI [0.55, 0.77]** — CI upper below 1. Resolve rate **identical** (24.0% vs 24.0%, diff CI [−4%, +4%]). Output tokens 0.63×, median turns 11 vs 16. **~34% cheaper per solve at zero measured quality cost** |
| **roust-only retrieval** ([narehart/roust](https://github.com/narehart/roust): one ranked, token-budgeted bundle per query instead of iterative grep; grep-family hard-denied by hook) | ❌ rejected as configured | Fully adopted (median 3 calls/run) and quality held — but **1.37×** cost/solved, CI [1.14, 1.94]. Turns didn't drop (18 vs 18): the agent used roust *in addition to* normal reading, so each ~8k-token bundle added context mass with no offsetting turn reduction. Diagnostic: recall isn't the bottleneck here, turn conversion is |

## Upcoming experiments

All from the ranked pipeline
([bench/docs/TOKEN_REDUCTION_CANDIDATES.md](bench/docs/TOKEN_REDUCTION_CANDIDATES.md)),
all aimed at the binding terms, all cache-safe by construction:

| candidate | lever | published claim to test |
|---|---|---|
| Diagnostic front-loading (SHERLOC-style) | turns | −23% tokens **and** +6pp resolve — agents burn ~half their budget locating the fault |
| Course-correction feedback (SWE-PRM-style) | turns | +10.6pp resolve with shorter trajectories |
| Edit-retry-loop elimination (SWE-Edit ingredients) | turns | +2.1pp resolve, −17.9% cost — half of SWE trajectories contain failed-edit retry loops |
| Batched recon tool-calls | turns | unmeasured on SWE in the literature — our rig can produce the number |
| Rich-feature early termination | turns | only if features beat the simple-rule screen above |

## What the literature says

**Corroborating our findings** (all verified against arXiv):
- [arXiv:2607.12161](https://arxiv.org/abs/2607.12161) *Token Reduction Is Not
  Cost Reduction* — the independent replication: removing 38% of tool-output
  tokens *increased* billed cost 6.8%; compression corrupted edit anchors.
- [arXiv:2601.06007](https://arxiv.org/abs/2601.06007) *Don't Break the
  Cache* — caching alone cuts agent cost 41–80%; stable-prefix /
  dynamic-suffix discipline dominates.
- [arXiv:2606.17016](https://arxiv.org/abs/2606.17016) (TokenPilot) and
  [arXiv:2606.11213](https://arxiv.org/abs/2606.11213) (CWL) — independently
  name the failure we measured: the "perpetual cache-write regime" where
  context edits invalidate the prefix faster than reads amortize it.
- Pricing convergence: OpenAI's GPT-5.6+ adopted Anthropic's exact
  write-charged strict-prefix cache model; no API provider exposes non-prefix
  KV reuse. The constraint is industry-wide and durable.

**Claims our upcoming experiments exist to test**:
[arXiv:2601.20404](https://arxiv.org/abs/2601.20404) (repo-instruction output
savings), [arXiv:2606.24820](https://arxiv.org/abs/2606.24820) (SHERLOC),
[arXiv:2509.02360](https://arxiv.org/abs/2509.02360) (SWE-PRM),
[arXiv:2604.26102](https://arxiv.org/abs/2604.26102) (SWE-Edit),
[arXiv:2601.05777](https://arxiv.org/abs/2601.05777) (EET early termination).

**A caution we keep repeating**: most published "token savings" numbers are
cache-blind. Under cache-tier pricing, a 50–96% token-reduction claim can be
a cost *increase*. Re-derive before believing.

## The legacy plugin

Quartermaster began as a least-privilege tool-governance / enforced-delegation
plugin for Claude Code. That mechanism is **retired as a cost technique**
(ledger row 0), but the code remains in this repo and still works for its
governance value — architecture, install, and caveats in
[docs/legacy-plugin.md](docs/legacy-plugin.md).

## Contributing

See [AGENTS.md](AGENTS.md): the mission rule (*no cost claim the bench hasn't
earned*), development gates (`make verify`), and repo invariants.
