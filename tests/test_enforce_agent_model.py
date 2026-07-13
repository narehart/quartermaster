"""Unit tests for scripts/enforce-agent-model.py's decide() (the PreToolUse
hook logic), plus one subprocess smoke test of the script end-to-end."""

import io
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "enforce-agent-model.py"


# ---------------------------------------------------------------------------
# decide()
# ---------------------------------------------------------------------------


def test_decide_pins_scout_to_haiku(enforce_agent_model: ModuleType):
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "scout"}}
    result = enforce_agent_model.decide(payload)
    assert result is not None
    assert result["hookSpecificOutput"]["updatedInput"]["model"] == "haiku"
    assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "scout" in result["systemMessage"]


def test_decide_pins_builder_to_sonnet(enforce_agent_model: ModuleType):
    payload = {"tool_name": "Task", "tool_input": {"subagent_type": "builder"}}
    result = enforce_agent_model.decide(payload)
    assert result is not None
    assert result["hookSpecificOutput"]["updatedInput"]["model"] == "sonnet"


def test_decide_matches_namespaced_agent_name(enforce_agent_model: ModuleType):
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "quartermaster:mechanic"}}
    result = enforce_agent_model.decide(payload)
    assert result is not None
    assert result["hookSpecificOutput"]["updatedInput"]["model"] == "haiku"
    # original raw (namespaced) name preserved in the system message
    assert "quartermaster:mechanic" in result["systemMessage"]
    # subagent_type itself is untouched -- only model is added
    assert result["hookSpecificOutput"]["updatedInput"]["subagent_type"] == "quartermaster:mechanic"


def test_decide_orchestrator_passes_through_unchanged(enforce_agent_model: ModuleType):
    """orchestrator runs at the session model on purpose -- TIER["orchestrator"]
    is None, meaning decide() returns None (pass-through), per the actual
    behavior of the original script (want is None -> no rewrite)."""
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "orchestrator"}}
    assert enforce_agent_model.decide(payload) is None


def test_decide_leaf_tier_already_pinned_passes_through(enforce_agent_model: ModuleType):
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "scout", "model": "haiku"},
    }
    assert enforce_agent_model.decide(payload) is None


def test_decide_non_roster_agent_passes_through(enforce_agent_model: ModuleType):
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "some-custom-agent"}}
    assert enforce_agent_model.decide(payload) is None


def test_decide_non_agent_tool_passes_through(enforce_agent_model: ModuleType):
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert enforce_agent_model.decide(payload) is None


def test_decide_missing_tool_name_passes_through(enforce_agent_model: ModuleType):
    assert enforce_agent_model.decide({}) is None


def test_decide_missing_tool_input_treated_as_empty(enforce_agent_model: ModuleType):
    payload = {"tool_name": "Agent"}
    # subagent_type missing -> bare "" -> not in TIER -> pass through
    assert enforce_agent_model.decide(payload) is None


def test_decide_cost_shadowed_builtin_agent_pinned(enforce_agent_model: ModuleType):
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "Explore"}}
    result = enforce_agent_model.decide(payload)
    assert result is not None
    assert result["hookSpecificOutput"]["updatedInput"]["model"] == "haiku"


def test_decide_does_not_mutate_caller_dict(enforce_agent_model: ModuleType):
    tool_input = {"subagent_type": "scout"}
    payload = {"tool_name": "Agent", "tool_input": tool_input}
    enforce_agent_model.decide(payload)
    assert "model" not in tool_input  # decide() copies tool_input, doesn't mutate it


# ---------------------------------------------------------------------------
# main() / subprocess smoke test
# ---------------------------------------------------------------------------


def test_main_writes_hook_json_for_roster_agent(
    enforce_agent_model: ModuleType,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "scout"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    enforce_agent_model.main()
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["hookSpecificOutput"]["updatedInput"]["model"] == "haiku"


def test_main_exits_cleanly_on_malformed_stdin(
    enforce_agent_model: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    with pytest.raises(SystemExit) as exc_info:
        enforce_agent_model.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_exits_cleanly_when_decide_passes_through(
    enforce_agent_model: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        enforce_agent_model.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_subprocess_smoke_test_roster_agent() -> None:
    payload = json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": "scout"}})
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], input=payload, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed["hookSpecificOutput"]["updatedInput"]["model"] == "haiku"


def test_subprocess_smoke_test_malformed_input_exits_zero_no_output() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], input="not json", capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert result.stdout == ""
