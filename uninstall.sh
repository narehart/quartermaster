#!/usr/bin/env bash
# TokenWise uninstaller — reverses install.sh's settings changes.
# Removes the main-thread agent setting and the permission backstop it added.
# Does NOT remove the plugin package — run `/plugin uninstall tokenwise@tokenwise-marketplace`.
set -euo pipefail

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "TokenWise uninstaller"
if [ -f "$SETTINGS" ]; then
  command -v jq >/dev/null || { echo "  ERROR: jq required"; exit 1; }
  cp "$SETTINGS" "$SETTINGS.tokenwise-bak-$STAMP"
  tmp="$(mktemp)"
  jq '
    (if .agent == "tokenwise:orchestrator" then del(.agent) else . end)
    | if (.permissions.ask|type)=="array" then
        .permissions.ask |= map(select(. as $r | ["Agent(model:opus)","Agent(model:claude-opus-*)","Agent(model:fable)","Agent(model:claude-fable-*)"] | index($r) | not))
        | (if (.permissions.ask|length)==0 then del(.permissions.ask) else . end)
      else . end
  ' "$SETTINGS" > "$tmp"
  jq -e . "$tmp" >/dev/null || { echo "  ERROR: invalid JSON, aborting"; rm -f "$tmp"; exit 1; }
  mv "$tmp" "$SETTINGS"
  echo "  reverted settings.json (backup: $(basename "$SETTINGS").tokenwise-bak-$STAMP)"
fi
cat <<'EOF'

Also remove the plugin package (in Claude Code):
  /plugin uninstall tokenwise@tokenwise-marketplace
Then restart Claude Code. The main thread returns to the default (unrestricted) agent.
EOF
