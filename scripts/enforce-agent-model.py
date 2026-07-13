#!/usr/bin/env python3
"""PreToolUse hook on the Agent tool: hard-enforce the cost-tier roster.

Frontmatter `model:` pins have silently regressed before (claude-code #44385),
and a session-level model inherit means an unpinned sub-agent runs at the
expensive session model. This hook rewrites every spawn of a known agent to its
pinned tier, whatever the caller passed. It also pins the built-in agents
(Explore / general-purpose / claude-code-guide) so they stop inheriting the
session model. Non-roster agents pass through untouched.

Namespace-robust: a plugin agent may arrive as "quartermaster:scout"; we match on
the bare name after the last ':'.
"""
import json
import sys

TIER = {
    "orchestrator": None,      # runs at the session model on purpose (it's the brain)
    "scout": "haiku",
    "mechanic": "haiku",
    "builder": "sonnet",
    # cost-shadowed built-ins (otherwise inherit the expensive session model)
    "explore": "haiku",
    "general-purpose": "sonnet",
    "claude-code-guide": "haiku",
}

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

if data.get("tool_name") not in ("Agent", "Task"):
    sys.exit(0)

tool_input = dict(data.get("tool_input") or {})
raw = tool_input.get("subagent_type", "") or ""
bare = raw.split(":")[-1].strip().lower()   # quartermaster:scout -> scout

if bare not in TIER:
    sys.exit(0)
want = TIER[bare]
if want is None or tool_input.get("model") == want:
    sys.exit(0)

tool_input["model"] = want
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": tool_input,
    },
    "systemMessage": f"quartermaster: pinned {raw} to {want}",
}))
