# ADR 0004: Deterministic enumeration, with a model-assisted fallback

## Status

Accepted

## Context

Tiering MCP tools (ADR 0003) requires first knowing which tools exist.
Different MCP server types offer fundamentally different ways to find out:
stdio servers can be spoken to directly over their own process's stdin/
stdout, but OAuth/remote servers require a live, already-authenticated
session — a standalone probe process has no token to present. Asking a
Haiku session to recite its own tool list is the only way to reach OAuth
servers, but it's a model call that can truncate or drop servers on a large
(dozens-of-servers) setup, and it costs money and time on every run.

## Decision

Two enumeration paths are kept deliberately distinct, never collapsed into
one:

- **stdio servers** — `list_tools_stdio()` launches each server's own
  configured `command`/`args`/`env` and speaks the MCP `tools/list` protocol
  directly (`initialize` -> `notifications/initialized` -> `tools/list`).
  Deterministic, no model call.
- **OAuth/remote servers** — `enumerate_headless()` shells out to an
  authenticated `claude -p --agent claude --model haiku` pass and asks it to
  recite its own `mcp__*` tool list verbatim. This is the fallback path,
  used only when `enumerate_transcripts()` finds that no session transcript
  anywhere has ever recorded a `deferred_tools_delta` — the primary,
  deterministic source of tool names is replaying that attachment out of
  `~/.claude/projects/*/*.jsonl`, which Claude Code itself writes with no
  model call required.

`SessionStart` re-enumeration (wired in `hooks/hooks.json`, driven by
`classify-mcp.py`'s `main()`) is gated on `server_hash()` — a hash of every
configured server's name+status pair — changing since the last cached run;
an unchanged hash regenerates agents from cache with no re-enumeration at
all. `merge_with_cache()` additionally guards against a connected server
that produced zero tools this run clobbering its previously-cached,
last-known-good tool set (see ADR 0005's `classify_builtins` note and the
cache self-heal invariant in AGENTS.md).

## Consequences

stdio tool names and annotations are trustworthy and free; OAuth tool names
cost one Haiku call and only on a fresh machine or a genuinely new server —
in the steady state, most sessions do zero enumeration work. The tradeoff is
two code paths to maintain instead of one, and the headless fallback is
explicitly documented as flaky at scale rather than papered over.
