# ADR 0003: Least-privilege MCP tool tiering

## Status

Accepted

## Context

MCP tools are I/O the same way shell commands and file edits are — a `list`
or `search` call is cheap recon, while a `create`/`update`/`send`/`delete`
call mutates state. If the orchestrator held any MCP tools directly, it
could call them itself instead of delegating, defeating ADR 0001/0002. But
routing every MCP call through a single execution tier also throws away the
scout/mechanic cost split ADR 0001 established for file/shell work.

## Decision

`scripts/classify-mcp.py` classifies every enumerated MCP tool as `read` or
`write` (via `readOnlyHint`/`destructiveHint` annotations where available,
falling back to the `READ_RE`/`WRITE_RE` name heuristics in
`classify_by_name`), then `assign()` routes `read` tools into `scout` and
`write` tools into `mechanic` (the default in `policy.get("tiers", {"read":
"scout", "write": "mechanic"})`). `generate_agents()` appends the resulting
tool names onto each tier's template `tools:` line. The orchestrator holds no
MCP tools at all — `write_routing()` documents the per-server split in
`~/.claude/quartermaster/TOOL-ROUTING.md` so the orchestrator can route work
to the right tier without holding any of the tools itself.

## Consequences

Scout gets read-only MCP access at Haiku cost; mechanic gets write access at
Haiku cost; the orchestrator never touches an MCP tool directly, so a task
that needs both a lookup and a mutation against the same server is split
across two delegations rather than done in one. An unrecognized tool name
with no annotation defaults to `write` (`classify_by_name`'s "unknown -> safe
(execution tier)" fallback) — the safer failure mode is treating an unknown
tool as mutating rather than under-protecting it as read-only.
