#!/usr/bin/env python3
"""
scm_branch_report.py — operator-visible surface for scm_branch_proposer.

`scm_branch_proposer` implements the rules (which agent/<slug> branches ought to
exist, which terminal-state ones are old enough to delete) but nothing ever
called it, so the branch-management heuristic has been dead code since it
merged. This module is the missing caller: it loads projects and their tasks
from the DB, runs the proposer per project, and reports the proposals.

It is deliberately REPORT-ONLY. No proposal is executed here — no branch is
created, no branch is deleted. Turning a proposal into an SCM operation stays an
operator decision (or a separate, explicitly-gated job), because a bad deletion
rule against a live agent branch destroys unmerged work.

Periodic job interface: call run() from periodic.py.
CLI: python3 runner/scm_branch_report.py [--project NAME] [--retention-days N] [--json]

Configuration (all env vars):
  ORCH_SCM_REPORT_ENABLED     enable/disable — default "true"
  ORCH_SCM_REPORT_TASK_CAP    max tasks fetched per project — default 500
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import scm_branch_proposer  # noqa: E402

REPORT_ENABLED = os.environ.get("ORCH_SCM_REPORT_ENABLED", "true").lower() in ("1", "true", "yes")
TASK_CAP = int(os.environ.get("ORCH_SCM_REPORT_TASK_CAP", "500") or 500)

# Only these states can produce a proposal, so don't drag the rest over the wire.
_RELEVANT_STATES = ("QUEUED", "DONE", "MERGED")


def _load_projects(project_name=None):
    """Return project rows, or [] on any failure. Never raises."""
    try:
        params = {"select": "id,name,repo_path,default_base"}
        if project_name:
            params["name"] = f"eq.{project_name}"
        return db.select("projects", params) or []
    except Exception as e:
        print(f"[scm-branch-report] project query failed: {e}")
        return []


def _load_tasks(project_id):
    """Return proposal-relevant task rows for one project, or [] on failure."""
    try:
        return db.select("tasks", {
            "select": "id,slug,state,base_branch,project_id",
            "project_id": f"eq.{project_id}",
            "state": "in.({})".format(",".join(_RELEVANT_STATES)),
            "order": "updated_at.desc",
            "limit": str(TASK_CAP),
        }) or []
    except Exception as e:
        print(f"[scm-branch-report] task query failed for {project_id}: {e}")
        return []


def collect_proposals(project_name=None, retention_days=None):
    """Run the proposer across projects and return a flat list of proposals.

    Each proposal is the dict scm_branch_proposer emits, plus a "project_name"
    key so a report line is readable without a second lookup.

    Fail-soft: a project whose repo_path is missing, or whose query fails, is
    skipped with a diagnostic rather than aborting the whole report.
    """
    if not REPORT_ENABLED:
        return []
    proposals = []
    for project in _load_projects(project_name):
        repo = project.get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            print(f"[scm-branch-report] skipping {project.get('name')}: repo_path missing ({repo!r})")
            continue
        tasks = _load_tasks(project.get("id"))
        if not tasks:
            continue
        try:
            found = scm_branch_proposer.propose(tasks, project, retention_days=retention_days)
        except Exception as e:
            print(f"[scm-branch-report] proposer failed for {project.get('name')}: {e}")
            continue
        for p in found:
            p = dict(p)
            p["project_name"] = project.get("name")
            proposals.append(p)
    return proposals


def summarize(proposals):
    """Return {'create': n, 'delete': n, 'total': n} for a proposal list."""
    summary = {"create": 0, "delete": 0, "total": 0}
    for p in proposals or []:
        action = p.get("action")
        if action in summary:
            summary[action] += 1
        summary["total"] += 1
    return summary


def format_report(proposals):
    """Render proposals as human-readable lines. Returns a string."""
    if not proposals:
        return "[scm-branch-report] no branch proposals"
    lines = []
    for p in proposals:
        if p.get("action") == "create":
            lines.append("  CREATE {}/{} (base {})".format(
                p.get("project_name"), p.get("branch_name"), p.get("base")))
        else:
            lines.append("  DELETE {}/{} — {}".format(
                p.get("project_name"), p.get("branch_name"), p.get("reason")))
    s = summarize(proposals)
    header = "[scm-branch-report] {total} proposal(s): {create} create, {delete} delete".format(**s)
    return "\n".join([header] + sorted(lines))


def run(project_name=None, retention_days=None):
    """Periodic-job entry point. Prints the report, returns the summary dict."""
    if not REPORT_ENABLED:
        return {"create": 0, "delete": 0, "total": 0, "disabled": True}
    proposals = collect_proposals(project_name=project_name, retention_days=retention_days)
    print(format_report(proposals))
    return summarize(proposals)


def parse_args(argv):
    """Parse CLI args into (project_name, retention_days, as_json). Never raises."""
    project_name, retention_days, as_json = None, None, False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--project" and i + 1 < len(argv):
            project_name = argv[i + 1]
            i += 2
        elif arg == "--retention-days" and i + 1 < len(argv):
            try:
                retention_days = int(argv[i + 1])
            except ValueError:
                print(f"[scm-branch-report] ignoring non-numeric --retention-days {argv[i + 1]!r}")
            i += 2
        elif arg == "--json":
            as_json = True
            i += 1
        else:
            i += 1
    return project_name, retention_days, as_json


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    project_name, retention_days, as_json = parse_args(argv)
    if as_json:
        proposals = collect_proposals(project_name=project_name, retention_days=retention_days)
        print(json.dumps({"summary": summarize(proposals), "proposals": proposals}, indent=2))
        return 0
    run(project_name=project_name, retention_days=retention_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
