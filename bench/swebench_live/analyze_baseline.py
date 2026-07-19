#!/usr/bin/env python3
"""Directional analysis of the SWE-bench Live 3-arm baseline.

Reads every arm's per-run result.json and computes, per arm:
  - n_valid (status==ok), n_resolved, pass_rate
  - total true cost + cost-per-solved
  - swap-fired rate, real-drift count (non-background-haiku drift)
  - background-Haiku token share (mean/median/max), to check the
    trajectory-length confound (see SWEBENCH_LIVE_ANALYSIS.md, anomaly A1)

Prereg quality bar (PREREG_SWEBENCH_LIVE.md): a technique arm "preserves
quality" iff the bootstrap CI on the pass-rate difference (arm - opus-solo)
is NOT entirely below zero (i.e. includes zero or is positive). Because
each instance is run in every arm, we use a PAIRED bootstrap over the
instance intersection.

stdlib-only. Seeded for reproducibility. Safe to run mid-flight -- it just
reports whatever runs have completed so far.

Usage: analyze_baseline.py [results_root] [n_boot]
"""

import glob
import json
import random
import statistics
import sys
from pathlib import Path

ARMS = ["opus-solo", "prewalk-sonnet", "prewalk-haiku"]
BASELINE = "opus-solo"
BG_HAIKU = "claude-haiku-4-5"


def tok_total(d: object) -> int:
    if isinstance(d, dict):
        return sum(int(d.get(k, 0) or 0) for k in ("input", "output", "cache_read", "cache_creation"))
    if isinstance(d, (int, float)):
        return int(d)
    return 0


def load_arm(results_root: Path, arm: str) -> dict:
    """instance_id -> record for one arm."""
    recs = {}
    for f in sorted(glob.glob(str(results_root / arm / "*" / "result.json"))):
        r = json.loads(Path(f).read_text())
        iid = r.get("instance_id", Path(f).parent.name)
        m = r.get("metrics") or {}
        rr = r.get("run_result") or {}
        ev = r.get("eval") or {}
        rep = ev.get("report") if isinstance(ev, dict) else {}
        resolved = None
        if isinstance(rep, dict):
            if "resolved" in rep:
                resolved = rep.get("resolved")
            elif isinstance(rep.get(iid), dict):
                resolved = rep[iid].get("resolved")
        pmt = m.get("per_model_tokens") or {}
        hk = sum(tok_total(v) for k, v in pmt.items() if BG_HAIKU in k)
        allt = sum(tok_total(v) for v in pmt.values())
        drift = (r.get("model_pin_check") or {}).get("drift") or []
        real_drift = [d for d in drift if not d.startswith(BG_HAIKU)]
        recs[iid] = {
            "status": r.get("status"),
            "resolved": bool(resolved),
            "valid": r.get("status") == "ok",
            "cost": float(m.get("true_cost_usd") or 0.0),
            "swap_fired": bool(rr.get("swap_fired")),
            "haiku_share": (hk / allt) if allt else 0.0,
            "real_drift": real_drift,
            "n_turns": m.get("n_turns_total"),
        }
    return recs


def pct(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main() -> int:
    results_root = Path(sys.argv[1] if len(sys.argv) > 1 else "jobs_baseline/results")
    n_boot = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    rng = random.Random(20260719)

    arms = {a: load_arm(results_root, a) for a in ARMS}

    print("=" * 78)
    print("SWE-bench Live 3-arm baseline — directional analysis")
    print("=" * 78)
    for a in ARMS:
        recs = arms[a]
        if not recs:
            print(f"\n## {a}: (no runs yet)")
            continue
        valid = [r for r in recs.values() if r["valid"]]
        nres = sum(1 for r in valid if r["resolved"])
        tot_cost = sum(r["cost"] for r in recs.values())
        cps = (tot_cost / nres) if nres else float("nan")
        swaps = sum(1 for r in recs.values() if r["swap_fired"])
        rd = sum(1 for r in recs.values() if r["real_drift"])
        shares = [r["haiku_share"] for r in valid]
        pr = (nres / len(valid)) if valid else float("nan")
        print(f"\n## {a}")
        print(f"  runs={len(recs)}  valid={len(valid)}  resolved={nres}  pass_rate={pr:.1%}")
        print(f"  total_true_cost=${tot_cost:.2f}  cost_per_solved=${cps:.2f}")
        print(f"  swap_fired={swaps}/{len(recs)}  real_drift_runs={rd}")
        if shares:
            print(
                f"  bg_haiku_share: mean={statistics.mean(shares):.1%} "
                f"median={statistics.median(shares):.1%} max={max(shares):.1%}"
            )

    # Paired bootstrap: pass-rate diff (arm - baseline) over instance intersection
    base = arms[BASELINE]
    print("\n" + "=" * 78)
    print(f"Paired bootstrap vs {BASELINE} (n_boot={n_boot}, seeded)")
    print("=" * 78)
    for a in ARMS:
        if a == BASELINE or not arms[a]:
            continue
        arm = arms[a]
        common = [i for i in base if i in arm and base[i]["valid"] and arm[i]["valid"]]
        if len(common) < 2:
            print(f"\n{a}: paired n={len(common)} — too few for bootstrap")
            continue
        obs_diff = (
            sum(arm[i]["resolved"] for i in common) - sum(base[i]["resolved"] for i in common)
        ) / len(common)
        diffs = []
        cps_ratios = []
        for _ in range(n_boot):
            samp = [common[rng.randrange(len(common))] for _ in common]
            a_res = sum(arm[i]["resolved"] for i in samp)
            b_res = sum(base[i]["resolved"] for i in samp)
            diffs.append((a_res - b_res) / len(samp))
            a_cost = sum(arm[i]["cost"] for i in samp)
            b_cost = sum(base[i]["cost"] for i in samp)
            if a_res and b_res:
                cps_ratios.append((a_cost / a_res) / (b_cost / b_res))
        lo, hi = pct(diffs, 0.025), pct(diffs, 0.975)
        # Quality bar: PASS iff CI not entirely below zero
        quality = "PASS (quality preserved)" if hi >= 0 else "FAIL (quality dropped)"
        print(f"\n{a}: paired n={len(common)}")
        print(f"  pass_rate_diff (arm-baseline): obs={obs_diff:+.1%}  95%CI=[{lo:+.1%}, {hi:+.1%}]")
        print(f"  QUALITY BAR: {quality}")
        if cps_ratios:
            clo, chi = pct(cps_ratios, 0.025), pct(cps_ratios, 0.975)
            print(
                f"  cost_per_solved ratio (arm/baseline): median={statistics.median(cps_ratios):.2f} "
                f"95%CI=[{clo:.2f}, {chi:.2f}]  (<1 = cheaper per solve)"
            )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
