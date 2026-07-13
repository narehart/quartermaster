# AGENTS.md

Canonical contributor + agent guide for Quartermaster. Read this before
touching anything in the repo.

## Overview

Quartermaster is a Claude Code plugin that provides least-privilege tool
tiering and enforced delegation. A tool-restricted `orchestrator` (runs as
the main thread, holds no Edit/Write/Bash and no MCP tools) delegates all
execution to cheap tiered sub-agents — `scout` (Haiku, read-only tools +
read-only MCP tools), `mechanic` (Haiku, shell + mechanical edits + write MCP
tools), and `builder` (Sonnet, well-specified implementation). `scripts/
classify-mcp.py` enumerates and classifies every MCP tool and built-in tool,
writing read tools into `scout` and write tools into `mechanic`; `scripts/
enforce-agent-model.py` is a PreToolUse hook that pins agent models so a
cheap-tier agent can't silently run on an expensive one.

## Development setup

```bash
make setup   # pip install -r requirements-dev.txt, plus shellcheck/shfmt/gitleaks via brew
make verify  # run before every commit/PR
```

`make verify` runs, in order:

- `format-check` — `ruff format --check .`
- `lint` — `ruff check .`
- `typecheck` — `pyright` (strict mode)
- `test` — `pytest` with an >=80% coverage floor (`--cov-fail-under=80`)
- `shellcheck` — `install.sh uninstall.sh tools/*.sh`
- `shfmt` — `shfmt -d -i 2` diff-check over the same shell files
- `config-check` — `tools/check-config.sh`: every JSON config in the plugin
  (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
  `hooks/hooks.json`, `mcp-policy.example.json`) parses cleanly, plus `claude
  plugin validate .` if the `claude` CLI is on PATH
- `version-check` — `tools/check-version.sh`: `.claude-plugin/plugin.json`'s
  `version` matches the latest `## [x.y.z]` heading in `CHANGELOG.md`
- `suppressions-check` — `tools/check-suppressions.sh`: no forbidden inline
  suppression directive anywhere in a tracked `*.py`/`*.sh` file
- `secrets` — `gitleaks detect` if gitleaks is installed, otherwise a
  skip notice (not a failure)

All gates must be green before you open a PR; CI runs the same `make verify`.

## Invariants — never break these

1. **Orchestrator hard-denial.** `classify_builtins` in `scripts/
   classify-mcp.py` always subtracts `HARD_DENIED_ORCHESTRATOR_TOOLS`
   (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash`) from whatever the
   orchestrator would otherwise be granted, as the last step of that
   function — so the orchestrator is physically unable to implement, even
   if `BUILTIN_TIERS` or a `mcp-policy.json` override tried to hand it one
   of those tools. `tests/test_classify_mcp.py` asserts the orchestrator's
   assignment is always disjoint from that set — keep that test passing.

2. **stdlib-only runtime.** Everything under `scripts/*.py` must run using
   only the Python standard library — no third-party imports in
   `classify-mcp.py` or `enforce-agent-model.py`. Dev-only tooling (ruff,
   pyright, pytest, commitizen, …) lives in `requirements-dev.txt`, never
   as a runtime import, since these scripts run unattended from Claude
   Code hooks on a user's machine with no guarantee a venv is active.

3. **No inline suppressions.** None of `# type: ignore`, `# noqa`,
   `# pyright: ignore`, `# ruff: noqa`, `# shellcheck disable` may appear
   anywhere in the codebase (the one narrow exception is
   `.claude/hooks/block-inline-suppressions.sh`, where they appear only as
   literal strings being matched against, and which is explicitly excluded
   from the check for that reason). Project-level ruff ignores are allowed
   only when documented in `pyproject.toml` — see the `S603` note there.
   Enforced by the `.claude/hooks/block-inline-suppressions.sh` PreToolUse
   hook at edit time, and by the `suppressions-check` gate at `make verify`
   time.

4. **Two enumeration paths, kept distinct.** stdio MCP servers are
   enumerated deterministically by speaking the MCP `tools/list` protocol
   directly against each server's own configured command/env
   (`list_tools_stdio`); OAuth/remote servers are enumerated via an
   authenticated headless `claude -p` pass (`enumerate_headless`), because
   only that path has live OAuth tokens. Never collapse these into one
   path — the stdio path is deterministic and cheap, the headless path is a
   flaky, model-assisted fallback used only when no session transcript has
   ever recorded a `deferred_tools_delta`.

5. **Cache self-heal.** `merge_with_cache` must never let a connected
   server that returned zero tools this run clobber that server's
   previously-cached tools — it keeps last-known-good per server and only
   replaces a server's tool set when the current run actually produced
   tools for it. `SessionStart` re-enumeration in `classify-mcp.py`'s
   `main()` only re-runs the (expensive) enumeration when the
   `server_hash()` of currently-configured servers has changed since the
   cached run; otherwise it regenerates agents from cache with no
   re-enumeration.

## Testing

```bash
make test   # pytest, >=80% coverage floor on scripts/
```

`scripts/classify-mcp.py` and `scripts/enforce-agent-model.py` are hyphenated
filenames, so they can't be imported with a normal `import` statement — the
test suite loads them via `importlib.util.spec_from_file_location` against
their file path instead (see `tests/conftest.py`'s `load_script_module`
helper and its `classify_mcp` / `enforce_agent_model` fixtures).

## Commits

Conventional Commits, enforced by `commitizen` (`cz_conventional_commits`,
configured in `pyproject.toml`).

## Release process

1. Update `CHANGELOG.md` (Keep a Changelog format).
2. Bump `version` in `.claude-plugin/plugin.json` **and** in `CHANGELOG.md`
   so they match — the `version-check` gate enforces equality — or run
   `cz bump` to do both at once (it also updates the changelog per
   `update_changelog_on_bump` in `pyproject.toml`).
3. Tag `vX.Y.Z`.
4. Push and confirm CI is green.
5. Verify the release against `origin/HEAD` (e.g. `git show
   origin/HEAD:.claude-plugin/plugin.json`), **not** the working tree. A
   staged-but-uncommitted rename once shipped a broken release — always
   confirm the committed/pushed state before declaring a release done, not
   just what's sitting locally.

## Architecture

See `docs/adr/` for architecture decision records.
