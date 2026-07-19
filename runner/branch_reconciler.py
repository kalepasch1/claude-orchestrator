#!/usr/bin/env python3
"""Admit legacy remote agent branches into the canonical merge train.

Historically, some runners pushed ``origin/agent/*`` directly without creating
the corresponding task row.  The merge train only consumes task-backed work,
leaving those branches invisible forever.  This bounded reconciler creates one
task per unique, non-sensitive branch patch so the normal serialized rebase,
test, and release gates decide whether it can ship.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import merge_train

LIMIT = int(os.environ.get("BRANCH_RECONCILE_LIMIT", "25"))
DISCOVERY_LIMIT = int(os.environ.get("BRANCH_RECONCILE_DISCOVERY_LIMIT", "250"))
CONTROL_KEY = "branch_reconciliation"
SENSITIVE = re.compile(r"(^|/)(auth|oauth|security|legal|privacy|payment|stripe|secret|token|\.env)(/|$)", re.I)
PREFIX = re.compile(r"^(?:recover-missing-branch-|merge-legacy-agent-|rework-(?:[a-z0-9-]+-)?|qafix-|relfix-|buildfix-|deployfix-)+", re.I)


def _git(repo, *args, timeout=60):
    try:
        result = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                                text=True, timeout=timeout)
        return result.returncode, result.stdout.strip()
    except Exception:
        return 1, ""


def _base(project):
    repo = project.get("repo_path") or ""
    for name in (project.get("default_base"), project.get("prod_branch"), "main", "master"):
        if name and _git(repo, "rev-parse", "--verify", f"origin/{name}")[0] == 0:
            return name
    return project.get("default_base") or "main"


def _root_slug(slug):
    """Collapse retry/recovery naming wrappers without conflating distinct work."""
    prior = None
    while slug and slug != prior:
        prior = slug
        slug = PREFIX.sub("", slug)
    return slug or prior or "unknown"


def _branches(repo, base):
    rc, out = _git(repo, "for-each-ref", "--sort=-committerdate", f"--count={max(1, DISCOVERY_LIMIT)}",
                   "--format=%(refname:short)|%(objectname)|%(committerdate:unix)",
                   "refs/remotes/origin/agent", timeout=120)
    if rc:
        return []
    rows = []
    for line in out.splitlines():
        ref, sha, stamp = (line.split("|") + ["", "", ""])[:3]
        if not ref.startswith("origin/agent/"):
            continue
        slug = ref[len("origin/agent/"):]
        if _git(repo, "merge-base", "--is-ancestor", ref, f"origin/{base}")[0] == 0:
            continue
        rc, files = _git(repo, "diff", "--name-only", f"origin/{base}...{ref}")
        changed = [p for p in files.splitlines() if p]
        # Exact patch fingerprint lets retries with identical output share one champion.
        rc, diff = _git(repo, "diff", "--binary", f"origin/{base}...{ref}", timeout=120)
        fingerprint = hashlib.sha256(diff.encode()).hexdigest() if not rc else sha
        rows.append({"ref": ref, "slug": slug, "root": _root_slug(slug), "sha": sha,
                     "stamp": int(stamp or 0), "files": changed, "fingerprint": fingerprint,
                     "sensitive": any(SENSITIVE.search(p) for p in changed)})
    return rows


def champions(branches):
    """Return newest representative of each exact patch; retain distinct patches."""
    selected = {}
    duplicates = []
    for branch in sorted(branches, key=lambda b: (b["stamp"], b["slug"]), reverse=True):
        key = (branch["root"], branch["fingerprint"])
        if key in selected:
            duplicates.append(branch)
        else:
            selected[key] = branch
    return list(selected.values()), duplicates


def _existing(project_id):
    rows = db.select("tasks", {"select": "slug,state", "project_id": f"eq.{project_id}",
                                "limit": "5000"}) or []
    return {str(row.get("slug") or ""): row.get("state") for row in rows}


def reconcile_project(project, capacity):
    repo = project.get("repo_path") or ""
    if not repo or not os.path.isdir(repo) or capacity <= 0:
        return {"mapped": 0, "duplicates": 0, "blocked": 0, "skipped": 0, "processed": 0}
    base = _base(project)
    branches = _branches(repo, base)
    chosen, duplicates = champions(branches)
    existing = _existing(project["id"])
    mapped = blocked = skipped = processed = 0
    for branch in sorted(chosen, key=lambda b: b["stamp"], reverse=True):
        if processed >= capacity:
            break
        if branch["slug"] in existing:
            if existing[branch["slug"]] != "BLOCKED" and not branch["sensitive"]:
                merge_train.ensure_integration_card(
                    project.get("name") or project["id"], branch["slug"],
                    kind="integrate", title=f"merge of {branch['slug']}",
                    why="branch_reconciler found an already-mapped legacy branch",
                    detail=f"ref={branch['ref']} sha={branch['sha'][:12]}",
                    status="approved", decided_by="canonical-train:branch-reconciler",
                )
            skipped += 1
            continue
        processed += 1
        state = "BLOCKED" if branch["sensitive"] else "DONE"
        note = ("branch_reconciler: raw remote branch mapped; "
                f"ref={branch['ref']} sha={branch['sha'][:12]} base={base} "
                f"patch={branch['fingerprint'][:12]}")
        if branch["sensitive"]:
            note += "; sensitive paths require explicit review"
        row = {"project_id": project["id"], "slug": branch["slug"], "state": state,
               "kind": "bugfix", "deps": [],
               "prompt": f"Integrate existing branch {branch['ref']} through the canonical merge train. Do not redraft work.",
               "note": note, "base_branch": base}
        if db.insert("tasks", row) is not None:
            if state == "DONE":
                # Reconciliation is the missing bridge: task rows alone wait for the
                # sweeper's oldest-first window, while this explicit card places the
                # existing branch directly on the serialized integration train.
                merge_train.ensure_integration_card(
                    project.get("name") or project["id"], branch["slug"],
                    kind="integrate", title=f"merge of {branch['slug']}",
                    why="branch_reconciler mapped a legacy remote agent branch",
                    detail=note, status="approved", decided_by="canonical-train:branch-reconciler",
                )
                mapped += 1
            else:
                blocked += 1
    return {"mapped": mapped, "duplicates": len(duplicates), "blocked": blocked, "skipped": skipped, "processed": processed,
            "discovered": len(branches), "base": base}


def run(limit=LIMIT):
    remaining = max(1, limit)
    report = {}
    for project in db.select("projects", {"select": "id,name,repo_path,default_base,prod_branch", "limit": "100"}) or []:
        result = reconcile_project(project, remaining)
        report[project.get("name") or project["id"]] = result
        remaining -= result["processed"]
        if remaining <= 0:
            break
    payload = {"generated_at": datetime.datetime.utcnow().isoformat(), "projects": report,
               "remaining_capacity": remaining}
    db.insert("controls", {"key": CONTROL_KEY, "value": json.dumps(payload), "updated_at": "now()"}, upsert=True)
    print(json.dumps(payload, default=str))
    return payload


if __name__ == "__main__":
    run()
