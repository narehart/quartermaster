# SWE-bench Live baseline — running analysis log

Preregistration: `PREREG_SWEBENCH_LIVE.md` (locked at commit 27b619c, before
data). This log records results and every anomaly + its resolution, per the
"treat each suspicious result as a bug until proven" discipline.

## Status

- **opus-solo arm: COMPLETE.** 25/25 runs healthy (swap not applicable; model
  pins clean). **8/25 resolved = 32% pass rate.** cost_per_solved $2.35.
- **prewalk-sonnet arm: COMPLETE.** 25/25 healthy, 25/25 swaps fired, 0 real
  drift. **7/25 resolved = 28%.** cost_per_solved $3.25.
  - Paired vs opus-solo (n=25, bootstrap): pass-rate diff −4% CI [−12%, 0%]
    → **quality bar PASS** (not statistically below). cost_per_solved ratio
    median **1.35×** CI **[0.97, 2.42]** → **NOT cheaper; trends ~35% more
    expensive per solve.** Verdict: preserves quality, fails the cost
    criterion on this distribution. Driver = executor turn-inflation (F1).
- **prewalk-haiku arm: COMPLETE.** 25/25 healthy, 25/25 swaps fired, 0 real
  drift. **6/25 resolved = 24%.** cost_per_solved $2.04; total $12.22.
  - Paired vs opus-solo (n=25): pass-rate diff −8% CI [−20%, 0%] → quality
    bar PASS (but CI upper touches 0; lost 2 of opus's 8 solves, gained 0).
    cost_per_solved ratio median **0.86×** CI **[0.60, 1.62]** (includes 1);
    total-cost ratio **0.65×**, cheaper on 17/25. **Directionally cheaper,
    but at a real quality cost, and neither CI is conclusive at n=25.**
  - Median turns opus 18 / haiku **19** — haiku did NOT turn-inflate (unlike
    sonnet's 25). Prediction "haiku ≥ sonnet cost" was WRONG.

### Verdict on prewalk for real-repo SWE (directional, underpowered)

The driver is **per-token discount ÷ turn-inflation**:
- **prewalk-sonnet** — only ~3–5× per-token discount; turn-inflation
  (25 vs 19) overcomes it → **1.35× MORE expensive**, quality ~flat.
  Worst of both. Fails the pivot's cost bar outright.
- **prewalk-haiku** — ~10–15× per-token discount, no turn-inflation → real
  **35% total cost cut**, but capability drop costs 2 solves (32%→24%). A
  genuine cost↔quality TRADE, not a free lunch; quality bar passes only
  marginally.

**Neither variant clears "cheaper WITHOUT compromising quality" on this
distribution.** Terminal-Bench's clean 40.9% prewalk saving does NOT
generalize to real-repo dev work. This is a decisive-direction (but n=25
underpowered) negative for prewalk under the pivot rule, and motivates
pursuing context-reduction techniques (see TOKEN_REDUCTION_CANDIDATES.md)
instead, which the literature reports as quality-NEUTRAL cost wins.

Caveat: cost-per-solved denominators are tiny (8/7/6 solves), all CIs wide.
DIRECTIONAL, not certifying. A powered run (larger n or healthier-resolve
subset) is required before any published claim.

### (superseded) earlier in-progress note

### Underpowered — directional read only

opus-solo's 32% pass trips preregistered kill-flag (c) (baseline pass rate
< ~40%). This subset (25 fresh Sep–Aug 2025 SWE-bench Live instances) is
hard; ~32% one-shot opus is itself evidence of contamination-resistance
(vs ~70% on the memorized/deprecated Verified split). But it makes the
cost-per-solved denominators small (~8 solved for opus-solo), so the
bootstrap quality-bar test on n=25×1 is **underpowered**. This run is a
DIRECTIONAL read; a powered confirmation (larger n or a healthier-resolve
subset) is required before any certifying claim.

## Anomaly log

### A1 — Background Haiku in "opus-solo" runs (RESOLVED: not a bug)

**Observation.** Every opus-solo run shows some `claude-haiku-4-5-20251001`
tokens despite opus-solo launching `claude -p --model claude-opus-4-8` with
no swap. One run, `sissbruecker__linkding-1175`, is a wild outlier: **51.4%**
of its token volume is Haiku (Haiku 2.29M tok vs opus 2.16M; Haiku
$0.41 of $2.32 total). The other 24 runs: 0.1–3.1% Haiku share.

**Diagnosis.** The Haiku usage is Claude Code's own automatic background
work (context compaction / summarization), NOT tool execution:
- linkding-1175 Haiku did **15.7K output** tokens against **2.18M
  cache_read** — the signature of repeatedly re-reading a large cached
  context to emit tiny summaries, not producing edits/tool calls.
- It was the **longest trajectory (111 turns)**; background-Haiku volume
  scales with trajectory length and context size, which is why one very
  long run ballooned to 51% while typical runs sit under 3%.

**Why it's not a harness bug and doesn't invalidate the baseline.**
- `true_cost_usd` sums actual per-model spend, so this Haiku is counted as
  the real cost it was. Cost-per-solved uses actual spend — honest.
- If anything it biases **conservatively** for the prewalk hypothesis: the
  opus-solo baseline is slightly *cheaper* than a hypothetical
  no-background-Haiku opus would be, shrinking (not inflating) any measured
  prewalk saving.

**Consequences carried into the analysis.**
1. The same background-Haiku mechanism runs in ALL arms, so prewalk's
   marginal opus→sonnet benefit on long runs is partly pre-empted (a chunk
   of long-run cost is already cheap Haiku). Interpretation caveat.
2. **Must report per-arm background-Haiku share** to rule out a systematic
   trajectory-length confound between arms (e.g. if opus-solo triggers more
   compaction than prewalk, it gets more "discount," biasing the comparison).
3. The model-pin `drift` flag fires on this background Haiku for
   prewalk-sonnet (expected=[opus, sonnet]). Handled: `validate_arm.py`
   classifies drift as benign iff every drift entry is the known
   `claude-haiku-4-5*` housekeeping model and `all_expected_matched` is
   True (both work-loop pins present), verified against `model_sequence`.

### F1 — INTERIM (n=10): prewalk-sonnet not showing savings, trending costlier

**Not a conclusion — wildly underpowered, recorded for the full-run read.**

At 10/25 prewalk-sonnet runs (all healthy, 10/10 swap fired, 0 real drift):

| arm | $/run | cost_per_solved | pass_rate |
|---|---|---|---|
| opus-solo (n=25) | $0.75 | $2.35 | 32% (8/25) |
| prewalk-sonnet (n=10) | $1.17 | $3.89 | 30% (3/10) |

Paired (n=10) cost_per_solved ratio arm/baseline: median **1.74×**, 95%CI
**[0.93, 5.08]** — spans "slightly cheaper" to "5× worse". Pass-rate diff
CI [-30%, 0%] → quality bar PASS.

**Mechanism — RESOLVED by paired same-instance data (n=17):** the driver is
**executor turn-inflation**, NOT caching.

- **Cold-cache hypothesis REFUTED.** For every prewalk-sonnet run the
  executor's `cache_creation / cache_read` ratio is **0.01–0.12** — the
  swap's one cold write is 1–12% of what sonnet then reads warm. Prewalk
  *does* avoid the cache hit, as designed. My earlier "cold-cache penalty
  is primary" call was wrong.
- **Real driver: the cheaper executor takes MORE turns**, and each extra
  turn re-reads the whole accumulated context as `cache_read`, so token
  volume (hence cost) scales with turn count. Median turns opus **19** →
  prewalk **25**. Per-instance the correlation is tight and monotone:
  where sonnet's turn count ≈ opus's, prewalk is cheaper (0.55–0.73×);
  where sonnet flails to 2–7× the turns, prewalk is 1.7–2.9× costlier
  (pex-2888 6→43T=2.92×, openai-1601 48→112T=2.02×, dspy-8718 3→11T=1.95×).
  The lower per-token rate is overwhelmed by higher token volume.
- **Paired totals (n=17):** prewalk **1.21×** opus cost, cheaper on only
  **6/17** instances. Quality roughly held: opus 6/17 resolved, prewalk
  5/17 (lost openai-1601 — sonnet burned 112 turns and still failed what
  opus solved in 48).
- **Background-Haiku confound (A1)** is a secondary flatterer of the
  baseline (prewalk 0% vs opus-solo mean 2.7%), but small next to the
  turn-inflation effect.

**Implication for the pivot.** Terminal-Bench (small contexts, executor
finishes in few turns) showed 40.9% savings *because* the executor was
turn-efficient there. On real-repo SWE work the executor is less
turn-efficient, and turn-inflation erases the per-token discount. Under the
pivoted "only ship what reduces token cost without hurting quality" rule,
prewalk-sonnet is **not** currently earning its place on this distribution.
prewalk-haiku (even cheaper executor, but likely even less turn-efficient)
is the next test — cheaper per token but probably more turns still.

### A3 — prewalk-haiku executor pin: alias vs dated snapshot (RESOLVED: benign)

**Observation.** prewalk-haiku runs tripped the validator's
`WORKLOOP_PIN_MISSING` check: expected executor `claude-haiku-4-5` (the
undated alias in `metrics.EXECUTOR_MODEL_HAIKU`) vs observed
`claude-haiku-4-5-20251001` (the dated snapshot the alias resolves to).
`verify_model_pins` uses exact-string equality, so they didn't match —
unlike the planner (`claude-opus-4-8`) and sonnet executor
(`claude-sonnet-5`), whose observed ids carry no date suffix.

**Diagnosis: substantively fine.** swap_fired=True, model_sequence shows the
clean prewalk pattern (contiguous opus block → haiku block, not interspersed
background housekeeping), and metrics priced the *observed dated* model. The
exact cheap snapshot did the work; only the EXPECTED constant string was the
undated alias. `analyze_baseline.py`'s real-drift check already prefix-matches
`claude-haiku-4-5*` as benign, so the final numbers were never affected —
only the interim health-checker mis-flagged it.

**Fix applied.** `validate_arm.py` now matches date-tolerantly: observed `o`
satisfies expected `e` iff `o == e` or `o.startswith(e + "-")` (a dated
snapshot of the expected family), while still flagging genuinely different
models as real drift. All 3 arms read healthy after the fix.

**For a certifying run:** set `EXECUTOR_MODEL_HAIKU` to the exact dated id
`claude-haiku-4-5-20251001` so the launch flag and the pin expectation are
both the exact snapshot (honoring the "exact IDs, no floating aliases" rule
literally). NOT changed mid-arm here — the alias resolved to the same dated
model across all runs, so the data is consistent; editing the running
runner's source would risk the in-flight arm.

### F2 — Sliding-window observation masking is cache-hostile (n=1, mechanism confirmed)

**Setup.** Tail-only observation masking applied to the real agent CLI via a
host egress proxy on ANTHROPIC_BASE_URL (`bench/masking/mask_proxy.py`):
replace all but the most-recent N=3 `tool_result` blocks with a placeholder.
Validated the mechanism end-to-end (proxy honored, masking fires, pins clean).

**Result (ipython-14969, opus-masked vs opus-solo on the same instance):**
| | opus-solo | opus-masked (keep_n=3) |
|---|---|---|
| turns | 6 | 34 |
| true cost | ~$0.13 | **$3.63 (~28×)** |
| cache_creation/cache_read | ~0.05 | **0.39** |
| resolved | (baseline) | False |

**Mechanism (confirmed per-turn, not sampling noise):** cache_creation stays
high across the run — 37 of 52 model calls > 10k cache_creation. A SLIDING
mask window flips a different observation from full→masked EVERY turn, mutating
the already-cached prefix, so the whole suffix re-creates at cache_creation
(1.25–2×) turn after turn. Masking cuts token COUNT but converts the cheapest
tokens (warm cache_read, 0.1×) into the most expensive (cold cache_creation).
Plus turn-inflation (6→34) from the agent losing observations and re-exploring.

**Conclusion.** Any technique that MUTATES already-sent (cached) content is
disqualified on a prompt-cached agent. The paper's "~52% cut" (The Complexity
Trap, measured WITHOUT prompt caching) does not survive contact with caching.
This is the SECOND technique the cache-aware cost-per-solved discipline has
killed (after prewalk's turn-inflation) — strong validation of the bench.
n=1, but the cache mechanism is a structural certainty; the 28× magnitude and
turn-inflation are n=1 and would need confirmation IF pursued (they are not:
the mutation-of-cached-content flaw is fatal regardless of magnitude).

**Next:** cache-SAFE + quality-SAFE tool-output reduction (native context
management / at-source frozen reduction / reference-and-refetch) — see the
research sweep feeding `TOKEN_REDUCTION_CANDIDATES.md`.

### F3 — Whale-capping at 16k chars: safe but INERT on this distribution (n=25)

Full run (25 capped + 3 parity, 0 errors, $24.96). All mechanism gates PASSED:
cc/cr median 0.036 (no F2 cache pathology — the pure content-keyed transform
is cache-stable at scale), median turns 18 vs 18 (no F1 re-fetch flailing),
quality preserved (7/25 vs 8/25, CI [−12%, 0%]). The E2E probe also proved
the quality net works (agent recovered mid-file content the cap removed).

**But capping fired on only 2/25 runs (59 events).** At the preregistered
16k-char threshold, >16k observations are too rare on this scaffold — 23/25
runs were byte-identical to control. The formal cost read (cost/solved ratio
1.32, CI [1.01, 2.08]) is noise-dominated, not causal: untouched runs also
trended pricier (A4 same-day trajectory variance; whale-run 1633's $1.93
matches its no-cap passthru twin's $2.00). Verdict: **no measurable cost
effect — the technique as parameterized is inert here**, consistent with our
mining (tool output ≈14% of median context; the mass is the standing prefix
and the conversation, and per-observation sizes mostly sit under 16k chars).

**Options forward:** (i) threshold sweep at ~4k chars — engages broadly,
real reduction mass, real quality risk (the actual test of at-source capping;
~$18, config-only change on the resume-safe driver); (ii) pivot to the
(b)-class tail-targeted epoch clearing (ORIGINAL_IDEAS idea 2) — attacks the
conversation mass on tail runs where the break-even math says the money is;
(iii) prefix slimming (idea 4) for the median-run mass. The bench has now
cheaply killed/nulled three techniques (prewalk, sliding-mask, 16k-cap) —
the discipline is working.

### F4 — cap4k: fully engaged at-source capping still does not reduce cost (n=25)

Dose-response arm (4k-char threshold): engagement fixed — 19/25 runs, 1,882
cap events. All safety gates PASS (cc/cr 0.026; turns 16 vs 18; quality
7/25 vs 8/25, CI [−16%, +8%]). Cost: total 1.38×, cost/solved ratio median
**1.59** CI [0.89, 3.01] — NOT cheaper despite heavy engagement and zero
mechanism pathology.

**This confirms the caching-collapse arithmetic:** capped tokens are mostly
0.1×-rate cache_reads plus a one-time 1.25× write — removing a 5k-token whale
from a 30-turn run saves ~2% of run cost. At-source context reduction is
economically inert on a prompt-cached agent, at any threshold.

### F5 — epoch clearing: fires rarely (by design) and HURTS when it fires (n=25, treated n=2)

Tail-targeted clearing (trigger 50k tok, keep 5, clear_at_least 60k chars):
fired on 2/25 runs, as the distribution predicted. Arm overall: 5/25 resolved
vs 8/25 (CI [−24%, 0%] — formally passes, but the worst quality point
estimate of the campaign); cost/solved ratio median **1.99** CI [1.16, 4.98].

**The treated runs are the signal.** Both runs where an epoch fired blew up:
- a2a-python-443: **71 turns vs 28** baseline, $2.74 vs $1.09
- SDV-2658: 58 vs 47 turns, $3.61 vs $1.70, **and lost the baseline's solve**

n=2, but 2.5× turn-inflation is far beyond the same-day variance envelope.
Mechanism: clearing dropped observations the agent still needed; it
re-explored (F1 signature) and in one case failed a task the baseline solved.
The re-fetch quality net did not compensate. Anthropic's "+29% with context
editing" (their own agentic evals) did NOT transfer to this coding workload.
(Reporting note: the per-run "cleared events" counter sums cumulative
per-request totals — an artifact; distinct cleared ids are lower. Verdicts
rest on cost/turns/resolve, not this counter.)

### CAMPAIGN CONCLUSION (rounds 0–2, five techniques, n=25 each, directional)

| technique | class | cost/solved vs opus-solo | quality | mechanism |
|---|---|---|---|---|
| prewalk-sonnet | model swap | 1.35× [0.97,2.42] | ~flat | executor turn-inflation |
| prewalk-haiku | model swap | 0.86× [0.60,1.62] | −8% (lost 2 solves) | discount > inflation, capability pays |
| sliding-mask | context (per-turn) | ~28× (killed at smoke) | — | perpetual cache_creation (F2) |
| whale-cap 16k | context (at-source) | inert (fired 2/25) | preserved | whales too rare |
| cap4k | context (at-source) | 1.59× [0.89,3.01] | preserved | caching-collapse: capped tokens were cheap |
| epoch clearing | context (batched clear) | 1.99× [1.16,4.98] | worst point est. | treated runs flailed (2.5× turns, lost solve) |

**On a prompt-cached, API-priced coding agent, context-size reduction does
not reduce cost-per-solved.** Prompt caching already collapsed the context
term (re-reads at 0.1×); what remains binding is TURNS (each re-reads
everything and emits full-price output tokens) and OUTPUT tokens (5× input,
never discounted). Every context technique either did nothing (cheap tokens
removed), paid a cache-invalidation tax (F2), or destabilized the agent into
extra turns (F5) — and extra turns cost more than context ever saved.
The cache-blind literature (52–96% "savings" claims) does not survive
cache-priced, quality-gated measurement on fresh SWE tasks.

**Implication for round 3:** attack turns and output tokens directly —
early-stopping of doomed trajectories, recon batching (parallel tool calls),
anti-re-exploration scaffolding — measured on this same rig.

### F6 — Simple early-termination rules screened out by corpus mining (no spend)

Mined all 103 healthy opus-scaffold runs (baseline + rounds 1–2) for
EET-style stop-rule features before building the round-3 early-termination
arm. Result: **no simple feature discriminates doomed from slow-but-solvable
runs on this distribution.**
- turns>40 → 29% resolve (≥ the 27% base rate); turns>50 → 1/7 (n too small)
- "no first edit by turn N" → 22–26% resolve for all N in {15,20,25,30} ≈ base
- an abort@40 policy would kill ~4 of 28 total solves to save ~8% of spend —
  a guaranteed quality-bar failure.
EET's published −32%/−0.2pp (arXiv:2601.05777) evidently requires richer
experience features than turn/edit-timing. The simple-rule arm was screened
out WITHOUT spending its ~$20 budget. Revisit only with a materially richer
feature set (e.g. error-loop/repeat-command signatures).

### A4 — Capping-experiment parity criterion (c) fired as-written; judged mis-specified

PREREG_CAPPING.md kill-criterion (c) said: parity arm within 10% of paired
baseline per-run tokens, else escalate to a fresh full control. The n=3
passthru runs came in at 2.44×, 0.58×, 2.00× tokens — formally a trip.

**Root-cause: trajectory stochasticity, not proxy overhead.** Token deltas
track turn deltas exactly (27→42, 35→16, 14→17 turns); the proxy altered
ZERO bytes (0 transform events; byte-identical forwarding verified at the
plumbing level), so it cannot shift the trajectory distribution. Same-instance
independent re-runs vary ~2× in turns across ALL our data (e.g. 6→34), so a
±10% n=3 token-parity test was never passable and was mis-designed.

**Decision (recorded before capped-arm results were known):** proceed without
the $18 fresh control. The criterion's intent — "does the proxy itself add
tokens?" — is answered mechanically (byte-identical requests) more strongly
than an n=3 statistical test could. Consequence for analysis: within-instance
run-to-run variance is LARGE; the paired n=25 bootstrap absorbs it as noise,
and the final writeup must report it as the dominant uncertainty. A fresh
n=25 unmasked control remains available (resume-safe driver) if the capped
arm's result is borderline.

### A2 — validator `resolved` field (RESOLVED: fixed)

`validate_arm.py` initially read `eval.resolved`; the SWE-bench verdict
actually nests at `eval.report.resolved` (or `eval.report.<iid>.resolved`).
Fixed; opus-solo now reads 8 resolved / 17 not = 32%.
