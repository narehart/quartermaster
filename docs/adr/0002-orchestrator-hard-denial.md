# ADR 0002: Orchestrator hard-denial of implementation tools

## Status

Accepted

## Context

ADR 0001 establishes that the orchestrator should never implement. A policy
that only says "please delegate" is not durable: prompts drift, defaults
change, and a future built-in tool or a permissive `mcp-policy.json` override
could hand the orchestrator an implementation tool without anyone noticing
until it's used.

## Decision

The orchestrator's inability to implement is enforced twice, structurally:

1. **Tool allowlist.** `templates/orchestrator.md` grants it only `Read,
   Grep, Glob, Agent, Skill, TodoWrite, WebFetch, WebSearch` — no
   `Edit`/`Write`/`Bash`, and no MCP tools at all.
2. **Defensive subtraction in code.** `classify_builtins()` in
   `scripts/classify-mcp.py` computes the orchestrator's built-in tool grant
   from `BUILTIN_TIERS` and any `mcp-policy.json` `builtins` override, then
   as its *last* step subtracts `HARD_DENIED_ORCHESTRATOR_TOOLS` (`Edit`,
   `Write`, `MultiEdit`, `NotebookEdit`, `Bash`) from that result —
   unconditionally, regardless of what the map or an override said. This is
   deliberate defense in depth: the allowlist protects against the common
   case, the subtraction protects against a policy override or a future
   `BUILTIN_TIERS` entry trying to grant one of those tools anyway.

`tests/test_classify_mcp.py` asserts the orchestrator's assignment is always
disjoint from `HARD_DENIED_ORCHESTRATOR_TOOLS`, including under a policy
override that tries to grant one — this test must keep passing.

## Consequences

The orchestrator is physically incapable of editing files or running shell
commands, even against a hostile or mistaken policy file — there is no
config-only path back to it holding those tools. The cost is that any new
built-in tool that should reasonably go to the orchestrator has to be added
to `BUILTIN_TIERS["orchestrator"]` explicitly and reviewed against this list;
it can never be granted "by accident" via a broad override.
