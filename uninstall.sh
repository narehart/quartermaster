#!/usr/bin/env bash
# Quartermaster uninstaller — reverses install.sh's settings changes.
# Removes the main-thread agent setting and the permission backstop it added.
# Does NOT remove the plugin package — run `/plugin uninstall quartermaster@quartermaster-marketplace`.
set -euo pipefail

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "Quartermaster uninstaller"

# remove the plugin package + marketplace via the claude CLI (idempotent)
if command -v claude >/dev/null 2>&1; then
  claude plugin uninstall quartermaster@quartermaster-marketplace || echo "  (plugin not installed — continuing)"
  claude plugin marketplace remove quartermaster-marketplace || echo "  (marketplace not present — continuing)"
fi

if [ -f "$SETTINGS" ]; then
  command -v jq >/dev/null || {
    echo "  ERROR: jq required"
    exit 1
  }
  cp "$SETTINGS" "$SETTINGS.quartermaster-bak-$STAMP"
  tmp="$(mktemp)"
  jq '
    (if .agent == "quartermaster:orchestrator" then del(.agent) else . end)
    | if (.permissions.ask|type)=="array" then
        .permissions.ask |= map(select(. as $r | ["Agent(model:opus)","Agent(model:claude-opus-*)","Agent(model:fable)","Agent(model:claude-fable-*)"] | index($r) | not))
        | (if (.permissions.ask|length)==0 then del(.permissions.ask) else . end)
      else . end
  ' "$SETTINGS" >"$tmp"
  jq -e . "$tmp" >/dev/null || {
    echo "  ERROR: invalid JSON, aborting"
    rm -f "$tmp"
    exit 1
  }
  mv "$tmp" "$SETTINGS"
  echo "  reverted settings.json (backup: $(basename "$SETTINGS").quartermaster-bak-$STAMP)"
fi
cat <<'EOF'

Then restart Claude Code. The main thread returns to the default (unrestricted) agent.
(If the `claude` CLI was unavailable above, also run in Claude Code:
  /plugin uninstall quartermaster@quartermaster-marketplace )
EOF
