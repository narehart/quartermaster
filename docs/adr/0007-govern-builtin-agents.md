# ADR 0007: Govern Claude Code's built-in `Explore`/`general-purpose` agents

## Status

Accepted

## Context

Quartermaster's whole enforcement model rests on agent-file `tools:`
allowlists — Claude Code refuses any tool an agent's frontmatter doesn't
grant, so the allowlist itself IS the tiering. Two of Claude Code's own
built-in agents are ungoverned holes in that model:

- `general-purpose` ships with `tools: *` — literally every tool, including
  `Edit`/`Write`/`Bash` AND `Agent` (it can spawn further sub-agents). A task
  routed to `general-purpose` bypasses every tier below the orchestrator: it
  can implement, run shell, and recurse, all at once.
- `Explore` ships with every tool except `Edit`/`Write`/`NotebookEdit` — it
  still holds `Bash`, so it can execute arbitrary commands despite being
  billed as a read-only recon agent.

`install.sh` already backs up any existing `Explore`/`general-purpose` agent
file on disk before quartermaster's generation runs (see the legacy-backup
loop in `install.sh`), but until now it never supplied a governed
replacement — a fresh install left both built-in names untouched and fully
ungoverned.

## Decision

Shadow both `Explore` and `general-purpose` with restricted, read-only,
no-recursion templates (`templates/Explore.md`, `templates/general-purpose.md`),
generated into `~/.claude/agents/` the same way orchestrator/scout/mechanic/
builder are:

- **`Explore`** becomes a read-only recon agent — `tools: Read, Grep, Glob,
  LSP, WebFetch, WebSearch`, matching `scout`'s shape and voice.
- **`general-purpose`** becomes an intentionally NEUTRALIZED read-only
  catch-all — same restricted tool set, with a body explaining that real
  implementation/shell work must be routed to `builder`/`mechanic` instead.

Both templates set `disallowedTools: Agent, Task, Workflow, Edit, Write,
MultiEdit, NotebookEdit, Bash` unconditionally — denying recursion (`Agent`/
`Task`/`Workflow`) and every implementation tool, regardless of what a future
policy override might try to grant.

`scripts/classify-mcp.py`'s `generate_agents()` is extended via a
`TEMPLATE_TO_ASSIGNMENT_BUCKET` mapping (`Explore` -> `"scout"`,
`general-purpose` -> `"scout"`, alongside the identity mapping for the four
real agents) so both generated files draw their appended MCP/built-in tools
from the SAME read-only bucket `scout` gets — never the `mechanic`/`builder`
write buckets. This is defense in depth on top of `disallowedTools`: even if
`disallowedTools` were ever removed or ignored, the appended tool set itself
can never contain a write tool.

`claude-code-guide` is deliberately left alone: it holds no `Agent` tool, so
it cannot recurse and was never part of the bypass this ADR closes.

## Consequences

Default delegations to `general-purpose` (whether from a human habit or
another tool's default routing) can no longer implement anything, run shell,
or spawn sub-agents — callers must explicitly route write/shell work to
`builder` or `mechanic`. `Explore` loses its shell entirely, matching its
advertised read-only recon role. The cost is one more pair of files to keep
in sync with `scout.md`'s style if that template's voice changes, and one
more entry (`TEMPLATE_TO_ASSIGNMENT_BUCKET`) to keep current if a fifth real
agent tier is ever added.
