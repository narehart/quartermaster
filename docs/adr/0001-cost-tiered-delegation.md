# ADR 0001: Cost-tiered delegation (orchestrator / scout / mechanic / builder)

## Status

Accepted

## Context

A single Claude Code session that both plans and implements accumulates
mechanical implementation tokens in the same context that holds the original
intent. As that context fills, the model's attention drifts toward recent
low-value detail (diffs, command output, edit mechanics) and away from
judgment — and every one of those tokens is billed at whatever model is
driving the session, even when the work itself (a rename, a lookup, a
scripted command) doesn't need a frontier model at all.

## Decision

Split the work by shape onto four tiers, each running as a Claude Code agent:

- **orchestrator** (main thread, session model) — plans, decomposes, reviews,
  synthesizes. Never implements.
- **scout** (Haiku) — read-only recon: lookups, searches, "where/how is X".
- **mechanic** (Haiku) — shell + mechanical, fully-specified edits.
- **builder** (Sonnet) — well-specified implementation, test suites,
  diagnosed bug fixes.

Execution always runs on the cheapest tier that can do it reliably;
judgment, ambiguity, and synthesis stay on the orchestrator. `templates/*.md`
define each agent's tools and prompt; `scripts/enforce-agent-model.py` pins
each tier to its model via a PreToolUse hook on every `Agent`/`Task` spawn, so
a frontmatter regression or an unpinned spawn can't silently run a cheap-tier
agent at the expensive session model.

## Consequences

Trivial tasks get slower (everything routes through a sub-agent spawn), which
is the accepted tradeoff for the orchestrator never over-working. Any task
that needs an edit, a shell command, or an MCP call must be decomposed into a
self-contained brief for a sub-agent rather than done inline — see ADR 0002
for how that's enforced structurally rather than by policy alone.

**On the cost claim specifically:** a preregistered A/B benchmark
([docs/benchmarks/2026-07-cost-ab.md](../benchmarks/2026-07-cost-ab.md))
confirms the mechanism this ADR describes — moving execution tokens off the
expensive main-thread model — cuts opus-thread token share by 82.7% pooled
when the main thread runs opus. It does NOT confirm a net per-task cost
saving: cost-per-solved was statistically null at a sonnet main thread and
1.39x *higher* for Quartermaster (95% CI [1.06x, 1.84x]) at an opus main
thread, because delegation overhead (extra round-trips, re-transmitted
context per sub-agent call) roughly doubled total token volume in both
one-shot, cold-start experiments — enough to outweigh the per-token price
cut on tokens that did move to a cheaper tier. Both experiments also ran
~1.3x–1.9x slower (median exec) than stock. Read the linked benchmark before
citing this ADR as evidence that tiering reduces overall spend; what it
reliably buys is governance (ADR 0002) and expensive-model token-share
reduction, not a demonstrated net cost reduction — and long interactive-session
economics (cross-turn caching) remain untested.
