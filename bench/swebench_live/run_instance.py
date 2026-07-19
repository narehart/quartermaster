"""Run ONE SWE-bench Live instance end-to-end: agent -> patch -> Live's own
scorer -> result.json + a swebench_live_results.csv-ready row. This is the
per-task unit `run_swebench_live.sh` calls once per task per wave (same
"one harness invocation per task" shape as run_prewalk_prereg.sh's harbor
job-per-wave, adapted to plain docker since this harness doesn't use
Harbor).

Greppable markers (stdout), one per instance, so a wave driver can `grep`
progress without parsing JSON:
  INSTANCE_START, IMAGE_OK, REPO_READY, AGENT_RUN_DONE, AGENT_DIFF_PRODUCED /
  AGENT_DIFF_EMPTY, TOKENS_CAPTURED, MODEL_PIN_OK / MODEL_PIN_DRIFT,
  EVAL_DONE, SCORE_DONE, INSTANCE_DONE / INSTANCE_ERRORED.

Usage:
  .venv/bin/python run_instance.py --instance-id <id> --arm opus-solo
  .venv/bin/python run_instance.py --instance-id <id> --arm prewalk-sonnet
  .venv/bin/python run_instance.py --instance-id <id> --arm prewalk-haiku
  .venv/bin/python run_instance.py --instance-id <id> --arm gold   # sanity check
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _bootstrap_sys_path() -> None:
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))


_bootstrap_sys_path()

import agent_runner
import dataset_cache
import metrics

HERE = Path(__file__).resolve().parent
VENV_PYTHON = HERE / ".venv" / "bin" / "python3"
VENDOR_REPO = HERE / "vendor" / "SWE-bench-Live"
WORK_ROOT = HERE / "work"
RESULTS_ROOT = HERE / "results"
DATASET = "SWE-bench-Live/SWE-bench-Live"
SPLIT = "full"

PLANNER_MODEL = metrics.PLANNER_MODEL

# Prewalk executor tier per arm name -- both share the same opus-4-8 planner
# and swap-at-first-edit mechanism; only the resumed executor model differs.
PREWALK_ARMS = {
    "prewalk-sonnet": metrics.EXECUTOR_MODEL_SONNET,
    "prewalk-haiku": metrics.EXECUTOR_MODEL_HAIKU,
}

# Masking arms: pure opus-4-8 scaffold (like opus-solo) with tail-only
# observation masking applied by the host egress proxy. opus-masked masks;
# opus-passthru runs the identical proxy in pass-through mode (parity control).
# Value = mask_enabled.
MASKED_ARMS = {
    "opus-masked": True,
    "opus-passthru": False,
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def run_evaluation(
    instance_id: str, predictions_path: Path, output_dir: Path, split: str = SPLIT, workers: int = 1
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    launch_dir = str(VENDOR_REPO / "launch")
    env["PYTHONPATH"] = launch_dir + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [
        str(VENV_PYTHON),
        "-m",
        "evaluation.evaluation",
        "--dataset",
        DATASET,
        "--patch_dir",
        str(predictions_path),
        "--platform",
        "linux",
        "--workers",
        str(workers),
        "--output_dir",
        str(output_dir),
        "--overwrite",
        "1",
        "--split",
        split,
        "--instance_ids",
        instance_id,
    ]
    log(f"EVAL_CMD {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(VENDOR_REPO), env=env, capture_output=True, text=True, timeout=3600)
    (output_dir / "eval_stdout.log").write_text(proc.stdout)
    (output_dir / "eval_stderr.log").write_text(proc.stderr)
    report_path = output_dir / instance_id / "report.json"
    report: dict[str, Any] | None = None
    verdict_source = "unavailable"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())
            verdict_source = str(report_path)
        except Exception as exc:
            log(f"REPORT_PARSE_FAILED {report_path}: {exc}")
    return {
        "eval_returncode": proc.returncode,
        "report": report,
        "report_path": str(report_path) if report_path.exists() else None,
        "verdict_source": verdict_source,
        "eval_stdout_tail": proc.stdout[-2000:],
        "eval_stderr_tail": proc.stderr[-2000:],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-id", required=True)
    ap.add_argument(
        "--arm",
        required=True,
        choices=[
            "opus-solo",
            "prewalk-sonnet",
            "prewalk-haiku",
            "opus-masked",
            "opus-passthru",
            "gold",
        ],
    )
    ap.add_argument("--max-budget-usd", type=float, default=agent_runner.DEFAULT_MAX_BUDGET_USD)
    ap.add_argument("--keep-n", type=int, default=3, help="masking arms: tool observations kept full-fidelity")
    ap.add_argument("--results-root", default=str(RESULTS_ROOT))
    ap.add_argument("--work-root", default=str(WORK_ROOT))
    ap.add_argument("--wave", default="")
    ap.add_argument("--fresh-repo", action="store_true", help="Force a fresh clone even if one exists.")
    args = ap.parse_args()

    instance_id = args.instance_id
    arm = args.arm
    results_root = Path(args.results_root)
    work_root = Path(args.work_root)

    log(f"INSTANCE_START instance_id={instance_id} arm={arm}")

    instance = dataset_cache.get_instance(instance_id)

    instance_results_dir = results_root / arm / instance_id
    instance_results_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = instance_results_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    repo_path = work_root / arm / instance_id / "repo"
    if args.fresh_repo and repo_path.exists():
        shutil.rmtree(repo_path)

    error_detail = None
    status = "ok"
    run_result: dict[str, Any] = {}
    patch = ""
    log_metrics: dict[str, Any] = {}
    pin_check: dict[str, Any] = {}
    eval_result: dict[str, Any] = {"eval_returncode": None, "report": None, "verdict_source": "unavailable (not reached)"}

    try:
        if arm != "gold":
            agent_runner.ensure_agent_image()
            log(f"IMAGE_OK tag={agent_runner.AGENT_IMAGE}")

        agent_runner.prepare_repo(instance, repo_path)
        log(f"REPO_READY path={repo_path}")

        if arm == "gold":
            patch = instance["patch"]
            run_result = {
                "status": "ok",
                "error_detail": None,
                "wall_clock_s": 0.0,
                "log_path": None,
                "arm": "gold",
                "planner_model": None,
                "executor_model": None,
                "swap_fired": False,
            }
        elif arm == "opus-solo":
            run_result = agent_runner.run_opus_solo(
                instance,
                repo_path,
                meta_dir,
                api_key=os.environ["ANTHROPIC_API_KEY"],
                model=PLANNER_MODEL,
                max_budget_usd=args.max_budget_usd,
            )
            patch = agent_runner.extract_patch(repo_path)
        elif arm in MASKED_ARMS:
            run_result = agent_runner.run_opus_masked(
                instance,
                repo_path,
                meta_dir,
                api_key=os.environ["ANTHROPIC_API_KEY"],
                model=PLANNER_MODEL,
                keep_n=args.keep_n,
                mask_enabled=MASKED_ARMS[arm],
                max_budget_usd=args.max_budget_usd,
            )
            patch = agent_runner.extract_patch(repo_path)
        elif arm in PREWALK_ARMS:
            run_result = agent_runner.run_prewalk(
                instance,
                repo_path,
                meta_dir,
                api_key=os.environ["ANTHROPIC_API_KEY"],
                planner_model=PLANNER_MODEL,
                executor_model=PREWALK_ARMS[arm],
                max_budget_usd=args.max_budget_usd,
            )
            patch = agent_runner.extract_patch(repo_path)

        log(f"AGENT_RUN_DONE status={run_result.get('status')} wall_clock_s={run_result.get('wall_clock_s')}")
        if patch.strip():
            log(f"AGENT_DIFF_PRODUCED bytes={len(patch)}")
        else:
            log("AGENT_DIFF_EMPTY")

        # --- metrics / model-pin verification ---
        if run_result.get("log_path"):
            log_metrics = metrics.analyze_log(Path(run_result["log_path"]))
            log(
                "TOKENS_CAPTURED "
                f"prompt_side={log_metrics.get('true_prompt_side_tokens')} "
                f"completion={log_metrics.get('true_output_tokens')} "
                f"cost_usd={log_metrics.get('true_cost_usd')} "
                f"models={log_metrics.get('distinct_models')}"
            )
            if arm == "opus-solo" or arm in MASKED_ARMS:
                expected = [PLANNER_MODEL]
            elif arm in PREWALK_ARMS:
                expected = [PLANNER_MODEL, PREWALK_ARMS[arm]]
            else:
                expected = []
            if not (arm in PREWALK_ARMS and not run_result.get("swap_fired")):
                pin_check = metrics.verify_model_pins(log_metrics.get("distinct_models") or [], expected)
                log(f"{'MODEL_PIN_OK' if pin_check.get('pin_ok') else 'MODEL_PIN_DRIFT'} {pin_check}")

        # --- predictions.json + scoring ---
        predictions_path = instance_results_dir / "predictions.json"
        predictions_path.write_text(json.dumps({instance_id: {"model_patch": patch}}, indent=2))

        eval_output_dir = instance_results_dir / "eval"
        eval_result = run_evaluation(instance_id, predictions_path, eval_output_dir)
        log(f"EVAL_DONE returncode={eval_result['eval_returncode']}")

        report = eval_result.get("report") or {}
        resolved = report.get("resolved")
        log(f"SCORE_DONE instance_id={instance_id} resolved={resolved} source={eval_result['verdict_source']}")

    except Exception as exc:
        status = "errored"
        error_detail = f"{type(exc).__name__}: {exc}"
        log(f"INSTANCE_ERRORED instance_id={instance_id} error={error_detail}")

    result = {
        "instance_id": instance_id,
        "arm": arm,
        "wave": args.wave,
        "repo": instance.get("repo"),
        "created_at": instance.get("created_at"),
        "status": status,
        "error_detail": error_detail,
        "run_result": run_result,
        "metrics": log_metrics,
        "model_pin_check": pin_check,
        "eval": {k: v for k, v in eval_result.items() if k not in ("eval_stdout_tail", "eval_stderr_tail")},
        "patch_bytes": len(patch),
        "patch_empty": not patch.strip(),
    }
    (instance_results_dir / "result.json").write_text(json.dumps(result, indent=2, default=str))
    log(f"INSTANCE_DONE instance_id={instance_id} arm={arm} status={status}")


if __name__ == "__main__":
    main()
