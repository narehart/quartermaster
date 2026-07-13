"""Unit tests for the PURE logic in scripts/classify-mcp.py.

IO-heavy functions (run, list_tools_stdio, enumerate_headless, main, ...) are
covered only where cheap to mock (e.g. enumerate_transcripts via a stubbed
transcript_files()); genuinely subprocess/network-bound paths are left
uncovered per the project's own docstring guidance -- see the coverage note in
the task report.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "classify-mcp.py"


def _no_transcript_history(
    servers: list[dict[str, str]] | None = None,
) -> tuple[list[str] | None, list[str], list[str]]:
    """Stand-in for enumerate_transcripts() when no transcript has ever
    recorded a deferred_tools_delta -- the signal that tells enumerate_tools()
    to fall back to enumerate_headless()."""
    return None, [], []


# ---------------------------------------------------------------------------
# parse_mcp_servers
# ---------------------------------------------------------------------------


def test_parse_mcp_servers_handles_colons_and_spaces_in_names(classify_mcp: ModuleType):
    text = (
        "claude.ai Google Drive: https://example.com/gdrive - ✔ Connected\n"
        "plugin:slack:slack: https://mcp.slack.com/mcp (HTTP) - ! Needs authentication\n"
    )
    servers = classify_mcp.parse_mcp_servers(text)
    assert servers == [
        {"name": "claude.ai Google Drive", "status": "✔ Connected"},
        {"name": "plugin:slack:slack", "status": "! Needs authentication"},
    ]


def test_parse_mcp_servers_connected_vs_failed(classify_mcp: ModuleType):
    text = "server-a: stdio - ✔ Connected\nserver-b: stdio - ✘ Failed\n"
    servers = classify_mcp.parse_mcp_servers(text)
    assert servers[0]["status"] == "✔ Connected"
    assert servers[1]["status"] == "✘ Failed"


def test_parse_mcp_servers_skips_blank_and_unmatched_lines(classify_mcp: ModuleType):
    text = "\n   \nthis line matches nothing\n"
    assert classify_mcp.parse_mcp_servers(text) == []


def test_parse_mcp_servers_empty_text(classify_mcp: ModuleType):
    assert classify_mcp.parse_mcp_servers("") == []


def test_parse_mcp_servers_default_arg_calls_run(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """text=None -> falls back to `run(["claude", "mcp", "list"])`; mocked here
    so this never actually shells out to the `claude` CLI."""

    def _fake_run(cmd: list[str], timeout: int = 30) -> str:
        return "server-a: stdio - ✔ Connected\n"

    monkeypatch.setattr(classify_mcp, "run", _fake_run)
    assert classify_mcp.parse_mcp_servers() == [{"name": "server-a", "status": "✔ Connected"}]


# ---------------------------------------------------------------------------
# _norm / tool_segment / connected_display_names / tool_server_segments
# ---------------------------------------------------------------------------


def test_norm_strips_non_alnum_and_lowercases(classify_mcp: ModuleType):
    assert classify_mcp._norm("Claude.ai Google-Drive_2") == "claudeaigoogledrive2"
    assert classify_mcp._norm("plugin:slack:slack") == "pluginslackslack"


def test_tool_segment_extracts_server_from_full_name(classify_mcp: ModuleType):
    assert classify_mcp.tool_segment("mcp__slack__send_message") == "slack"
    assert classify_mcp.tool_segment("mcp__plugin_foo_slack__send_message") == "plugin_foo_slack"


@pytest.mark.parametrize("name", ["Bash", "mcp__onlytwoparts", ""])
def test_tool_segment_returns_empty_for_non_mcp_shaped_names(classify_mcp: ModuleType, name: str):
    assert classify_mcp.tool_segment(name) == ""


def test_connected_display_names_filters_by_status(classify_mcp: ModuleType):
    servers = [
        {"name": "a", "status": "✔ Connected"},
        {"name": "b", "status": "! Needs authentication"},
        {"name": "c", "status": "✘ Failed"},
    ]
    assert classify_mcp.connected_display_names(servers) == ["a"]


def test_tool_server_segments_ignores_non_mcp_tools(classify_mcp: ModuleType):
    tools = [
        {"name": "mcp__slack__send_message"},
        {"name": "mcp__gdrive__list_files"},
        {"name": "Bash"},
    ]
    assert classify_mcp.tool_server_segments(tools) == {"slack", "gdrive"}


def test_tool_server_segments_handles_none(classify_mcp: ModuleType):
    assert classify_mcp.tool_server_segments(None) == set()


# ---------------------------------------------------------------------------
# classify_by_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["list_files", "search_docs", "get_item", "read_file", "fetch_status"]
)
def test_classify_by_name_read_tier(classify_mcp: ModuleType, name: str):
    assert classify_mcp.classify_by_name(name) == "read"


@pytest.mark.parametrize(
    "name", ["create_item", "update_record", "send_message", "delete_file", "upload_doc"]
)
def test_classify_by_name_write_tier(classify_mcp: ModuleType, name: str):
    assert classify_mcp.classify_by_name(name) == "write"


def test_classify_by_name_unknown_name_defaults_to_write(classify_mcp: ModuleType):
    assert classify_mcp.classify_by_name("frobnicate") == "write"


# ---------------------------------------------------------------------------
# classify_proto
# ---------------------------------------------------------------------------


def test_classify_proto_read_only_hint_wins(classify_mcp: ModuleType):
    # name heuristic alone would call this "write" (delete_*); annotation overrides.
    tool = {"name": "delete_cached_thing", "annotations": {"readOnlyHint": True}}
    assert classify_mcp.classify_proto(tool) == "read"


def test_classify_proto_destructive_hint_wins(classify_mcp: ModuleType):
    # name heuristic alone would call this "read" (list_*); annotation overrides.
    tool = {"name": "list_things", "annotations": {"destructiveHint": True}}
    assert classify_mcp.classify_proto(tool) == "write"


def test_classify_proto_falls_back_to_name_heuristic_without_annotations(classify_mcp: ModuleType):
    assert classify_mcp.classify_proto({"name": "list_things"}) == "read"
    assert classify_mcp.classify_proto({"name": "delete_things"}) == "write"


def test_classify_proto_handles_missing_annotations_key(classify_mcp: ModuleType):
    assert classify_mcp.classify_proto({"name": "get_thing", "annotations": None}) == "read"


# ---------------------------------------------------------------------------
# assign
# ---------------------------------------------------------------------------


def test_assign_full_read_write_split(classify_mcp: ModuleType):
    tools = [
        {"name": "mcp__x__list_things", "tier": "read"},
        {"name": "mcp__x__delete_things", "tier": "write"},
        {"name": "mcp__y__get_data", "tier": "read"},
        {"name": "mcp__y__send_data", "tier": "write"},
    ]
    result = classify_mcp.assign(tools, {})
    assert result["scout"] == ["mcp__x__list_things", "mcp__y__get_data"]
    assert result["mechanic"] == ["mcp__x__delete_things", "mcp__y__send_data"]


def test_assign_tool_override_beats_tier(classify_mcp: ModuleType):
    tools = [{"name": "mcp__x__risky_thing", "tier": "read"}]
    policy = {"tools": {"mcp__x__risky_thing": "write"}}
    result = classify_mcp.assign(tools, policy)
    assert result["mechanic"] == ["mcp__x__risky_thing"]
    assert result["scout"] == []


def test_assign_server_override_beats_tier(classify_mcp: ModuleType):
    tools = [{"name": "mcp__x__anything", "tier": "write"}]
    policy = {"servers": {"x": "read"}}
    result = classify_mcp.assign(tools, policy)
    assert result["scout"] == ["mcp__x__anything"]


def test_assign_skip_tier_drops_tool_entirely(classify_mcp: ModuleType):
    tools = [{"name": "mcp__x__anything", "tier": "read"}]
    policy = {"servers": {"x": "skip"}}
    result = classify_mcp.assign(tools, policy)
    assert "mcp__x__anything" not in result["scout"]
    assert "mcp__x__anything" not in result["mechanic"]


def test_assign_dedupes_and_sorts(classify_mcp: ModuleType):
    tools = [
        {"name": "mcp__x__b", "tier": "read"},
        {"name": "mcp__x__a", "tier": "read"},
        {"name": "mcp__x__a", "tier": "read"},
    ]
    result = classify_mcp.assign(tools, {})
    assert result["scout"] == ["mcp__x__a", "mcp__x__b"]


# ---------------------------------------------------------------------------
# classify_builtins -- including the hard orchestrator-safety invariant
# ---------------------------------------------------------------------------


def test_classify_builtins_unknown_falls_to_mechanic_default(classify_mcp: ModuleType):
    assignment, unknown = classify_mcp.classify_builtins(["SomeBrandNewTool"], {})
    assert assignment["mechanic"] == ["SomeBrandNewTool"]
    assert unknown == ["SomeBrandNewTool"]
    assert assignment["orchestrator"] == []


def test_classify_builtins_curated_tool_can_grant_multiple_agents(classify_mcp: ModuleType):
    assignment, unknown = classify_mcp.classify_builtins(["LSP"], {})
    granted_to = {agent for agent, names in assignment.items() if "LSP" in names}
    assert granted_to == {"scout", "mechanic", "builder"}
    assert unknown == []


def test_classify_builtins_policy_override_replaces_curated_default(classify_mcp: ModuleType):
    # Monitor is curated to orchestrator by default; override it to scout only.
    policy = {"builtins": {"Monitor": "scout"}}
    assignment, _ = classify_mcp.classify_builtins(["Monitor"], policy)
    assert assignment["scout"] == ["Monitor"]
    assert assignment["orchestrator"] == []


def test_classify_builtins_orchestrator_never_gets_hard_denied_tools(classify_mcp: ModuleType):
    """The project's core safety property: no policy override, curated map, or
    unknown-builtin default can ever put Bash/Edit/Write/MultiEdit/NotebookEdit
    on the orchestrator."""
    policy = {
        "builtins": {
            "Bash": "orchestrator",
            "Edit": "orchestrator",
            "Write": "orchestrator",
            "MultiEdit": "orchestrator",
            "NotebookEdit": "orchestrator",
        }
    }
    assignment, _ = classify_mcp.classify_builtins(
        ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"], policy
    )
    assert assignment["orchestrator"] == []
    assert set(assignment["orchestrator"]).isdisjoint(classify_mcp.HARD_DENIED_ORCHESTRATOR_TOOLS)


def test_builtin_tiers_map_itself_never_lists_denied_tools_under_orchestrator(
    classify_mcp: ModuleType,
):
    """Static check on the curated map (defense in depth on top of the
    runtime-enforced invariant above)."""
    orchestrator_defaults = set(classify_mcp.BUILTIN_TIERS.get("orchestrator", []))
    assert orchestrator_defaults.isdisjoint(classify_mcp.HARD_DENIED_ORCHESTRATOR_TOOLS)


def test_classify_builtins_handles_none_names(classify_mcp: ModuleType):
    assignment, unknown = classify_mcp.classify_builtins(None, {})
    assert unknown == []
    assert all(v == [] for v in assignment.values())


# ---------------------------------------------------------------------------
# merge_tool_lists / merge_with_cache
# ---------------------------------------------------------------------------


def test_merge_tool_lists_union_no_duplicates_base_wins(classify_mcp: ModuleType):
    base = [{"name": "a", "tier": "read"}]
    extra = [{"name": "a", "tier": "write"}, {"name": "b", "tier": "write"}]
    merged = classify_mcp.merge_tool_lists(base, extra)
    by_name = {t["name"]: t for t in merged}
    assert set(by_name) == {"a", "b"}
    assert by_name["a"]["tier"] == "read"  # base entry wins on duplicate name


def test_merge_tool_lists_handles_none_inputs(classify_mcp: ModuleType):
    assert classify_mcp.merge_tool_lists(None, None) == []
    assert classify_mcp.merge_tool_lists([{"name": "a"}], None) == [{"name": "a"}]


def test_merge_with_cache_self_heals_incomplete_connected_server(classify_mcp: ModuleType):
    """Server 'y' returned fresh tools this run (trust it, drop stale cache
    entries for it); server 'x' returned nothing this run (still connecting
    or otherwise incomplete) so its cached tools must be preserved."""
    tools = [{"name": "mcp__y__list", "tier": "read"}]
    cache_tools = [
        {"name": "mcp__x__list", "tier": "read"},
        {"name": "mcp__y__old", "tier": "write"},
    ]
    merged = classify_mcp.merge_with_cache(tools, cache_tools)
    names = {t["name"] for t in merged}
    assert "mcp__x__list" in names  # preserved: no fresh data for x this run
    assert "mcp__y__old" not in names  # dropped: fresh data for y this run wins
    assert "mcp__y__list" in names


def test_merge_with_cache_no_cache_returns_tools_unchanged(classify_mcp: ModuleType):
    tools = [{"name": "a"}]
    assert classify_mcp.merge_with_cache(tools, None) == tools
    assert classify_mcp.merge_with_cache(None, None) == []


def test_merge_with_cache_no_duplicate_names(classify_mcp: ModuleType):
    tools = [{"name": "mcp__x__a", "tier": "read"}]
    cache_tools = [{"name": "mcp__x__a", "tier": "write"}, {"name": "mcp__z__b", "tier": "read"}]
    merged = classify_mcp.merge_with_cache(tools, cache_tools)
    names = [t["name"] for t in merged]
    assert names.count("mcp__x__a") == 1
    assert merged[names.index("mcp__x__a")]["tier"] == "read"  # this run's data, not cache's


# ---------------------------------------------------------------------------
# _transcript_deferred_names
# ---------------------------------------------------------------------------


def test_transcript_deferred_names_parses_delta_records_in_order(
    classify_mcp: ModuleType, tmp_path: Path
):
    transcript = tmp_path / "session.jsonl"
    records = [
        {
            "attachment": {
                "type": "deferred_tools_delta",
                "addedNames": ["mcp__slack__send_message", "LSP", "Monitor"],
                "needsAuthMcpServers": ["slack"],
            }
        },
        {
            "attachment": {
                "type": "deferred_tools_delta",
                "addedNames": ["mcp__gdrive__list_files"],
                "removedNames": ["mcp__slack__send_message", "Monitor"],
            }
        },
        {"unrelated": "record, not a deferred_tools_delta attachment"},
    ]
    transcript.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    names, builtin_names, needs_auth, saw_record = classify_mcp._transcript_deferred_names(
        transcript
    )
    assert names == {"mcp__gdrive__list_files"}  # slack's tool was removed later
    assert builtin_names == {"LSP"}  # Monitor was removed later
    assert needs_auth == ["slack"]
    assert saw_record is True


def test_transcript_deferred_names_no_delta_records(classify_mcp: ModuleType, tmp_path: Path):
    transcript = tmp_path / "empty.jsonl"
    transcript.write_text(json.dumps({"foo": "bar"}) + "\n")
    names, builtin_names, needs_auth, saw_record = classify_mcp._transcript_deferred_names(
        transcript
    )
    assert (names, builtin_names, needs_auth, saw_record) == (set(), set(), None, False)


def test_transcript_deferred_names_skips_malformed_lines(classify_mcp: ModuleType, tmp_path: Path):
    transcript = tmp_path / "mixed.jsonl"
    good = json.dumps({"attachment": {"type": "deferred_tools_delta", "addedNames": ["mcp__x__y"]}})
    transcript.write_text("not json at all\n" + good + "\n")
    names, _builtin_names, _needs_auth, saw_record = classify_mcp._transcript_deferred_names(
        transcript
    )
    assert names == {"mcp__x__y"}
    assert saw_record is True


def test_transcript_deferred_names_skips_blank_lines_and_wrong_attachment_type(
    classify_mcp: ModuleType, tmp_path: Path
):
    transcript = tmp_path / "mixed2.jsonl"
    good = json.dumps({"attachment": {"type": "deferred_tools_delta", "addedNames": ["mcp__x__y"]}})
    other_attachment = json.dumps({"attachment": {"type": "some_other_event"}})
    transcript.write_text(f"\n   \n{other_attachment}\n{good}\n")
    names, _builtin_names, _needs_auth, saw_record = classify_mcp._transcript_deferred_names(
        transcript
    )
    assert names == {"mcp__x__y"}
    assert saw_record is True


def test_transcript_deferred_names_unreadable_file_returns_empty(
    classify_mcp: ModuleType, tmp_path: Path
):
    missing = tmp_path / "does-not-exist.jsonl"
    result = classify_mcp._transcript_deferred_names(missing)
    assert result == (set(), set(), None, False)


def test_transcript_deferred_names_ignores_non_string_added_names(
    classify_mcp: ModuleType, tmp_path: Path
):
    transcript = tmp_path / "weird.jsonl"
    transcript.write_text(
        json.dumps(
            {"attachment": {"type": "deferred_tools_delta", "addedNames": [123, None, "LSP"]}}
        )
        + "\n"
    )
    names, builtin_names, _needs_auth, _saw_record = classify_mcp._transcript_deferred_names(
        transcript
    )
    assert names == set()
    assert builtin_names == {"LSP"}


# ---------------------------------------------------------------------------
# enumerate_transcripts (transcript_files() stubbed out -- no real filesystem
# scan of ~/.claude/projects)
# ---------------------------------------------------------------------------


def test_enumerate_transcripts_unions_newest_first_and_filters_stale_servers(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    newest = tmp_path / "newest.jsonl"
    older = tmp_path / "older.jsonl"
    newest.write_text(
        json.dumps(
            {
                "attachment": {
                    "type": "deferred_tools_delta",
                    "addedNames": ["mcp__slack__send", "Monitor"],
                }
            }
        )
        + "\n"
    )
    older.write_text(
        json.dumps(
            {
                "attachment": {
                    "type": "deferred_tools_delta",
                    "addedNames": ["mcp__gdrive__list", "mcp__oldserver__list"],
                }
            }
        )
        + "\n"
    )
    monkeypatch.setattr(classify_mcp, "transcript_files", lambda: [newest, older])

    configured = [
        {"name": "slack", "status": "✔ Connected"},
        {"name": "gdrive", "status": "✔ Connected"},
    ]
    names, needs_auth, builtin_names = classify_mcp.enumerate_transcripts(configured)
    assert names == ["mcp__gdrive__list", "mcp__slack__send"]
    assert "mcp__oldserver__list" not in names  # stale server filtered out
    assert builtin_names == ["Monitor"]
    assert needs_auth == []


def test_enumerate_transcripts_skips_transcripts_with_no_delta_records(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    no_record = tmp_path / "no_record.jsonl"
    has_record = tmp_path / "has_record.jsonl"
    no_record.write_text(json.dumps({"some": "unrelated record"}) + "\n")
    has_record.write_text(
        json.dumps({"attachment": {"type": "deferred_tools_delta", "addedNames": ["mcp__x__y"]}})
        + "\n"
    )
    monkeypatch.setattr(classify_mcp, "transcript_files", lambda: [no_record, has_record])
    names, _needs_auth, _builtin_names = classify_mcp.enumerate_transcripts(None)
    assert names == ["mcp__x__y"]


def test_enumerate_transcripts_returns_none_with_no_history_anywhere(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(classify_mcp, "transcript_files", list)
    names, needs_auth, builtin_names = classify_mcp.enumerate_transcripts(None)
    assert names is None
    assert needs_auth == []
    assert builtin_names == []


def test_enumerate_transcripts_stops_early_once_all_configured_servers_covered(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    covers_all = tmp_path / "covers_all.jsonl"
    never_read = tmp_path / "never_read.jsonl"
    covers_all.write_text(
        json.dumps(
            {"attachment": {"type": "deferred_tools_delta", "addedNames": ["mcp__slack__send"]}}
        )
        + "\n"
    )

    def _boom() -> None:
        raise AssertionError("never_read.jsonl should not have been opened")

    # never_read is a callable stand-in checked only if enumerate_transcripts
    # actually tries to open a 2nd transcript after the 1st already satisfied
    # every configured server.
    monkeypatch.setattr(classify_mcp, "transcript_files", lambda: [covers_all, never_read])
    original = classify_mcp._transcript_deferred_names

    def _guarded(path: Path):
        if path is never_read:
            _boom()
        return original(path)

    monkeypatch.setattr(classify_mcp, "_transcript_deferred_names", _guarded)

    configured = [{"name": "slack", "status": "✔ Connected"}]
    names, _needs_auth, _builtin_names = classify_mcp.enumerate_transcripts(configured)
    assert names == ["mcp__slack__send"]


# ---------------------------------------------------------------------------
# incomplete_connected_servers / status_category / server_hash
# ---------------------------------------------------------------------------


def test_incomplete_connected_servers_detects_zero_tool_connected_server(classify_mcp: ModuleType):
    statuses = [
        {"name": "slack", "status": "✔ Connected"},
        {"name": "gdrive", "status": "✔ Connected"},
    ]
    tools = [{"name": "mcp__gdrive__list"}]
    assert classify_mcp.incomplete_connected_servers(statuses, tools) == ["slack"]


def test_incomplete_connected_servers_empty_when_all_covered(classify_mcp: ModuleType):
    statuses = [{"name": "slack", "status": "✔ Connected"}]
    tools = [{"name": "mcp__slack__send"}]
    assert classify_mcp.incomplete_connected_servers(statuses, tools) == []


def test_incomplete_connected_servers_ignores_non_connected(classify_mcp: ModuleType):
    statuses = [{"name": "slack", "status": "! Needs authentication"}]
    assert classify_mcp.incomplete_connected_servers(statuses, []) == []


@pytest.mark.parametrize(
    "status,expected",
    [
        ("✔ Connected", "connected"),
        ("! Needs authentication", "needs authentication"),
        ("✘ Failed", "failed"),
        ("Connecting...", "connecting"),
        ("Checking", "connecting"),
        ("something else entirely", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_status_category_buckets(classify_mcp: ModuleType, status: str | None, expected: str):
    assert classify_mcp.status_category(status) == expected


def test_server_hash_changes_when_status_changes_not_just_name_set(classify_mcp: ModuleType):
    needs_auth_servers = [{"name": "slack", "status": "! Needs authentication"}]
    connected_servers = [{"name": "slack", "status": "✔ Connected"}]
    hash_a, _ = classify_mcp.server_hash(needs_auth_servers)
    hash_b, _ = classify_mcp.server_hash(connected_servers)
    assert hash_a != hash_b


def test_server_hash_is_order_independent(classify_mcp: ModuleType):
    a = [{"name": "slack", "status": "✔ Connected"}, {"name": "gdrive", "status": "✔ Connected"}]
    b = list(reversed(a))
    hash_a, _ = classify_mcp.server_hash(a)
    hash_b, _ = classify_mcp.server_hash(b)
    assert hash_a == hash_b


def test_server_hash_returns_servers_passed_through(classify_mcp: ModuleType):
    servers = [{"name": "slack", "status": "✔ Connected"}]
    _h, returned = classify_mcp.server_hash(servers)
    assert returned == servers


def test_server_hash_default_arg_calls_parse_mcp_servers(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    servers = [{"name": "slack", "status": "✔ Connected"}]
    monkeypatch.setattr(classify_mcp, "parse_mcp_servers", lambda: servers)
    _h, returned = classify_mcp.server_hash()
    assert returned == servers


# ---------------------------------------------------------------------------
# generate_agents -- TEMPLATES/AGENTS_DIR monkeypatched to tmp_path, so this
# never touches the real ~/.claude/agents or the repo's templates/.
# ---------------------------------------------------------------------------


def test_generate_agents_appends_tools_without_duplicating_existing(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    templates = tmp_path / "templates"
    agents = tmp_path / "agents"
    templates.mkdir()
    (templates / "scout.md").write_text("---\nname: scout\ntools: Read, Grep\n---\nbody\n")
    (templates / "mechanic.md").write_text("---\nname: mechanic\ntools: Bash\n---\nbody\n")
    monkeypatch.setattr(classify_mcp, "TEMPLATES", templates)
    monkeypatch.setattr(classify_mcp, "AGENTS_DIR", agents)

    mcp_assignment = {"scout": ["mcp__gdrive__list_files"], "mechanic": ["mcp__gdrive__delete"]}
    builtin_assignment = {"scout": ["Read"], "mechanic": ["NotebookEdit"]}
    classify_mcp.generate_agents(mcp_assignment, builtin_assignment)

    scout_content = (agents / "scout.md").read_text()
    assert "mcp__gdrive__list_files" in scout_content
    # "Read" was already in the template's tools: line -- must not be duplicated
    assert scout_content.count("Read") == 1

    mechanic_content = (agents / "mechanic.md").read_text()
    assert "mcp__gdrive__delete" in mechanic_content
    assert "NotebookEdit" in mechanic_content


def test_generate_agents_skips_missing_template(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    templates = tmp_path / "templates"
    agents = tmp_path / "agents"
    templates.mkdir()
    # no builder.md template on disk at all
    monkeypatch.setattr(classify_mcp, "TEMPLATES", templates)
    monkeypatch.setattr(classify_mcp, "AGENTS_DIR", agents)

    classify_mcp.generate_agents({"builder": ["mcp__x__y"]}, {})
    assert not (agents / "builder.md").exists()


def test_generate_agents_leaves_template_untouched_when_nothing_to_add(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    templates = tmp_path / "templates"
    agents = tmp_path / "agents"
    templates.mkdir()
    original = "---\nname: orchestrator\ntools: Read, Grep\n---\nbody\n"
    (templates / "orchestrator.md").write_text(original)
    monkeypatch.setattr(classify_mcp, "TEMPLATES", templates)
    monkeypatch.setattr(classify_mcp, "AGENTS_DIR", agents)

    classify_mcp.generate_agents({}, {})
    assert (agents / "orchestrator.md").read_text() == original


# ---------------------------------------------------------------------------
# write_routing -- STATE_DIR/ROUTING monkeypatched to tmp_path.
# ---------------------------------------------------------------------------


def test_write_routing_covers_every_advisory_section(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_dir = tmp_path / "state"
    routing = state_dir / "TOOL-ROUTING.md"
    monkeypatch.setattr(classify_mcp, "STATE_DIR", state_dir)
    monkeypatch.setattr(classify_mcp, "ROUTING", routing)

    tools = [
        {"name": "mcp__gdrive__list_files", "tier": "read"},
        {"name": "mcp__gdrive__delete_file", "tier": "write"},
        {"name": "Bash", "tier": "write"},  # non-mcp-shaped name -> skipped, not a server row
    ]
    assignment = {"scout": ["mcp__gdrive__list_files"], "mechanic": ["mcp__gdrive__delete_file"]}
    servers = [
        {"name": "gdrive", "status": "✔ Connected"},
        {"name": "slack", "status": "! Needs authentication"},
        {"name": "flaky", "status": "Connecting..."},
        {"name": "broken", "status": "✘ Failed"},
        {"name": "empty-but-connected", "status": "✔ Connected"},
        # connected per `claude mcp list`, but transcript flagged it needs-auth
        {"name": "transcript-flagged", "status": "✔ Connected"},
    ]
    needs_auth = ["slack", "transcript-flagged"]
    builtin_assignment = {
        "orchestrator": ["Monitor"],
        "scout": ["LSP"],
        "mechanic": ["NotebookEdit"],
        "builder": [],
    }
    unknown_builtins = ["SomeNewTool"]

    classify_mcp.write_routing(
        tools, assignment, servers, needs_auth, builtin_assignment, unknown_builtins
    )

    content = routing.read_text()
    assert "| gdrive | 1 | 1 |" in content
    assert "needs authentication; authorize via /mcp then re-run the classifier" in content
    assert "still connecting; re-run the classifier once it settles" in content
    assert "failed to connect" in content
    assert "needs authentication per session transcript" in content
    assert "declare a tier in mcp-policy.json if expected" in content
    assert "## Built-in tools" in content
    assert "| orchestrator | Monitor |" in content
    assert "### Unknown built-ins (fell to mechanic default)" in content
    assert "SomeNewTool" in content


def test_write_routing_stale_grant_needs_auth_section(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A server with an existing grant (nonzero row) that currently needs auth
    gets the separate 'granted but needs auth' advisory, not the zero-tool one."""
    state_dir = tmp_path / "state"
    routing = state_dir / "TOOL-ROUTING.md"
    monkeypatch.setattr(classify_mcp, "STATE_DIR", state_dir)
    monkeypatch.setattr(classify_mcp, "ROUTING", routing)

    tools = [{"name": "mcp__slack__list_channels", "tier": "read"}]
    assignment = {"scout": ["mcp__slack__list_channels"], "mechanic": []}
    servers = [{"name": "slack", "status": "! Needs authentication"}]

    classify_mcp.write_routing(tools, assignment, servers)

    content = routing.read_text()
    assert "## Granted but currently needs authentication" in content
    assert "slack" in content
    assert "## Configured, zero tools enumerated" not in content


def test_write_routing_no_servers_no_advisories(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_dir = tmp_path / "state"
    routing = state_dir / "TOOL-ROUTING.md"
    monkeypatch.setattr(classify_mcp, "STATE_DIR", state_dir)
    monkeypatch.setattr(classify_mcp, "ROUTING", routing)

    classify_mcp.write_routing([], {}, [])

    content = routing.read_text()
    assert "## Configured, zero tools enumerated" not in content
    assert "## Granted but currently needs authentication" not in content
    assert "(none)" in content  # every agent row falls back to "(none)"


# ---------------------------------------------------------------------------
# wait_for_settled -- parse_mcp_servers() mocked, real intervals kept at 0 so
# the test doesn't actually sleep.
# ---------------------------------------------------------------------------


def test_wait_for_settled_returns_once_stable_across_confirm_polls(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    settled = [{"name": "slack", "status": "✔ Connected"}]
    monkeypatch.setattr(classify_mcp, "parse_mcp_servers", lambda: settled)
    result = classify_mcp.wait_for_settled(timeout=5, interval=0, confirm=1)
    assert result == settled


def test_wait_for_settled_gives_up_at_deadline_if_never_stable(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        # a server that keeps flapping between two statuses never settles
        status = "Connecting..." if calls["n"] % 2 else "✔ Connected"
        return [{"name": "slack", "status": status}]

    monkeypatch.setattr(classify_mcp, "parse_mcp_servers", _flaky)
    result = classify_mcp.wait_for_settled(timeout=0.05, interval=0.01, confirm=2)
    assert result[0]["name"] == "slack"
    assert calls["n"] > 1


# ---------------------------------------------------------------------------
# load_servers / load_policy -- light IO-touching coverage, filesystem mocked
# via monkeypatched module constants (never touches the real ~/.claude).
# ---------------------------------------------------------------------------


def test_load_servers_merges_claude_json_and_mcp_json(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"slack": {"command": "slack-mcp"}}})
    )
    (cwd / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"gdrive": {"command": "gdrive-mcp"}}})
    )
    monkeypatch.setattr(classify_mcp, "HOME", home)
    monkeypatch.chdir(cwd)

    servers = classify_mcp.load_servers()
    assert servers["slack"]["command"] == "slack-mcp"
    assert servers["gdrive"]["command"] == "gdrive-mcp"


def test_load_servers_skips_malformed_config(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text("{not valid json")
    monkeypatch.setattr(classify_mcp, "HOME", home)
    monkeypatch.chdir(tmp_path)

    assert classify_mcp.load_servers() == {}


def test_load_policy_reads_existing_file(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    policy_path = tmp_path / "mcp-policy.json"
    policy_path.write_text(json.dumps({"tiers": {"read": "scout"}}))
    monkeypatch.setattr(classify_mcp, "POLICY", policy_path)
    assert classify_mcp.load_policy() == {"tiers": {"read": "scout"}}


def test_load_policy_missing_file_returns_empty_dict(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(classify_mcp, "POLICY", tmp_path / "missing.json")
    assert classify_mcp.load_policy() == {}


# ---------------------------------------------------------------------------
# transcript_files -- real filesystem glob, but scoped to a monkeypatched
# HOME under tmp_path so it never touches the real ~/.claude.
# ---------------------------------------------------------------------------


def test_transcript_files_lists_jsonl_newest_first(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "home"
    project_dir = home / ".claude" / "projects" / "some-project"
    project_dir.mkdir(parents=True)
    old = project_dir / "old.jsonl"
    new = project_dir / "new.jsonl"
    old.write_text("{}\n")
    new.write_text("{}\n")
    old_time = 1_700_000_000
    new_time = 1_700_000_100
    os.utime(old, (old_time, old_time))
    os.utime(new, (new_time, new_time))
    monkeypatch.setattr(classify_mcp, "HOME", home)

    files = classify_mcp.transcript_files()
    assert files == [new, old]


def test_transcript_files_empty_when_no_projects_dir(
    classify_mcp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(classify_mcp, "HOME", tmp_path / "empty-home")
    assert classify_mcp.transcript_files() == []


# ---------------------------------------------------------------------------
# enumerate_tools -- dependencies (load_servers, list_tools_stdio,
# enumerate_transcripts, enumerate_headless) mocked; this function's own
# merge/trust-order logic is real logic worth covering, not just plumbing.
# ---------------------------------------------------------------------------


def test_enumerate_tools_prefers_transcript_names_and_backfills_proto(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    def _fake_load_servers() -> dict[str, dict[str, Any]]:
        return {"slack": {"command": "slack-mcp", "args": []}}

    def _fake_list_tools_stdio(
        command: str, args: list[str], env: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return [{"name": "send_message", "annotations": {"destructiveHint": True}}]

    def _fake_enumerate_transcripts(
        servers: list[dict[str, str]] | None = None,
    ) -> tuple[list[str] | None, list[str], list[str]]:
        return ["mcp__slack__list_channels"], ["slack"], ["Monitor"]

    monkeypatch.setattr(classify_mcp, "load_servers", _fake_load_servers)
    monkeypatch.setattr(classify_mcp, "list_tools_stdio", _fake_list_tools_stdio)
    monkeypatch.setattr(classify_mcp, "enumerate_transcripts", _fake_enumerate_transcripts)

    tools, needs_auth, builtin_names = classify_mcp.enumerate_tools(None)
    assert tools is not None
    names = {t["name"] for t in tools}
    # transcript-reported name is present, classified by the name heuristic
    assert "mcp__slack__list_channels" in names
    listed = next(t for t in tools if t["name"] == "mcp__slack__list_channels")
    assert listed["tier"] == "read"
    # proto-confirmed tool the transcript replay missed is backfilled in,
    # keeping the protocol-confirmed (destructive -> write) tier
    assert "mcp__slack__send_message" in names
    backfilled = next(t for t in tools if t["name"] == "mcp__slack__send_message")
    assert backfilled["tier"] == "write"
    assert needs_auth == ["slack"]
    assert builtin_names == ["Monitor"]


def test_enumerate_tools_falls_back_to_headless_when_no_transcript_history(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(classify_mcp, "load_servers", dict)
    monkeypatch.setattr(classify_mcp, "enumerate_transcripts", _no_transcript_history)
    monkeypatch.setattr(
        classify_mcp,
        "enumerate_headless",
        lambda: [{"name": "mcp__gdrive__list_files", "tier": "read"}],
    )

    tools, _needs_auth, _builtin_names = classify_mcp.enumerate_tools(None)
    assert tools == [{"name": "mcp__gdrive__list_files", "tier": "read"}]


def test_enumerate_tools_headless_path_backfills_proto_confirmed_tools(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    def _fake_load_servers() -> dict[str, dict[str, Any]]:
        return {"gdrive": {"command": "gdrive-mcp", "args": []}}

    def _fake_list_tools_stdio(
        command: str, args: list[str], env: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return [{"name": "list_files", "annotations": {"readOnlyHint": True}}]

    monkeypatch.setattr(classify_mcp, "load_servers", _fake_load_servers)
    monkeypatch.setattr(classify_mcp, "list_tools_stdio", _fake_list_tools_stdio)
    monkeypatch.setattr(classify_mcp, "enumerate_transcripts", _no_transcript_history)
    # headless reports a DIFFERENT tool for the same server; the proto-confirmed
    # one it missed must still be backfilled in.
    monkeypatch.setattr(
        classify_mcp,
        "enumerate_headless",
        lambda: [{"name": "mcp__gdrive__share_file", "tier": "write"}],
    )

    tools, _needs_auth, _builtin_names = classify_mcp.enumerate_tools(None)
    assert tools is not None
    names = {t["name"] for t in tools}
    assert "mcp__gdrive__share_file" in names
    assert "mcp__gdrive__list_files" in names  # backfilled from proto


def test_enumerate_tools_returns_none_when_nothing_found_anywhere(
    classify_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(classify_mcp, "load_servers", dict)
    monkeypatch.setattr(classify_mcp, "enumerate_transcripts", _no_transcript_history)
    monkeypatch.setattr(classify_mcp, "enumerate_headless", list)

    tools, needs_auth, builtin_names = classify_mcp.enumerate_tools(None)
    assert tools is None
    assert needs_auth == []
    assert builtin_names == []


# ---------------------------------------------------------------------------
# Reentrancy guard (module-level `if QUARTERMASTER_CLASSIFYING: sys.exit(0)`)
# -- exercised via a real subprocess since it fires at import time, before
# any monkeypatching in-process could reach it.
# ---------------------------------------------------------------------------


def test_reentrancy_guard_exits_immediately_when_env_var_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-process import with the env var set, so coverage actually sees the
    module-level `sys.exit(0)` guard execute (a subprocess child wouldn't be
    tracked by coverage.py without extra machinery)."""
    import importlib.util

    monkeypatch.setenv("QUARTERMASTER_CLASSIFYING", "1")
    spec = importlib.util.spec_from_file_location("classify_mcp_reentrancy_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(SystemExit) as exc_info:
        spec.loader.exec_module(module)
    assert exc_info.value.code == 0


def test_reentrancy_guard_exits_immediately_when_env_var_set_subprocess() -> None:
    """Companion end-to-end smoke test via a real subprocess, matching how the
    SessionStart hook actually re-invokes this script."""
    env = dict(os.environ)
    env["QUARTERMASTER_CLASSIFYING"] = "1"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--print"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout == ""


# ---------------------------------------------------------------------------
# main() -- every collaborator (server_hash, wait_for_settled, enumerate_tools,
# generate_agents, write_routing, TEMPLATES) mocked/redirected to tmp_path;
# this exercises main()'s own cache-hit / cache-miss / retry / --print glue
# logic, which is real branching worth covering, without doing any real
# subprocess/network work.
# ---------------------------------------------------------------------------


def test_main_cache_hit_skips_reenumeration(
    classify_mcp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    cache_path = state_dir / "cache.json"
    servers = [{"name": "gdrive", "status": "✔ Connected"}]
    cached_tools = [{"name": "mcp__gdrive__list_files", "tier": "read"}]
    fixed_hash = "deadbeef"
    cache_path.write_text(
        json.dumps(
            {"hash": fixed_hash, "tools": cached_tools, "needs_auth": [], "builtin_names": []}
        )
    )

    monkeypatch.setattr(classify_mcp, "STATE_DIR", state_dir)
    monkeypatch.setattr(classify_mcp, "CACHE", cache_path)
    monkeypatch.setattr(classify_mcp, "ROUTING", state_dir / "TOOL-ROUTING.md")
    monkeypatch.setattr(classify_mcp, "POLICY", tmp_path / "no-policy.json")
    monkeypatch.setattr(classify_mcp, "TEMPLATES", tmp_path / "no-templates")
    monkeypatch.setattr(classify_mcp, "AGENTS_DIR", tmp_path / "agents")

    def _fake_server_hash(
        s: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        return fixed_hash, s or servers

    def _fake_parse_mcp_servers() -> list[dict[str, str]]:
        return servers

    def _must_not_be_called(*_a: object, **_k: object) -> None:
        raise AssertionError("cache-hit path must not re-enumerate")

    monkeypatch.setattr(classify_mcp, "server_hash", _fake_server_hash)
    monkeypatch.setattr(classify_mcp, "parse_mcp_servers", _fake_parse_mcp_servers)
    monkeypatch.setattr(classify_mcp, "wait_for_settled", _must_not_be_called)
    monkeypatch.setattr(classify_mcp, "enumerate_tools", _must_not_be_called)
    monkeypatch.setattr(sys, "argv", ["classify-mcp.py"])

    classify_mcp.main()

    out = capsys.readouterr().out
    assert "1 MCP tools classified across 1 servers" in out
    saved = json.loads(cache_path.read_text())
    assert saved["hash"] == fixed_hash
    assert saved["tools"] == cached_tools


def test_main_cache_miss_reenumerates_and_retries_incomplete_servers(
    classify_mcp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    state_dir = tmp_path / "state"
    cache_path = state_dir / "cache.json"  # no cache file yet -> guaranteed miss

    settled_servers = [{"name": "gdrive", "status": "✔ Connected"}]
    monkeypatch.setattr(classify_mcp, "STATE_DIR", state_dir)
    monkeypatch.setattr(classify_mcp, "CACHE", cache_path)
    monkeypatch.setattr(classify_mcp, "ROUTING", state_dir / "TOOL-ROUTING.md")
    monkeypatch.setattr(classify_mcp, "POLICY", tmp_path / "no-policy.json")
    monkeypatch.setattr(classify_mcp, "TEMPLATES", tmp_path / "no-templates")
    monkeypatch.setattr(classify_mcp, "AGENTS_DIR", tmp_path / "agents")

    def _fake_server_hash(
        s: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        return "newhash", settled_servers

    def _fake_wait_for_settled() -> list[dict[str, str]]:
        return settled_servers

    def _fake_parse_mcp_servers() -> list[dict[str, str]]:
        return settled_servers

    monkeypatch.setattr(classify_mcp, "server_hash", _fake_server_hash)
    monkeypatch.setattr(classify_mcp, "wait_for_settled", _fake_wait_for_settled)
    monkeypatch.setattr(classify_mcp, "parse_mcp_servers", _fake_parse_mcp_servers)
    monkeypatch.setattr(classify_mcp, "RETRY_WAIT", 0)

    call_count = {"n": 0}

    def _fake_enumerate_tools(
        servers: list[dict[str, str]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # first pass: gdrive connected but returned nothing yet (still settling)
            return [], [], []
        # retry: gdrive's tools show up
        return [{"name": "mcp__gdrive__list_files", "tier": "read"}], [], []

    monkeypatch.setattr(classify_mcp, "enumerate_tools", _fake_enumerate_tools)
    monkeypatch.setattr(sys, "argv", ["classify-mcp.py"])

    classify_mcp.main()

    assert call_count["n"] == 2  # one initial pass + one retry
    out = capsys.readouterr().out
    assert "1 MCP tools classified across 1 servers" in out
    saved = json.loads(cache_path.read_text())
    assert saved["tools"] == [{"name": "mcp__gdrive__list_files", "tier": "read"}]


def test_main_print_flag_writes_routing_and_prints_it_without_regenerating_agents(
    classify_mcp: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    cache_path = state_dir / "cache.json"
    servers = [{"name": "gdrive", "status": "✔ Connected"}]
    cached_tools = [{"name": "mcp__gdrive__list_files", "tier": "read"}]
    fixed_hash = "deadbeef"
    cache_path.write_text(
        json.dumps(
            {"hash": fixed_hash, "tools": cached_tools, "needs_auth": [], "builtin_names": []}
        )
    )
    agents_dir = tmp_path / "agents"

    monkeypatch.setattr(classify_mcp, "STATE_DIR", state_dir)
    monkeypatch.setattr(classify_mcp, "CACHE", cache_path)
    monkeypatch.setattr(classify_mcp, "ROUTING", state_dir / "TOOL-ROUTING.md")
    monkeypatch.setattr(classify_mcp, "POLICY", tmp_path / "no-policy.json")
    monkeypatch.setattr(classify_mcp, "AGENTS_DIR", agents_dir)

    def _fake_server_hash(
        s: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        return fixed_hash, s or servers

    monkeypatch.setattr(classify_mcp, "server_hash", _fake_server_hash)
    monkeypatch.setattr(classify_mcp, "parse_mcp_servers", lambda: servers)

    def _must_not_be_called(
        mcp_assignment: dict[str, list[str]], builtin_assignment: dict[str, list[str]]
    ) -> None:
        raise AssertionError("--print must not regenerate agents")

    monkeypatch.setattr(classify_mcp, "generate_agents", _must_not_be_called)
    monkeypatch.setattr(sys, "argv", ["classify-mcp.py", "--print"])

    classify_mcp.main()

    out = capsys.readouterr().out
    assert "| gdrive | 1 | 0 |" in out
    assert not agents_dir.exists()
