# ADR 0006: Unified tool policy — any tool, any agent

## Status

Accepted

## Context

ADR 0003 gave MCP tools a policy (`mcp-policy.json`'s `servers`/`tools`/
`tiers` keys), and ADR 0005 added a second, separate `builtins` key for
built-in tools. Both accepted only a tier keyword (`read`/`write`/`skip`) as
an override value, and `assign()`'s output was hardcoded to just `{"scout":
[...], "mechanic": [...]}` — there was no way to route an MCP tool, an MCP
server, or a built-in tool to `orchestrator` or `builder` via policy at all,
even though `classify_builtins()` already supported those agents for
built-ins specifically. Two separate override keys for what is conceptually
the same problem (which agent should hold this tool?) was also just harder to
document and reason about than one.

## Decision

The policy file is renamed `mcp-policy.json` -> `tools.json` (`POLICY` in
`scripts/classify-mcp.py`), with the old filename read as a fallback in
`load_policy()` when the new one isn't present, so existing overrides keep
working with no manual migration step.

A single helper, `resolve_override(value, policy)`, interprets an override
value the same way everywhere it appears — in `policy["tools"]`,
`policy["servers"]`, or `policy["builtins"]`, for an MCP tool name, an MCP
server name, or a built-in tool name alike:

1. If `value` is a key in `policy["tiers"]` (default `{"read": "scout",
   "write": "mechanic"}`), resolve through that tier map.
2. Else if `value` is a literal agent name (`orchestrator`, `scout`,
   `mechanic`, `builder`), target that agent directly.
3. Else if `value == "skip"`, drop the tool entirely.
4. Else report unmatched, so the caller falls through to its own
   tier-based default (unchanged from before this ADR) instead of guessing.

`assign()` now returns all four agent buckets (`{"orchestrator": [...],
"scout": [...], "mechanic": [...], "builder": [...]}`) and routes MCP tools
through `resolve_override()`, so a policy can target any agent for any MCP
tool or server — not just split reads from writes. `classify_builtins()`
routes built-in-tool overrides through the same helper, reading from either
the unified `tools` key or the original `builtins` key (kept as a back-compat
alias, checked first).

Orchestrator hard-denial (ADR 0002) is preserved as an inviolable final
guard, unconditionally, regardless of the new flexibility: `classify_builtins
()` still subtracts `HARD_DENIED_ORCHESTRATOR_TOOLS` as its own last step, and
`main()` subtracts it once more from the orchestrator's combined MCP +
built-in assignment right before it's written into the generated agent files
and `TOOL-ROUTING.md`. No policy shape — a tier override, a direct
`"orchestrator"` target, or a future third override source — can ever hand
the orchestrator `Edit`/`Write`/`MultiEdit`/`NotebookEdit`/`Bash`.

## Consequences

One file, one override key set, one resolution rule, usable for every tool
kind — a user who wants a specific MCP tool or a built-in tool routed to
`builder` (or `orchestrator`, for the built-ins that are safe there) can now
say so directly instead of only choosing between the two tier defaults. The
cost is a slightly less trivial `assign()`/`classify_builtins()` (an extra
helper call per tool) and one more thing to keep in sync going forward if a
fifth agent tier is ever added — `AGENT_NAMES` and `HARD_DENIED_ORCHESTRATOR_
TOOLS` both need to stay current with the real agent roster.
