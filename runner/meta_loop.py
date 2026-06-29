#!/usr/bin/env python3
"""
meta_loop.py - the loop ON the loops. Scores how well each app's learning/remediation loops
are actually working (from outcomes), tunes their cadence (raises remediate frequency for
flaky apps, lowers optimize for stable ones), cross-deploys the best-performing loop configs
from one app to underperforming apps, and asks each loop's Claude Code agent "how could this
app's loop or the app itself be improved?" — routing those answers through feedback_review.
Schedule daily.
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, feedback, claude_cli

MODEL = os.environ.get("METALOOP_MODEL", "claude-sonnet-4-6")

# Cadence bounds (seconds) per loop type
CADENCE_BOUNDS = {
    "remediate": (60, 600),        # flaky apps: tighter; stable: looser
    "optimize":  (21600, 604800),  # stable apps: less frequent
    "learn":     (86400, 604800),
    "review":    (43200, 604800),
}
# How much to adjust cadence each meta_loop run (fraction of current cadence)
TUNE_STEP = 0.25
# Health score gap that triggers a cross-deploy proposal
CROSS_DEPLOY_GAP = 15


def _project_score(project):
    rows = db.select("outcomes", {"select": "tests_passed,integrated,rate_limited",
                                  "project": f"eq.{project}", "limit": "300"}) or []
    if not rows:
        return None
    n = len(rows)
    passed = sum(1 for r in rows if r.get("tests_passed")) / n
    merged = sum(1 for r in rows if r.get("integrated")) / n
    rl = sum(1 for r in rows if r.get("rate_limited")) / n
    return round(100 * (0.5 * passed + 0.5 * merged) - 20 * rl, 1)


def _tune_cadence(loop, score):
    """
    Adjust a loop's cadence based on the project's health score.
    Flaky (low score) -> tighter remediate cadence, looser optimize.
    Stable (high score) -> looser remediate, tighter optimize.
    Returns new cadence_seconds or None if no change needed.
    """
    typ = loop["type"]
    if typ not in CADENCE_BOUNDS:
        return None
    lo, hi = CADENCE_BOUNDS[typ]
    cur = int(loop.get("cadence_seconds") or (lo + hi) // 2)
    if score is None:
        return None
    if typ == "remediate":
        # low score -> decrease cadence (more frequent)
        direction = -1 if score < 60 else (1 if score > 85 else 0)
    elif typ == "optimize":
        # high score -> decrease cadence (more frequent); low -> less frequent (don't waste on broken)
        direction = -1 if score > 80 else (1 if score < 50 else 0)
    else:
        direction = 0
    if direction == 0:
        return None
    step = max(60, int(cur * TUNE_STEP))
    new_cad = max(lo, min(hi, cur + direction * step))
    return new_cad if new_cad != cur else None


def _ask_improvement(project, loop_type):
    """
    Ask a Claude Code agent how this app's loop or the app itself could be improved.
    Routes the answer through feedback.submit so feedback_review can cluster it.
    """
    prompt = (
        f"You are reviewing the orchestration loop for project '{project}' (loop type: {loop_type}). "
        f"Based on general knowledge of software quality loops, suggest ONE concrete improvement "
        f"for either (a) the loop itself (cadence, scope, checks) or (b) the app. "
        f"Reply as a JSON object: "
        f'{{\"category\":\"strategy\",\"severity\":\"med\",\"observation\":\"...\",\"suggestion\":\"...\"}}'
    )
    try:
        resp = claude_cli.run(prompt, MODEL, permission=None, max_turns=1, timeout=90)
        import re, json
        m = re.search(r"\{.*\}", resp["text"] or "", re.S)
        if m:
            it = json.loads(m.group(0))
            feedback.submit(
                it.get("category", "strategy"), it.get("observation", ""),
                it.get("suggestion", ""), it.get("severity", "med"),
                project=project, slug=f"metaloop-{loop_type}", source="meta_loop",
            )
    except Exception as e:
        print(f"meta_loop: improvement question failed for {project}/{loop_type}: {e}")


def run():
    loops = db.select("loops", {"select": "*"}) or []
    by_project = {}
    for l in loops:
        by_project.setdefault(l["project"], []).append(l)
    scores = {p: _project_score(p) for p in by_project}
    rated = {p: s for p, s in scores.items() if s is not None}

    tuned = 0
    for p, ls in by_project.items():
        score = scores.get(p)
        if score is None:
            db.update("loops", {"project": p}, {"health": 0})
            continue
        for l in ls:
            db.update("loops", {"id": l["id"]}, {"health": score})
            new_cad = _tune_cadence(l, score)
            if new_cad:
                db.update("loops", {"id": l["id"]}, {"cadence_seconds": new_cad})
                tuned += 1
                print(f"meta_loop: tuned {p}/{l['type']} cadence {l['cadence_seconds']}s -> {new_cad}s (score {score})")
        # Ask for loop improvement suggestions (one per project per meta_loop run)
        _ask_improvement(p, "remediate")

    if len(rated) < 2:
        print(f"meta_loop: tuned {tuned} cadences; not enough projects to cross-deploy")
        return tuned

    best = max(rated, key=rated.get)
    worst = min(rated, key=rated.get)

    # write health back + cross-deploy if gap is large
    if rated[best] - rated[worst] > CROSS_DEPLOY_GAP:
        best_cfg = {l["type"]: {"cadence_seconds": l["cadence_seconds"], "config": l.get("config")}
                    for l in by_project[best]}
        db.insert("approvals", {"project": worst, "kind": "self",
            "title": f"Cross-deploy '{best}' loop config to '{worst}'",
            "why": f"{best} loop-health {rated[best]} vs {worst} {rated[worst]}.",
            "value": "Propagate the better-performing learning/remediation cadence.",
            "risk": "Tune after applying; revertible.",
            "detail": str(best_cfg)})
        print(f"meta_loop: proposed cross-deploy {best}({rated[best]}) -> {worst}({rated[worst]})")
        tuned += 1

    print(f"meta_loop: {tuned} cadence tunes; best {best}={rated[best]}, worst {worst}={rated[worst]}")
    return tuned


if __name__ == "__main__":
    run()
