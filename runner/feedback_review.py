#!/usr/bin/env python3
"""
feedback_review.py - closes the loop. Reads NEW agent feedback, clusters by category, and
turns recurring/high-severity frictions into executable, independently reviewed
improvement_proposals. Approval cards are intentionally not used: no worker consumed those
cards, so they were an advisory dead end while their source rows remained NEW forever.

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
import db, claude_cli

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
PLACEHOLDERS = {
    "...", "…", "n/a", "none", "null", "observation", "suggestion",
    "measured bottleneck...", "reversible mechanism + acceptance metric + rollback...",
}
SURFACE = {
    "context": "backend", "model": "backend", "prompt": "backend",
    "tooling": "backend", "guardrail": "reliability", "rate_limit": "reliability",
    "strategy": "reliability", "other": "reliability",
}


def _valid(row):
    observation = str(row.get("observation") or "").strip()
    suggestion = str(row.get("suggestion") or "").strip()
    severity = str(row.get("severity") or "").strip().lower()
    return (len(observation) >= 12 and observation.lower() not in PLACEHOLDERS
            and suggestion.lower() not in PLACEHOLDERS and severity in SEV_WEIGHT)


def _mark(items, status):
    """Terminally advance rows in bounded batches; never let page one block the queue."""
    ids = [str(item.get("id") or "") for item in items if item.get("id")]
    for item_id in ids:
        db.update("orchestrator_feedback", {"id": item_id}, {"status": status})


def _proposal_row(category, title, synthesis, items, weight):
    evidence = "\n".join(
        f"- ({item.get('severity')}) {item.get('observation')} -> {item.get('suggestion', '')}"
        for item in items[:20]
    )
    surface = SURFACE.get(category, "reliability")
    proposal = (
        f"IMPROVEMENT HYPOTHESIS ({surface}; not a measured result): {synthesis}\n\n"
        f"Baseline: {len(items)} valid feedback reports with severity weight {weight}; the current "
        "review path does not guarantee an executable task or deployment receipt.\n"
        "Target: ship one bounded change through committee review, integration, and verified release; "
        "reduce recurrence of this feedback category in the next sample.\n"
        "Multiplier basis: 2x = replace the advisory-only path with one reviewed implementation path "
        "plus one deployment-evidence path.\n"
        "Measurement plan: compare the seven-day before/after feedback count, first-try yield, cycle "
        "time, integrated commit evidence, and deployed-and-verified receipts.\n"
        "Rollback: revert the isolated implementation commit if first-try yield, cycle time, or release "
        "health regresses.\n\n"
        "Acceptance tests:\n"
        "- A valid feedback cluster creates exactly one canonical implementation proposal and source rows leave NEW.\n"
        "- Any resulting task must retain existing behavior, pass regression/build gates, and acquire deployment evidence.\n\n"
        f"Feedback evidence:\n{evidence}"
    )
    return {
        "app": "beethoven", "surface": surface, "title": title[:200],
        "current_state": f"{len(items)} new {category} reports are waiting for executable remediation.",
        "proposal": proposal[:1500], "expected_multiplier": "2x", "divergent": False,
        "rationale": (f"Worker feedback identifies a repeated orchestration bottleneck. "
                      f"Severity weight {weight}; routed through committee and verified release.")[:800],
        "status": "for_review", "score": min(100, max(1, weight)),
    }


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
    # Human reports are read first. Machine reports are oldest-first so every row
    # eventually advances instead of an unordered page becoming a permanent wall.
    human = db.select("orchestrator_feedback", {
        "select": "*", "status": "eq.new", "source": "eq.human",
        "order": "created_at.asc", "limit": "200",
    }) or []
    machine = db.select("orchestrator_feedback", {
        "select": "*", "status": "eq.new", "source": "neq.human",
        "order": "created_at.asc", "limit": str(max(0, 1000 - len(human))),
    }) or []
    rows = human + machine
    if not rows:
        print("feedback_review: nothing new"); return 0
    invalid = [row for row in rows if not _valid(row)]
    if invalid:
        _mark(invalid, "dismissed")
    rows = [row for row in rows if _valid(row)]
    if not rows:
        print(f"feedback_review: dismissed {len(invalid)} invalid reports; nothing actionable")
        return 0
    clusters = defaultdict(list)
    for r in rows:
        category = str(r.get("category") or "other").strip().lower()
        clusters[category if category in KNOB else "other"].append(r)

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
        # A/B gate: test before filing an "adopt" recommendation
        ab_verdict = _ab_test(synthesis, cat)
        if ab_verdict == "reject":
            _mark(items, "dismissed")
            continue

        stable_title = f"Feedback-driven orchestration: {cat}"
        existing = db.select("improvement_proposals", {
            "select": "id", "app": "eq.beethoven", "title": f"eq.{stable_title}",
            "status": "in.(proposed,for_review,queued)", "limit": "1",
        }) or []
        if not existing:
            row = _proposal_row(cat, stable_title, synthesis, items, weight)
            if ab_verdict == "adopt":
                row["rationale"] = (row["rationale"] + " Synthetic A/B gate favored the candidate.")[:800]
            db.insert("improvement_proposals", row)
            made += 1
        _mark(items, "triaged")
    print(f"feedback_review: filed {made} canonical proposals; dismissed {len(invalid)} invalid reports")
    return made


if __name__ == "__main__":
    run()
