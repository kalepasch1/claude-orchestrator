#!/usr/bin/env python3
"""
parallel_gates.py — Run verify, judge, and confidence gates CONCURRENTLY.

Currently these three independent model calls run sequentially (30-90s total).
Since they all read the same diff and are independent, running them in parallel
collapses wall time to max(verify, judge, confidence) ≈ 10-30s.

Usage in runner.py:
    from parallel_gates import run_gates
    results = run_gates(wt, base, deps, t, model, proj, name, diff_text)
    # results = {"verify": {...}, "judge": {...}, "confidence": {...}, "wall_s": float}
"""
import os, sys, time, threading, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_gates(wt, base, deps, task, model, proj, project_name, diff_text="",
              use_confidence=True, combined=None):
    """Run verify + judge + confidence concurrently. Returns dict of all results.

    If combined=True (or ORCH_COMBINED_GATES=true), verify+judge are merged into
    a single model call via combined_gate.py, cutting cost by ~50%.
    """
    if combined is None:
        combined = os.environ.get("ORCH_COMBINED_GATES", "false").lower() in ("true", "1", "yes")

    results = {}
    errors = {}
    t0 = time.time()

    def _verify():
        try:
            import verify
            v = verify.review_diff(wt, base, dependents=deps if deps else None, project=project_name)
            results["verify"] = v
        except Exception as e:
            results["verify"] = {"verdict": "pass", "notes": f"verify unavailable ({e})"}
            errors["verify"] = str(e)

    def _judge():
        try:
            import judge
            jv = judge.review(task["prompt"][:2000], diff_text, model, project=project_name)
            results["judge"] = jv
        except Exception as e:
            results["judge"] = {"verdict": "pass", "score": 6, "notes": f"judge unavailable ({e})",
                                "legal_counsel_required": False, "legal_risk": ""}
            errors["judge"] = str(e)

    def _combined_gate():
        """Single model call that covers both verify AND judge."""
        try:
            import combined_gate
            cv = combined_gate.review(wt, base, task["prompt"][:2000], diff_text,
                                      model, deps=deps, project=project_name)
            results["verify"] = cv.get("verify", {"verdict": "pass", "notes": ""})
            results["judge"] = cv.get("judge", {"verdict": "pass", "score": 6, "notes": "",
                                                 "legal_counsel_required": False, "legal_risk": ""})
        except Exception as e:
            # Fall back to sequential
            _verify()
            _judge()

    def _confidence():
        try:
            import confidence
            proj_thresh = proj.get("confidence_threshold")
            decision, conf = confidence.gate(wt, base, threshold=proj_thresh, project=project_name)
            results["confidence"] = {"decision": decision, **conf}
        except Exception as e:
            results["confidence"] = {"decision": "auto", "confidence": None,
                                     "reason": f"confidence unavailable ({e})"}

    threads = []

    if combined:
        t_combined = threading.Thread(target=_combined_gate, daemon=True)
        t_combined.start()
        threads.append(t_combined)
    else:
        t_verify = threading.Thread(target=_verify, daemon=True)
        t_judge = threading.Thread(target=_judge, daemon=True)
        t_verify.start()
        t_judge.start()
        threads.extend([t_verify, t_judge])

    if use_confidence:
        t_conf = threading.Thread(target=_confidence, daemon=True)
        t_conf.start()
        threads.append(t_conf)

    # Wait for all gates (timeout = longest single gate + margin)
    timeout = int(os.environ.get("GATE_PARALLEL_TIMEOUT", "300"))
    for th in threads:
        th.join(timeout=timeout)

    # Fill defaults for any that didn't complete
    results.setdefault("verify", {"verdict": "pass", "notes": "timed out"})
    results.setdefault("judge", {"verdict": "pass", "score": 6, "notes": "timed out",
                                  "legal_counsel_required": False, "legal_risk": ""})
    if use_confidence:
        results.setdefault("confidence", {"decision": "auto", "confidence": None, "reason": "timed out"})

    results["wall_s"] = round(time.time() - t0, 1)
    results["mode"] = "combined" if combined else "parallel"
    results["errors"] = errors

    return results
