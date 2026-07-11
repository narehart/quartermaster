# Changelog

All notable changes to TokenWise. Versions follow [semver](https://semver.org).

## [0.2.3] — 2026-07-11

### Fixed
- Server-list parser silently dropped servers whose names contain spaces or
  colons (`claude.ai Google Drive`, `plugin:slack:slack`) — tokenwise was
  only tracking 4 of 7 configured servers. Replaced with one robust parser
  used everywhere; all servers now tracked.
- Auth-gated servers (status "Needs authentication") were silently absent
  from TOOL-ROUTING.md. They're now listed under "Configured, zero tools
  enumerated" with the reason and the fix ("authorize via /mcp then re-run").
- Cache key now includes each server's connection STATUS, so authenticating a
  server (needs-auth -> connected) auto-triggers re-enumeration on the next
  classify run instead of being masked by the name-only cache key.

### Notes
- No Claude Code hook fires on MCP OAuth/connection change (ConfigChange only
  covers settings/skills), so after authenticating a server via /mcp you must
  re-run `classify-mcp.py --force` or restart for it to be picked up.

## [0.2.2] — 2026-07-11

### Fixed
- MCP connection race: the classifier ran at SessionStart while some servers
  (e.g. a plugin-provided `slack`) were still connecting, so their tools were
  missed and never granted. Now waits for `claude mcp list` connections to
  settle before enumerating, retries enumeration (up to 3×) if a Connected
  server yields zero tools, and never clobbers a server's cached grants with
  an empty result. Also removes the run-to-run enumeration variance.

## [0.2.1] — 2026-07-11

### Fixed
- Plugin-provided MCP servers were not granted correctly: their runtime tools
  use the `mcp__plugin_<plugin>_<server>__<tool>` scheme and aren't in
  ~/.claude.json, so the classifier emitted non-matching patterns (e.g.
  `mcp__slack__*`) and the real plugin tools went ungranted. Headless
  enumeration is now the source of truth for exact tool NAMES (prompt forbids
  normalizing the plugin prefix); the stdio protocol path only supplies
  read/write annotations for names it can confirm. Reported from real use
  (Slack plugin on a second machine).

## [0.2.0] — 2026-07-11

### Added — MCP tool tiering
- MCP tools are now classified read/write and tiered like everything else:
  read tools -> scout, write tools -> mechanic, orchestrator holds none and
  delegates (an MCP call is I/O = execution). Unblocks Linear and repairs
  MCP-dependent skills that the v0.1.x orchestrator allowlist was silently
  blocking.
- `scripts/classify-mcp.py`: hybrid enumerator — deterministic MCP `tools/list`
  over stdio (launched WITH each server's configured env, so API-key servers
  like naver work; uses readOnlyHint/destructiveHint annotations) + an
  authenticated headless `claude -p` pass that reaches OAuth/remote servers
  (Google Drive, Linear connectors) the standalone probe can't. Caches on the
  set of configured servers (one Haiku call only when servers change), guards
  against SessionStart reentrancy, writes ~/.claude/tokenwise/TOOL-ROUTING.md.
- Agents are now GENERATED into ~/.claude/agents/ from templates (so MCP grants
  can be written into their static frontmatter), regenerated at SessionStart.
  Plugin ships templates + scripts + hooks, not namespaced agents.
- `mcp-policy.example.json`: optional per-server/per-tool overrides.

### Changed
- Plugin restructured from "provides namespaced agents" to
  "generates bare-named agents"; install.sh now runs the generator.

### Notes
- OAuth servers CAN be enumerated (via the authed headless pass); only the
  standalone protocol probe can't. Hybrid covers both.
## [0.1.3] — 2026-07-11

### Changed
- Cleaner tier split instead of giving scout blanket Bash (v0.1.2). scout is now
  read-only file/code recon with NO shell (Bash explicitly denied); command
  execution — git, lint/typecheck/test gates, "run X and report" — routes to
  **mechanic**, which already has Bash and owns scripted commands. Fixes the
  "scout couldn't run git" case without handing a recon agent an unrestricted
  shell (scoped Bash in `tools` isn't a real restriction, and hooks don't fire
  inside sub-agents, so shell-free + route-to-mechanic is the enforceable design).
- orchestrator prompt repointed: read-only command inspection goes to mechanic;
  scout gets only read-the-files work.

## [0.1.2] — 2026-07-11

### Fixed
- `scout` could not run `git`/lint/typecheck gates: it had read-only FILE tools
  but no Bash, while the orchestrator delegates read-only command execution to
  it. Gave scout `Bash` for inspection (and explicitly denied Edit/Write/
  NotebookEdit so it stays recon-only). Reported from real use on a second
  machine ("Scout couldn't run git — read-only, no shell").

## [0.1.1] — 2026-07-11

### Changed
- `install.sh` now installs the plugin itself via the `claude` CLI
  (`plugin validate` + `plugin marketplace add` + `plugin install`) and derives
  the repo path from its own location — no path to fill in. `uninstall.sh`
  likewise removes the plugin + marketplace via the CLI.

## [0.1.0] — 2026-07-11

First packaged release — the strict delegation framework as a Claude Code plugin.

### Added
- `orchestrator` agent: delegation-only main-thread lead with no Edit/Write/Bash
  (tools: Read, Grep, Glob, Agent, Skill, WebFetch, WebSearch; model: inherit).
- Tiered leaf agents `scout` (Haiku), `mechanic` (Haiku), `builder` (Sonnet),
  each with `disallowedTools: Agent, Task, Workflow` (no recursion) and explicit
  `maxTurns` / `effort` caps.
- `enforce-agent-model.py` PreToolUse hook: hard-pins every roster + built-in
  sub-agent's model (namespace-robust: matches `tokenwise:scout` and `scout`).
- SessionStart `CLAUDE_CODE_SUBAGENT_MODEL` tripwire; SubagentStart/Stop logging.
- `install.sh` / `uninstall.sh`: set/revert the main-thread `agent` and the
  Opus/Fable permission backstop, and migrate away a prior manual install
  (backs up settings.json and legacy agent/hook files, strips duplicated hooks).

### Notes
- The orchestrator-as-main-thread and permission rules are set by `install.sh`
  because a plugin cannot set user settings itself.
