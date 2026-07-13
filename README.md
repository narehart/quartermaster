# Quartermaster

**Strict cost-tiered agent delegation for Claude Code, now with MCP tool tiering.**

A tool-restricted orchestrator runs your main session and *cannot implement
anything itself* — no `Edit`/`Write`/`Bash`, and no MCP tools. It plans,
reviews, and delegates every bit of execution to cheap tiered sub-agents. MCP
tools are tiered the same way: reads to a cheap recon agent, writes to the
execution agent — because an MCP call is I/O, which the expensive orchestrator
shouldn't be doing either.

## Tiers

| Agent | Model | Holds |
|---|---|---|
| **orchestrator** (main thread) | inherit (your session model) | Read/Grep/Glob/Agent/Skill/WebFetch/WebSearch. **No** Edit/Write/Bash, **no** MCP. Delegates everything. |
| **scout** | Haiku | read-only file/code recon + **read-only MCP tools** (list/search/get) |
| **mechanic** | Haiku | shell + mechanical edits + **write MCP tools** (create/update/send/delete) |
| **builder** | Sonnet | well-specified implementation, tests, diagnosed fixes |

The orchestrator reads `~/.claude/quartermaster/TOOL-ROUTING.md` to know which tier
holds which server's tools.

## How MCP tiering works

`scripts/classify-mcp.py` enumerates and classifies every MCP tool, then writes
the read tools into scout and the write tools into mechanic:

- **stdio servers** (incl. API-key ones like naver): enumerated deterministically
  by speaking the MCP `tools/list` protocol, launched with each server's
  configured env; classified via `readOnlyHint`/`destructiveHint` annotations
  then name heuristics.
- **OAuth / remote servers** (Google Drive, Linear connectors, …): enumerated via
  an authenticated headless `claude -p` pass — the only path that has the live
  tokens. (A standalone probe can't auth them; headless can.)

It re-runs at **SessionStart**, but only does the (Haiku) enumeration call when
your set of MCP servers actually changed — otherwise it regenerates agents from
cache. Add or remove an MCP server and the tiering updates itself.

Optional `~/.claude/quartermaster/mcp-policy.json` (see `mcp-policy.example.json`)
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
Upgrading from this project's old name, TokenWise? Just run `install.sh` — it
migrates a prior `tokenwise@tokenwise-marketplace` install and moves the old
`~/.claude/tokenwise/` state dir to `~/.claude/quartermaster/` automatically.

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
