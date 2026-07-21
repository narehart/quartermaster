# Token-reduction candidates for Quartermaster (research memo)

## v3 synthesis (2026-07-21) — after the full campaign (F1–F5) + 3-scout cache-native sweep

### The field confirms the campaign conclusion

- **"Token Reduction Is Not Cost Reduction" (arXiv:2607.12161, Jul 13 2026,
  verified):** 2,848 Claude Code runs, billing-level. Cache traffic ≈ 87% of
  cost; token-reduction↔cost r=0.15; removing 38% of tool-output tokens
  INCREASED cost +6.8%; compression corrupted edit anchors (27/40→15/40
  patch application). Independently replicates F2/F4/F5 at 40× our scale.
  Lead citation for the campaign writeup. (They lack: preregistration,
  quality-gated cost-per-solved, model-swap findings, the break-even policy.)
- **Pricing is converging on the constraint:** OpenAI GPT-5.6+ now charges
  cache writes at 1.25× (was free), strict-prefix, 30m TTL — the Anthropic
  shape is becoming the industry standard. Non-prefix KV reuse is
  production-real ONLY self-hosted (LMCache/CacheBlend, RedKnot/SGLang,
  MiniPIC/vLLM); no API provider exposes it. Killed techniques stay killed
  at the API layer; falling read prices make turns/output MORE dominant.
- **Still-unoccupied ground:** no published work derives stop/clear/swap
  policies from a tiered cache cost model, and nobody attacks output tokens
  + turns with cache pricing in the objective. Our formula + campaign data
  remain publishable.

### Round-3 slate (turns + output tokens — the binding terms), ranked

1. **EET-style experience-driven early termination** (arXiv:2601.05777,
   verified): −21% API calls, −25% output tokens, −32% avg cost, ≤0.2pp
   resolve loss on SWE-bench Verified. Pure stop-decision — append-nothing,
   cache-perfect. Implementable as a monitor over the stream; our 125+
   scored trajectories are the experience corpus it needs.
2. **AGENTS.md + thinking-budget tuning** (arXiv:2601.20404: −16.6% output
   tokens, −28.6% runtime, completion preserved; 2512.10398: 32k→8k thinking
   ≈ −1.4pp resolve): near-zero implementation cost, pure output-token
   lever. The cheapest arm we could ever run.
3. **Diagnostic front-loading (SHERLOC-style, arXiv:2606.24820):** −23.1%
   total tokens AND +5.95pp resolve — kills the fault-localization half of
   the trajectory. Append-only pre-phase; a cheap model can draft the
   diagnosis.
4. **Course-correction feedback (SWE-PRM, arXiv:2509.02360):** +10.6pp
   resolve, shorter trajectories, ~$0.2/instance. Append-only hook.
5. **Edit-retry-loop elimination (SWE-Edit ingredients, arXiv:2604.26102):**
   +2.1pp AND −17.9% cost — adopt the format-fallback/lint-feedback
   ingredients, NOT the sub-agent delegation (F1 says delegation inflates
   turns).
6. **Batched recon tool-calls on SWE:** literature gap — nobody has the
   number; our rig could produce it.

### Future arms (user-requested, not yet scheduled)

- **context-mode plugin as a live arm** (mksglu/context-mode): we dissected
  it (v2 memo) but never ran it — a bench arm would be the first honest
  cost-per-solved measurement of it anywhere. Implementation note from
  source: its headless passthrough gates on the LAUNCHER setting
  `CLAUDE_CODE_HEADLESS=1` (hooks/formatters/claude-code.mjs) — our harness
  does NOT set it, so routing/denials stay fully ACTIVE in our headless
  runs. Two-sided risk to measure: deny-and-retry turn tax, and its own
  documented headless-brick failure mode (denies with no TTY path forward).
- **LSP-based navigation arm** (per karanbansal.in/blog/claude-code-lsp):
  language-server go-to-definition/references instead of text search — a
  turns-lever sibling of the roust arm. Subset is all-Python, so one
  language server (pylsp/pyright) covers it. Design when scheduled: compare
  against BOTH opus-solo and opus-roust to separate "structured retrieval"
  from "any retrieval upgrade".

### Fleet-level lever (fixed-cost, not per-task; provider-documented)

Anthropic caches are workspace-scoped with free refresh-on-hit and documented
`max_tokens=0` pre-warming. Scheduling bench runs back-to-back within TTL
amortizes the Claude Code system-prompt write across the whole fleet. Worth
doing for the bench itself; not a per-task technique.

### Cache-native context work (for completeness; low priority given F4/F5)

Self-GC (2607.00692: cache-aware commit boundaries + recoverable sidecars —
the correct-by-construction epoch design; production 10–15% input reduction),
CAPC (2607.15516: first published two-tier cache cost model; LongBench-only,
unlikely to survive our re-read-dominated workload), Governance Decay
(2606.22528: compaction erases safety constraints 0%→30% — generalizes F5).

## v2 synthesis (2026-07-20) — after the F2 cache-hostility finding

A second sweep (native Anthropic context management, the context-mode plugin
dissected at source level, a cache-focused arXiv pass) plus our own trajectory
mining (see ORIGINAL_IDEAS.md) converges on one architecture with three
cache-safe component classes:

- **(a) Shrink at creation, then FREEZE** — the transform must be a pure
  function of the observation's content (never its age/position), so every
  request carries identical bytes and the prefix stays cache-stable.
  Evidence: SWE-Pruner (arXiv:2601.16746 — 23–54% reduction on SWE-bench
  Verified with IMPROVED solve rate), CoACT (2607.02911 — 33%, next-action
  invariance as the quality gate), TokenPilot's ingestion pass (2606.17016),
  context-mode's >5KB indexing threshold, our "cap the whales" (top-3
  observations = 71% of tool bytes).
- **(b) Infrequent batched clearing that re-anchors** — threshold-gated,
  fire-once-and-freeze; never per-turn. Evidence: Anthropic's native
  `clear_tool_uses` (invalidates prefix per firing, amortized via
  clear_at_least; +29% quality on their evals), Self-Compacting Agents
  (2606.23525 — semantic when-to-fire rubric), TokenPilot's lifecycle
  eviction (B=3 batching), CWL (2606.11213 — τ≈50k up to 3× cheaper, τ>120k
  waste). Our break-even derivation (ORIGINAL_IDEAS.md) — refined with the
  stable prefix P: clearing D from context S pays iff expected remaining
  turns n* > [1.25·(S−D−P) − 0.1·(S−P)] / (0.1·D). NO published closed-form
  policy exists — our data + this derivation is a publishable note.
- **(c) Externalize with retrieval handles** — full output goes to an
  external store; a frozen preview + deterministic handle stays in context;
  the agent drills in on demand. Quality-safe because nothing is
  unrecoverable. Evidence: context-mode's SQLite FTS5 + ctx_search,
  TokenPilot's artifact registry, Demand Paging (2603.09023 — the
  architectural twin of our egress proxy, 0.03% fault rate).

**The field has independently confirmed F2:** TokenPilot names the "text
sparsity vs prompt cache continuity" trade-off; CWL describes verbatim the
perpetual-cache-write regime we measured at 28×. And the papers our first
sweep ranked highest (Complexity Trap, AgentDiet, Less-Context) are all
cache-HOSTILE with no caching in their cost models — their claimed savings
invert under a cached API, exactly as we measured. Cache accounting is the
difference between literature and truth here.

**context-mode plugin verdict** (mksglu/context-mode, source-verified):
cache-safe by construction (prevention-at-append, never mutates history) —
but publishes only byte-compression numbers (96–98%): no cost-per-solved, no
quality eval, no cache accounting, and an unmeasured deny-and-retry
turn-inflation tax (our F1 mode in miniature). Our bench can produce the
first honest evaluation of this class. Two ideas adopted: the >5KB
overflow-indexing threshold and the isStructurallyBounded allowlist; one
warning adopted: ~60% compliance for instruction-only routing (tempers any
prompt-steering-only arm).

**Next experiment (class a, cheapest, highest yield-to-risk): deterministic
whale-capping via the existing egress proxy** — cap tool_result blocks above
a size threshold with a pure content-hash-keyed transform (head + tail +
overflow note), identical in every request (cache-stable), overflow written
to a sandbox-readable file for re-fetch (quality net). Control = existing
opus-solo. Mechanism gates: cc/cr stays ~0.05; n_turns must not inflate;
re-fetch count reported. See PREREG update.

---

## v1 memo (2026-07-19) — pre-F2; cache-naive rankings below are SUPERSEDED
(The Complexity Trap ranking in particular: its technique is cache-hostile
and was killed by F2. Kept for the record.)

Synthesis of a 4-scout arXiv sweep (2024–2026), filtered through Quartermaster's
pivoted rule: **only ship techniques that PROVABLY reduce token cost on
long-horizon SWE tool-use work WITHOUT hurting resolve rate**, implementable as
prompt/harness orchestration around a black-box Claude API.

## Verification caveat (read first)

Every scout independently flagged that many hits carry **2026-dated arXiv IDs**
(beyond model training) and that LLMs fabricate plausible IDs. **Verify every ID
against the live arXiv listing before citing in-repo.** IDs I can treat as
more likely real (pre-2026 or corroborated): observation masking "The Complexity
Trap" (2508.21433), AgentDiet (2509.23586), Adaptive Reasoning Executor
(2510.13214), Speculative Actions (2510.04371), Plan-and-Act (2503.09572),
Small LLMs Are Weak Tool Learners (2401.07324), BEST-Route (2506.22716),
Early Abstention (2502.09054). Treat all numbers as "claimed, verify."

## The lens: our own cost model

From the SWE-bench Live baseline: **cost ≈ Σ_turns (context_size × rate).**
Three levers, and our data already tested one badly:

- **(A) Fewer turns** — kills the re-read multiplier.
- **(B) Smaller per-turn context** — shrinks the term every turn re-reads.
- **(C) Cheaper rate via routing** — what prewalk attempted and got wrong.

Key result from our run: naive lever-C (prewalk = global opus→sonnet swap at
first edit) **backfired 1.21×** because the weaker executor took more turns
(median 25 vs 19), and turn-inflation swamped the per-token discount. The
literature explains why and points at lever B as the reliable win.

---

## Ranked shortlist — what to A/B on our rig, best first

### 1. Observation masking (tail-only) — lever B — SHIP-AND-TEST FIRST
- "The Complexity Trap" (arXiv:2508.21433, 2025). Rolling-window heuristic:
  replace older tool outputs in-context with short placeholders. No LLM
  compression call.
- **~52.7% cost cut, resolve rate neutral** (54.8% vs 53.8%) on SWE-bench
  Verified, SWE-agent scaffold. A dumb heuristic matched expensive LLM
  summarization.
- Pure prompt/harness. Highest leverage-to-effort ratio in the whole sweep.
- **Cache-safety rule:** mask the TAIL only, keep the stable prefix cached —
  else you invalidate downstream prompt-cache reads and erase the saving.
- Directly attacks the exact driver our data isolated (growing re-read context).

### 2. Trajectory pruning between turns — lever B — SWE-PROVEN ON CLAUDE
- AgentDiet (arXiv:2509.23586, 2025). Cheap reflection model strips
  redundant/expired content from OLDER trajectory steps each turn.
- **−39.9% input tokens, −21–36% cost, resolve maintained (~65%)** on
  SWE-bench Verified **with Claude 4 Sonnet** — the closest-to-our-setup
  measured result in the sweep. Does NOT cut turns (pure context lever);
  stacks orthogonally with #1.
- Black-box; needs a cheap Haiku reflection pass. Slightly more work than #1.

### 3. Cache-aware prompt ordering — lever B multiplier / hygiene
- "Don't Break the Cache" (arXiv:2601.06007, 2026 — verify). Keep stable
  prefix (system prompt, tool defs) cached; volatile content (tool results,
  latest turn) after the cache boundary. **41–80% cost cut, quality-neutral
  by construction.**
- This is a MULTIPLIER under #1/#2 and a warning: it formalizes the same
  model-scoped-cache tax that sank prewalk and that any context mutation
  triggers. First action here is diagnostic: confirm Claude Code's default
  ordering isn't already thrashing cache in our runs (our metrics capture
  cache_read/cache_creation per model, so we can measure it directly).

### 4. Viewer/Editor file scaffolding — lever B + structural — SWE-PROVEN BOTH AXES
- SWE-Edit (arXiv:2604.26102, 2026 — verify). Viewer subagent returns only
  task-relevant snippets (39.7% of requested content); Editor applies NL
  edits. **+2.1 resolve AND −17.9% cost** on SWE-bench Verified (500),
  closed-model compatible.
- Architecturally this is Quartermaster's own delegation model retargeted at
  a cost win — the most natural fit to the existing plugin shape. Bigger
  integration lift than #1–#3.

### 5. Assembled routing: LLM-judge escalation gate + verify-before-commit — lever C — THE PRINCIPLED PREWALK SUCCESSOR
- Diagnosis of our prewalk failure, from **SWE-Router** (2607.00053 — verify)
  and **"Is Escalation Worth It?"** (2605.06350 — verify): route on
  **observed partial-trajectory signal**, not a global up-front swap, and
  **price the cheap turns into the escalation decision**. A pure up-front
  router can beat a run-cheap-then-escalate cascade because the cascade pays
  a fixed "structural cost."
- **Shippable black-box assembly:** (a) **Speculative Actions**
  (arXiv:2510.04371) verify-before-commit — cheap Claude drafts an action,
  strong Claude verifies, commit only on agreement → **quality-lossless by
  construction**, a bad cheap step is discarded not compounded into a
  7×-turn spiral; plus (b) an LLM-judge gate ("given this partial trajectory,
  will cheap Claude finish? else escalate") approximating SWE-Router's value
  head.
- Highest risk/effort; test only after instrumenting turn-accounting. No
  drop-in, black-box, SWE-proven routing win exists — it must be assembled
  and re-benchmarked here.

---

## Lever-A (fewer turns): real but capped on SWE
- Parallel/batched tool calls — W&D (2602.07359 — verify): **~48% fewer
  turns** at equal accuracy, but on **browse/search** (independent subgoals).
  SWE's sequential read→edit→test loop caps this; worth trying only for the
  **recon phase** (batch independent grep/read/ls into one turn). Low effort,
  bounded upside.
- Meta-tools (2601.22037 — verify): compile recurring call-sequences into one
  tool; modest single-digit % on web/GUI, needs trace-mining first.

## Kill-the-losers levers (cost-cap, not per-success savings)
- Early-termination / doomed-episode abort (EET 2601.05777; "Doomed from the
  Start" 2607.06503 — verify): abort unresolvable SWE attempts early. Saves
  budget on FAILURES, not on shortening successes. Highest quality-risk
  (mis-calibrated threshold abandons solvable-but-slow tasks). Useful as a
  harness budget cap, not a core technique.

---

## Strategic read for the pivot

The evidence points somewhere notable: **Quartermaster's original mechanisms
(tool-tier delegation, prewalk model-swap) are NOT where the measured cost wins
are.** The reliable, quality-neutral, SWE-bench-proven, black-box-shippable
family is **per-turn context reduction** (masking, trajectory pruning,
cache-aware ordering, snippet-scoped file reads). That family:
- attacks the exact cost driver our own baseline isolated,
- has multiple independent SWE-bench measurements (incl. one on Claude Sonnet),
- composes (they stack), and
- our harness already captures the cache_read/creation tokens needed to
  evaluate it honestly (the metric naive analyses miss).

Recommended first experiment when the baseline finishes: **tail-only
observation masking on the SWE-bench Live rig**, measured on cost-per-solved
AND cache_read tokens, same preregistered discipline. It's the cheapest to
build and the most likely to clear the "cheaper without quality loss" bar.
