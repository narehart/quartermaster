#!/usr/bin/env python3
"""Validate the per-run result.json files for a given arm against the
preregistered health checks, applying the corrected pin-check semantics:

  - swap_fired is the PRIMARY gate for prewalk arms (executor never runs if
    the opus->executor resume didn't fire).
  - The raw model_pin_check.pin_ok flag is TOO STRICT for prewalk-sonnet: it
    flags Claude Code's benign internal background Haiku (title/summary
    housekeeping) as "drift". The honest check is:
      * all_expected_matched == True  (both work-loop pins actually present)
      * every drift entry is ONLY the known background-Haiku model id
        (claude-haiku-4-5*), never a different opus/sonnet snapshot.
  - patch_empty must be False (the agent produced a diff).

Usage: validate_arm.py <arm> [results_root]
Prints one line per run + a summary verdict. Exit 0 iff every completed run
passes the corrected health checks (or there are no runs yet).
"""

import json
import sys
from pathlib import Path

BACKGROUND_HAIKU_PREFIX = "claude-haiku-4-5"


def classify_drift(drift: list[str]) -> tuple[bool, list[str]]:
    """Return (benign, offenders). Drift is benign iff every entry is the
    known background-Haiku housekeeping model."""
    offenders = [m for m in drift if not m.startswith(BACKGROUND_HAIKU_PREFIX)]
    return (len(offenders) == 0, offenders)


def main() -> int:
    arm = sys.argv[1]
    results_root = Path(sys.argv[2] if len(sys.argv) > 2 else "jobs_baseline/results")
    arm_dir = results_root / arm
    if not arm_dir.is_dir():
        print(f"(no results dir yet for arm={arm})")
        return 0

    result_files = sorted(arm_dir.glob("*/result.json"))
    if not result_files:
        print(f"(no completed runs yet for arm={arm})")
        return 0

    is_prewalk = arm.startswith("prewalk-")
    n_ok = n_bad = 0
    print(f"=== arm={arm}  n_runs={len(result_files)} ===")
    for rf in result_files:
        r = json.loads(rf.read_text())
        iid = r.get("instance_id", rf.parent.name)
        status = r.get("status")
        rr = r.get("run_result") or {}
        met = r.get("metrics") or {}
        pin = r.get("model_pin_check") or {}
        swap = bool(rr.get("swap_fired") or met.get("swap_fired"))
        patch_empty = bool(r.get("patch_empty", True))
        seq = met.get("model_sequence") or []
        ev = r.get("eval") or {}
        resolved = None
        if isinstance(ev, dict):
            rep = ev.get("report")
            if isinstance(rep, dict):
                # SWE-bench report.json nests the per-instance verdict under
                # {"report": {"<iid>": {"resolved": ...}}} or directly as
                # {"resolved": ...}; handle both shapes.
                if "resolved" in rep:
                    resolved = rep.get("resolved")
                else:
                    inner = rep.get(iid)
                    if isinstance(inner, dict):
                        resolved = inner.get("resolved")
            elif "resolved" in ev:
                resolved = ev.get("resolved")

        problems = []
        if status != "ok":
            problems.append(f"status={status}")
        if is_prewalk and not swap:
            problems.append("SWAP_DID_NOT_FIRE")
        if not patch_empty:
            pass  # good
        else:
            problems.append("PATCH_EMPTY")

        # Pin semantics (only meaningful when a pin_check ran). Re-derive
        # the match with DATE-TOLERANCE: a dated snapshot of an expected
        # family (e.g. observed "claude-haiku-4-5-20251001" for expected
        # "claude-haiku-4-5") IS that pin — the runner's stored
        # all_expected_matched uses exact-string equality and so mis-flags
        # the haiku executor, whose observed id carries a date suffix while
        # the expected constant is the undated alias.
        drift_note = ""
        if pin:
            expected = pin.get("expected_exact") or []
            observed = pin.get("observed_normalized") or []

            def _matches(exp: str, obs: str) -> bool:
                return obs == exp or obs.startswith(exp + "-")

            workloop_ok = all(any(_matches(e, o) for o in observed) for e in expected)
            # observed models explained by neither an expected pin (exact or
            # dated snapshot) nor the benign background-haiku housekeeping model
            unexplained = [
                o
                for o in observed
                if not any(_matches(e, o) for e in expected)
                and not o.startswith(BACKGROUND_HAIKU_PREFIX)
            ]
            if not workloop_ok:
                problems.append(f"WORKLOOP_PIN_MISSING(expected={expected} observed={observed})")
            if unexplained:
                problems.append(f"REAL_DRIFT={unexplained}")
            bg = [
                o
                for o in observed
                if o.startswith(BACKGROUND_HAIKU_PREFIX)
                and not any(_matches(e, o) for e in expected)
            ]
            if bg and not unexplained and workloop_ok:
                drift_note = f" (benign-haiku-bg={bg})"
        elif is_prewalk and not swap:
            drift_note = " (pin-check skipped: swap never fired)"

        verdict = "OK" if not problems else "FAIL:" + ",".join(problems)
        if problems:
            n_bad += 1
        else:
            n_ok += 1
        print(
            f"  [{verdict:<40}] {iid:<45} swap={swap} patch_empty={patch_empty} "
            f"resolved={resolved} seq={seq}{drift_note}"
        )

    print(f"--- summary: {n_ok} healthy, {n_bad} unhealthy ---")
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
