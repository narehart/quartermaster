#!/usr/bin/env bash
# PreToolUse hook for Edit/Write/MultiEdit: block any call whose new content
# introduces a forbidden inline suppression directive. tools/check-suppressions.sh
# enforces the same list repo-wide at `make verify` time; this catches it
# before the write ever lands. This file is the one place in the repo the
# forbidden strings below are allowed to appear, since they're matched
# against as data, not used as directives -- see tools/check-suppressions.sh's
# exclusion list.
set -euo pipefail

payload_file="$(mktemp)"
trap 'rm -f "$payload_file"' EXIT

cat >"$payload_file"

python3 - "$payload_file" <<'PYEOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    payload = json.load(fh)

if payload.get("tool_name") not in ("Edit", "Write", "MultiEdit"):
    sys.exit(0)

patterns = [
    "# type: ignore",
    "# noqa",
    "# pyright: ignore",
    "# ruff: noqa",
    "# shellcheck disable",
]

tool_input = payload.get("tool_input") or {}
texts = []
for key in ("content", "new_string", "file_text"):
    value = tool_input.get(key)
    if isinstance(value, str):
        texts.append(value)
for edit in tool_input.get("edits") or []:
    if not isinstance(edit, dict):
        continue
    for key in ("new_string", "file_text"):
        value = edit.get(key)
        if isinstance(value, str):
            texts.append(value)

hit = next((p for text in texts for p in patterns if p in text), None)
if hit is None:
    sys.exit(0)

decision = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"blocked: new content contains forbidden inline suppression "
            f"directive '{hit}' (see tools/check-suppressions.sh)"
        ),
    }
}
print(json.dumps(decision))
PYEOF
