#!/usr/bin/env bash
# Apply the main-branch-protection ruleset (.github/rulesets/main.json) to
# narehart/quartermaster via the GitHub API. Manual-only: this mutates live
# branch protection, so it is intentionally not wired into `make verify` or
# any other automated target.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: not authenticated with the GitHub CLI. Run 'gh auth login' and try again." >&2
  exit 1
fi

echo "This will create a ruleset on narehart/quartermaster."
echo "You must have admin permission on the repository for this to succeed."

gh api -X POST repos/narehart/quartermaster/rulesets --input .github/rulesets/main.json
