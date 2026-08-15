#!/usr/bin/env python3
"""One-time evidence-gated re-enqueue of PHANTOM_UNVERIFIED / QUARANTINED tasks.

2026-08-04 evidence recovery. For every phantom/quarantined task that still has
real evidence of finished work -- a surviving agent branch (possibly just
restored from the ~/branch-rescue-20260802 bundles), a recorded
artifact_commit, or a stored diff in merged_diffs -- either:

  (a) branch survives locally  -> set state back to DONE (never MERGED) so the
      guarded merge train (integration_sweeper + merge_train) integrates and
      VERIFIES it;
  (b) only a merged_diffs row  -> file ONE recover-missing-branch-* task using
      integration_sweeper's own dedup helpers and reuse-first prompt builder
      (imported, not reimplemented);
  (c) the ~10k evidence-free phantoms are never selected, never touched.

Rules honoured: every DB write matches a single id (no bulk statements), state
MERGED is never written (it now requires landed evidence -- DONE is the entry
state for the merge train), and git is strictly read-only here (branch
existence checks only; restoration happened separately from bundles).
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(os.path.dirname(HERE), "runner")
sys.path.insert(0, RUNNER)

# The queue admission ceiling (default 800; current QUEUED depth ~2.1k) would
# silently swallow the handful of recover-task inserts this one-time script
# files. Raise it for THIS process only via the documented knob (see
# db._queue_depth_block's own log message). Nothing is persisted.
os.environ.setdefault("ORCH_MAX_QUEUE_DEPTH", "4000")
os.environ.setdefault("ORCH_ACTOR", "requeue_evidence_phantoms")

import db  # noqa: E402  runner/.env auto-loaded; SUPABASE_URL rides the Vercel relay (normal)
import integration_sweeper as sweeper  # noqa: E402

EVIDENCE_STATES = "in.(PHANTOM_UNVERIFIED,QUARANTINED)"
FIELDS = ("id,slug,project_id,state,note,kind,prompt,base_branch,material,"
          "force_coder,artifact_branch,artifact_commit")
NOTE = "evidence-recovery 2026-08-04: surviving branch {branch}, routed to merge train"


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _repo_for(proj):
    return db.localize_repo_path(proj.get("repo_path") or "")


def _branch_candidates(task):
    """Ref names that would prove this task's work still exists locally."""
    cands = []
    ab = (task.get("artifact_branch") or "").strip()
    if ab:
        cands.append(ab)
        if not ab.startswith(("agent/", "refs/")):
            cands.append(f"agent/{ab}")
    slug = (task.get("slug") or "").strip()
    if slug:
        cands.append(f"agent/{slug}")
    # rescue namespace restored from the 2026-08-02 bundles (slash -> underscore)
    for c in list(cands):
        if not c.startswith("refs/"):
            cands.append("refs/rescue/" + c.replace("/", "_"))
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _load_evidence_tasks():
    """Phantom/quarantined rows with a recorded artifact_branch or artifact_commit."""
    tasks = {}
    for artifact_filter in ({"artifact_branch": "not.is.null"},
                            {"artifact_commit": "not.is.null"}):
        params = {"select": FIELDS, "state": EVIDENCE_STATES, "limit": "5000"}
        params.update(artifact_filter)
        for row in db.select("tasks", params) or []:
            tasks[row["id"]] = row
    return {tid: t for tid, t in tasks.items()
            if (t.get("artifact_branch") or "").strip()
            or (t.get("artifact_commit") or "").strip()}


def _load_diff_pairs():
    rows = db.select("merged_diffs", {"select": "project,slug", "limit": "20000"}) or []
    return {(r.get("project"), r.get("slug")) for r in rows if r.get("slug")}


def _load_diff_only_tasks(tasks, projects_by_id, diff_pairs):
    """Add phantom/quarantined rows whose only evidence is a merged_diffs row."""
    name_to_pid = {p.get("name"): pid for pid, p in projects_by_id.items()}
    wanted = collections.defaultdict(set)
    for project, slug in diff_pairs:
        pid = name_to_pid.get(project)
        if pid:
            wanted[slug].add(pid)
    for chunk in _chunks(sorted(wanted), 80):
        quoted = ",".join('"%s"' % s.replace('"', "") for s in chunk)
        rows = db.select("tasks", {"select": FIELDS, "state": EVIDENCE_STATES,
                                   "slug": f"in.({quoted})", "limit": "5000"}) or []
        for row in rows:
            if row["id"] not in tasks and row.get("project_id") in wanted.get(row.get("slug"), set()):
                tasks[row["id"]] = row
    return tasks


def main():
    projects_by_id = {p["id"]: p for p in (db.select("projects") or [])}
    diff_pairs = _load_diff_pairs()
    tasks = _load_evidence_tasks()
    tasks = _load_diff_only_tasks(tasks, projects_by_id, diff_pairs)
    recovery_index = sweeper._active_recovery_index()

    c = collections.Counter()
    per_project = collections.defaultdict(collections.Counter)
    routed_branches = set()

    for t in sorted(tasks.values(), key=lambda r: (str(r.get("project_id")), str(r.get("slug")))):
        proj = projects_by_id.get(t.get("project_id")) or {}
        pname = proj.get("name") or str(t.get("project_id"))
        repo = _repo_for(proj)
        c["considered"] += 1
        if not repo or not os.path.isdir(repo):
            c["skipped_repo_missing"] += 1
            per_project[pname]["skipped_repo_missing"] += 1
            continue
        surviving = next((b for b in _branch_candidates(t)
                          if sweeper._branch_exists(repo, b)), None)
        slug = str(t.get("slug") or "")
        if surviving:
            key = (t.get("project_id"), surviving)
            if key in routed_branches:
                # same surviving branch already routed once this run -- one merge, not two
                c["skipped_duplicate_branch"] += 1
                per_project[pname]["skipped_duplicate_branch"] += 1
                continue
            routed_branches.add(key)
            # single-id PATCH: respects the no-bulk-statement DB guard
            db.update("tasks", {"id": t["id"]},
                      {"state": "DONE", "note": NOTE.format(branch=surviving),
                       "updated_at": "now()"})
            c["done_requeued"] += 1
            per_project[pname]["done_requeued"] += 1
            continue
        if (pname, slug) in diff_pairs:
            if sweeper.RECOVERY_PREFIX in slug:
                # nesting guard, same as sweep(): never recover a recovery
                c["skipped_nested_recovery"] += 1
                per_project[pname]["skipped_nested_recovery"] += 1
                continue
            recovery_slug = f"{sweeper.RECOVERY_PREFIX}{slug}"
            created = sweeper._handle_missing_branch(t, proj, recovery_index=recovery_index)
            if not created:
                c["recover_deduped"] += 1
                per_project[pname]["recover_deduped"] += 1
                continue
            # _handle_missing_branch returns True even when db.insert was refused by
            # an admission guard; verify the recovery row actually exists before counting.
            rows = db.select("tasks", {"select": "id,state",
                                       "project_id": f"eq.{t['project_id']}",
                                       "slug": f"eq.{recovery_slug}", "limit": "1"}) or []
            if rows:
                recovery_index["exact"].add(
                    (t.get("project_id"), sweeper._recovery_root(recovery_slug)))
                c["recover_created"] += 1
                per_project[pname]["recover_created"] += 1
            else:
                c["recover_insert_blocked"] += 1
                per_project[pname]["recover_insert_blocked"] += 1
            continue
        commit = (t.get("artifact_commit") or "").strip()
        if commit and sweeper._branch_exists(repo, f"{commit}^{{commit}}"):
            # commit object survives but no ref and no stored diff: leave untouched,
            # report so a human can decide whether to ref it. Never fabricate branches.
            c["skipped_commit_object_only"] += 1
            per_project[pname]["skipped_commit_object_only"] += 1
        else:
            c["skipped_no_local_evidence"] += 1
            per_project[pname]["skipped_no_local_evidence"] += 1

    summary = {"totals": dict(c),
               "per_project": {k: dict(v) for k, v in sorted(per_project.items())}}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    main()
