"""Token/cost/model-pin extraction from a Claude Code `--output-format
stream-json` log, reused from the qm-bench-spike prewalk harness's two
extraction modules (extract_true_metrics.py + prewalk_metrics.py), unified
here because a SWE-bench Live task run can be either:

  - opus-solo: ONE `claude` process, prints its own final `{"type":
    "result", "modelUsage": {...}}` line covering the whole run -- that
    line alone would be sufficient.
  - prewalk (opus-4-8 plans/explores -> swap to sonnet-5 executor): TWO
    `claude` processes appended to the SAME log file. The first (opus) is
    SIGTERM'd mid-stream at the first successful Edit/Write/MultiEdit and
    NEVER prints a final result line; only the second (sonnet) process's
    final result line exists, and it covers only the sonnet phase. Trusting
    the final result line alone would silently drop 100% of the opus-phase
    cost/tokens for a swapped run.

So, same rule as prewalk_metrics.py: derive true per-model tokens/cost from
RAW per-turn `assistant` message usage, deduped by `message.id` keeping the
LAST usage seen for that id (streamed chunks report cumulative-so-far
usage; only the final chunk for a given id is real). This works uniformly
for both single- and dual-process logs with no special-casing.

Pricing table: Anthropic's published per-model list pricing, same table
prewalk_metrics.py uses (introductory pricing in effect through 2026-08-31
per platform.claude.com/docs/en/about-claude/pricing).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# $ / MTok: (base_input, cache_write_5m, cache_read, output).
_PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-4-8": (5.0, 6.25, 0.50, 25.0),
    "claude-haiku-4-5": (1.0, 1.25, 0.10, 5.0),
    "claude-sonnet-5": (2.0, 2.50, 0.20, 10.0),
}

# Model-pin requirement (coordinator correction): exact model IDs only, no
# floating aliases. These are the pins the harness must verify actually took,
# per run. Two prewalk executor tiers (sonnet, haiku) share the same planner.
PLANNER_MODEL = "claude-opus-4-8"
EXECUTOR_MODEL_PREWALK = "claude-sonnet-5"  # kept for backward compat (prewalk-sonnet)
EXECUTOR_MODEL_SONNET = "claude-sonnet-5"
EXECUTOR_MODEL_HAIKU = "claude-haiku-4-5"

_BRACKET_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")


def normalize_model_id(model: str) -> str:
    """Strip Claude Code's own local annotation suffixes (e.g. the
    `[1m]` long-context-mode tag seen on `claude-opus-4-8[1m]` in raw
    modelUsage/message.model) so pin comparison isn't tripped up by a
    benign local annotation -- NOT a normalization of dated snapshot
    suffixes, which must still show up as drift (see verify_model_pins)."""
    return _BRACKET_SUFFIX_RE.sub("", model)


def _pricing_for_model(model: str) -> tuple[float, float, float, float] | None:
    base = normalize_model_id(model)
    for prefix, rates in _PRICING.items():
        if base.startswith(prefix):
            return rates
    return None


def _cost_usd(model: str, input_tok: int, cache_creation: int, cache_read: int, output_tok: int) -> float | None:
    rates = _pricing_for_model(model)
    if rates is None:
        return None
    p_in, p_cache_write, p_cache_read, p_out = rates
    return (
        input_tok * p_in + cache_creation * p_cache_write + cache_read * p_cache_read + output_tok * p_out
    ) / 1_000_000.0


def _load_lines(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _turn_sequence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        mid = msg.get("id")
        if not mid:
            continue
        if mid not in by_id:
            order.append(mid)
        by_id[mid] = {"model": msg.get("model"), "usage": msg.get("usage") or {}}
    return [by_id[mid] for mid in order]


def _result_lines(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ALL `{"type":"result",...}` lines in the log, in order. A prewalk
    (kill+resume) log can contain zero (if the resumed process was itself
    killed/crashed) up to two of these -- the SIGTERM'd opus phase never
    prints one of its own (confirmed empirically, see qm_prewalk_agent.py's
    docstring), so a swapped prewalk run typically has exactly ONE, covering
    only the post-swap (executor) phase."""
    return [ev for ev in events if ev.get("type") == "result"]


def _final_result_line(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    lines = _result_lines(events)
    return lines[-1] if lines else None


def analyze_log(log_path: Path) -> dict[str, Any]:
    """Per-model tokens/cost, preferring the AUTHORITATIVE source (Claude
    Code's own `modelUsage` from every `{"type":"result",...}` line in the
    log -- this is the CLI's own internal accounting and matches real
    billing exactly) and falling back to a raw per-turn dedup-by-message-id
    derivation ONLY for a model that appears in the turn stream but is
    covered by NO result line -- i.e. its process was killed before it
    could print one (the prewalk arm's pre-swap opus phase). The per-turn
    fallback is an ESTIMATE: cross-checking against a real single-process
    log showed input/cache-read/cache-creation tokens match modelUsage
    exactly, but per-turn `output_tokens` in intermediate stream chunks
    under-counts true output tokens by roughly an order of magnitude vs the
    CLI's own final accounting (only input-side accounting is reliably
    cumulative-per-chunk; output-side is not) -- so any `estimated`-flagged
    per-model entry should be treated as a cost/token LOWER BOUND, not an
    exact figure.
    """
    events = _load_lines(log_path)
    turns = _turn_sequence(events)

    model_sequence: list[str] = [t["model"] or "unknown" for t in turns]
    distinct_models = sorted({m for m in model_sequence if m != "unknown"})
    swap_fired = False
    if model_sequence:
        first_model = model_sequence[0]
        swap_fired = any(m != first_model for m in model_sequence)

    # Authoritative: sum modelUsage across every result line found.
    per_model_tokens: dict[str, dict[str, int]] = {}
    per_model_cost: dict[str, float] = {}
    authoritative_models: set[str] = set()
    for result_line in _result_lines(events):
        for model, usage in (result_line.get("modelUsage") or {}).items():
            authoritative_models.add(model)
            entry = per_model_tokens.setdefault(model, {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0})
            entry["input"] += usage.get("inputTokens") or 0
            entry["cache_creation"] += usage.get("cacheCreationInputTokens") or 0
            entry["cache_read"] += usage.get("cacheReadInputTokens") or 0
            entry["output"] += usage.get("outputTokens") or 0
            per_model_cost[model] = per_model_cost.get(model, 0.0) + (usage.get("costUSD") or 0.0)

    # Estimated fallback: any model seen in the turn stream but not covered
    # by any result line's modelUsage (its process was killed pre-swap).
    unpriced_models: set[str] = set()
    estimated_models: set[str] = set()
    turn_totals_by_model: dict[str, dict[str, int]] = {}
    for t in turns:
        model = t["model"] or "unknown"
        usage = t["usage"]
        entry = turn_totals_by_model.setdefault(model, {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0})
        entry["input"] += usage.get("input_tokens") or 0
        entry["cache_creation"] += usage.get("cache_creation_input_tokens") or 0
        entry["cache_read"] += usage.get("cache_read_input_tokens") or 0
        entry["output"] += usage.get("output_tokens") or 0

    for model, entry in turn_totals_by_model.items():
        base = normalize_model_id(model)
        if any(normalize_model_id(am) == base for am in authoritative_models):
            continue  # already covered authoritatively
        estimated_models.add(model)
        per_model_tokens[model] = entry
        cost = _cost_usd(model, entry["input"], entry["cache_creation"], entry["cache_read"], entry["output"])
        if cost is None:
            unpriced_models.add(model)
        else:
            per_model_cost[model] = cost

    true_prompt_side_tokens = sum(
        v["input"] + v["cache_creation"] + v["cache_read"] for v in per_model_tokens.values()
    )
    true_output_tokens = sum(v["output"] for v in per_model_tokens.values())
    true_cost_usd = sum(per_model_cost.values()) if per_model_cost else None

    final_result = _final_result_line(events)
    final_result_cost_usd = final_result.get("total_cost_usd") if final_result else None
    final_result_n_turns = final_result.get("num_turns") if final_result else None
    final_result_duration_ms = final_result.get("duration_ms") if final_result else None

    return {
        "n_turns_total": len(turns),
        "model_sequence": model_sequence,
        "distinct_models": distinct_models,
        "swap_fired": swap_fired,
        "per_model_tokens": per_model_tokens,
        "per_model_cost_usd": per_model_cost,
        "estimated_models": sorted(estimated_models),
        "n_result_lines": len(_result_lines(events)),
        "unpriced_models": sorted(unpriced_models),
        "true_prompt_side_tokens": true_prompt_side_tokens,
        "true_output_tokens": true_output_tokens,
        "true_cost_usd": true_cost_usd,
        "final_result_cost_usd": final_result_cost_usd,
        "final_result_n_turns": final_result_n_turns,
        "final_result_duration_ms": final_result_duration_ms,
        "final_result_present": final_result is not None,
    }


def bucket_cost(per_model_cost: dict[str, float]) -> dict[str, float]:
    """Bucket per-model cost into opus/sonnet/haiku/other, for the CSV's
    per-model cost split columns."""
    buckets = {"opus_cost_usd": 0.0, "sonnet_cost_usd": 0.0, "haiku_cost_usd": 0.0, "other_cost_usd": 0.0}
    for model, cost in per_model_cost.items():
        base = normalize_model_id(model)
        if base.startswith("claude-opus"):
            buckets["opus_cost_usd"] += cost
        elif base.startswith("claude-sonnet"):
            buckets["sonnet_cost_usd"] += cost
        elif base.startswith("claude-haiku"):
            buckets["haiku_cost_usd"] += cost
        else:
            buckets["other_cost_usd"] += cost
    return buckets


def verify_model_pins(distinct_models: list[str], expected_exact: list[str]) -> dict[str, Any]:
    """Verify the models actually observed in modelUsage/message.model match
    the EXACT pinned model IDs the coordinator required (no floating
    aliases). `normalize_model_id` only strips Claude Code's own local
    `[1m]`-style annotation suffix -- a genuinely different snapshot (e.g. a
    dated variant) or an alias resolving elsewhere still shows up as drift.
    """
    normalized_observed = {normalize_model_id(m) for m in distinct_models}
    matched = {exp for exp in expected_exact if exp in normalized_observed}
    drift = sorted(normalized_observed - set(expected_exact))
    return {
        "expected_exact": expected_exact,
        "observed_raw": distinct_models,
        "observed_normalized": sorted(normalized_observed),
        "all_expected_matched": set(expected_exact) == matched and len(matched) == len(expected_exact),
        "matched": sorted(matched),
        "drift": drift,
        "pin_ok": len(drift) == 0 and set(expected_exact).issubset(normalized_observed),
    }
