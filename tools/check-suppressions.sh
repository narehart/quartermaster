#!/usr/bin/env bash
# Scan every tracked *.py and *.sh file for forbidden inline suppression
# directives. Suppressing a lint/type error inline hides the root cause
# instead of fixing it, so none of these are allowed anywhere in the repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SELF="tools/check-suppressions.sh"
HOOK_EXCLUDE=".claude/hooks/block-inline-suppressions.sh"

cd "$REPO_ROOT"

patterns=(
  '# type: ignore'
  '# noqa'
  '# pyright: ignore'
  '# ruff: noqa'
  '# shellcheck disable'
)

files=()
while IFS= read -r f; do
  files+=("$f")
done < <(git ls-files -- '*.py' '*.sh')

found=0

for f in "${files[@]}"; do
  [ "$f" = "$SELF" ] && continue
  [ "$f" = "$HOOK_EXCLUDE" ] && continue
  for p in "${patterns[@]}"; do
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      echo "$line"
      found=1
    done < <(grep -Hn -F -- "$p" "$f" || true)
  done
done

if [ "$found" -eq 1 ]; then
  echo "ERROR: forbidden inline suppression directives found (see above)"
  exit 1
fi

echo "PASS: no forbidden suppression directives found"
