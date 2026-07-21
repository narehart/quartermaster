# Original ideas: cache-safe, quality-safe context reduction

Not from the literature — derived from our own measured failures (F1
turn-inflation, F2 cache-hostile masking) and from mining our 25 opus-solo
trajectories' per-call cache accounting. The empirical grounding is the point:
these numbers are for OUR distribution (SWE-bench Live, Claude Code scaffold),
which no paper measures.

## The data that shapes everything (mined 2026-07-20)

From the 25 opus-solo `agent_run.jsonl` transcripts (per-model-call
`cache_read`/`cache_creation`, per-observation sizes; bytes/4 ≈ tokens):

| fact | value | implication |
|---|---|---|
| peak context | median 38k, p75 51k, max 72k | Anthropic context-editing's default 100k trigger fires on ~ZERO of our runs — native defaults are a no-op here |
| model calls per run | median 30, p75 52, max 145 | tail runs dominate spend (145×50k ≈ 7M read-tok vs median ~750k) |
| tool-output share of peak context | median ~14% | Claude Code's ~30k standing prefix dominates median runs; clearing tool results has a LOW ceiling on the median run |
| top-3 observations' share of tool bytes | **71%** | the compressible mass is a few WHALES, not the long tail of small outputs |

**Break-even for oldest-first clearing (derived, original):** clearing C
tokens from a context of size ctx invalidates the suffix (≈ ctx−C), costing
~1.25×(ctx−C) cache_creation, and saves 0.1×C per remaining call. So it pays
iff remaining calls R > 12.5×(ctx−C)/C. Evaluated on our distribution:

- ctx=60k, clear 20k → needs >25 calls remaining (median run has 30 TOTAL)
- ctx=60k, clear 30k → needs >12 remaining
- ctx=100k, clear 60k → needs >8 remaining

**Consequence:** aggressive early clearing can never pay on median runs.
Context policies should be TAIL-TARGETED: do nothing (zero risk, zero cost)
until a run crosses a threshold that only long runs cross, then intervene
once, hard, with a batch big enough to amortize.

---

## Idea 1 — "Cap the whales": at-source size-capping of only the largest observations

Top-3 observations hold 71% of tool-output bytes. So don't reduce *all* tool
outputs (quality risk everywhere, small yield each) — cap only outputs above a
threshold (e.g. >4k tokens) at the moment they FIRST enter context, appending
a deterministic re-fetch instruction:

```
[output capped at 4000 tokens of 31200; full output saved — re-run the tool
 or read /tmp/qm-obs-<hash>.txt for the remainder]
```

- **Cache-safe by construction**: the capped form is frozen at creation and
  never mutated; the prefix stays byte-stable.
- **Quality-safe by design**: nothing is unrecoverable — the agent can
  re-fetch; and only a handful of observations per run are ever touched, so
  the blast radius (and the F1-style re-explore/turn-inflation risk) is
  bounded and measurable (count re-fetches as a mechanism metric).
- **Implementable in the sandbox** (wrap the tools / a shell shim), keeping
  the egress proxy out of the content path entirely.
- Predicted yield from the concentration data: most of the 14% tool-output
  mass on median runs, more on tail runs where whales recur — modest but
  near-zero-risk. The A/B measures whether re-fetches eat the saving.

## Idea 2 — Tail-targeted epoch clearing (fire-once, tuned by our break-even)

The cache-correct version of what F2's sliding mask got wrong, tuned by data:

- **Trigger** at ~50k input tokens (fires only on p75+ runs — the tail that
  both needs it and can amortize it), not Anthropic's 100k default (never
  fires here) and not per-turn (F2's fatal flaw).
- **Clear in one large batch** (clear_at_least ≈ half the clearable mass) so
  one cache re-write is amortized over the many remaining calls a tail run
  still has (by the break-even: at 60k clearing 30k needs only >12 remaining;
  tail runs have 20–100+).
- **Freeze between epochs**: the boundary only advances at firings; between
  firings the prefix is byte-stable and caches warm.

Two interchangeable implementations, same policy: (a) inject Anthropic's
server-side `context_management`/`clear_tool_uses` via our egress proxy with
these tuned params; (b) client-side epoch masking in the proxy we already
built (mask once at the epoch, never touch the region again). (a) is
sanctioned and simpler if the beta accepts Claude Code's request shape; (b)
is our fallback that works today. The A/B metric that proves cache-correctness
either way: cache_creation spikes ONLY at epoch firings, ~0.05 cc/cr ratio
between them.

## Idea 3 — Late-binding reads: steer WHEN large context enters, not whether

A token entering at call t is re-read (T−t) more times: the same 10k-token
file read costs ~12× more (in read-tokens) at call 5 than at call 55 of a
60-call run. So the cheapest "reduction" is ordering: recon narrowly first
(grep/snippet), pull full files only immediately before editing them.

- Implementation: a STABLE system-prompt addendum (constant text → sits in
  the cached prefix → cache-safe): "read the minimum needed to locate the
  fix; expand to full files only for the file you are about to edit."
- Zero mutation, zero information loss — it changes acquisition order, not
  availability.
- Risk: could increase turns (more, smaller reads) — the F1 lesson says turn
  count is the other cost driver, so the A/B must watch n_turns; the bet is a
  few extra cheap-early turns beat many expensive re-reads of an early whale.

## Idea 4 — Standing-prefix slimming (the median run's actual mass)

On median runs the dominant context is Claude Code's own ~30k standing prefix
(system prompt + tool definitions), not tool outputs. A proxy that
deterministically strips tool definitions provably unused on this task
distribution (e.g. notebook/web tools on SWE tasks) from request #1 onward
shrinks the prefix itself — cache-safe because it's consistent from the first
call. Modest yield (prefix is mostly 0.1× cache_read), but it also shrinks
every cache_creation, costs nothing at runtime, and has zero content-loss.
Quality caveat: removing a tool changes behavior if the agent would have used
it — start with tools with 0 uses across all 75 baseline transcripts.

## Idea 5 — The context-cost meter (make the agent price-aware)

Append (at the volatile TAIL, never the prefix) a one-line running meter:
"context: 54k tokens; each further 10k adds ~$X over this run's remaining
turns." Hypothesis: an agent that sees the price reads less junk voluntarily —
the behavioral complement to hard caps, with no information ever withheld.
Cheap to test; the risk is it does nothing (then drop it).

---

## Recommended sequencing (each gated by the bench, per the pivot rule)

1. **Idea 1 (cap the whales)** — highest yield-to-risk, purely at-source,
   validates the re-fetch safety-net mechanic that everything else can reuse.
2. **Idea 2 (tail-targeted epoch clearing)** — attacks the tail runs where
   the money is; our break-even math sets the params a priori instead of
   guessing.
3. **Idea 3 (late-binding reads)** — free to implement; run as a rider arm.
4. Ideas 4–5 as cheap add-ons once 1–2 have verdicts.

All four candidate arms share the mechanism metrics from PREREG_MASKING.md:
cache_read must drop (or prefix must shrink), cache_creation must NOT balloon
except at declared epoch firings, n_turns must not inflate (F1), resolve rate
CI must not sit below baseline.
