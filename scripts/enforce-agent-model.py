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
from typing import Any

TIER: dict[str, str | None] = {
    "orchestrator": None,  # runs at the session model on purpose (it's the brain)
    "scout": "haiku",
    "mechanic": "haiku",
    "builder": "sonnet",
    # cost-shadowed built-ins (otherwise inherit the expensive session model)
    "explore": "haiku",
    "general-purpose": "sonnet",
    "claude-code-guide": "haiku",
}


def decide(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Compute the PreToolUse hook decision for one payload, or None to pass
    through untouched (non-Agent/Task tool calls, non-roster agents, and
    already-correctly-pinned calls)."""
    if payload.get("tool_name") not in ("Agent", "Task"):
        return None

    tool_input: dict[str, Any] = dict(payload.get("tool_input") or {})
    raw = tool_input.get("subagent_type", "") or ""
    bare = raw.split(":")[-1].strip().lower()  # quartermaster:scout -> scout

    if bare not in TIER:
        return None
    want = TIER[bare]
    if want is None or tool_input.get("model") == want:
        return None

    tool_input["model"] = want
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": tool_input,
        },
        "systemMessage": f"quartermaster: pinned {raw} to {want}",
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    result = decide(payload)
    if result is None:
        sys.exit(0)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
