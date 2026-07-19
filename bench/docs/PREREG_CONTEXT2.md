# Preregistration — context-reduction round 2: cap4k + epoch clearing

Locked before data. Two arms over the same 25-instance subset, control = the
existing opus-solo baseline (per A4: proxy byte-transparency is established
mechanically; trajectory variance is the dominant noise and is absorbed by
the paired n=25 bootstrap).

## Arm 1 — opus-cap4k (dose-response for at-source capping)

F3 showed capping at 16k chars is inert (fires on 2/25 runs). This arm drops
the threshold to **4000 chars (head 2000 + tail 1000 + overflow note)** so
capping engages broadly — the real test of at-source reduction, now with real
quality risk (that's the point of the dose-response).

- Hypothesis: broad capping reduces cost-per-solved without breaking the
  quality bar; alternatively it inflates turns/re-fetches or drops resolve
  rate — either verdict is informative for the dose-response curve.
- Expected engagement: most runs (report per-run capped events; if engagement
  is again <20% of runs, the arm is inert and the at-source lever is dead on
  this scaffold at any reasonable threshold).

## Arm 2 — opus-epoch (tail-targeted fire-once clearing; ORIGINAL_IDEAS idea 2)

Client-side, cache-correct emulation of server-side clear_tool_uses via the
egress proxy: per-run cleared-ids state; a cleared tool_result renders as the
SAME placeholder (with overflow re-fetch pointer) in every later request —
byte-stable between epochs; new ids added ONLY at threshold firings.

Parameters (fixed, from the break-even analysis and our context distribution):
- trigger: request size > **50k est. tokens** (fires on ~p75+ runs only;
  median peak is 38k → most runs never fire, by design)
- keep recent: **5** tool results
- clear_at_least: **60k chars** reclaimed per firing, else skip (amortization
  batch rule)

- Hypothesis: no effect on median runs (never fires — zero risk), material
  cost reduction on tail runs (the spend-dominant subpopulation), quality
  preserved via the re-fetch net.

## Shared metrics & gates (as PREREG_CAPPING.md, plus)

- Primary: paired cost-per-solved vs opus-solo (10k bootstrap, seeded).
- Quality bar: pass-rate diff CI not entirely below zero.
- Cache gate: per-run cc/cr median ≤ 0.15. For opus-epoch additionally:
  cache_creation concentration — spikes must coincide with epoch firings
  (report firings/run; expected 0 on most runs, 1–2 on tail runs).
- Turn gate: median n_turns inflation < +50% vs paired baseline.
- Engagement report: per-run capped events / epoch firings (an arm that
  never engages is inert, not vindicated).
- Tail-subgroup analysis (opus-epoch): paired cost ratio computed separately
  for runs where an epoch actually fired (the treated subpopulation). Note:
  subgroup conditioning on firing is post-treatment; report it as mechanism
  evidence, not the primary endpoint.

## Kill criteria

- (a) cc/cr median > 0.15 in either arm → cache instability; abort arm.
- (b) median turns inflation > +50% → flailing; abort arm.
- (c) resolve CI entirely below baseline → quality broken; record and stop.

## Budget

2 arms × 25 ≈ $36–40 expected. Abort gate at **$55** cumulative for
jobs_context2. No parity arm (established in the capping experiment; A4).
