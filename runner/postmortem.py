#!/usr/bin/env python3
"""
postmortem.py - autonomous postmortem generation for rollbacks/incidents.

Every rollback or incident auto-writes a postmortem record and creates a
preventive guard TASK so reliability provably improves after each failure.
Records are stored in the incidents_postmortems table.
"""
from __future__ import annotations
import datetime, hashlib, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MAX_CONTEXT_CHARS = int(os.environ.get("ORCH_POSTMORTEM_MAX_CONTEXT", "4000"))
GUARD_KIND = "bugfix"
_BUILD_FAIL = re.compile(r"build.*fail|BUILDFAIL|build error|build red", re.I)
_TEST_FAIL = re.compile(r"test.*fail|tests? (failed|error)|vitest|pytest.*FAILED", re.I)
_MERGE_CONFLICT = re.compile(r"conflict|merge.*fail|rebase.*fail|HTTP Error 409", re.I)
_TIMEOUT = re.compile(r"timeout|timed? out|deadline exceeded", re.I)
_ROLLBACK = re.compile(r"rollback|revert|rolled back|reverted", re.I)

def _classify(note):
    if not note: return "unknown"
    if _ROLLBACK.search(note): return "rollback"
    if _BUILD_FAIL.search(note): return "build_failure"
    if _TEST_FAIL.search(note): return "test_failure"
    if _MERGE_CONFLICT.search(note): return "merge_conflict"
    if _TIMEOUT.search(note): return "timeout"
    return "unknown"

def _fingerprint(project_id, slug, category):
    """Deterministic 16-char hex ID for deduplicating postmortems of the same failure."""
    return hashlib.sha256(f"{project_id}:{slug}:{category}".encode()).hexdigest()[:16]

def _truncate(text, limit=MAX_CONTEXT_CHARS):
    if not text or len(text) <= limit: return text or ""
    return text[:limit] + "\n... [truncated]"

def _guard_prompt(slug, category, note):
    ctx = _truncate(note, 800)
    return (f"Prevent recurrence of '{category}' failure from task '{slug}'. "
            f"Add a guard/check so this class of failure is caught before merge. "
            f"Context: {ctx}")

def create_postmortem(task_row):
    slug = task_row.get("slug", "")
    project_id = task_row.get("project_id", "")
    note = task_row.get("note") or task_row.get("error") or ""
    category = _classify(note)
    row = {"fingerprint": _fingerprint(project_id, slug, category),
           "project_id": project_id, "task_slug": slug,
           "task_id": task_row.get("id"), "category": category,
           "summary": f"Auto-postmortem for {slug}: {category}",
           "failure_context": _truncate(note),
           "preventive_action": _guard_prompt(slug, category, note),
           "created_at": datetime.datetime.utcnow().isoformat() + "Z"}
    try: return db.upsert("incidents_postmortems", row)
    except Exception: return None

def create_guard_task(task_row, project_id=None):
    slug = task_row.get("slug", "")
    pid = project_id or task_row.get("project_id", "")
    note = task_row.get("note") or task_row.get("error") or ""
    category = _classify(note)
    guard = {"project_id": pid, "slug": f"guard-{category}-{slug}"[:80],
             "kind": GUARD_KIND, "state": "QUEUED",
             "prompt": _guard_prompt(slug, category, note),
             "base_branch": task_row.get("base_branch", "master"),
             "deps": [], "note": f"auto-generated guard from postmortem of {slug}"}
    try: return db.insert("tasks", guard)
    except Exception: return None

def process_incident(task_row):
    pm = create_postmortem(task_row)
    guard = create_guard_task(task_row) if pm else None
    return {"postmortem": pm, "guard_task": guard}

def sweep(project_id, limit=50):
    try:
        rows = db.select("tasks", {
            "select": "id,slug,project_id,note,state,base_branch,kind",
            "project_id": f"eq.{project_id}",
            "state": "in.(BLOCKED,SHELVED)",
            "order": "updated_at.desc", "limit": str(limit)}) or []
    except Exception: return []
    results = []
    for row in rows:
        note = row.get("note") or ""
        if not note or "auto-generated guard" in note: continue
        result = process_incident(row)
        if result.get("postmortem"): results.append(result)
    return results
