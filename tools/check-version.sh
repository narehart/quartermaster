#!/usr/bin/env bash
# Verify .claude-plugin/plugin.json's `version` matches the latest CHANGELOG.md
# entry, so a release can't ship with the two out of sync.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

plugin_json="$REPO_ROOT/.claude-plugin/plugin.json"
changelog="$REPO_ROOT/CHANGELOG.md"

plugin_version="$(python3 -c "import json; print(json.load(open('$plugin_json'))['version'])")"
changelog_version="$(grep -m1 -E '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' "$changelog" | sed -E 's/^## \[([0-9]+\.[0-9]+\.[0-9]+)\].*/\1/')"

echo "plugin.json version:   $plugin_version"
echo "CHANGELOG.md version:  $changelog_version"

if [ -z "$changelog_version" ]; then
  echo "ERROR: could not find a '## [x.y.z]' heading in CHANGELOG.md"
  exit 1
fi

if [ "$plugin_version" != "$changelog_version" ]; then
  echo "ERROR: version mismatch — plugin.json ($plugin_version) != CHANGELOG.md ($changelog_version)"
  exit 1
fi

echo "PASS: versions match ($plugin_version)"
