#!/usr/bin/env bash
# Quartermaster certified output-tuning injection (SessionStart hook).
# Injects the certified efficiency block (tuned/EFFICIENCY-CLAUDE-MD.md,
# certified in bench/docs/PREREG_POWERED_TUNED.md / finding F9) as
# additionalContext, so every session in every project gets it with zero
# per-project setup. Emits a one-line nudge if MAX_THINKING_TOKENS (the
# certified companion setting) is not set.
set -euo pipefail
BLOCK_FILE="${CLAUDE_PLUGIN_ROOT:-.}/tuned/EFFICIENCY-CLAUDE-MD.md"
[ -f "$BLOCK_FILE" ] || exit 0
python3 - "$BLOCK_FILE" <<'PY'
import json
import os
import re
import sys

raw = open(sys.argv[1]).read()
# strip the provenance HTML comment; ship only the instruction text
block = re.sub(r"<!--.*?-->\s*", "", raw, count=1, flags=re.S)
out = {
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": block,
    }
}
if not os.environ.get("MAX_THINKING_TOKENS"):
    out["systemMessage"] = (
        "quartermaster tune: MAX_THINKING_TOKENS is not set - run "
        "/quartermaster:tune once to apply the certified thinking cap "
        "(user-level settings)"
    )
print(json.dumps(out))
PY
