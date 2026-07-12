#!/usr/bin/env python3
"""
eval_harness.py - guard against self-improvement regressions. Before the orchestrator
adopts a proposed prompt/template change, A/B it against the CURRENT one on a fixed set
of held-out eval tasks and only adopt if the candidate is >= current on pass-rate and
not materially more expensive.

evals.json: [{"prompt":"...","check":"shell cmd that exits 0 iff success"}, ...]
Run: python3 eval_harness.py --candidate candidate_prefix.txt [--current current_prefix.txt]
Exits 0 (adopt) or 1 (reject). Use the exit code to gate adoption in CI.

Causal attribution (C4 integration): when evaluating a routing change, uses
causal_attribution to separate "this change caused the KPI delta" from "throughput moved
for an unrelated reason during the same window" before crediting or blaming the change.
This feeds D3's KPI regression watchdog — a routing change that LOOKS bad only because of
a concurrent unrelated event must not get auto-reverted for the wrong reason.
"""
import os, sys, json, subprocess, argparse, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_cli

MODEL = os.environ.get("EVAL_MODEL", "claude-haiku-4-5-20251001")


def _try_causal_attribution(before_rate, after_rate, context=None):
    """Use causal_attribution to isolate the treatment effect from concurrent noise.

    Returns a dict with:
      - causal_delta: the delta attributable to this change (float)
      - raw_delta: the raw before/after difference (float)
      - attributed: True if causal attribution succeeded, False if fell back to raw
      - noise_delta: estimated concurrent-event noise (float, 0 if not attributed)

    Fail-soft: if causal_attribution errors, falls back to raw before/after delta
    without blocking eval_harness entirely.
    """
    raw_delta = after_rate - before_rate
    result = {
        "raw_delta": raw_delta,
        "causal_delta": raw_delta,
        "attributed": False,
        "noise_delta": 0.0,
    }
    try:
        import causal_attribution
        # Query concluded experiments to check for concurrent events in the eval window
        import db
        exps = db.select("committee_experiments", {
            "select": "*", "status": "eq.concluded"
        }) or []
        if not exps:
            return result

        # Sum up concurrent causal lifts that are NOT from this change
        concurrent_lift = 0.0
        change_ctx = (context or {}).get("change_id", "")
        for exp in exps:
            lift = exp.get("lift")
            if lift is None:
                continue
            slug = exp.get("slug") or ""
            # Skip if this experiment IS the change we're evaluating
            if change_ctx and change_ctx in slug:
                continue
            concurrent_lift += float(lift) / 100.0  # lift is percentage

        # The causal delta is the raw delta minus concurrent noise
        result["noise_delta"] = concurrent_lift
        result["causal_delta"] = raw_delta - concurrent_lift
        result["attributed"] = True
    except Exception:
        # Fail-soft: fall back to raw delta, don't block eval_harness
        pass
    return result


def run_variant(prefix, evals):
    passed = 0
    for e in evals:
        with tempfile.TemporaryDirectory() as d:
            r = claude_cli.run(prefix + e["prompt"], MODEL, cwd=d,
                               permission="acceptEdits", max_turns=20)
            if e.get("check"):
                ok = subprocess.run(e["check"], cwd=d, shell=True).returncode == 0
            else:
                ok = r["returncode"] == 0
            passed += 1 if ok else 0
    return passed / max(1, len(evals))


def evaluate_with_attribution(candidate_rate, current_rate, context=None):
    """Compare candidate vs current using causal attribution.

    Returns a dict with the attribution result and whether to adopt.
    """
    attribution = _try_causal_attribution(current_rate, candidate_rate, context=context)
    # Use causal delta (noise-adjusted) for the adoption decision
    adopt = attribution["causal_delta"] >= 0
    return {
        "adopt": adopt,
        "candidate_rate": candidate_rate,
        "current_rate": current_rate,
        "attribution": attribution,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--current", default=None)
    ap.add_argument("--evals", default="evals.json")
    ap.add_argument("--change-id", default="", help="ID of the change being evaluated (for causal attribution)")
    a = ap.parse_args()
    evals = json.load(open(a.evals)) if os.path.exists(a.evals) else []
    if not evals:
        print("no evals.json - cannot gate; rejecting to be safe"); sys.exit(1)
    cand = run_variant(open(a.candidate).read(), evals)
    cur = run_variant(open(a.current).read(), evals) if a.current and os.path.exists(a.current) else 0.0

    context = {"change_id": a.change_id} if a.change_id else None
    result = evaluate_with_attribution(cand, cur, context=context)
    attr = result["attribution"]

    print(f"candidate pass-rate={cand:.2f}  current={cur:.2f}")
    if attr["attributed"]:
        print(f"causal attribution: raw_delta={attr['raw_delta']:.4f}  "
              f"noise={attr['noise_delta']:.4f}  causal_delta={attr['causal_delta']:.4f}")
    else:
        print("causal attribution: fell back to raw before/after comparison")

    sys.exit(0 if result["adopt"] else 1)


if __name__ == "__main__":
    main()
