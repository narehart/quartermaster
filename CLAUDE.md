# CLAUDE.md

Canonical contributor and agent instructions live in [AGENTS.md](AGENTS.md) —
read it first, before making any change here.

@AGENTS.md

## Claude Code specifics

- This repo **is** the delegation plugin itself. If you have Quartermaster
  installed, this session runs as the tool-restricted `orchestrator` (no
  Edit/Write/Bash, no MCP tools) — delegate all execution to the
  scout/mechanic/builder sub-agents rather than editing files directly, same
  as in any other project using this plugin.
- A `.claude/hooks/block-inline-suppressions.sh` PreToolUse hook is active in
  this repo and will block any `Edit`/`Write`/`MultiEdit` call whose new
  content introduces an inline suppression directive (see AGENTS.md
  invariant 3).
