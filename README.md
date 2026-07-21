# Quartermaster

**A discipline for reducing token cost on long-horizon agentic
software-engineering work — without sacrificing quality. A technique ships only
when a preregistered benchmark proves it clears that bar.**

## Mission

Quartermaster's goal is to cut the token cost of long-running Claude Code
sessions on real daily development work, holding task success constant. It is
governed by one rule: **the plugin contains only techniques that the benchmark
in [`bench/`](bench/) shows reduce cost without hurting quality.** Nothing is
grandfathered — including the plugin's own original mechanism.

## Status — honest and evidence-based

- **The bench is live and has completed its first campaign.** [`bench/`](bench/)
  is a preregistered **SWE-bench Live** cost-per-solved harness with exact
  model pins and cache-aware token accounting. See
  [bench/README.md](bench/README.md).
- **Campaign result (5 techniques, n=25 each, directional): none cleared the
  bar — and the arithmetic explains why.** On a prompt-cached, API-priced
  coding agent, **context-size reduction does not reduce cost-per-solved**:
  cache reads are 0.1×, so caching has already collapsed the context term.
  What binds is **turn count** (each turn re-reads everything and emits
  full-price output) and **output tokens** (never discounted). Every context
  technique tested either removed already-cheap tokens (at-source capping:
  no effect at any threshold), paid a cache-invalidation tax (sliding-window
  masking: ~28× blowup), or destabilized the agent into extra turns (batched
  clearing: 2.5× turns on treated runs, one lost solve). Model-swap (prewalk)
  fails separately via executor turn-inflation.
  [Full analysis + anomaly log.](bench/docs/SWEBENCH_LIVE_ANALYSIS.md)
  - Independently replicated at 40× scale within days:
    ["Token Reduction Is Not Cost Reduction" (arXiv:2607.12161)](https://arxiv.org/abs/2607.12161)
    — cache traffic ≈87% of billed cost; token-reduction↔cost r=0.15.
  - The cache-blind literature's 50–96% "savings" claims do not survive
    cache-priced, quality-gated measurement. This bench's curation rule —
    only ship what provably cuts cost without hurting resolve rate — is the
    project's product.
- **No token-reduction technique is confirmed-shipped yet.** The original
  mechanism — least-privilege **tool governance + enforced delegation**
  (documented below) — is measured **cost-neutral-to-worse** and remains for
  its *governance* value. [The A/B result.](docs/benchmarks/2026-07-cost-ab.md)
- **Next (round 3):** attack the binding terms directly — output-token
  reduction (repo-instruction + thinking-budget tuning) and experience-driven
  early termination — all cache-safe by construction.
  [Candidate pipeline.](bench/docs/TOKEN_REDUCTION_CANDIDATES.md)

---

## The current mechanism: least-privilege tool governance + delegation

This is Quartermaster's original mechanism. It provides real least-privilege
governance, but — per the Status above — it is **not** a proven cost reduction;
it is documented here as the shipped governance behavior, pending
bench-validated cost techniques.

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
- **Cost is not proven to go down.** A preregistered A/B benchmark measured
  what tiering actually does to spend: it cuts expensive-model (opus)
  token share by 82.7%, as designed — but net per-task cost was
  statistically null at a sonnet main thread and **1.39x higher** (a
  reversal of the hypothesis) at an opus main thread, because delegation
  overhead roughly doubles total token volume under one-shot, cold-start
  conditions. Long interactive-session economics (cross-turn caching) are
  untested. See [docs/benchmarks/2026-07-cost-ab.md](docs/benchmarks/2026-07-cost-ab.md)
  for the full result, including where Quartermaster measured cheaper (3 of
  6 opus-experiment tasks) and where it didn't.

## Security gates

Secret scanning (`gitleaks`) runs twice: locally on `pre-commit` via
[lefthook](lefthook.yml) (`gitleaks protect --staged`, alongside `ruff`
lint/format and `shfmt` checks on staged files), and again in CI/`make
verify` (`gitleaks detect`). Dependency-CVE scanning (`osv-scanner`) now
runs in CI too, as its own `osv-scan` job in
[ci.yml](.github/workflows/ci.yml) — it scans the actually-installed
dependency set (`pip freeze`) rather than the loose
`requirements-dev.txt`, and is kept out of `make verify` since it needs
network access; see
[ADR 0009](docs/adr/0009-local-pre-commit-gates-and-cve-scanning.md) for why.
