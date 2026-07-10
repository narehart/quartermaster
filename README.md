# TokenWise

**Strict cost-tiered agent delegation for Claude Code.** A tool-restricted
orchestrator runs your main session and *cannot implement anything itself* — no
`Edit`, `Write`, or `Bash`. It plans, reviews, and delegates every bit of
execution to cheap tiered sub-agents, and a hook hard-pins each sub-agent's
model so nothing silently runs on the expensive session model.

The problem it fixes: told-to-delegate-but-doesn't. Soft instructions ("you are
an orchestrator, delegate") are reliably ignored — the expensive model just does
the work inline ("just this one small edit"). TokenWise makes delegation
**structural**: the orchestrator literally lacks the tools to implement, so it
has to hand off.

## What's inside

- `agents/orchestrator.md` — the delegation-only lead (`tools: Read, Grep, Glob,
  Agent, Skill, WebFetch, WebSearch`; runs at the session model via `inherit`).
- `agents/scout.md` (Haiku) — read-only recon, searches, "run X and report".
- `agents/mechanic.md` (Haiku) — precisely-specified mechanical edits + commands.
- `agents/builder.md` (Sonnet) — well-specified implementation, tests, fixes.
- `hooks/hooks.json` + `scripts/enforce-agent-model.py` — pins every sub-agent's
  model (incl. the built-in `Explore`/`general-purpose`/`claude-code-guide` so
  they stop inheriting the session model), a SessionStart tripwire for the
  `CLAUDE_CODE_SUBAGENT_MODEL` override, and SubagentStart/Stop logging to
  `~/.claude/logs/` (feeds an "active subagents" status line if you use one).
- `install.sh` / `uninstall.sh` — do the two things a plugin can't (set the
  main-thread `agent`, add the Opus/Fable permission backstop) and migrate away
  any previous manual install.

## Install

Two parts: the plugin package, and the settings a plugin can't set.

```bash
# 1. the settings + legacy migration (safe to run on a fresh machine)
bash install.sh

# 2. the plugin package, inside Claude Code:
/plugin marketplace add /path/to/this/tokenwise            # or a git URL
/plugin install tokenwise@tokenwise-marketplace
# restart Claude Code — the main-thread agent loads at startup
```

Verify it's strict:
```bash
claude -p --agent tokenwise:orchestrator "List your exact tool names."
# expect: Read, Grep, Glob, Agent, Skill, WebFetch, WebSearch — NO Edit/Write/Bash
```

## Upgrade

```bash
/plugin update tokenwise@tokenwise-marketplace     # bumps to the new version, old cache cleaned by Claude Code
/plugin marketplace update                          # refresh the marketplace first if needed
```
Versions are tagged in git; `plugin.json` `version` gates when users are offered
the update. Re-run `bash install.sh` only if a release changes the settings/hooks
contract (see CHANGELOG).

## Uninstall

```bash
bash uninstall.sh                                   # reverts agent + permission settings
/plugin uninstall tokenwise@tokenwise-marketplace   # removes the package
# restart — main thread returns to the default unrestricted agent
```

## Notes & caveats

- **Escape hatch:** for a session where you want to drive hands-on, launch
  `claude --agent claude` — that restores Edit/Write/Bash for that session only.
- **Skills that write files** run in the orchestrator's context and will hit its
  tool restriction. Run those under `claude --agent claude`, or have the
  orchestrator delegate their execution.
- **The tradeoff you're opting into:** every edit — even a one-liner — routes
  through a sub-agent. That's slower and costs more on trivial tasks; it's the
  price of the guarantee that the orchestrator never over-works. Realistic net
  savings on real workloads are ~30%, not 5–10× — delegation is a
  context-preservation tool first, a cost tool second.
- Keep the orchestrator → scout/mechanic/builder hierarchy flat; the leaf agents
  have `disallowedTools: Agent, Task, Workflow` so they can't recurse.
