#!/usr/bin/env python3
"""
quarantine_remediation.py - periodic quarantine-to-requeue remediation.

Scans QUARANTINED tasks, identifies real improvements that were never deployed,
cross-references against successfully merged work, and requeues undelivered
improvements so they get a fresh execution attempt.

Runs as a periodic job in the runner schedule. Designed to prevent quarantined
improvements from accumulating forever without resolution.

Categories handled:
  - orphaned DECOMPOSED: parent never got children → requeue original prompt
  - branch-lost: work done but branch GC'd → requeue with original prompt
  - merge conflicts: work done but branch too diverged → requeue fresh
  - generic errors: execution failed → requeue with retry note
  - secret/credential flags: rework needed → requeue with sanitization directive

Categories skipped (terminal):
  - sentinel/semantic dedupes: original task exists elsewhere
  - garbage/non-actionable: not real improvements
  - canary/routing tests: infrastructure, not improvements
  - recovery-of-recovery: meta-tasks, not original work
"""
import os
import sys
import re
import time
import hashlib
from typing import Optional
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ── Config ──────────────────────────────────────────────────────────────────
MAX_REQUEUE_PER_RUN = int(os.environ.get("ORCH_REMEDIATION_BATCH", "50"))
REMEDIATION_COOLDOWN_H = float(os.environ.get("ORCH_REMEDIATION_COOLDOWN_H", "24"))
MIN_QUARANTINE_AGE_H = float(os.environ.get("ORCH_REMEDIATION_MIN_AGE_H", "4"))
MAX_REMEDIATION_ATTEMPTS = int(os.environ.get("ORCH_REMEDIATION_MAX_ATTEMPTS", "3"))

# Slugs matching these patterns are NOT real improvements — skip them
SKIP_SLUG_PATTERNS = [
    r"^canary-",
    r"^recover-missing-branch-",
    r"^rework-recover-",
    r"^retry-recover-",
    r"^queue-bankruptcy",
    r"^sentinel-",
    r"^shadow-",
    r"^backlog-batch-",
    r"^fused-canary-",
]

# Prompts matching these are garbage — skip
SKIP_PROMPT_PATTERNS = [
    r"^PATCH TEMPLATE",
    r"^- PATCH TEMPLATE",
    r"^- SOURCE.*PATCH TEMPLATE",
    r"^MERGED-DIFF LIBRARY.*PATCH TEMPLATE",
    r"^REUSE FIRST.*PATCH TEMPLATE",
    r"Recovery-backlog canary",
    r"Historical merged-task canary",
]

# Notes indicating the task is a dupe (original exists elsewhere)
DUPE_NOTE_PATTERNS = [
    r"sentinel.dedupe",
    r"semantic.dedupe",
    r"duplicate of",
    r"preflight:.*garbage",
    r"non-actionable",
    r"Junk:",
]


def _is_skip_slug(slug: str) -> bool:
    for pat in SKIP_SLUG_PATTERNS:
        if re.search(pat, slug, re.I):
            return True
    return False


def _is_garbage_prompt(prompt: str) -> bool:
    if not prompt or len(prompt) < 20:
        return True
    for pat in SKIP_PROMPT_PATTERNS:
        if re.search(pat, prompt[:200], re.I):
            return True
    return False


def _is_dupe_note(note: str) -> bool:
    for pat in DUPE_NOTE_PATTERNS:
        if re.search(pat, note, re.I):
            return True
    return False


def _normalize_slug(slug: str) -> str:
    """Extract core improvement intent from a slug."""
    s = slug
    s = re.sub(r"-slice-\d+$", "", s)
    s = re.sub(r"-\d{10,}$", "", s)
    s = re.sub(r"-[0-9a-f]{8,}$", "", s)
    s = re.sub(r"^recover-missing-branch-", "", s)
    s = re.sub(r"^rework-", "", s)
    s = re.sub(r"^retry-", "", s)
    s = re.sub(r"^remediate-", "", s)
    return s


def _age_hours(iso_ts: str) -> float:
    """Hours since an ISO timestamp."""
    try:
        from datetime import datetime, timezone
        if iso_ts.endswith("Z"):
            iso_ts = iso_ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 999


def _get_deployed_slugs() -> set:
    """Get normalized slugs of all successfully deployed improvements."""
    deployed = set()
    offset = 0
    while True:
        rows = db.select("tasks", {
            "select": "slug",
            "state": "eq.MERGED",
            "artifact_branch": "not.is.null",
            "limit": "1000",
            "offset": str(offset),
        }) or []
        for r in rows:
            s = r.get("slug", "")
            deployed.add(s)
            deployed.add(_normalize_slug(s))
        if len(rows) < 1000:
            break
        offset += 1000
    return deployed


def _requeue_task(task: dict, reason: str) -> bool:
    """Create a fresh QUEUED task from a quarantined one."""
    prompt = task.get("prompt", "")
    if not prompt:
        return False

    slug_base = _normalize_slug(task.get("slug", ""))
    h = hashlib.md5(prompt.encode()).hexdigest()[:6]
    new_slug = f"remediate-{slug_base}-{h}"[:80]

    remediation_count = int(task.get("remediation_count") or 0)

    try:
        db.insert("tasks", {
            "slug": new_slug,
            "prompt": prompt,
            "project_id": task.get("project_id"),
            "state": "QUEUED",
            "kind": task.get("kind") or "improvement",
            "note": f"auto-remediation: {reason} (attempt {remediation_count + 1})",
            "priority": 5,
            "remediation_count": remediation_count + 1,
        })
        return True
    except Exception as e:
        if "23505" in str(e):  # unique constraint — already requeued
            return False
        print(f"[remediation] requeue failed for {task.get('slug')}: {e}")
        return False


def run():
    """Main periodic entry point. Scan quarantined tasks and requeue viable ones."""
    started = time.time()

    # Get quarantined tasks that are old enough
    quarantined = []
    offset = 0
    while True:
        rows = db.select("tasks", {
            "select": "id,slug,prompt,note,project_id,kind,created_at,updated_at,remediation_count",
            "state": "eq.QUARANTINED",
            "limit": "1000",
            "offset": str(offset),
        }) or []
        quarantined.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000

    if not quarantined:
        return

    # Get deployed slugs for cross-reference
    deployed = _get_deployed_slugs()

    requeued = 0
    skipped_meta = 0
    skipped_garbage = 0
    skipped_dupe = 0
    skipped_deployed = 0
    skipped_max_attempts = 0
    skipped_too_young = 0

    for t in quarantined:
        if requeued >= MAX_REQUEUE_PER_RUN:
            break
        if time.time() - started > 120:  # 2-minute budget
            break

        slug = t.get("slug", "")
        prompt = t.get("prompt", "") or ""
        note = t.get("note", "") or ""
        updated = t.get("updated_at", "")
        remediation_count = int(t.get("remediation_count") or 0)

        # Skip if too recently quarantined
        if updated and _age_hours(updated) < MIN_QUARANTINE_AGE_H:
            skipped_too_young += 1
            continue

        # Skip meta/infrastructure tasks
        if _is_skip_slug(slug):
            skipped_meta += 1
            continue

        # Skip garbage prompts
        if _is_garbage_prompt(prompt):
            skipped_garbage += 1
            continue

        # Skip known dupes
        if _is_dupe_note(note):
            skipped_dupe += 1
            continue

        # Skip if already successfully deployed
        norm = _normalize_slug(slug)
        if norm in deployed or slug in deployed:
            skipped_deployed += 1
            # Mark as MERGED since the improvement landed via another path
            db.update("tasks", {"id": t["id"]}, {
                "state": "MERGED",
                "note": f"auto-remediation: improvement already deployed via {norm}"
            })
            continue

        # Skip if max attempts reached
        if remediation_count >= MAX_REMEDIATION_ATTEMPTS:
            skipped_max_attempts += 1
            continue

        # Determine reason from note
        reason = "quarantined improvement retry"
        note_lower = note.lower()
        if "orphan" in note_lower:
            reason = "orphaned decomposed — children never materialized"
        elif "branch lost" in note_lower:
            reason = "branch lost during GC"
        elif "conflict" in note_lower:
            reason = "merge conflict — fresh attempt on current base"
        elif "error" in note_lower or "fail" in note_lower:
            reason = "execution error — retry"
        elif "secret" in note_lower or "credential" in note_lower:
            reason = "secret detected — retry with sanitization"

        if _requeue_task(t, reason):
            requeued += 1
            # Mark original as MERGED (terminal) so we don't process it again
            db.update("tasks", {"id": t["id"]}, {
                "state": "MERGED",
                "note": f"auto-remediation: requeued as remediate-{norm} ({reason})"
            })

    elapsed = time.time() - started
    print(f"[remediation] {elapsed:.1f}s | "
          f"scanned={len(quarantined)} requeued={requeued} "
          f"skip:meta={skipped_meta} garbage={skipped_garbage} dupe={skipped_dupe} "
          f"deployed={skipped_deployed} max_attempts={skipped_max_attempts} "
          f"too_young={skipped_too_young}")


if __name__ == "__main__":
    run()
