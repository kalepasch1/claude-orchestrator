"""Admission gate for high-leverage self-improvement proposals.

Large multipliers are hypotheses, never evidence.  This gate requires a baseline,
mechanism, falsifiable target, tests, measurement window, and rollback before an
idea may enter the committee review queue.  Committees remain the independent,
multi-vendor QA layer that decides whether a surviving draft is built.
"""
import re


REQUIRED = (
    "title", "current_state", "proposal", "expected_multiplier",
    "multiplier_basis", "baseline_metric", "target_metric",
    "acceptance_tests", "measurement_plan", "rollback_plan", "rationale",
)
VAGUE = ("improve things", "optimize everything", "use ai", "make better", "tbd", "somehow")


def multiplier_value(value):
    match = re.search(r"(\d+(?:\.\d+)?)\s*x", str(value or ""), re.I)
    return float(match.group(1)) if match else None


def assess(idea):
    reasons = []
    for field in REQUIRED:
        value = idea.get(field)
        min_len = 2 if field == "expected_multiplier" else 8
        if value is None or (isinstance(value, str) and len(value.strip()) < min_len):
            reasons.append(f"missing-or-thin:{field}")
    proposal = str(idea.get("proposal") or "").lower()
    if any(term in proposal for term in VAGUE):
        reasons.append("vague-mechanism")
    multiplier = multiplier_value(idea.get("expected_multiplier"))
    if multiplier is None or multiplier < 2 or multiplier > 500:
        reasons.append("invalid-multiplier")
    if multiplier and multiplier >= 50:
        basis = str(idea.get("multiplier_basis") or "")
        if not re.search(r"\d", basis) or not any(op in basis for op in ("/", "*", "×", "from", "to")):
            reasons.append("50x-claim-lacks-baseline-math")
        claimed = f"{multiplier:g}x"
        if claimed.lower() not in basis.lower():
            reasons.append("multiplier-math-does-not-match-claim")
        else:
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", basis)]
            positive = [n for n in numbers if n > 0 and abs(n - multiplier) > 1e-9]
            implied = (max(positive) / min(positive)) if len(positive) >= 2 else multiplier
            if implied < multiplier / 2 and not re.search(
                    rf"(?:=|≈|~)\s*{re.escape(multiplier.__format__('g'))}\s*x", basis, re.I):
                reasons.append("multiplier-math-does-not-match-claim")
    tests = idea.get("acceptance_tests")
    if not isinstance(tests, list) or len([t for t in tests if str(t).strip()]) < 2:
        reasons.append("needs-two-acceptance-tests")
    plan = str(idea.get("measurement_plan") or "").lower()
    if not any(token in plan for token in ("hour", "day", "week", "sample", "before", "after", "control")):
        reasons.append("measurement-window-not-falsifiable")
    return {
        "pass": not reasons,
        "reasons": reasons,
        "multiplier_hypothesis": multiplier,
        "label": "scrutiny-ready-hypothesis" if not reasons else "draft-needs-revision",
    }


def implementation_spec(idea, surface, bottleneck_context=""):
    tests = "\n".join(f"- {t}" for t in (idea.get("acceptance_tests") or []))
    return (
        f"IMPROVEMENT HYPOTHESIS ({surface}; not a measured result): {idea.get('proposal','')}\n\n"
        f"Baseline: {idea.get('baseline_metric','')}\n"
        f"Target: {idea.get('target_metric','')}\n"
        f"Multiplier basis: {idea.get('multiplier_basis','')}\n"
        f"Measurement plan: {idea.get('measurement_plan','')}\n"
        f"Rollback: {idea.get('rollback_plan','')}\n\n"
        f"Acceptance tests:\n{tests}\n\n"
        "Implement the smallest reversible change that tests this hypothesis. Keep production green; "
        "do not report the multiplier as achieved until post-deploy measurement confirms it.\n\n"
        f"Live bottleneck context:\n{bottleneck_context[:2500]}"
    )


def redirect_legacy_direct_queue(db, limit=1000):
    """Move untouched legacy auto-queued ideas behind committee scrutiny.

    Active, completed, or already-decomposed work is deliberately preserved.
    Only QUEUED tasks that have not begun execution are quarantined and detached
    so the committee can compose a fresh, reviewed implementation task if approved.
    """
    proposals = db.select("improvement_proposals", {
        "select": "id,task_slug,status", "status": "eq.queued", "limit": str(limit)
    }) or []
    by_slug = {p.get("task_slug"): p for p in proposals if p.get("task_slug")}
    if not by_slug:
        return {"redirected": 0, "preserved_active_or_decomposed": 0}
    tasks = db.select("tasks", {"select": "id,slug,state,note",
                                "slug": "like.improve-%", "limit": str(limit * 3)}) or []
    redirected = preserved = 0
    for task in tasks:
        proposal = by_slug.get(task.get("slug"))
        if not proposal:
            continue
        state = task.get("state")
        if state not in ("QUEUED", "QUARANTINED"):
            preserved += 1
            continue
        if state == "QUEUED":
            db.update("tasks", {"id": task["id"]}, {
                "state": "QUARANTINED",
                "note": "legacy direct improvement queue redirected to committee scrutiny",
                "updated_at": "now()",
            })
        db.update("improvement_proposals", {"id": proposal["id"]}, {
            "status": "for_review", "task_slug": None,
        })
        redirected += 1
    return {"redirected": redirected,
            "preserved_active_or_decomposed": preserved}
