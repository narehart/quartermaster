"""Build swebench_live_subset.json: the 25 most-recent VIABLE SWE-bench Live
instances, for the opus-solo re-baseline (and any follow-up arms) run by
run_swebench_live.sh.

"Viable" = both of:
  1. the instance's scoring image (`starryzhang/sweb.eval.<arch>.<instance>`,
     `evaluation.evaluation.get_default_image_name`) actually exists on
     Docker Hub -- checked via `docker manifest inspect` (no pull), NOT
     assumed. Several `full`-split instances have no published image yet;
     silently including them would only be discovered wave 1 into the real
     baseline run.
  2. its test suite isn't one of the extreme outliers noted in the spike
     (some repos have 4600-8500+ PASS_TO_PASS tests -> a single instance can
     dominate wall-clock/cost of a whole wave). `--max-test-count` biases
     the manifest toward lighter repos without abandoning recency order: it
     is applied as a filter, not a re-sort -- the final 25 are still in
     strict `created_at` DESCENDING order among instances that pass both
     checks.

Usage:
  .venv/bin/python build_subset.py \
      --dataset SWE-bench-Live/SWE-bench-Live --split full \
      --n 25 --max-test-count 2000 \
      --out swebench_live_subset.json

Requires `docker` on PATH (manifest checks only -- nothing is pulled here).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def _load_get_default_image_name():
    # evaluation/evaluation.py does `sys.path.insert(0, os.path.join(os.getcwd(),
    # "launch"))` -- i.e. it assumes CWD is the SWE-bench-Live repo root. Add both
    # paths ourselves so this works regardless of the caller's CWD.
    repo_root = Path(__file__).resolve().parent / "vendor" / "SWE-bench-Live"
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "launch"))
    from evaluation.evaluation import get_default_image_name

    return get_default_image_name


get_default_image_name = _load_get_default_image_name()


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def image_exists(image: str, timeout_s: int = 20) -> bool:
    try:
        proc = subprocess.run(
            ["docker", "manifest", "inspect", image],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={"DOCKER_CLI_EXPERIMENTAL": "enabled", "PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        log(f"IMAGE_CHECK_TIMEOUT {image}")
        return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="SWE-bench-Live/SWE-bench-Live")
    ap.add_argument("--split", default="full")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--max-test-count", type=int, default=2000)
    ap.add_argument("--platform", default="linux", choices=["linux", "windows"])
    ap.add_argument("--out", default="swebench_live_subset.json")
    ap.add_argument(
        "--scan-limit",
        type=int,
        default=400,
        help="Max most-recent candidates to probe before giving up (bounds docker manifest calls).",
    )
    args = ap.parse_args()

    from datasets import load_dataset

    log(f"Loading dataset={args.dataset} split={args.split} (token=False)")
    ds = load_dataset(args.dataset, split=args.split, token=False)
    log(f"Loaded {len(ds)} instances")

    rows = [dict(r) for r in ds]
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    selected: list[dict] = []
    scanned = 0
    skipped_no_image = 0
    skipped_heavy = 0
    for row in rows:
        if len(selected) >= args.n or scanned >= args.scan_limit:
            break
        scanned += 1
        instance_id = row["instance_id"]
        n_tests = len(row.get("PASS_TO_PASS") or []) + len(row.get("FAIL_TO_PASS") or [])
        image = get_default_image_name(instance_id, args.platform)

        if n_tests > args.max_test_count:
            skipped_heavy += 1
            log(f"SKIP_HEAVY {instance_id} n_tests={n_tests} > {args.max_test_count}")
            continue

        if not image_exists(image):
            skipped_no_image += 1
            log(f"SKIP_NO_IMAGE {instance_id} image={image}")
            continue

        log(f"SELECT {instance_id} created_at={row.get('created_at')} n_tests={n_tests} image={image}")
        selected.append(
            {
                "instance_id": instance_id,
                "repo": row.get("repo"),
                "created_at": str(row.get("created_at")) if row.get("created_at") is not None else None,
                "n_tests": n_tests,
                "image": image,
                "difficulty": str(row.get("difficulty")) if row.get("difficulty") is not None else None,
            }
        )

    if len(selected) < args.n:
        log(
            f"WARNING: only found {len(selected)}/{args.n} viable instances after "
            f"scanning {scanned} candidates (skipped_no_image={skipped_no_image}, "
            f"skipped_heavy={skipped_heavy}). Consider raising --scan-limit or "
            "--max-test-count."
        )

    manifest = {
        "dataset": args.dataset,
        "split": args.split,
        "platform": args.platform,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_requested": args.n,
        "max_test_count": args.max_test_count,
        "n_candidates_scanned": scanned,
        "n_skipped_no_image": skipped_no_image,
        "n_skipped_heavy": skipped_heavy,
        "instances": selected,
    }
    out_path = Path(args.out)
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")
    log(f"SUBSET_DONE n_selected={len(selected)} out={out_path}")


if __name__ == "__main__":
    main()
