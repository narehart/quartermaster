"""Load+cache the SWE-bench Live `full` split locally (as JSONL, one row per
line) so repeated per-instance driver invocations (one per task, across
waves) don't each pay the ~4-8s HF `load_dataset` cost. Built lazily on
first use; `--refresh` forces a re-pull."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

CACHE_PATH = Path(__file__).resolve().parent / "full_dataset_cache.jsonl"


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {msg}", file=sys.stderr, flush=True)


def _stringify_scalars(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in ("created_at", "difficulty"):
        if key in out and out[key] is not None and not isinstance(out[key], (str, int, float, bool)):
            out[key] = str(out[key])
    return out


def build_cache(dataset: str = "SWE-bench-Live/SWE-bench-Live", split: str = "full") -> None:
    from datasets import load_dataset

    log(f"CACHE_BUILD dataset={dataset} split={split} (token=False)")
    ds = load_dataset(dataset, split=split, token=False)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        for row in ds:
            f.write(json.dumps(_stringify_scalars(dict(row))) + "\n")
    log(f"CACHE_BUILD_OK n={len(ds)} -> {CACHE_PATH}")


def load_all(refresh: bool = False) -> dict[str, dict[str, Any]]:
    if refresh or not CACHE_PATH.exists():
        build_cache()
    by_id: dict[str, dict[str, Any]] = {}
    with open(CACHE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            by_id[row["instance_id"]] = row
    return by_id


def get_instance(instance_id: str, refresh: bool = False) -> dict[str, Any]:
    by_id = load_all(refresh=refresh)
    if instance_id not in by_id:
        raise KeyError(f"instance_id {instance_id!r} not found in cached full split ({CACHE_PATH})")
    return by_id[instance_id]
