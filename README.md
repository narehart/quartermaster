# Quartermaster

**An evidence-gated search for techniques that reduce token cost on
long-horizon agentic software-engineering work — without sacrificing quality.**

One rule governs the project: a technique ships only if the preregistered
benchmark in [`bench/`](bench/) shows it **reduces cost-per-solved without a
statistically significant drop in resolve rate**, under real cache-tier
pricing. Nothing is grandfathered — including this project's own original
mechanism, which is how it earned its first row in the ledger below.

## The instrument

[`bench/`](bench/) runs **SWE-bench Live** (fresh, contamination-resistant
GitHub issues) through real Claude Code in per-task Docker sandboxes, with:
exact model pins verified per run, per-model cache-tier token accounting
(`cache_read` 0.1×, `cache_creation` 1.25×), paired-bootstrap analysis on
**cost-per-solved** (never raw token counts), preregistered kill criteria,
and a public anomaly log. See [bench/README.md](bench/README.md).

## Experiment ledger

| # | technique | class | verdict | why |
|---|---|---|---|---|
| 0 | **Tool-tier delegation** (the original Quartermaster plugin: orchestrator/scout/mechanic/builder) | governance / model routing | ❌ **rejected** | Cost-neutral at Sonnet, **1.39×** at Opus: delegation overhead ~doubles token volume. Governance value real; cost value absent. [Result](docs/benchmarks/2026-07-cost-ab.md) · [legacy docs](docs/legacy-plugin.md) |
| 1 | **prewalk-sonnet** (Opus plans → swap to Sonnet executor at first edit) | model swap | ❌ rejected | **1.35×** cost/solved: the cheaper executor takes more turns (19→25 median) and turn-inflation eats the per-token discount |
| 2 | **prewalk-haiku** (same, Haiku executor) | model swap | ❌ rejected | 0.86× cost but **−8% quality** (lost 2 of 8 solves): a cost↔quality trade, not a win |
| 3 | **Sliding-window observation masking** (keep last N tool results) | context, per-turn | ❌ **killed at smoke** | **~28× cost**: mutating cached history every turn forces perpetual cache re-writes (cc/cr 0.39 vs 0.05). The literature's ~52% claim is cache-blind |
| 4 | **Whale-capping @16k chars** (cap huge tool outputs at source, frozen, re-fetchable) | context, at-source | ⚪ inert | Fired on 2/25 runs — >16k observations too rare on this distribution |
| 5 | **Whale-capping @4k chars** (dose-response) | context, at-source | ❌ rejected | Fully engaged (19/25 runs, 1,882 caps), mechanically clean — and still **1.59×**: capped tokens were 0.1×-rate cache reads; there was nothing to save |
| 6 | **Epoch clearing** (batched, threshold-gated, cache-correct clearing of old observations) | context, batched | ❌ rejected | **1.99×** and the worst quality point-estimate: both treated runs flailed (2.5× turns, one lost solve). Anthropic's context-editing quality claims did not transfer |
| 7 | **Simple early termination** (abort long/edit-less runs) | turns | ⚪ **screened out, $0 spent** | Corpus mining (103 runs): long runs resolve at ≥ base rate here — an abort rule kills ~4 of 28 solves for ~8% savings. Guaranteed quality failure |
| 8 | **Output tuning** (efficiency repo-instructions + thinking-budget cap) | output tokens | 🔄 **in evaluation** | First arm aimed at a full-price cost term. Interim (n=6 paired): output tokens 0.56×, cost 0.67×, cheaper on every instance — quality bar pending full n=25 |

## What the campaign established

**On a prompt-cached, API-priced coding agent, context-size reduction does not
reduce cost-per-solved.** Cache reads at 0.1× have already collapsed the
context term; the binding cost terms are **turn count** and **output tokens**
(full price, never discounted). Every context technique tested either removed
already-cheap tokens, paid a cache-invalidation tax, or destabilized the agent
into extra turns — and extra turns cost more than context ever saved.

Independently replicated at 40× scale within days of our campaign:
["Token Reduction Is Not Cost Reduction" (arXiv:2607.12161)](https://arxiv.org/abs/2607.12161)
— prompt-cache traffic ≈87% of billed cost; token-reduction↔cost correlation
r=0.15. The cache-blind literature's 50–96% "savings" claims do not survive
cache-priced, quality-gated measurement.

Full findings (F1–F6), mechanisms, anomaly log, and the clearing break-even
derivation: [bench/docs/SWEBENCH_LIVE_ANALYSIS.md](bench/docs/SWEBENCH_LIVE_ANALYSIS.md).

## Upcoming experiments

From the ranked pipeline
([bench/docs/TOKEN_REDUCTION_CANDIDATES.md](bench/docs/TOKEN_REDUCTION_CANDIDATES.md),
v3 — all aimed at the binding terms, all cache-safe by construction):

| candidate | lever | published claim to test |
|---|---|---|
| Diagnostic front-loading (SHERLOC-style) | turns | −23% tokens **and** +6pp resolve |
| Course-correction feedback (SWE-PRM-style) | turns | +10.6pp resolve, shorter trajectories |
| Edit-retry-loop elimination (SWE-Edit ingredients) | turns | +2.1pp resolve, −17.9% cost |
| Batched recon tool-calls on SWE | turns | unmeasured in the literature — our rig can produce the number |
| Rich-feature early termination | turns | only if features beat the F6 screen |

All results to date are **directional** (n=25, small solve-denominators); any
technique that passes gets a powered confirmation before being declared shipped.

## The legacy plugin

Quartermaster began as a least-privilege tool-governance / enforced-delegation
plugin for Claude Code. That mechanism is **retired as a cost technique**
(ledger row 0) but the code remains in this repo and still works for its
governance value — see [docs/legacy-plugin.md](docs/legacy-plugin.md) for the
architecture, install, and caveats.

## Contributing

See [AGENTS.md](AGENTS.md) — the mission rule ("no cost claim the bench hasn't
earned"), development gates (`make verify`), and repo invariants.
