---
description: Apply Quartermaster's certified output tuning (one-time, user-level)
---

Apply the one piece of Quartermaster's certified output-tuning configuration
that a plugin hook cannot set automatically: the thinking-budget cap, as a
USER-LEVEL setting (applies to all projects).

Certified result (bench/docs/PREREG_POWERED_TUNED.md, finding F9, n=150 on
SWE-bench Live): cost-per-solved ratio 0.66 (95% CI [0.55, 0.77]) at an
identical resolve rate (24.0% vs 24.0%). The technique = the efficiency
instruction block (already injected automatically by this plugin's
SessionStart hook) + `MAX_THINKING_TOKENS=8000`.

Steps:

1. Read `~/.claude/settings.json` (create `{}` if missing).
2. Merge in — WITHOUT disturbing any other keys:
   ```json
   { "env": { "MAX_THINKING_TOKENS": "8000" } }
   ```
   If `env.MAX_THINKING_TOKENS` already exists with a DIFFERENT value, show
   the current value and ask before overwriting.
3. Write the file back, then confirm to the user:
   - the cap is set user-level (all projects),
   - the instruction block is delivered automatically by the plugin at every
     session start (no per-project setup),
   - the change takes effect on the next session start,
   - to undo: remove `env.MAX_THINKING_TOKENS` from `~/.claude/settings.json`
     and disable the plugin.
