# ADR 0008: Orchestrator has no web I/O

## Status

Accepted

## Context

`templates/orchestrator.md` shipped with `WebFetch`/`WebSearch` in its
`tools:` allowlist. This contradicts the project's own no-I/O principle for
the orchestrator (see ADR 0002): the orchestrator already holds no MCP
tools, on the grounds that any MCP call is I/O and belongs on a cheap tiered
sub-agent instead. Web fetch/search is exactly the same shape of I/O —
network calls that can return large, unbounded raw content directly into the
expensive orchestrator's context — so leaving it out of that principle was an
oversight, not a deliberate exception.

## Decision

Remove `WebFetch`/`WebSearch` from the orchestrator: its `tools:` line in
`templates/orchestrator.md` no longer lists them, and `BUILTIN_TIERS["orchestrator"]`
in `scripts/classify-mcp.py` no longer curates them by default. Web research
is delegated to the `scout` sub-agent (which keeps both tools, alongside
`mechanic` and `builder`), and scout returns a short summary of what it found
rather than raw page or search-result content.

`Read`/`Grep`/`Glob` stay on the orchestrator — they're needed for planning
(reading the codebase to decompose work) and for reviewing sub-agent diffs,
neither of which can be delegated without breaking the orchestrator's own
review step.

## Consequences

Any workflow that needs live web content now costs an extra round-trip: the
orchestrator must dispatch a scout call and wait for its summary instead of
fetching/searching inline. In exchange, the orchestrator's context is
protected from unbounded raw web content the same way it's already protected
from unbounded MCP tool output — consistent with why it holds no MCP tools at
all.
