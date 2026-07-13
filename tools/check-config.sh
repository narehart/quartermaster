#!/usr/bin/env bash
# Validate that every JSON config file in the plugin parses cleanly, and (if
# the `claude` CLI is available) that the plugin manifest itself validates.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

files=(
  ".claude-plugin/plugin.json"
  ".claude-plugin/marketplace.json"
  "hooks/hooks.json"
  "tools.example.json"
)

status=0

for f in "${files[@]}"; do
  path="$REPO_ROOT/$f"
  if [ ! -f "$path" ]; then
    echo "FAIL: $f (file not found)"
    status=1
    continue
  fi
  if python3 -m json.tool "$path" >/dev/null 2>&1; then
    echo "PASS: $f"
  else
    echo "FAIL: $f (invalid JSON)"
    status=1
  fi
done

if command -v claude >/dev/null 2>&1; then
  echo "running: claude plugin validate ."
  if (cd "$REPO_ROOT" && claude plugin validate .); then
    echo "PASS: claude plugin validate ."
  else
    echo "FAIL: claude plugin validate ."
    status=1
  fi
else
  echo "NOTICE: 'claude' CLI not found on PATH — skipping 'claude plugin validate .'"
fi

exit "$status"
