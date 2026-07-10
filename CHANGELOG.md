# Changelog

All notable changes to TokenWise. Versions follow [semver](https://semver.org).

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
