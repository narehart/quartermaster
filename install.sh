#!/usr/bin/env bash
# TokenWise installer / migrator.
#
# Installs the plugin (marketplace + plugin via the `claude` CLI) AND does the
# two things a Claude Code plugin cannot do for itself:
#   1. sets the main-thread agent to orchestrator (the strict, no
#      Edit/Write/Bash lead) in ~/.claude/settings.json
#   2. adds the Opus/Fable "ask before spawning" permission backstop
# It also migrates away any previous MANUAL install of this framework (moves the
# hand-installed agent files + hook aside and strips the duplicated settings
# hooks the plugin now provides). Safe on a fresh machine (legacy steps no-op).
#
# The plugin path is derived from this script's own location — no path to fill in.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$CLAUDE_DIR/.tokenwise-legacy-backup-$STAMP"

echo "TokenWise installer"
echo "  plugin dir: $SCRIPT_DIR"
echo "  config dir: $CLAUDE_DIR"

# 1. install the plugin package via the claude CLI (derived path, idempotent)
if command -v claude >/dev/null 2>&1; then
  echo "  validating manifest..."
  claude plugin validate "$SCRIPT_DIR" || echo "  (validate reported issues — continuing)"
  echo "  adding marketplace from this repo..."
  claude plugin marketplace add "$SCRIPT_DIR" || echo "  (marketplace already added — continuing)"
  echo "  installing tokenwise@tokenwise-marketplace..."
  claude plugin install tokenwise@tokenwise-marketplace \
    || { echo "  (already installed — updating instead)"; claude plugin update tokenwise@tokenwise-marketplace || true; }
else
  echo "  NOTE: 'claude' CLI not on PATH — install the plugin manually in Claude Code:"
  echo "    /plugin marketplace add $SCRIPT_DIR"
  echo "    /plugin install tokenwise@tokenwise-marketplace"
fi

# 2. back up settings.json
if [ -f "$SETTINGS" ]; then
  cp "$SETTINGS" "$SETTINGS.tokenwise-bak-$STAMP"
  echo "  backed up settings.json -> $(basename "$SETTINGS").tokenwise-bak-$STAMP"
fi

# 3. move aside legacy manually-installed agents + hook script (plugin/generator own these now)
mkdir -p "$BACKUP/agents"
for a in orchestrator scout mechanic builder Explore general-purpose claude-code-guide; do
  f="$CLAUDE_DIR/agents/$a.md"
  [ -f "$f" ] && mv "$f" "$BACKUP/agents/" && echo "  moved legacy agent: agents/$a.md"
done
[ -f "$CLAUDE_DIR/hooks/enforce-agent-model.py" ] && \
  mv "$CLAUDE_DIR/hooks/enforce-agent-model.py" "$BACKUP/" && echo "  moved legacy hooks/enforce-agent-model.py"
rmdir "$BACKUP/agents" 2>/dev/null || true
rmdir "$BACKUP" 2>/dev/null && echo "  (no legacy files found)" || echo "  legacy files backed up in: $(basename "$BACKUP")"

# 3b. generate the working agents into ~/.claude/agents with MCP tools tiered in
#     (one-time; the SessionStart hook keeps them in sync afterward). This does a
#     headless enumeration if you have MCP servers, so it can take a minute.
if command -v python3 >/dev/null 2>&1; then
  echo "  generating agents + classifying MCP tools (may take a minute if you have MCP servers)..."
  python3 "$SCRIPT_DIR/scripts/classify-mcp.py" --templates "$SCRIPT_DIR/templates" --agents "$CLAUDE_DIR/agents" --force || \
    echo "  (classifier had trouble — agents still generated from templates; re-runs at each SessionStart)"
else
  echo "  WARNING: python3 not found — agents not generated; install python3 and re-run."
fi

# 4. patch settings.json: main-thread agent, permission backstop, strip legacy hooks
if [ -f "$SETTINGS" ]; then
  command -v jq >/dev/null || { echo "  ERROR: jq required to patch settings.json"; exit 1; }
  tmp="$(mktemp)"
  jq '
    .agent = "orchestrator"
    | .permissions.ask = (((.permissions.ask // [])
        + ["Agent(model:opus)","Agent(model:claude-opus-*)","Agent(model:fable)","Agent(model:claude-fable-*)"]) | unique)
    | if (.hooks|type)=="object" then .hooks |= (
        (if .PreToolUse   then .PreToolUse   |= map(select(((.hooks // [])|any((.command // "")|test("enforce-agent-model")))|not))       else . end)
        | (if .SessionStart then .SessionStart |= map(select(((.hooks // [])|any((.command // "")|test("CLAUDE_CODE_SUBAGENT_MODEL")))|not)) else . end)
        | (if .SubagentStart then .SubagentStart |= map(select(((.hooks // [])|any((.command // "")|test("subagents.jsonl")))|not))         else . end)
        | (if .SubagentStop  then .SubagentStop  |= map(select(((.hooks // [])|any((.command // "")|test("subagent-stops.jsonl")))|not))    else . end)
      ) | .hooks |= with_entries(select((.value|length) > 0))
      else . end
  ' "$SETTINGS" > "$tmp"
  jq -e . "$tmp" >/dev/null || { echo "  ERROR: produced invalid JSON, aborting (settings.json untouched)"; rm -f "$tmp"; exit 1; }
  mv "$tmp" "$SETTINGS"
  echo "  patched settings.json: agent=orchestrator, permission asks added, legacy hooks removed"
fi

cat <<'EOF'

Done. Restart Claude Code so the main-thread agent loads at startup.

Verify:
  claude -p --agent orchestrator "List your exact tool names."
  -> expect Read/Grep/Glob/Agent/Skill/WebFetch/WebSearch; NO Edit/Write/Bash.

Escape hatch for a hands-on session: claude --agent claude
EOF
