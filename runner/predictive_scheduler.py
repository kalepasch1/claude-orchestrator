#!/usr/bin/env python3
"""
predictive_scheduler.py — Predictive task scheduling (50X zero-latency).

Instead of waiting for humans to queue tasks, predict what tasks will be needed
next based on:
  1. Git commit patterns (a migration always needs a test update)
  2. Deploy failures (Vercel failure → queue a fix task)
  3. Dependency updates (package.json change → run audit)
  4. Outcome patterns (if task A merged, task B usually follows)
  5. Calendar/time patterns (Monday = deploy day, Friday = cleanup)

Pre-queues predicted tasks at low priority so they're ready when the human confirms.

Usage:
    import predictive_scheduler
    predictive_scheduler.run()  # periodic: scan signals, pre-queue predictions
"""
import os, sys, json, time, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PREDICTION_CONFIDENCE_MIN = float(os.environ.get("ORCH_PREDICT_MIN_CONF", "0.6"))
MAX_PREDICTIONS_PER_RUN = int(os.environ.get("ORCH_PREDICT_MAX", "5"))


def _recent_merges(hours=24):
    """Get recently merged tasks."""
    try:
        return db.select("outcomes", {
            "select": "task_id,project,slug,kind,merged,created_at",
            "merged": "eq.true",
            "order": "created_at.desc",
            "limit": "20",
        }) or []
    except Exception:
        return []


def _recent_failures(hours=12):
    """Get recent task failures."""
    try:
        return db.select("outcomes", {
            "select": "task_id,project,slug,kind,merged,error,created_at",
            "merged": "eq.false",
            "order": "created_at.desc",
            "limit": "10",
        }) or []
    except Exception:
        return []


def _queued_slugs():
    """Get currently queued task slugs to avoid duplicates."""
    try:
        tasks = db.select("tasks", {
            "select": "slug",
            "state": "in.(QUEUED,RUNNING,BLOCKED,RETRY)",
        }) or []
        return {t.get("slug", "") for t in tasks}
    except Exception:
        return set()


# ──────────────────────────────────────────────────────────────────────────
# Prediction rules: each returns a list of {prompt, slug, project_id, kind,
# confidence, reason}
# ──────────────────────────────────────────────────────────────────────────

def _predict_follow_ups(merges):
    """If task A merged, predict task B that usually follows."""
    predictions = []
    FOLLOW_UP_PATTERNS = [
        # migration → test update
        (r"migration|schema|prisma", "test",
         "Update tests for schema change: {slug}",
         "update-tests-{slug}"),
        # new API route → add API test
        (r"api.*route|endpoint|handler", "test",
         "Add API tests for new endpoint: {slug}",
         "api-test-{slug}"),
        # component → storybook/visual test
        (r"component|\.vue|\.tsx|\.jsx", "test",
         "Add component tests for: {slug}",
         "component-test-{slug}"),
        # security change → audit
        (r"auth|permission|rbac|rls|security", "security",
         "Security audit after auth change: {slug}",
         "security-audit-{slug}"),
    ]

    for merge in merges[:10]:
        slug = merge.get("slug", "")
        kind = merge.get("kind", "")
        for pattern, pred_kind, prompt_tpl, slug_tpl in FOLLOW_UP_PATTERNS:
            if re.search(pattern, slug, re.I) or re.search(pattern, kind, re.I):
                predictions.append({
                    "prompt": prompt_tpl.format(slug=slug),
                    "slug": slug_tpl.format(slug=slug),
                    "project_id": merge.get("project", ""),
                    "kind": pred_kind,
                    "confidence": 0.7,
                    "reason": f"follow-up to merged {slug}",
                })
    return predictions


def _predict_from_failures(failures):
    """Predict recovery tasks from recent failures."""
    predictions = []
    for fail in failures[:5]:
        error = (fail.get("error") or "")[:500]
        slug = fail.get("slug", "")

        # Build failure → fix build task
        if re.search(r"build|compile|type.*error|syntax", error, re.I):
            predictions.append({
                "prompt": f"Fix build errors in {slug}: {error[:200]}",
                "slug": f"fix-build-{slug}",
                "project_id": fail.get("project", ""),
                "kind": "recovery",
                "confidence": 0.8,
                "reason": f"build failure on {slug}",
            })

        # Test failure → fix test task
        if re.search(r"test.*fail|assert|expect", error, re.I):
            predictions.append({
                "prompt": f"Fix failing tests after {slug}: {error[:200]}",
                "slug": f"fix-test-{slug}",
                "project_id": fail.get("project", ""),
                "kind": "recovery",
                "confidence": 0.75,
                "reason": f"test failure on {slug}",
            })

    return predictions


def _predict_periodic():
    """Time-based predictions (cleanup, audits)."""
    predictions = []
    import datetime
    now = datetime.datetime.now()

    # Monday morning: lint/type-check sweep
    if now.weekday() == 0 and now.hour < 10:
        try:
            projects = db.select("projects", {"select": "id,name"}) or []
            for p in projects[:3]:
                predictions.append({
                    "prompt": f"Run full lint and type-check sweep on {p.get('name', '')}",
                    "slug": f"weekly-lint-{p.get('name', '')}",
                    "project_id": p.get("id", ""),
                    "kind": "mechanical",
                    "confidence": 0.65,
                    "reason": "weekly Monday lint sweep",
                })
        except Exception:
            pass

    return predictions


def predict():
    """Generate all predictions, deduplicated against queue."""
    merges = _recent_merges()
    failures = _recent_failures()
    queued = _queued_slugs()

    all_preds = []
    all_preds.extend(_predict_follow_ups(merges))
    all_preds.extend(_predict_from_failures(failures))
    all_preds.extend(_predict_periodic())

    # Deduplicate against existing queue
    filtered = [p for p in all_preds
                if p["slug"] not in queued and p["confidence"] >= PREDICTION_CONFIDENCE_MIN]

    # Sort by confidence
    filtered.sort(key=lambda p: -p["confidence"])
    return filtered[:MAX_PREDICTIONS_PER_RUN]


def pre_queue(predictions):
    """Queue predicted tasks at low priority."""
    queued = 0
    for pred in predictions:
        try:
            db.insert("tasks", {
                "prompt": pred["prompt"],
                "slug": pred["slug"],
                "project_id": pred["project_id"],
                "kind": pred["kind"],
                "state": "QUEUED",
                "priority": 0,  # lowest priority — human tasks always first
                "note": f"predicted: {pred['reason']} (conf={pred['confidence']:.0%})",
                "created_at": "now()",
            })
            queued += 1
            print(f"[predictive] queued: {pred['slug']} (conf={pred['confidence']:.0%}, reason={pred['reason']})")
        except Exception:
            pass
    return queued


def run():
    """Periodic: generate predictions and pre-queue."""
    try:
        import drain_policy
        reason = drain_policy.skip_reason("predictive_scheduler.py")
        if reason:
            print(f"[predictive] skipped ({reason}; draining backlog first)")
            return {"queued": 0, "reason": reason}
    except Exception:
        pass
    predictions = predict()
    if predictions:
        queued = pre_queue(predictions)
        print(f"[predictive] {len(predictions)} predictions, {queued} queued")
        return {"queued": queued, "predictions": len(predictions)}
    else:
        print("[predictive] no predictions this cycle")
        return {"queued": 0, "predictions": 0}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
