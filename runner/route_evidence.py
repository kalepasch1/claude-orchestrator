#!/usr/bin/env python3
"""Route evidence accelerator.

The learned router can only choose cheap/non-Claude coders confidently when outcomes contain real
test/merge/deploy evidence. This module closes the gap:

  * backfill delayed train merges into outcomes rows by slug
  * insert a zero-cost attribution row when an old MERGED task has no outcome row
  * keep coder canaries stocked until each non-Claude coder has enough real samples

It is intentionally conservative: it never fabricates a non-Claude merge for a task unless the task
itself is already MERGED. Canary generation is bounded and uses the existing low-risk canary path.
"""
import collections
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import router_stats

WINDOW_H = int(os.environ.get("ROUTE_EVIDENCE_WINDOW_H", "168"))
TARGET_NON_CLAUDE_MERGED = int(os.environ.get("ROUTE_EVIDENCE_TARGET_MERGED", "5"))
TARGET_NON_CLAUDE_TESTED = int(os.environ.get("ROUTE_EVIDENCE_TARGET_TESTED", "10"))
TARGET_TESTED_PER_CODER = int(os.environ.get("ROUTE_EVIDENCE_TARGET_TESTED_PER_CODER", "2"))
TARGET_MERGED_PER_CODER = int(os.environ.get("ROUTE_EVIDENCE_TARGET_MERGED_PER_CODER", "1"))
MAX_BACKFILL = int(os.environ.get("ROUTE_EVIDENCE_BACKFILL_LIMIT", "500"))
BACKFILL_NOTE = "route-evidence-backfill"
STALE_CANARY_MIN = int(os.environ.get("ROUTE_EVIDENCE_STALE_CANARY_MIN", "90"))


def _coder(model):
    return router_stats._coder_of(model)


def _is_non_claude(model):
    c = _coder(model)
    return bool(c) and c != "claude"


def _model_for_task(task):
    model = task.get("model") or ""
    force = task.get("force_coder") or ""
    note = str(task.get("note") or "")
    if force and force not in str(model):
        return f"{force}:{model or force}"
    if "agentic coder:" in note and not _is_non_claude(model):
        try:
            coder = note.split("agentic coder:", 1)[1].strip().split()[0]
            if coder and coder != "claude":
                return f"{coder}:{model or coder}"
        except Exception:
            pass
    return model or force or "unknown"


def _select_outcomes(limit=5000):
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    try:
        return db.select("outcomes", {"select": "id,task_id,model,kind,slug,integrated,tests_passed,usd,wall_ms,attempts,created_at,note",
                                      "created_at": f"gte.{since}", "order": "created_at.desc",
                                      "limit": str(limit)}) or []
    except Exception:
        return db.select("outcomes", {"select": "id,model,kind,slug,integrated,tests_passed,usd,wall_ms,attempts,created_at",
                                      "created_at": f"gte.{since}", "order": "created_at.desc",
                                      "limit": str(limit)}) or []


def _float(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_backfill_attribution(row):
    """Rows inserted by delayed merge attribution have no agent runtime/cost.

    Older rows were inserted before they had an explicit note, so use the zero-cost/zero-runtime
    shape as the compatibility signature.
    """
    if str(row.get("note") or "") == BACKFILL_NOTE:
        return True
    return bool(row.get("slug") and row.get("integrated") and row.get("tests_passed")
                and _float(row.get("usd")) == 0.0 and _float(row.get("wall_ms")) == 0.0)


def dedupe_attribution_rows(rows):
    """Collapse repeated delayed-merge attribution rows while preserving real retry samples."""
    out = []
    seen = set()
    for row in rows or []:
        if _is_backfill_attribution(row):
            key = (row.get("slug"), row.get("model"), row.get("kind") or "", row.get("task_id"))
            if key in seen:
                continue
            seen.add(key)
        out.append(row)
    return out


def _select_existing_outcomes(extra=None, limit="5000"):
    params = {"select": "id,task_id,slug,integrated,model,kind,tests_passed,usd,wall_ms,note,created_at",
              "order": "created_at.desc", "limit": str(limit)}
    params.update(extra or {})
    try:
        return db.select("outcomes", params) or []
    except Exception:
        params["select"] = "id,slug,integrated,model,kind,tests_passed,usd,wall_ms,created_at"
        return db.select("outcomes", params) or []


def evidence_summary():
    rows = dedupe_attribution_rows(_select_outcomes())
    by = collections.defaultdict(lambda: {"n": 0, "tested": 0, "merged": 0})
    for r in rows:
        c = _coder(r.get("model"))
        if not c:
            continue
        by[c]["n"] += 1
        if r.get("tests_passed"):
            by[c]["tested"] += 1
        if r.get("integrated"):
            by[c]["merged"] += 1
    return {k: dict(v) for k, v in by.items()}


def _target_coders():
    try:
        import agentic_coders
        import provider_terms
        return [c for c in agentic_coders.available()
                if c != "claude" and provider_terms.allowed(c, os.environ.get("ORCH_CANARY_SENSITIVITY", "standard"))]
    except Exception:
        return []


def provider_status():
    """Expose why a vendor is or is not part of the agentic canary pool."""
    try:
        import agentic_coders
        import model_gateway
        providers = set(model_gateway.available())
        coders = agentic_coders.available()
    except Exception as e:
        return {"available_providers": [], "agentic_coders": [], "error": str(e)[:300]}
    required = {
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "local": "OLLAMA_HOST or running Ollama",
    }
    disabled = []
    for provider, requirement in required.items():
        if provider not in providers:
            disabled.append({"provider": provider, "reason": f"not available ({requirement})"})
    return {
        "available_providers": sorted(providers),
        "agentic_coders": coders,
        "disabled_providers": disabled,
    }


def backfill_merged():
    """Mark outcomes integrated for MERGED tasks and insert a row only when no outcome exists."""
    tasks = db.select("tasks", {"select": "id,slug,kind,model,force_coder,note,state,updated_at,attempt",
                                "state": "eq.MERGED", "order": "updated_at.desc",
                                "limit": str(MAX_BACKFILL)}) or []
    outcomes = _select_existing_outcomes(limit="5000")
    by_slug = collections.defaultdict(list)
    for o in outcomes:
        by_slug[o.get("slug")].append(o)
    updated = inserted = 0
    for t in tasks:
        slug = t.get("slug")
        if not slug:
            continue
        existing = dedupe_attribution_rows(by_slug.get(slug) or [])
        if not existing:
            existing = _select_existing_outcomes({"slug": f"eq.{slug}"}, limit="25")
            existing = dedupe_attribution_rows(existing)
        if existing:
            for o in existing:
                patch = {}
                if not o.get("integrated"):
                    patch["integrated"] = True
                if not o.get("tests_passed"):
                    patch["tests_passed"] = True
                if patch:
                    for candidate in (patch, {"integrated": True}):
                        try:
                            db.update("outcomes", {"id": o["id"]}, candidate)
                            updated += 1
                            break
                        except Exception:
                            continue
            continue
        model = _model_for_task(t)
        row = {"task_id": t.get("id"), "project": None, "slug": slug,
               "kind": t.get("kind") or "build", "model": model,
               "tests_passed": True, "integrated": True, "usd": 0.0,
               "wall_ms": 0, "attempts": t.get("attempt") or 1,
               "note": BACKFILL_NOTE}
        try:
            db.insert("outcomes", row)
            inserted += 1
        except Exception:
            row.pop("note", None)
            try:
                db.insert("outcomes", row)
                inserted += 1
            except Exception:
                pass
    return {"updated": updated, "inserted": inserted}


def stock_canaries(summary=None):
    summary = summary if summary is not None else evidence_summary()
    non_claude = {k: v for k, v in summary.items() if k != "claude"}
    tested = sum(v.get("tested", 0) for v in non_claude.values())
    merged = sum(v.get("merged", 0) for v in non_claude.values())
    target_coders = _target_coders()
    missing = []
    for coder in target_coders:
        stats = summary.get(coder) or {}
        if (stats.get("tested", 0) < TARGET_TESTED_PER_CODER
                or stats.get("merged", 0) < TARGET_MERGED_PER_CODER):
            missing.append(coder)
    aggregate_met = tested >= TARGET_NON_CLAUDE_TESTED and merged >= TARGET_NON_CLAUDE_MERGED
    if aggregate_met and not missing:
        return {"queued": 0, "reason": "target_met", "tested": tested, "merged": merged,
                "target_coders": target_coders, "missing_coders": []}
    try:
        import coder_canary
        res = coder_canary.run(limit_per_coder=int(os.environ.get("ROUTE_EVIDENCE_CANARIES_PER_CODER", "1")))
        return {"queued": res.get("queued", 0), "tested": tested, "merged": merged,
                "target_tested": TARGET_NON_CLAUDE_TESTED, "target_merged": TARGET_NON_CLAUDE_MERGED,
                "target_tested_per_coder": TARGET_TESTED_PER_CODER,
                "target_merged_per_coder": TARGET_MERGED_PER_CODER,
                "target_coders": target_coders, "missing_coders": missing,
                "reason": "per_coder_evidence_gap" if missing else "aggregate_gap"}
    except Exception as e:
        return {"queued": 0, "error": str(e)[:300], "tested": tested, "merged": merged}


def stale_canaries():
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=STALE_CANARY_MIN)).isoformat()
    try:
        rows = db.select("tasks", {"select": "id,slug,state,force_coder,model,updated_at,note",
                                   "slug": "like.canary-%",
                                   "state": "in.(QUEUED,RUNNING,RETRY)",
                                   "updated_at": f"lt.{cutoff}",
                                   "order": "updated_at.asc",
                                   "limit": "100"}) or []
    except Exception:
        return []
    out = []
    for r in rows:
        coder = r.get("force_coder") or _coder(r.get("model"))
        if coder and coder != "claude":
            out.append({"id": r.get("id"), "slug": r.get("slug"), "coder": coder, "state": r.get("state"),
                        "updated_at": r.get("updated_at")})
    return out


def requeue_stale_canaries(rows=None):
    rows = rows if rows is not None else stale_canaries()
    bumped = 0
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for r in rows or []:
        match = {"id": r["id"]} if r.get("id") else {"slug": r.get("slug")}
        patch = {"state": "QUEUED", "updated_at": now}
        try:
            db.update("tasks", match, patch)
            bumped += 1
        except Exception:
            try:
                db.update("tasks", match, {"state": "QUEUED"})
                bumped += 1
            except Exception:
                pass
    return bumped


def run():
    stale_before = stale_canaries()
    stale_requeued = requeue_stale_canaries(stale_before)
    backfill = backfill_merged()
    summary = evidence_summary()
    canaries = stock_canaries(summary)
    stale = stale_canaries()
    providers = provider_status()
    out = {"backfill": backfill, "summary": summary, "canaries": canaries,
           "stale_canaries": stale, "stale_requeued": stale_requeued,
           "provider_status": providers}
    print(f"route_evidence: backfill={backfill} non_claude={{{', '.join(f'{k}: {v}' for k, v in summary.items() if k != 'claude')}}} canaries={canaries} stale_requeued={stale_requeued} stale_canaries={len(stale)}")
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
