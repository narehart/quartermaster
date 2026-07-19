"""Build swebench_live_results.csv from every result.json under one or more
results-root/<arm>/<instance_id>/ dirs (mirrors build_prewalk_prereg_results.py's
"walk trial dirs -> one CSV row per trial" shape, adapted from Harbor trial
dirs to this harness's own results/<arm>/<instance_id>/result.json layout).

Usage: .venv/bin/python build_results_csv.py [<results-root> ...] [--out swebench_live_results.csv]

Columns match what the existing bootstrap/cost-per-solved analysis tooling
expects from prior *_results.csv files: instance_id, repo, created_at,
model, resolved (0/1), total_cost_usd, prompt_side_tokens,
completion_tokens, per-model (opus/sonnet/haiku) token+cost split, n_turns,
wall_clock_s, status, and the resolved-verdict source.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

FIELDNAMES = [
    "instance_id",
    "repo",
    "created_at",
    "arm",
    "model",
    "model_ids_observed",
    "resolved",
    "total_cost_usd",
    "prompt_side_tokens",
    "completion_tokens",
    "opus_prompt_tokens",
    "opus_completion_tokens",
    "opus_cost_usd",
    "sonnet_prompt_tokens",
    "sonnet_completion_tokens",
    "sonnet_cost_usd",
    "haiku_prompt_tokens",
    "haiku_completion_tokens",
    "haiku_cost_usd",
    "n_turns",
    "wall_clock_s",
    "status",
    "swap_fired",
    "model_pin_ok",
    "model_pin_drift",
    "resolved_verdict_source",
    "patch_empty",
    "result_dir",
]


def _model_label(result: dict[str, Any]) -> str:
    run_result = result.get("run_result") or {}
    planner = run_result.get("planner_model")
    executor = run_result.get("executor_model")
    if result.get("arm") == "gold":
        return "gold-patch"
    if executor and run_result.get("swap_fired"):
        return f"{planner}->{executor}"
    return planner or "unknown"


def build_row(result_path: Path) -> dict[str, Any] | None:
    try:
        result = json.loads(result_path.read_text())
    except Exception as exc:
        print(f"RESULT_PARSE_FAILED {result_path}: {exc}")
        return None

    metrics = result.get("metrics") or {}
    per_model_tokens = metrics.get("per_model_tokens") or {}
    per_model_cost = metrics.get("per_model_cost_usd") or {}

    def bucket_tokens(prefix: str) -> tuple[int, int]:
        prompt = 0
        completion = 0
        for model, tok in per_model_tokens.items():
            base = model.split("[")[0]
            if base.startswith(prefix):
                prompt += tok.get("input", 0) + tok.get("cache_creation", 0) + tok.get("cache_read", 0)
                completion += tok.get("output", 0)
        return prompt, completion

    def bucket_cost(prefix: str) -> float:
        total = 0.0
        for model, cost in per_model_cost.items():
            base = model.split("[")[0]
            if base.startswith(prefix):
                total += cost
        return total

    opus_prompt, opus_completion = bucket_tokens("claude-opus")
    sonnet_prompt, sonnet_completion = bucket_tokens("claude-sonnet")
    haiku_prompt, haiku_completion = bucket_tokens("claude-haiku")

    report = (result.get("eval") or {}).get("report") or {}
    resolved = report.get("resolved")
    resolved_int = 1 if resolved is True else (0 if resolved is False else "")

    pin_check = result.get("model_pin_check") or {}

    return {
        "instance_id": result.get("instance_id"),
        "repo": result.get("repo"),
        "created_at": result.get("created_at"),
        "arm": result.get("arm"),
        "model": _model_label(result),
        "model_ids_observed": "|".join(metrics.get("distinct_models") or []),
        "resolved": resolved_int,
        "total_cost_usd": metrics.get("true_cost_usd"),
        "prompt_side_tokens": metrics.get("true_prompt_side_tokens"),
        "completion_tokens": metrics.get("true_output_tokens"),
        "opus_prompt_tokens": opus_prompt,
        "opus_completion_tokens": opus_completion,
        "opus_cost_usd": bucket_cost("claude-opus"),
        "sonnet_prompt_tokens": sonnet_prompt,
        "sonnet_completion_tokens": sonnet_completion,
        "sonnet_cost_usd": bucket_cost("claude-sonnet"),
        "haiku_prompt_tokens": haiku_prompt,
        "haiku_completion_tokens": haiku_completion,
        "haiku_cost_usd": bucket_cost("claude-haiku"),
        "n_turns": metrics.get("n_turns_total"),
        "wall_clock_s": (result.get("run_result") or {}).get("wall_clock_s"),
        "status": result.get("status"),
        "swap_fired": (result.get("run_result") or {}).get("swap_fired"),
        "model_pin_ok": pin_check.get("pin_ok"),
        "model_pin_drift": "|".join(pin_check.get("drift") or []),
        "resolved_verdict_source": (result.get("eval") or {}).get("verdict_source"),
        "patch_empty": result.get("patch_empty"),
        "result_dir": str(result_path.parent),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_roots", nargs="*", default=["results"])
    ap.add_argument("--out", default="swebench_live_results.csv")
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    n_parse_failed = 0
    for root in args.results_roots:
        root_path = Path(root)
        if not root_path.exists():
            print(f"WARN: results root {root_path} does not exist, skipping")
            continue
        for result_path in sorted(root_path.glob("*/*/result.json")):
            row = build_row(result_path)
            if row is None:
                n_parse_failed += 1
                continue
            rows.append(row)

    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("instance_id") or ""), reverse=True)

    out_path = Path(args.out)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows to {out_path}; RESULT_PARSE_FAILED_count={n_parse_failed}")


if __name__ == "__main__":
    main()
