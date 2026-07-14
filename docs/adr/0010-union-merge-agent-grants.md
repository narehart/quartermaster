# ADR 0010: Union-merge agent grants across project-scoped MCP servers

## Status

Accepted

## Context

MCP servers can be PROJECT-SCOPED: a server like `pixellab` might be
registered only in one project's `.mcp.json` (or one worktree's), never in
`~/.claude.json`. But `scripts/classify-mcp.py` writes ONE global set of
agent files into `~/.claude/agents/` and one global `~/.claude/quartermaster/
cache.json`/`TOOL-ROUTING.md` — there is no per-project output.

Before this change, `main()` decided whether to re-enumerate at all using a
single whole-set hash (`server_hash()`) over every server `claude mcp list`
currently reports, and — on a cache miss — pre-filtered the previous run's
cached tools down to only servers considered "currently configured"
(`_norm(s["name"]) in configured_norm`) before merging. Both of these are
scoped to THIS session's visible server set. A real incident: `pixellab` (51
tools) was present in `TOOL-ROUTING.md` and granted to `mechanic`/`scout` in
one project's session; a classify run from a *different* project's session —
one that doesn't configure `pixellab` at all — saw a different visible
server set, took the whole-set-hash cache miss path, pre-filtered
`pixellab`'s cached tools out of `cache_tools` (since it wasn't "configured"
in that session), and clobbered the global cache/agents so `pixellab`'s
grants vanished entirely, for every project, until a session that happens to
configure `pixellab` runs the classifier again. Last writer wins, globally,
every SessionStart.

## Decision

Generated agent grants and `TOOL-ROUTING.md` now draw from the UNION of
every server the cache has ever recorded, not just the current session's
visible set. Concretely, in `scripts/classify-mcp.py`:

- **Per-server cache entries.** `cache.json`'s `"servers"` dict
  (schema version `CACHE_SCHEMA = 2`) keys each server by
  `_norm(display name)` and stores `{"display", "fingerprint", "last_seen",
  "first_seen_project"}`. `server_fingerprint()` hashes one server's
  name+status pair (the per-server analogue of the old whole-set
  `server_hash()`). `changed_or_new_servers()` compares each currently-visible
  server's fingerprint against its cache entry and returns just the
  `_norm()`-ed names that are new or changed — `main()` passes this set into
  `enumerate_tools(..., stdio_only_norm=...)` so only those servers pay for a
  fresh stdio subprocess launch; an unrelated, unchanged server (very often:
  every server, when the only thing that changed is *which project* is
  running the classifier) is never re-enumerated. This also kills the
  cross-project re-enumeration thrash the old whole-set hash caused — a
  session in a different project no longer looks like "everything changed."
- **Union output.** `main()` no longer pre-filters cached tools down to the
  current session's configured servers before calling `merge_with_cache()`
  — it hands that function the FULL cached tool union instead.
  `merge_with_cache()`'s own logic already does the right thing when given
  the full union: a server segment THIS run produced fresh tools for is
  trusted (stale cached entries for it dropped, preserving invariant 5's
  self-heal); every other segment — including ones for servers not
  configured/visible in this session at all — is preserved untouched.
  `assign()`/`generate_agents()`/`write_routing()` then run over that union,
  same as before; tools.json policy still applies on top, and the
  orchestrator still gets nothing (invariant 1 is untouched, and
  `tests/test_classify_mcp.py`'s disjoint-set test still passes).
- **`last_seen` refresh, never implicit drop.** Every server visible in a
  given run gets its `fingerprint`/`last_seen` refreshed (and
  `first_seen_project` set once, from `current_project_hint()` = `cwd`, if
  not already set). A server invisible this run is left completely alone —
  neither refreshed nor dropped. Removal is now only ever an EXPLICIT
  `--prune` (default 30 days, `--prune-days N`), which drops cache entries
  (and their tools) whose `last_seen` is older than the threshold. A missing
  or unparseable `last_seen` is never pruned (fail safe).
- **Cache migration.** `migrate_cache()` upgrades a pre-0.7.0 cache (flat
  `"tools"` list, single whole-set `"hash"`, no per-server metadata) by
  bucketing its tools by server segment into synthetic per-server entries
  with `fingerprint=None` (so each is correctly treated as changed/unverified
  the next time that server is actually visible, rather than migration
  guessing a fingerprint it can't know) and `last_seen` set to the migration
  moment (never some unknowable past moment, which would risk an immediate
  `--prune` wiping everything on the very first run of the new code). An
  empty/corrupt/missing cache migrates to an empty cache, same as a fresh
  install. Migration never raises.
- **`TOOL-ROUTING.md` header.** A new "Cached servers (union across
  projects) — last seen" table lists every cached server's `display`,
  `last_seen`, and `first_seen_project`, so it's visible which grants are
  coming from a different project/session and when each was last seen.

**Inert-grant rationale.** A grant for a server that isn't configured in the
current project is INERT: the Claude Code CLI will not connect a server
that isn't in that project's `.mcp.json`/`~/.claude.json`, so `mechanic`
holding a `pixellab` tool name in a project that never configures `pixellab`
grants nothing that can actually be invoked there. Unioning therefore
over-grants nothing that functions — it only prevents a *different*
project's legitimate, currently-inert-here grant from being permanently
deleted globally.

## Alternatives considered

**Per-project agent output** (writing agents/routing into each project's own
`.claude/` instead of the single global `~/.claude/agents/`) was considered
and rejected for now: it's a bigger change (more moving parts — the
generator would need to know which project each grant belongs to at
*generation* time, not just observe it after the fact via `cwd`, and
Claude Code's own agent-loading path would need to prefer a project-local
agent file over the global one). Given that an inert grant costs nothing
functionally, union-merge gets the practical fix (no more disappearing
grants) without that added complexity. Per-project output remains an option
if a future need (e.g. wanting agents to actually differ in write access
per project, not just in which grants are inert) makes the extra complexity
worth it.

## Consequences

- Every generated agent lists grants for every server the cache has ever
  seen, globally, across every project — including servers that only
  function in their own project. This is intentional (see inert-grant
  rationale above), but means `TOOL-ROUTING.md`/agent files are no longer a
  precise picture of "what works in THIS project" — just "what could work in
  some project this cache has seen."
- The removal valve is now explicit and age-based (`--prune`/`--prune-days`)
  rather than implicit and immediate. A server genuinely deleted from every
  project's config keeps its grant (harmlessly inert) until either
  `--prune` runs past its `last_seen` threshold or someone manually clears
  `cache.json`.
- Per-server fingerprinting adds a small bookkeeping cost (`cache.json`'s
  `"servers"` dict) but removes the cross-project re-enumeration thrash the
  old whole-set hash caused — a session in a different project no longer
  triggers a full re-enumeration of every server just because the visible
  set differs.
