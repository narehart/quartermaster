# Token-reduction candidates for Quartermaster (research memo)

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
