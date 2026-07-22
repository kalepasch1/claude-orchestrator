#!/usr/bin/env python3
"""
intake_gate.py - Pre-queue EV filter and semantic deduplication for intake tasks.

Called by intake_watcher.ingest_file() before each task row is inserted.

Filters applied in order (first rejection wins):
  1. EV threshold (always on, INTAKE_VALUE_THRESHOLD default $0.10):
       Tasks whose estimated value < threshold are logged and skipped.
       Material-flagged tasks bypass this check.
  2. Semantic dedup (opt-in: INTAKE_EMBEDDING_DEDUP=1):
       Tasks whose prompt is cosine-similar (>= SIM_THRESHOLD, default 0.92) to an
       already-QUEUED/RUNNING task are rejected as duplicates.
       Fails open (passes the task) if embeddings are unavailable.

INTAKE_DRY_RUN=1: logs all rejections but always returns ok=True (preview mode).

Returns (ok: bool, reason: str) from should_queue().
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

VALUE_THRESHOLD = float(os.environ.get("INTAKE_VALUE_THRESHOLD", "0.10"))
EMBEDDING_DEDUP = os.environ.get("INTAKE_EMBEDDING_DEDUP", "").lower() in ("1", "true", "yes")
DRY_RUN = os.environ.get("INTAKE_DRY_RUN", "").lower() in ("1", "true", "yes")
SIM_THRESHOLD = float(os.environ.get("INTAKE_SIM_THRESHOLD", "0.92"))
_DEFAULT_VALUE = float(os.environ.get("INTAKE_DEFAULT_VALUE_USD", "0.50"))
_MIN_PROMPT_LEN = 30  # prompts shorter than this get zero value


def estimate_value(task, proj):
    """
    Estimate USD value for one intake task.
    Priority: explicit value_usd field > project MRR signal > prompt-quality heuristic.
    """
    if task.get("value_usd") is not None:
        return float(task["value_usd"])
    if task.get("material"):
        return 1.0
    mrr = _project_mrr(proj)
    if mrr > 0:
        # log10(1+mrr)*0.1 yields ~$0.29 at MRR=$100, ~$0.59 at MRR=$10k
        return math.log10(1 + mrr) * 0.1
    # Heuristic: a meaningful task needs a substantive prompt
    if len((task.get("prompt") or "").strip()) < _MIN_PROMPT_LEN:
        return 0.0
    return _DEFAULT_VALUE


def _project_mrr(proj):
    """Return MRR float for the project, 0.0 on any error."""
    if proj and proj.get("mrr_usd"):
        try:
            return float(proj["mrr_usd"])
        except (TypeError, ValueError):
            pass
    if proj and proj.get("name"):
        try:
            rows = db.select("app_revenue", {
                "select": "mrr_usd",
                "app": f"eq.{proj['name']}",
                "limit": "1",
            }) or []
            if rows:
                return float(rows[0].get("mrr_usd") or 0)
        except Exception:
            pass
    return 0.0


def _log_rejection(slug, reason, project_id):
    try:
        db.insert("resource_events", {
            "kind": "intake_rejected",
            "detail": f"slug={slug}: {reason}",
            "project_id": project_id,
        })
    except Exception:
        pass


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    mag = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return dot / mag if mag else 0.0


def _similar_exists(prompt, project_id):
    """True if an active QUEUED/RUNNING task is semantically close to prompt. Fails open."""
    try:
        import context_embed
        if not context_embed.ENABLED:
            return False
        vecs = context_embed._batch_embed([prompt])
        if not vecs:
            return False
        v = vecs[0]
        active = db.select("tasks", {
            "select": "id,prompt",
            "state": "in.(QUEUED,RUNNING,RETRY)",
            "project_id": f"eq.{project_id}",
            "limit": "300",
        }) or []
        for t in active:
            other = (t.get("prompt") or "").strip()
            if not other:
                continue
            evs = context_embed._batch_embed([other])
            if not evs:
                continue
            if _cosine(v, evs[0]) >= SIM_THRESHOLD:
                return True
    except Exception:
        pass
    return False


def should_queue(task, proj):
    """
    Decide whether an intake task should be inserted into the queue.

    Returns (ok: bool, reason: str).
    When ok=False the caller should skip the task.
    In DRY_RUN mode ok is always True but reason still describes the rejection.
    """
    slug = task.get("slug") or "?"
    project_id = proj.get("id") if proj else None

    if task.get("material"):
        return True, "material"

    val = estimate_value(task, proj)
    if val < VALUE_THRESHOLD:
        reason = (f"ev-rejection: estimated value ${val:.2f} below "
                  f"threshold ${VALUE_THRESHOLD:.2f}")
        _log_rejection(slug, reason, project_id)
        return DRY_RUN, reason

    if EMBEDDING_DEDUP and project_id:
        if _similar_exists(task.get("prompt") or "", project_id):
            reason = "dedup: semantically similar task already active"
            _log_rejection(slug, reason, project_id)
            return DRY_RUN, reason

    return True, "ok"
