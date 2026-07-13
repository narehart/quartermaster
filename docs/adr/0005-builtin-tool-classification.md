# ADR 0005: Built-in tools are tiered too, with a safe unknown default

## Status

Accepted

## Context

ADR 0003 tiers MCP tools, but Claude Code also has its own DEFERRED
built-in tools — `Monitor`, `SendMessage`, `TaskCreate`/`TaskList`/...,
`CronCreate`/..., `PushNotification`, `RemoteTrigger`, `LSP`, `NotebookEdit`,
worktree tools, and others — that only ever appear once Claude Code defers
them into a session (recorded the same way as MCP tools, in a session
transcript's `deferred_tools_delta` attachment). Before this classification
existed, each agent's allowlist named only a fixed base set plus MCP tools,
so every one of these built-ins was simply unusable by any tier. And because
new built-in tools ship with new Claude Code releases, whatever handles this
has to fail safe on a name it's never seen before.

## Decision

`classify_builtins()` in `scripts/classify-mcp.py` assigns each observed
built-in name to agent(s) with this precedence:

1. An explicit `mcp-policy.json` `builtins` override for that name, if
   present — single agent, replaces the default.
2. `BUILTIN_TIERS`, a curated allowlist mapping names to one or more agents
   (e.g. `Monitor`/`SendMessage`/`Task*`/`Cron*` -> orchestrator;
   `NotebookEdit`/worktree tools -> mechanic/builder; `LSP`/`WebFetch`/
   `WebSearch` -> multiple tiers at once).
3. **Unknown** — a name observed in transcript history but present in
   neither of the above is granted *only* to mechanic, and reported
   separately (surfaced in `TOOL-ROUTING.md`'s "Unknown built-ins" section)
   so it can be reclassified via policy once someone notices it.

Whatever the map or an override computed, `HARD_DENIED_ORCHESTRATOR_TOOLS`
is subtracted from the orchestrator's result as the unconditional last step
(ADR 0002) — an unknown or misconfigured built-in can never reach the
orchestrator if it happens to collide with a hard-denied name.

## Consequences

New Claude Code releases that add built-in tools degrade gracefully: an
unrecognized tool becomes usable (by mechanic) rather than invisible, without
ever risking an unreviewed grant to the orchestrator. The cost is that a
genuinely read-only new built-in sits on the more expensive/less-trusted
mechanic tier until someone notices it in `TOOL-ROUTING.md`'s unknown-builtins
section and reclassifies it via `mcp-policy.json`.
