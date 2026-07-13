#!/usr/bin/env python3
"""Per-coder canary batches.

Creates tiny, low-risk tasks forced to each available coder so router_stats gets
meaningful samples sooner than passive traffic would provide.
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import agentic_coders
import provider_terms


CANARY_PROMPT = """Canary task for the orchestrator coder pool.
Make the smallest safe repository-local improvement available, such as fixing a typo,
adding a tiny comment to clarify non-obvious test setup, or improving a harmless doc line.
Do not change product behavior, secrets, credentials, dependencies, or package managers.
Commit the change if and only if it is useful and passes existing checks."""
STALE_ACTIVE_MIN = int(os.environ.get("ORCH_CANARY_ACTIVE_STALE_MIN", "90"))


def _project():
    name = os.environ.get("ORCH_CANARY_PROJECT", "beethoven")
    rows = db.select("projects", {"select": "id,name", "name": f"eq.{name}", "limit": "1"}) or []
    if rows:
        return rows[0]
    rows = db.select("projects", {"select": "id,name", "limit": "1"}) or []
    return rows[0] if rows else None


def _canary_state(project_id):
    rows = db.select("tasks", {"select": "slug,state,force_coder,updated_at", "project_id": f"eq.{project_id}",
                               "slug": "like.canary-%", "limit": "1000"}) or []
    active, existing = set(), set()
    for r in rows:
        slug = str(r.get("slug") or "")
        coder = r.get("force_coder") or slug.replace("canary-", "").rsplit("-", 1)[0]
        existing.add(slug)
        if r.get("state") in ("QUEUED", "RUNNING", "RETRY") and not _stale(r.get("updated_at")):
            active.add(coder)
    return active, existing


def _stale(updated_at):
    if not updated_at:
        return False
    try:
        t = datetime.datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - t).total_seconds() > STALE_ACTIVE_MIN * 60
    except Exception:
        return False


def _historical_prompt(project_id):
    try:
        rows = db.select("tasks", {"select": "slug,kind,prompt,note", "project_id": f"eq.{project_id}",
                                   "slug": "like.recover-missing-branch-%",
                                   "state": "eq.QUEUED", "order": "updated_at.asc", "limit": "10"}) or []
    except Exception:
        rows = []
    non_recovery_rows = []
    for r in rows:
        if not str(r.get("slug") or "").startswith("recover-missing-branch-"):
            non_recovery_rows.append(r)
            continue
        prompt = str(r.get("prompt") or "").strip()
        if prompt and len(prompt) > 80:
            return (
                "Recovery-backlog canary for coder routing.\n"
                f"Use queued recovery task {r.get('slug')} as the acceptance style, but make only one tiny safe analogous change.\n"
                "This canary measures whether the coder can reconstruct missing-branch work from reuse-first context.\n"
                "Do not change secrets, dependencies, package managers, billing, legal copy, or product behavior.\n\n"
                "Recovery task prompt excerpt:\n" + prompt[:2200]
            )
    try:
        rows = db.select("tasks", {"select": "slug,kind,prompt,note", "project_id": f"eq.{project_id}",
                                   "state": "eq.MERGED", "order": "updated_at.desc", "limit": "20"}) or []
    except Exception:
        rows = non_recovery_rows
    if not rows and non_recovery_rows:
        rows = non_recovery_rows
    for r in rows:
        prompt = str(r.get("prompt") or "").strip()
        if prompt and len(prompt) > 80:
            return (
                "Historical merged-task canary for coder routing.\n"
                f"Prior merged task: {r.get('slug')} ({r.get('kind') or 'build'}).\n"
                "Use this as the acceptance style and project context, but do not duplicate the exact feature.\n"
                "Make one tiny safe analogous improvement, doc clarification, or test hygiene improvement that can merge cleanly.\n"
                "Do not change secrets, dependencies, package managers, billing, legal copy, or product behavior.\n\n"
                "Historical task prompt excerpt:\n" + prompt[:1800]
            )
    return CANARY_PROMPT


def run(limit_per_coder=2):
    if os.environ.get("ORCH_CODER_CANARIES", "true").lower() not in ("1", "true", "yes", "on"):
        return {"queued": 0, "reason": "disabled"}
    try:
        import drain_policy
        reason = drain_policy.skip_reason("coder_canary.py")
        if reason:
            return {"queued": 0, "reason": f"drain: {reason}"}
    except Exception:
        pass
    project = _project()
    if not project:
        return {"queued": 0, "reason": "no project"}
    sensitivity = os.environ.get("ORCH_CANARY_SENSITIVITY", "standard")
    active_for, existing_slugs = _canary_state(project["id"])
    canary_prompt = _historical_prompt(project["id"])
    queued = 0
    for coder in agentic_coders.available():
        if coder in active_for or not provider_terms.allowed(coder, sensitivity):
            continue
        for idx in range(int(limit_per_coder)):
            slug = _next_slug(coder, existing_slugs)
            row = {"project_id": project["id"], "slug": slug, "kind": "canary",
                   "state": "QUEUED", "prompt": canary_prompt,
                   "force_coder": coder, "material": False,
                   "sensitivity": sensitivity,
                   "note": "coder-canary: historical merged-task routing sample"}
            if not _insert_task(row):
                continue
            existing_slugs.add(slug)
            queued += 1
            break
    print(f"coder_canary: queued {queued} canaries")
    return {"queued": queued}


def _next_slug(coder, existing):
    i = 1
    while f"canary-{coder}-{i}" in existing:
        i += 1
    return f"canary-{coder}-{i}"


def _insert_task(row):
    """Insert a canary task, falling back to fewer columns on schema mismatch.

    The tasks table schema may lag behind code deploys (e.g. a new 'sensitivity'
    or 'force_coder' column hasn't been migrated yet). Rather than hard-failing,
    try progressively smaller column sets so canary routing isn't blocked by a
    pending migration.
    """
    variants = [
        row,
        {k: v for k, v in row.items() if k != "sensitivity"},
        {k: v for k, v in row.items() if k not in ("sensitivity", "material")},
        {k: v for k, v in row.items() if k not in ("sensitivity", "material", "force_coder")},
    ]
    for candidate in variants:
        try:
            db.insert("tasks", candidate)
            return True
        except Exception:
            pass
    return False


if __name__ == "__main__":
    print(run())
