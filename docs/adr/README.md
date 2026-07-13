# Architecture Decision Records

An ADR is a short, dated record of one significant architectural decision:
what problem forced it, what was decided, and what it costs going forward.
Quartermaster uses them so the reasoning behind non-obvious constraints (why
the orchestrator has no shell, why enumeration has two separate code paths,
…) survives independently of whoever made the call — future contributors
(human or agent) can find out *why* an invariant exists instead of just being
told not to break it.

## Index

- [0001 — Cost-tiered delegation](0001-cost-tiered-delegation.md)
- [0002 — Orchestrator hard-denial](0002-orchestrator-hard-denial.md)
- [0003 — Least-privilege MCP tiering](0003-least-privilege-mcp-tiering.md)
- [0004 — Deterministic enumeration](0004-deterministic-enumeration.md)
- [0005 — Built-in tool classification](0005-builtin-tool-classification.md)
- [0006 — Unified tool policy](0006-unified-tool-policy.md)

## Adding a new ADR

1. Copy [`0000-template.md`](0000-template.md) to `NNNN-short-title.md`,
   numbered sequentially after the highest existing ADR.
2. Fill in Status (`Proposed` until it's actually decided and acted on),
   Context, Decision, and Consequences — ground it in the real code/files
   the decision touches, not generic filler.
3. Add it to the Index above, in numeric order.
