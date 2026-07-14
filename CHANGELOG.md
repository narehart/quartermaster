# Changelog

All notable changes to Quartermaster. Versions follow [semver](https://semver.org).

## [0.7.0] — 2026-07-14

### Added — union-merge agent grants across project-scoped MCP servers
- Generated agent grants and `TOOL-ROUTING.md` now draw from the UNION of
  every MCP server the cache has ever recorded, not just the current
  session's visible set. Fixes a real clobbering incident: a project-scoped
  server (e.g. `pixellab`, registered in only one project's `.mcp.json`)
  had its grants vanish from every generated agent whenever a session from
  a *different* project ran the classifier, since the old whole-set
  `server_hash()` treated a differing visible-server-set as a wholesale
  cache miss, and the cache-merge call site pre-filtered cached tools down
  to "servers configured in this session" before merging — silently
  dropping any server not visible right now. A grant for a server not
  configured in the current project is inert (the CLI won't connect it
  there), so unioning over-grants nothing that actually functions.
- `cache.json` gains a per-server `"servers"` dict (schema `2`, migrated
  automatically and losslessly from the old flat-`"tools"` schema) keyed by
  each server's config fingerprint + `last_seen` timestamp
  (`server_fingerprint()`/`changed_or_new_servers()`) — only servers that
  are new or changed since they were last cached are re-enumerated, which
  also eliminates the cross-project re-enumeration thrash the old
  whole-set hash caused.
- New `--prune` flag (default 30 days, `--prune-days N`) drops cache
  entries — and their tools — for servers not seen in that long; this is
  now the only way a server's grant is ever actually removed. A missing or
  unparseable `last_seen` is never pruned.
- `TOOL-ROUTING.md` gains a "Cached servers (union across projects) — last
  seen" header table showing every cached server's last-seen time and
  (when cheaply available) the project it was first seen from.
- See [ADR 0010](docs/adr/0010-union-merge-agent-grants.md).

## [0.6.2] — 2026-07-13

### Added
- Local pre-commit gates via [lefthook](lefthook.yml): `secrets`
  (`gitleaks protect --staged`), `lint`/`format` (`ruff check` /
  `ruff format --check` on staged `*.py`), and `shell` (`shfmt -d -i 2` on
  staged `*.sh`) all run on `pre-commit`, plus a `commit-msg` gate
  (`cz check`) — so these checks fail a commit locally instead of being
  caught only by CI/`make verify`. `make setup` now also installs lefthook
  and runs `lefthook install`. See ADR 0009.

### Security
- `.gitignore` now defensively excludes `.env` and `.env.*`, so a local env
  file can't be accidentally committed even though none is currently
  tracked or required by the project.
- `osv-scanner` CVE scanning now runs in CI (new `osv-scan` job in
  [ci.yml](.github/workflows/ci.yml)), scanning the actually-installed
  dependency set (`pip freeze`) rather than the loose
  `requirements-dev.txt`, which otherwise resolves an unpinned transitive
  `pygments` range to a vulnerable phantom floor version. See ADR 0009.

## [0.6.1] — 2026-07-13

### Changed
- The orchestrator no longer holds `WebFetch`/`WebSearch` — web research is
  now delegated to `scout`, consistent with the orchestrator's existing
  no-I/O principle (it already held no MCP tools). See ADR 0008.

## [0.6.0] — 2026-07-13

### Added — govern built-in agents
- Claude Code's built-in `Explore` and `general-purpose` agents are now
  shadowed with restricted, read-only, no-recursion templates
  (`templates/Explore.md`, `templates/general-purpose.md`), closing a bypass
  where an all-tools `general-purpose` (with `Edit`/`Write`/`Bash`/`Agent`) or
  an `Explore` with `Bash` could implement or execute completely outside the
  tiering model. Both draw their generated tools from the same read-only
  bucket `scout` gets (never `mechanic`/`builder`) and deny
  `Agent`/`Task`/`Workflow`/`Edit`/`Write`/`MultiEdit`/`NotebookEdit`/`Bash`
  unconditionally via `disallowedTools`. See ADR 0007.

### Changed — unified tool policy
- Policy file renamed `mcp-policy.json` -> `tools.json` (and the shipped
  example `mcp-policy.example.json` -> `tools.example.json`), with the old
  filename read as a transparent fallback when the new one isn't present —
  no manual migration needed.
- The policy is generalized so ANY tool — an MCP tool, an MCP server, or a
  built-in tool (e.g. `WebSearch`) — can be tiered to ANY agent
  (`orchestrator`/`scout`/`mechanic`/`builder`), not just MCP tools split
  between scout/mechanic. A shared `resolve_override()` helper interprets
  every override value the same way, whether it came from `assign()` or
  `classify_builtins()`: a tier keyword (a key in `tiers`), a direct agent
  name, or `"skip"`.
- `classify_builtins()` now honors overrides from either the unified `tools`
  key or the original `builtins` key (kept as a back-compat alias).
- Orchestrator hard-denial (`Edit`/`Write`/`MultiEdit`/`NotebookEdit`/`Bash`)
  is unchanged and still enforced unconditionally in code — now applied
  twice: once inside `classify_builtins()`, and once more where the MCP and
  built-in assignments are combined in `main()`, so no policy shape can ever
  route one of those tools to the orchestrator.

## [0.5.1] — 2026-07-13

### Fixed
- Complete the rename to Quartermaster — v0.5.0 shipped with marketplace.json
  and install.sh still using the old tokenwise plugin/marketplace ids, so a
  fresh install was still tracked as tokenwise@tokenwise-marketplace. Installs
  are now tracked as quartermaster@quartermaster-marketplace, and install.sh
  migrates a prior tokenwise install (uninstalls it, removes the old
  marketplace, moves ~/.claude/tokenwise -> ~/.claude/quartermaster).

## [0.4.0] — 2026-07-12

### Added — built-in tool tiering
- Claude Code's deferred BUILT-IN tools (Monitor, SendMessage, Task*, Cron*,
  PushNotification, RemoteTrigger, LSP, NotebookEdit, worktree tools, …) are
  now classified and granted instead of silently dropped. The agent allowlists
  previously named only a fixed base set + MCP tools, so these were unusable.
- Coordination tools -> orchestrator (Monitor, SendMessage, Task*, Cron*,
  PushNotification, RemoteTrigger, plan-mode, MCP-resource readers).
  Mutating tools -> mechanic/builder (NotebookEdit, worktree, DesignSync, LSP).
  Read-only -> scout.
- Unknown/new built-ins default to mechanic ONLY and are surfaced in
  TOOL-ROUTING.md, so a future Claude Code release can't silently hand the
  orchestrator an implementation tool.
- Hard denial enforced in code: the orchestrator can never be granted Edit,
  Write, MultiEdit, NotebookEdit or Bash — not via the map, not via the
  unknown default, not via a policy override (verified by test).
- Optional `builtins` overrides in tools.json.

### Note
- `Monitor` executes a command, so granting it to the orchestrator is a
  deliberate exception to "the orchestrator has no shell". Set
  `{"builtins": {"Monitor": "mechanic"}}` in tools.json to keep that
  guarantee strict (you lose wake-on-output in the main thread).

## [0.3.1] — 2026-07-11

### Fixed
- `install.sh` now runs the classifier with `--force`, so a (re)install always
  re-classifies instead of taking a stale cache hit — you no longer have to
  run `classify-mcp.py --force` by hand after installing.
- Classifier self-heals an incomplete cache: on a cache-hash hit it now checks
  that every currently-Connected server has at least one cached tool; if a
  Connected server has zero (a poisoned/incomplete cache written under a hash
  that looks current), it re-enumerates instead of reusing. So SessionStart
  recovers on its own, not just installs.

## [0.3.0] — 2026-07-11

### Changed — deterministic MCP enumeration
- Tool enumeration no longer asks a headless Haiku model to recite its tool
  list (which truncated/dropped servers on large setups — a 30-server / 219-
  tool user lost the Slack plugin's tools entirely). It now replays the
  `deferred_tools_delta` records Claude Code writes into session transcripts
  (~/.claude/projects/*/*.jsonl) — the exact runtime tool-name list, incl.
  plugin-provided servers (`mcp__plugin_<plugin>_<server>__*`). No model
  call, fully deterministic (identical output run-to-run), can't truncate.
- Unions newest-first across transcripts until every configured server is
  covered, so a single session that raced a slow-connecting server can't
  cause a miss.
- Headless enumeration is kept ONLY as a fallback for a brand-new machine
  with no prior session transcripts.
- Verified end-to-end against the real authenticated Slack plugin: 19 tools
  -> 12 scout / 7 mechanic, deterministically, zero model calls.

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
- `tools.example.json`: optional per-server/per-tool overrides.

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
