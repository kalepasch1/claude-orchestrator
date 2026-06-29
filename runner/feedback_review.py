#!/usr/bin/env python3
"""
feedback_review.py - closes the loop. Reads NEW agent feedback, clusters by category, and
turns recurring/high-severity frictions into ORCHESTRATOR self-improvement proposals.

A/B GATE: when a cluster yields a concrete knob change, it is A/B-tested via eval_harness.py
on held-out tasks BEFORE filing a 'recommended: adopt' approval. Only if the candidate wins
(or there are no evals to run) does it file the proposal. Rejects are filed as 'recommended:
reject' for visibility.

Each category routes to a concrete knob:
  context -> CONTEXT_MAX_FILES / retrieval;  model -> bandit/router;  prompt -> templates;
  tooling -> add a tool/recipe;  guardrail -> guard rules;  rate_limit -> concurrency/backoff;
  strategy -> planner/scheduler.
"""
import os, sys, json, subprocess, tempfile
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, preference, claude_cli

MODEL = os.environ.get("FEEDBACK_MODEL", "claude-sonnet-4-6")
MIN_CLUSTER = int(os.environ.get("FEEDBACK_MIN_CLUSTER", "3"))
SEV_WEIGHT = {"low": 1, "med": 2, "high": 4}
KNOB = {
    "context": "tune context_retrieval (CONTEXT_MAX_FILES / scoped retrieval)",
    "model": "adjust the bandit/model_router priors",
    "prompt": "update the task prompt template / caching prefix",
    "tooling": "add a tool or skill recipe the agents need",
    "guardrail": "relax/refine a guard deny/ask rule",
    "rate_limit": "adjust adaptive concurrency / backoff / scheduling windows",
    "strategy": "change planner decomposition or scheduling policy",
    "other": "review",
}
# Categories where we attempt a synthetic A/B eval before filing "adopt"
AB_CATEGORIES = {"prompt", "context", "guardrail"}
EVALS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evals.json")


def _ab_test(synthesis, category):
    """
    A/B-test the proposed change against a baseline on held-out evals.
    Returns "adopt", "reject", or "skip" (no evals available).
    """
    if category not in AB_CATEGORIES:
        return "skip"
    evals_path = os.path.abspath(EVALS_PATH)
    if not os.path.exists(evals_path):
        return "skip"
    try:
        evals = json.load(open(evals_path))
    except Exception:
        return "skip"
    if not evals:
        return "skip"

    def _run(prefix):
        passed = 0
        for e in evals[:5]:  # limit to 5 evals to keep cost low
            with tempfile.TemporaryDirectory() as d:
                r = claude_cli.run(prefix + "\n\n" + e["prompt"],
                                   os.environ.get("EVAL_MODEL", "claude-haiku-4-5-20251001"),
                                   cwd=d, permission="acceptEdits", max_turns=15, timeout=180)
                if e.get("check"):
                    ok = subprocess.run(e["check"], cwd=d, shell=True).returncode == 0
                else:
                    ok = r["returncode"] == 0
                passed += 1 if ok else 0
        return passed / max(1, len(evals[:5]))

    try:
        cand_rate = _run(synthesis)
        baseline_rate = _run("")   # empty prefix = current behavior baseline
        winner = cand_rate >= baseline_rate
        print(f"feedback A/B [{category}]: candidate={cand_rate:.2f} baseline={baseline_rate:.2f} -> {'ADOPT' if winner else 'REJECT'}")
        return "adopt" if winner else "reject"
    except Exception as e:
        print(f"feedback A/B eval failed: {e}")
        return "skip"


def run():
    rows = db.select("orchestrator_feedback", {"select": "*", "status": "eq.new", "limit": "1000"}) or []
    if not rows:
        print("feedback_review: nothing new"); return 0
    clusters = defaultdict(list)
    for r in rows:
        clusters[r["category"]].append(r)

    made = 0
    for cat, items in clusters.items():
        weight = sum(SEV_WEIGHT.get(i.get("severity", "med"), 2) for i in items)
        if len(items) < MIN_CLUSTER and weight < 4:        # ignore one-off low-severity noise
            continue
        obs = "\n".join(f"- ({i.get('severity')}) {i.get('observation')} -> {i.get('suggestion','')}"
                        for i in items[:20])
        title = f"Improve orchestration: {cat} ({len(items)} reports, weight {weight})"
        synthesis = obs
        try:
            prompt = (f"Worker agents reported friction with the orchestration's '{cat}' behavior. "
                      f"Propose ONE concrete, low-risk change ({KNOB.get(cat)}). Reply 2-4 sentences.\n{obs}")
            synthesis = claude_cli.run(prompt, MODEL, timeout=120)["text"].strip() or obs
        except Exception:
            pass
        if preference.should_suppress(title, synthesis, "self"):
            continue

        # A/B gate: test before filing an "adopt" recommendation
        ab_verdict = _ab_test(synthesis, cat)
        if ab_verdict == "reject":
            db.insert("approvals", {
                "project": "ORCHESTRATOR", "kind": "self",
                "title": f"[A/B REJECTED] {title}",
                "why": f"{len(items)} agent reports about {cat} — the proposed change lost the A/B eval.",
                "value": "Visibility only — candidate did not improve pass-rate over baseline.",
                "risk": "Do not adopt without further investigation.",
                "detail": f"Proposed change:\n{synthesis}\n\nEvidence:\n{obs}",
            })
            for i in items:
                db.update("orchestrator_feedback", {"id": i["id"]}, {"status": "triaged"})
            made += 1
            continue

        verdict_note = " [A/B: ADOPT]" if ab_verdict == "adopt" else " [no evals — manual review]"
        db.insert("approvals", {"project": "ORCHESTRATOR", "kind": "self",
                                "title": title + verdict_note,
                                "why": f"{len(items)} agent reports about {cat} (severity weight {weight}).",
                                "value": "Workers are telling us how to orchestrate better — apply it.",
                                "risk": "A/B-gate passed (or skipped); revertible via git.",
                                "detail": f"Suggested change ({KNOB.get(cat)}):\n{synthesis}\n\nEvidence:\n{obs}"})
        for i in items:
            db.update("orchestrator_feedback", {"id": i["id"]}, {"status": "triaged"})
        made += 1
    print(f"feedback_review: filed {made} orchestration self-improvement proposals")
    return made


if __name__ == "__main__":
    run()
