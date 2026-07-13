# Quartermaster

**Strict cost-tiered agent delegation for Claude Code, now with MCP tool tiering.**

A tool-restricted orchestrator runs your main session: it reads and searches
the codebase to plan and review, invokes skills, and tracks tasks — but it
can't edit files, run shell, call MCP tools, or fetch/search the web. Research,
like all other I/O, is delegated: web lookups go to `scout`, which returns a
summary instead of raw page content. It also gains, once tiered, built-in
orchestration tools (`Monitor`, `SendMessage`, `Task*`, `Cron*`, plan-mode,
MCP-resource reads). It delegates every bit of execution to cheap tiered
sub-agents. MCP tools are tiered the same way: reads to a cheap recon agent,
writes to the execution agent — because an MCP call is I/O, which the
expensive orchestrator shouldn't be doing either.

## Tiers

| Agent | Model | Holds |
|---|---|---|
| **orchestrator** (main thread) | inherit (your session model) | Read/Grep/Glob/Agent/Skill/TodoWrite, plus tiered built-in orchestration tools (Monitor, SendMessage, Task\*/Cron\*, plan-mode, MCP-resource reads). **No** Edit/Write/MultiEdit/NotebookEdit/Bash, **no** MCP server tools, **no** WebFetch/WebSearch — web research is delegated to scout. Delegates everything. |
| **scout** | Haiku | read-only file/code recon + **read-only MCP tools** (list/search/get) |
| **mechanic** | Haiku | shell + mechanical edits + **write MCP tools** (create/update/send/delete) |
| **builder** | Sonnet | well-specified implementation, tests, diagnosed fixes |

The orchestrator reads `~/.claude/quartermaster/TOOL-ROUTING.md` to know which tier
holds which server's tools.

Quartermaster also **governs Claude Code's built-in `Explore` and
`general-purpose` agents**, which otherwise bypass the tiering above:
upstream `general-purpose` ships with `tools: *` (Edit/Write/Bash *and*
`Agent`, so it can implement, run shell, and spawn further sub-agents in one
call) and `Explore` still holds `Bash`. Quartermaster shadows both names with
restricted, read-only, no-recursion templates (`templates/Explore.md`,
`templates/general-purpose.md`) drawing only the same read-only tools `scout`
gets — see [ADR 0007](docs/adr/0007-govern-builtin-agents.md).

## How tool tiering works

`scripts/classify-mcp.py` enumerates and classifies every MCP tool, then writes
the read tools into scout and the write tools into mechanic:

- **stdio servers** (incl. API-key ones like Brave Search): enumerated deterministically
  by speaking the MCP `tools/list` protocol, launched with each server's
  configured env; classified via `readOnlyHint`/`destructiveHint` annotations
  then name heuristics.
- **OAuth / remote servers** (Google Drive, Linear connectors, …): enumerated via
  an authenticated headless `claude -p` pass — the only path that has the live
  tokens. (A standalone probe can't auth them; headless can.)

Built-in tools (`Monitor`, `SendMessage`, `LSP`, `NotebookEdit`, …) are
classified and tiered across the agents too, not just MCP tools.

It re-runs at **SessionStart**, but only does the (Haiku) enumeration call when
your set of MCP servers actually changed — otherwise it regenerates agents from
cache. Add or remove an MCP server and the tiering updates itself.

Optional `~/.claude/quartermaster/tools.json` (see `tools.example.json`)
overrides any classification — split a server, move it, or skip it. Not required.

## Install

```bash
bash install.sh     # installs the plugin via `claude plugin …`, generates the
                    # agents into ~/.claude/agents, sets the main-thread agent +
                    # permission backstop, migrates any prior manual install
# restart Claude Code
```
`install.sh` derives its own path and is safe on a fresh machine. First run does
one headless MCP-classification pass (a minute if you have MCP servers).

Verify:
```bash
claude -p --agent orchestrator "List your exact tool names."   # no Edit/Write/Bash
cat ~/.claude/quartermaster/TOOL-ROUTING.md                     # per-server tiering
```

## Upgrade / uninstall

```bash
claude plugin update quartermaster@quartermaster-marketplace   # or re-run install.sh
bash uninstall.sh                                                # reverts settings + removes plugin
```

## Notes & caveats

- **Escape hatch:** `claude --agent claude` gives an unrestricted session (all
  tools incl. MCP) when you want to drive hands-on.
- **Enumeration is model-assisted for OAuth servers**, so an occasional miss is
  possible; the routing table flags any *connected* server that came back empty
  so you can re-run or add a policy entry. stdio servers are deterministic.
- **The tradeoff:** every edit and every MCP call routes through a sub-agent.
  Slower on trivial tasks; the point is the orchestrator never over-works.
- Leaf agents have `disallowedTools: Agent, Task, Workflow` — no recursion.

## Security gates

Secret scanning (`gitleaks`) runs twice: locally on `pre-commit` via
[lefthook](lefthook.yml) (`gitleaks protect --staged`, alongside `ruff`
lint/format and `shfmt` checks on staged files), and again in CI/`make
verify` (`gitleaks detect`). Dependency-CVE scanning (`osv-scanner` against
`requirements-dev.txt`) was evaluated but is not yet wired into CI — see
[ADR 0009](docs/adr/0009-local-pre-commit-gates-and-cve-scanning.md) for why.
