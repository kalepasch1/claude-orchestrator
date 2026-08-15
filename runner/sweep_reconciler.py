#!/usr/bin/env python3
"""sweep_reconciler.py — reconcile offline git-deploy-sweep journal with the DB.

Called from sentinel.on_db_recovery() when the database comes back after an outage.
scripts/git_deploy_sweep.py journals every deployment action to
.runtime/git_deploy_sweep.jsonl while the DB is down. This module reads that journal
and:
  - DEPLOYED rows: verify the journal sha is an ancestor of the project's origin base;
    only then mark the task MERGED (artifact_commit=<sha>), mark matching
    integration_cards train:MERGED, insert outcomes (usd=0, integrated=true).
    Unverifiable claims go to DONE for merge_train to integrate honestly.
  - GATE-RED / CONFLICT / PUSH-FAIL rows: annotate the task with a note so the
    merge-train's redo path has context.

Idempotent: tracks the last-processed byte offset in .runtime/sweep_reconciler_offset.
"""
import json, os, re, datetime, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNTIME = os.environ.get("CLAUDE_ORCH_HOME",
                         os.path.join(ROOT, ".runtime"))
JOURNAL = os.path.join(RUNTIME, "git_deploy_sweep.jsonl")
OFFSET_FILE = os.path.join(RUNTIME, "sweep_reconciler_offset")

# States from which we allow transition to MERGED
MERGEABLE_STATES = {"DONE", "BLOCKED", "RUNNING"}


def _slug_from_branch(branch):
    """Extract task slug from 'agent/<slug>' or 'origin/agent/<slug>'."""
    m = re.match(r"^(?:origin/)?agent/(.+)$", branch or "")
    return m.group(1) if m else None


def _read_offset():
    try:
        with open(OFFSET_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def _write_offset(offset):
    os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))


def _parse_journal(start_offset=0):
    """Yield (row_dict, end_byte_offset) for each journal line after start_offset."""
    if not os.path.isfile(JOURNAL):
        return
    with open(JOURNAL, "r") as f:
        f.seek(start_offset)
        while True:
            line = f.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield row, f.tell()


def reconcile(db_module=None):
    """Main entry point. Pass a db module (or None to import runner.db).

    Returns dict with counts: deployed, annotated, skipped, errors.
    """
    if db_module is None:
        import db as db_module  # noqa: F811

    offset = _read_offset()
    stats = {"deployed": 0, "annotated": 0, "skipped": 0, "errors": 0}
    last_offset = offset

    for row, end_offset in _parse_journal(offset):
        action = (row.get("action") or "").upper()
        branch = row.get("branch", "")
        repo = row.get("repo", "")
        detail = row.get("detail", "")
        slug = _slug_from_branch(branch)

        if not slug:
            stats["skipped"] += 1
            last_offset = end_offset
            continue

        try:
            if action == "DEPLOYED":
                _handle_deployed(db_module, slug, detail, repo)
                stats["deployed"] += 1
            elif action in ("GATE-RED", "CONFLICT", "PUSH-FAIL"):
                _handle_failure(db_module, slug, action, detail, repo)
                stats["annotated"] += 1
            else:
                stats["skipped"] += 1
        except Exception:
            stats["errors"] += 1

        last_offset = end_offset

    _write_offset(last_offset)
    return stats


def _find_task_by_slug(db_module, slug):
    """Look up a task by slug. Returns the first match or None."""
    try:
        rows = db_module.select("tasks", {
            "select": "*",
            "slug": f"eq.{slug}",
            "limit": "1",
        }) or []
        return rows[0] if rows else None
    except Exception:
        return None


def _sha_on_origin_base(db_module, project_id, repo, sha):
    """True only when `sha` is confirmed an ancestor of the project's origin base branch.
    That is the evidence bar for MERGED — a journal line alone is a claim, not proof."""
    if not sha or not repo or not os.path.isdir(repo):
        return False
    base = "main"
    try:
        rows = db_module.select("projects", {
            "select": "base_branch,default_base",
            "id": f"eq.{project_id}",
        }) or []
        if rows:
            base = rows[0].get("base_branch") or rows[0].get("default_base") or "main"
    except Exception:
        pass
    try:
        subprocess.run(["git", "fetch", "origin", base], cwd=repo,
                       capture_output=True, timeout=60)
        r = subprocess.run(["git", "merge-base", "--is-ancestor", sha, f"origin/{base}"],
                           cwd=repo, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _handle_deployed(db_module, slug, detail, repo):
    """Reconcile a DEPLOYED journal entry with the DB.

    TRUTH FIX 2026-08-04: this used to PATCH the task straight to MERGED via raw _req with
    no evidence — a DB outage plus one journal line could certify anything. Now the write
    goes through db.update, and MERGED is only set when the journal row carries a sha that
    `git merge-base --is-ancestor` confirms on the project's origin base. Otherwise the
    task goes to DONE so merge_train integrates it for real."""
    task = _find_task_by_slug(db_module, slug)
    if not task:
        return

    task_id = task["id"]
    project_id = task.get("project_id")
    current_state = (task.get("state") or "").upper()

    # Guard: only transition from allowed states
    if current_state not in MERGEABLE_STATES:
        return

    sha = (detail or "").strip().split()[0] if detail else ""
    verified = _sha_on_origin_base(db_module, project_id, repo, sha)

    if verified:
        # _sha_on_origin_base checks the BASE branch and, critically, returns False on any
        # exception — so a fetch timeout reads identically to "not merged". merge_truth
        # re-checks against prod_branch with a three-valued verdict, so an infra error leaves
        # the row alone instead of certifying or downgrading it on bad information.
        import merge_truth
        merge_truth.guarded_task_update(
            task,
            {"state": "MERGED",
             "artifact_commit": sha,
             "note": f"offline-sweep deployed {sha[:12]} (verified on origin base)"},
            repo=repo)
    else:
        db_module.update("tasks", {"id": task_id},
                         {"state": "DONE",
                          "note": (f"offline-sweep claimed deployed "
                                   f"{sha[:12] if sha else '(no sha)'} but not verified on "
                                   f"origin base — left DONE for merge_train")})
        return

    # Verified path only: mark matching integration_cards train:MERGED
    try:
        db_module.update("integration_cards", {"task_id": task_id}, {"train": "MERGED"})
    except Exception:
        pass  # fail-soft: card update is best-effort

    # Record outcome (usd=0, integrated=true) per SPEC invariant
    try:
        db_module.insert("outcomes", {
            "task_id": task_id,
            "project_id": project_id,
            "slug": slug,
            "usd": 0,
            "integrated": True,
            "note": f"offline-sweep deployed {sha[:12]} (verified on origin base)",
        }, upsert=True)
    except Exception:
        pass  # fail-soft


def _handle_failure(db_module, slug, action, detail, repo):
    """Annotate a task with context from a GATE-RED/CONFLICT/PUSH-FAIL entry."""
    task = _find_task_by_slug(db_module, slug)
    if not task:
        return

    task_id = task["id"]
    existing_note = task.get("note") or ""
    append_note = f"sweep:{action.lower()} ({detail[:120]})" if detail else f"sweep:{action.lower()}"
    new_note = f"{existing_note}; {append_note}" if existing_note else append_note

    try:
        db_module._req("PATCH", f"/rest/v1/tasks",
                       body={"note": new_note},
                       params={"id": f"eq.{task_id}"},
                       headers={"Prefer": "return=minimal"})
    except Exception:
        pass  # fail-soft
