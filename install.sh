#!/usr/bin/env bash
# TokenWise installer / migrator.
#
# Does the two things a Claude Code plugin CANNOT do for itself, and cleans up
# any previous MANUAL install of this framework:
#   1. sets the main-thread agent to tokenwise:orchestrator (the strict, no
#      Edit/Write/Bash lead) in ~/.claude/settings.json
#   2. adds the Opus/Fable "ask before spawning" permission backstop
#   3. removes legacy hand-installed agent files + hook + settings hooks that
#      the plugin now provides (so nothing double-fires)
#
# It does NOT install the plugin package itself — run the /plugin commands it
# prints at the end. Safe to run on a fresh machine (no legacy = no-op cleanup).
set -euo pipefail

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$CLAUDE_DIR/.tokenwise-legacy-backup-$STAMP"

echo "TokenWise installer"
echo "  config dir: $CLAUDE_DIR"

# 1. back up settings.json
if [ -f "$SETTINGS" ]; then
  cp "$SETTINGS" "$SETTINGS.tokenwise-bak-$STAMP"
  echo "  backed up settings.json -> $(basename "$SETTINGS").tokenwise-bak-$STAMP"
fi

# 2. move aside legacy manually-installed agents + hook script (plugin ships these)
mkdir -p "$BACKUP/agents"
for a in orchestrator scout mechanic builder Explore general-purpose claude-code-guide; do
  f="$CLAUDE_DIR/agents/$a.md"
  [ -f "$f" ] && mv "$f" "$BACKUP/agents/" && echo "  moved legacy agent: agents/$a.md"
done
[ -f "$CLAUDE_DIR/hooks/enforce-agent-model.py" ] && \
  mv "$CLAUDE_DIR/hooks/enforce-agent-model.py" "$BACKUP/" && echo "  moved legacy hooks/enforce-agent-model.py"
rmdir "$BACKUP/agents" 2>/dev/null || true
rmdir "$BACKUP" 2>/dev/null && echo "  (no legacy files found)" || echo "  legacy files backed up in: $(basename "$BACKUP")"

# 3. patch settings.json: main-thread agent, permission backstop, strip legacy hooks
if [ -f "$SETTINGS" ]; then
  command -v jq >/dev/null || { echo "  ERROR: jq required to patch settings.json"; exit 1; }
  tmp="$(mktemp)"
  jq '
    .agent = "tokenwise:orchestrator"
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
  echo "  patched settings.json: agent=tokenwise:orchestrator, permission asks added, legacy hooks removed"
fi

cat <<'EOF'

Next — install the plugin package itself (in Claude Code):
  /plugin marketplace add <path-or-git-url-to-this-tokenwise repo>
  /plugin install tokenwise@tokenwise-marketplace
Then restart Claude Code (the main-thread agent loads at startup).

Verify:
  claude -p --agent tokenwise:orchestrator "List your exact tool names."
  -> expect Read/Grep/Glob/Agent/Skill/WebFetch/WebSearch; NO Edit/Write/Bash.

Escape hatch for a hands-on session: claude --agent claude
EOF
