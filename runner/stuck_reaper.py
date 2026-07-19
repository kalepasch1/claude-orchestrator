#!/usr/bin/env python3
"""
stuck_reaper.py - detect and recover tasks stuck in RUNNING state.

Tasks get stuck when the runner process crashes, the machine goes offline, or the
AI provider hangs indefinitely. Without this reaper, stuck tasks hold lane slots
permanently and never complete.

For each stuck task, the reaper:
  1. Diagnoses WHY it's stuck (auth, build failure, death loop, stale/unknown).
  2. Applies the lightest remediation that will let it flow again.
  3. Guards against death loops: after ORCH_MAX_STUCK_REMEDIATION cycles, quarantines
     the task instead of resetting it (prevents credit burn on structurally broken work).
  4. Caps the number of resets per run (ORCH_REAPER_MAX_PER_RUN) so a fleet-wide
     crash doesn't mass-reset everything at once.

Periodic job interface: call run() from periodic.py.
"""
import os, sys, re, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# --- Configuration (env vars with sensible defaults) ---

STUCK_THRESHOLD_H = float(os.environ.get("ORCH_STUCK_THRESHOLD_H", "2"))
MAX_REMEDIATION = int(os.environ.get("ORCH_MAX_STUCK_REMEDIATION", "2"))
MAX_PER_RUN = int(os.environ.get("ORCH_REAPER_MAX_PER_RUN", "5"))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Diagnosis patterns ---

_AUTH_ERROR = re.compile(
    r"not logged in|auth.?fail|auth.?error|token expired|unauthorized|"
    r"login required|session expired|credential.*invalid",
    re.I,
)

_BUILD_TEST_FAIL = re.compile(
    r"build.?fail|test.?fail|compilation.?error|type.?error|lint.?error|"
    r"ci.?fail|check.?fail|syntax.?error|BUILDFAIL|TESTFAIL",
    re.I,
)


def diagnose_stuck(task):
    """Classify why a RUNNING task is stuck and recommend an action.

    Returns dict: {diagnosis, action, reason}
      diagnosis: "auth_expired", "death_loop", "stale_no_progress",
                 "build_stuck", "unknown"
      action:    "reset", "reset_with_note", "quarantine"
      reason:    human-readable explanation
    """
    note = task.get("note") or ""
    log_tail = task.get("log_tail") or ""
    evidence = f"{note}\n{log_tail}"
    rc = int(task.get("remediation_count") or 0)
    slug = task.get("slug") or task.get("id") or "?"

    # Death loop guard (checked first - overrides all other diagnoses)
    if rc >= MAX_REMEDIATION:
        return {
            "diagnosis": "death_loop",
            "action": "quarantine",
            "reason": (f"task {slug} has been remediated {rc} times and keeps getting "
                       f"stuck; quarantining to prevent credit burn"),
        }

    # Auth errors - no point retrying the same way
    if _AUTH_ERROR.search(evidence):
        return {
            "diagnosis": "auth_expired",
            "action": "reset",
            "reason": f"task {slug} stuck with auth/login error; resetting to QUEUED",
        }

    # Build/test failures - retry with diagnostic note
    if _BUILD_TEST_FAIL.search(evidence):
        return {
            "diagnosis": "build_stuck",
            "action": "reset_with_note",
            "reason": (f"task {slug} stuck with build/test failure; incrementing "
                       f"remediation_count and resetting with diagnostic"),
        }

    # Otherwise: stale with no obvious error - do a lightweight check
    diagnostic_lines = []
    project_id = task.get("project_id")
    repo_path = _repo_path(project_id)
    branch_name = f"agent/{slug}"

    if repo_path and os.path.isdir(repo_path):
        # Check if the agent branch exists
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--verify", branch_name],
                cwd=repo_path, capture_output=True, timeout=10,
            )
            if r.returncode == 0:
                diagnostic_lines.append(f"branch {branch_name} exists")
                # Check for commits on branch vs base
                try:
                    base = task.get("base_branch") or "main"
                    r2 = subprocess.run(
                        ["git", "rev-list", "--count", f"{base}..{branch_name}"],
                        cwd=repo_path, capture_output=True, timeout=10,
                    )
                    count = r2.stdout.decode().strip() if r2.returncode == 0 else "?"
                    diagnostic_lines.append(f"{count} commits ahead of {base}")
                except Exception:
                    pass
            else:
                diagnostic_lines.append(f"branch {branch_name} does NOT exist")
        except Exception:
            diagnostic_lines.append("git check failed")

    if diagnostic_lines:
        diag_text = "; ".join(diagnostic_lines)
        return {
            "diagnosis": "stale_no_progress",
            "action": "reset_with_note",
            "reason": (f"task {slug} stale in RUNNING for >{STUCK_THRESHOLD_H}h; "
                       f"diagnostics: {diag_text}"),
        }

    return {
        "diagnosis": "unknown",
        "action": "reset_with_note",
        "reason": (f"task {slug} stuck in RUNNING for >{STUCK_THRESHOLD_H}h "
                   f"with no identifiable cause"),
    }


def _repo_path(project_id):
    """Look up repo_path for a project. Returns None on any failure."""
    if not project_id:
        return None
    try:
        rows = db.select("projects", {
            "select": "repo_path",
            "id": f"eq.{project_id}",
            "limit": "1",
        }) or []
        return rows[0].get("repo_path") if rows else None
    except Exception:
        return None


def run():
    """Periodic job entry point: find and remediate stuck RUNNING tasks.

    Uses Supabase's updated_at < now() - interval check via PostgREST
    lt filter with an ISO timestamp offset.
    """
    import datetime

    threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=STUCK_THRESHOLD_H)
    threshold_iso = threshold.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        stuck = db.select("tasks", {
            "select": "id,slug,state,account,note,log_tail,updated_at,"
                      "remediation_count,project_id,base_branch",
            "state": "eq.RUNNING",
            "updated_at": f"lt.{threshold_iso}",
            "order": "updated_at.asc",
            "limit": str(MAX_PER_RUN * 3),  # fetch extra in case some are skipped
        }) or []
    except Exception as e:
        print(f"[stuck-reaper] query failed: {e}")
        return {"error": str(e)}

    if not stuck:
        print(f"[stuck-reaper] no tasks stuck >{STUCK_THRESHOLD_H}h")
        return {"reaped": 0, "quarantined": 0}

    reaped = 0
    quarantined = 0

    for task in stuck:
        if reaped + quarantined >= MAX_PER_RUN:
            print(f"[stuck-reaper] budget cap ({MAX_PER_RUN}) reached; "
                  f"remaining stuck tasks deferred to next run")
            break

        tid = task.get("id")
        slug = task.get("slug") or tid or "?"
        rc = int(task.get("remediation_count") or 0)

        try:
            diag = diagnose_stuck(task)
        except Exception as e:
            print(f"[stuck-reaper] {slug}: diagnosis failed ({e}); skipping")
            continue

        action = diag.get("action", "reset")
        diagnosis = diag.get("diagnosis", "unknown")
        reason = diag.get("reason", "")

        print(f"[stuck-reaper] {slug}: diagnosis={diagnosis} action={action} "
              f"rc={rc} reason={reason}")

        try:
            if action == "quarantine":
                db.update("tasks", {"id": tid}, {
                    "state": "QUARANTINED",
                    "account": None,
                    "updated_at": "now()",
                    "note": (f"stuck-reaper: quarantined after {rc} stuck cycles "
                             f"(preventing credit burn). diagnosis={diagnosis}. "
                             f"{(task.get('note') or '')[:300]}")[:500],
                })
                quarantined += 1

            elif action == "reset_with_note":
                note_parts = [
                    f"stuck-reaper: {diagnosis}",
                    reason[:200],
                ]
                existing_note = task.get("note") or ""
                if existing_note:
                    note_parts.append(f"prev: {existing_note[:200]}")

                db.update("tasks", {"id": tid}, {
                    "state": "QUEUED",
                    "account": None,
                    "updated_at": "now()",
                    "remediation_count": rc + 1,
                    "note": ". ".join(note_parts)[:500],
                })
                reaped += 1

            else:  # "reset"
                db.update("tasks", {"id": tid}, {
                    "state": "QUEUED",
                    "account": None,
                    "updated_at": "now()",
                    "note": (f"stuck-reaper: {diagnosis}; reset to QUEUED. "
                             f"{(task.get('note') or '')[:300]}")[:500],
                })
                reaped += 1

        except Exception as e:
            print(f"[stuck-reaper] {slug}: update failed ({e})")

    print(f"[stuck-reaper] done: reaped={reaped} quarantined={quarantined} "
          f"total_stuck_found={len(stuck)}")
    return {"reaped": reaped, "quarantined": quarantined,
            "total_stuck": len(stuck)}


if __name__ == "__main__":
    run()
