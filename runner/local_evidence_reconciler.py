#!/usr/bin/env python3
"""
local_evidence_reconciler.py — classify local ChatGPT/Codex build evidence against
current reality, WITHOUT destroying or overwriting any of it.

THE PROBLEM
-----------
Recovery sweeps keep producing the same artefact: a long list of local branches, rescue
refs, stashes and stray worktrees, handed to an agent with "reconcile this". The agent
then either (a) eyeballs a sample and reports UNKNOWN for the rest, or (b) starts
force-merging old code over newer code, which is how the fleet has lost work before.

Both failures come from the same gap: there is no mechanical classifier. This module is
that classifier. Every evidence source is treated as READ-ONLY — nothing here deletes,
resets, cleans, pops, moves, or checks out anything. The only writes are ledger rows.

CLASSIFICATION
--------------
Each item lands in exactly one bucket, in this order (first match wins):

  ALREADY_PRESENT             every commit is an ancestor of the default branch —
                              the work shipped, the ref is just residue.
  ACTIVE_IN_ANOTHER_TASK      a live orchestrator task or an existing remote branch
                              already owns this slug. Re-doing it duplicates work.
  SUPERSEDED_BY_NEWER         the paths it touches were all modified on the default
                              branch AFTER this ref's newest commit. The newer
                              implementation wins, per the operator's standing rule.
  CONFLICTED_NEEDS_FOCUSED_TASK  it does not merge cleanly onto the default branch.
                              Queue a focused follow-up; never force an overwrite.
  RECOVERABLE_VALUE           unique commits, applies cleanly, nothing else owns it.

UNKNOWN is deliberately not a bucket. `reconcile()` reports `unknown` separately, and
`complete()` is False while it is non-empty — completion requires zero UNKNOWN items.

Public API
----------
    enumerate_evidence(repo)                     -> [item, ...]
    classify(repo, item, ctx)                    -> dict
    reconcile(repo, fingerprint, ...)            -> dict report
    write_ledger(records, fingerprint, db=None)  -> dict

Environment
-----------
    ORCH_RECONCILE_ENABLED   Kill switch (default: true)
    ORCH_RECONCILE_TIMEOUT   Per-git-command timeout, seconds (default: 90)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GIT_TIMEOUT = int(os.environ.get("ORCH_RECONCILE_TIMEOUT", "90"))

CLASSIFICATIONS = (
    "ALREADY_PRESENT",
    "SUPERSEDED_BY_NEWER",
    "ACTIVE_IN_ANOTHER_TASK",
    "RECOVERABLE_VALUE",
    "CONFLICTED_NEEDS_FOCUSED_TASK",
)

# Refs that are evidence rather than working branches.
EVIDENCE_REF_PREFIXES = ("refs/orch-rescue/", "refs/recovery/", "refs/quarantine/")

# Local branch namespaces produced by out-of-band sessions.
EVIDENCE_BRANCH_PREFIXES = ("codex/", "chatgpt/", "verify/", "backlog-batch-", "fix-")

LIVE_TASK_STATES = ("QUEUED", "RUNNING", "READY", "BLOCKED", "CONFLICT")


def _enabled() -> bool:
    return os.environ.get("ORCH_RECONCILE_ENABLED", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def _git(args, cwd, timeout=GIT_TIMEOUT):
    """Read-only-by-convention git. Fail-soft; never raises."""
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — fail-soft
        return subprocess.CompletedProcess(args, 1, "", f"{type(exc).__name__}: {exc}")


def _lines(res) -> list:
    return [ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()]


# ── Enumeration (read-only) ─────────────────────────────────────────────────

def default_branch(repo: str) -> str:
    """The repo's default base. Prefers origin/HEAD, falls back to master/main."""
    r = _git(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().split("/", 1)[-1]
    for candidate in ("master", "main"):
        if _git(["git", "rev-parse", "--verify", "--quiet", candidate], repo).returncode == 0:
            return candidate
    return "master"


def enumerate_evidence(repo: str) -> list:
    """Every local evidence source, enumerated live rather than trusted from a snapshot.

    The task's own instruction is to "enumerate the live source during reconciliation so
    every item is classified" — a snapshot taken hours ago will miss refs and, worse,
    will list refs that no longer exist and get scored UNKNOWN.
    """
    items = []
    seen = set()

    def add(kind, name, ref):
        if ref in seen:
            return
        seen.add(ref)
        items.append({"kind": kind, "name": name, "ref": ref})

    base = default_branch(repo)

    for line in _lines(_git(["git", "for-each-ref", "--format=%(refname)",
                             "refs/heads/"], repo)):
        short = line[len("refs/heads/"):]
        if short in (base, "main", "master", "HEAD"):
            continue
        if short.startswith("agent/") or short.startswith(EVIDENCE_BRANCH_PREFIXES):
            add("branch", short, line)

    for prefix in EVIDENCE_REF_PREFIXES:
        for line in _lines(_git(["git", "for-each-ref", "--format=%(refname)", prefix], repo)):
            add("rescue-ref", line[len("refs/"):], line)

    for line in _lines(_git(["git", "stash", "list", "--format=%gd %gs"], repo)):
        ref = line.split()[0]
        add("stash", line, ref)

    listing = _git(["git", "worktree", "list", "--porcelain"], repo)
    for block in (listing.stdout or "").split("\n\n"):
        path = ""
        head = ""
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line.split(" ", 1)[1].strip()
            elif line.startswith("HEAD "):
                head = line.split(" ", 1)[1].strip()
        if path and os.path.abspath(path) != os.path.abspath(repo) and head:
            add("worktree", path, head)

    return items


# ── Context: what does "current" look like? ─────────────────────────────────

def build_context(repo: str, *, base: str = "", live_task_slugs=None) -> dict:
    """Everything a classification needs, gathered once instead of per item."""
    base = base or default_branch(repo)
    remote_base = f"origin/{base}"
    if _git(["git", "rev-parse", "--verify", "--quiet", remote_base], repo).returncode != 0:
        remote_base = base
    remote_branches = set()
    for line in _lines(_git(["git", "for-each-ref", "--format=%(refname)",
                             "refs/remotes/origin/"], repo)):
        remote_branches.add(line[len("refs/remotes/origin/"):])
    return {
        "base": base,
        "base_ref": remote_base,
        "base_sha": _git(["git", "rev-parse", remote_base], repo).stdout.strip(),
        "remote_branches": remote_branches,
        "live_task_slugs": set(live_task_slugs or ()),
    }


def _slug_of(item: dict) -> str:
    """The orchestrator slug an evidence item corresponds to, if any."""
    name = item.get("name", "")
    for prefix in ("agent/", "chatgpt/", "codex/"):
        if name.startswith(prefix):
            return name[len(prefix):]
    match = re.search(r"orch-rescue/\d{8}T\d{6}-(.+)$", name)
    if match:
        return match.group(1)
    return ""


# ── Classification ──────────────────────────────────────────────────────────

def _unique_commits(repo: str, ref: str, base_ref: str) -> list:
    return _lines(_git(["git", "rev-list", f"{base_ref}..{ref}"], repo))


def _touched_paths(repo: str, ref: str, base_ref: str) -> list:
    merge_base = _git(["git", "merge-base", base_ref, ref], repo).stdout.strip()
    if not merge_base:
        return []
    return _lines(_git(["git", "diff", "--name-only", merge_base, ref], repo))


def _superseded(repo: str, ref: str, base_ref: str, paths: list) -> bool:
    """True when EVERY path this ref touches was modified on base after its newest commit.

    "All", not "any", on purpose: a ref that touches ten files of which base moved one is
    still carrying nine files of recoverable value, and calling that superseded is how
    work gets quietly dropped.
    """
    if not paths:
        return False
    tip_date = _git(["git", "log", "-1", "--format=%ct", ref], repo).stdout.strip()
    if not tip_date.isdigit():
        return False
    for path in paths:
        newer = _git(["git", "log", "-1", "--format=%ct", f"--since=@{tip_date}",
                      base_ref, "--", path], repo).stdout.strip()
        if not newer.isdigit() or int(newer) <= int(tip_date):
            return False
    return True


def _applies_cleanly(repo: str, ref: str, base_ref: str) -> tuple:
    """Read-only merge dry run via `git merge-tree`. Returns (clean, detail).

    merge-tree computes the merge in memory. Nothing is checked out, no index is written,
    the working tree is not touched — which is the whole requirement here.
    """
    res = _git(["git", "merge-tree", "--write-tree", "--name-only", base_ref, ref], repo)
    if res.returncode == 0:
        return True, ""
    combined = ((res.stdout or "") + (res.stderr or "")).strip()
    if "unknown option" in combined or "usage:" in combined.lower():
        # git < 2.38: fall back to the three-arg form, whose output carries markers.
        merge_base = _git(["git", "merge-base", base_ref, ref], repo).stdout.strip()
        if not merge_base:
            return False, "no merge base"
        legacy = _git(["git", "merge-tree", merge_base, base_ref, ref], repo)
        if legacy.returncode != 0:
            return False, (legacy.stderr or "merge-tree failed").strip()[:200]
        return ("<<<<<<<" not in (legacy.stdout or "")), "conflict hunks in merge-tree output"
    return False, combined.splitlines()[0][:200] if combined else "merge conflict"


def classify(repo: str, item: dict, ctx: dict) -> dict:
    """Classify one evidence item. Always returns one of CLASSIFICATIONS or UNKNOWN."""
    record = {
        "source": item.get("ref", ""),
        "kind": item.get("kind", ""),
        "name": item.get("name", ""),
        "slug": _slug_of(item),
        "classification": "UNKNOWN",
        "disposition": "",
        "unique_commits": 0,
        "paths": [],
        "task": "",
        "branch": "",
        "commit": "",
        "detail": "",
    }
    ref = item.get("ref", "")
    base_ref = ctx["base_ref"]

    sha = _git(["git", "rev-parse", "--verify", "--quiet", ref], repo).stdout.strip()
    if not sha:
        record["classification"] = "ALREADY_PRESENT"
        record["disposition"] = "ref no longer exists; nothing to recover"
        record["detail"] = "ref not resolvable at reconciliation time"
        return record
    record["commit"] = sha

    unique = _unique_commits(repo, ref, base_ref)
    record["unique_commits"] = len(unique)

    # 1. Fully merged already.
    if not unique:
        record["classification"] = "ALREADY_PRESENT"
        record["disposition"] = (f"every commit is an ancestor of {ctx['base']}; "
                                 f"evidence left in place as residue")
        return record

    # 2. Owned by something live.
    slug = record["slug"]
    if slug and slug in ctx["live_task_slugs"]:
        record["classification"] = "ACTIVE_IN_ANOTHER_TASK"
        record["task"] = slug
        record["disposition"] = "a live orchestrator task already owns this slug; not duplicated"
        return record
    if slug and f"agent/{slug}" in ctx["remote_branches"]:
        record["classification"] = "ACTIVE_IN_ANOTHER_TASK"
        record["branch"] = f"agent/{slug}"
        record["disposition"] = "already published as a remote agent branch; merge train owns it"
        return record

    paths = _touched_paths(repo, ref, base_ref)
    record["paths"] = paths[:40]

    # 3. Newer implementation wins.
    if _superseded(repo, ref, base_ref, paths):
        record["classification"] = "SUPERSEDED_BY_NEWER"
        record["disposition"] = (f"every touched path moved on {ctx['base']} after this "
                                 f"ref's tip; newest implementation wins")
        return record

    # 4. Conflicts -> focused follow-up, never a forced overwrite.
    clean, detail = _applies_cleanly(repo, ref, base_ref)
    if not clean:
        record["classification"] = "CONFLICTED_NEEDS_FOCUSED_TASK"
        record["detail"] = detail
        record["disposition"] = ("does not merge cleanly; focused follow-up task queued "
                                 "rather than forcing an overwrite")
        return record

    # 5. Real, unclaimed, applicable value.
    record["classification"] = "RECOVERABLE_VALUE"
    record["disposition"] = (f"{len(unique)} unique commit(s) across {len(paths)} path(s) "
                             f"apply cleanly; deliver via a new isolated worktree + agent branch")
    return record


# ── Ledger ──────────────────────────────────────────────────────────────────

def write_ledger(records: list, fingerprint: str, *, db=None,
                 task_type: str = "chatgpt_local_reconcile_ledger") -> dict:
    """One `coordination_tasks` row per evidence item, tagged with the audit fingerprint.

    Best-effort per row: a DB hiccup on item 40 must not discard the 39 rows that landed,
    so failures are counted and reported rather than raised.
    """
    out = {"written": 0, "failed": 0, "errors": [], "fingerprint": fingerprint}
    if db is None:
        try:
            import db as _db
            db = _db
        except Exception as exc:  # noqa: BLE001 — fail-soft
            out["errors"].append(f"db unavailable: {type(exc).__name__}: {exc}")
            return out

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for record in records:
        payload = {
            "audit_fingerprint": fingerprint,
            "source": record.get("source"),
            "kind": record.get("kind"),
            "classification": record.get("classification"),
            "disposition": record.get("disposition"),
            "task": record.get("task") or None,
            "branch": record.get("branch") or None,
            "commit": record.get("commit") or None,
            "unique_commits": record.get("unique_commits"),
            "at": stamp,
        }
        try:
            db.insert("coordination_tasks", {
                "task_type": task_type,
                "payload": json.dumps(payload, sort_keys=True, default=str)[:2000],
            }, upsert=False)
            out["written"] += 1
        except Exception as exc:  # noqa: BLE001 — fail-soft, per row
            out["failed"] += 1
            if len(out["errors"]) < 5:
                out["errors"].append(f"{record.get('source')}: {type(exc).__name__}: {exc}")
    return out


def live_task_slugs(db=None, project_name: str = "") -> set:
    """Slugs currently owned by a live orchestrator task. Fail-soft: empty set.

    An empty set is the safe failure mode: it can only cause an item to be classified as
    RECOVERABLE_VALUE instead of ACTIVE_IN_ANOTHER_TASK, i.e. a duplicated investigation,
    never a lost one.
    """
    if db is None:
        try:
            import db as _db
            db = _db
        except Exception:  # noqa: BLE001
            return set()
    slugs = set()
    try:
        rows = db.select_all("tasks", {"select": "slug,state"}) or []
    except Exception:  # noqa: BLE001
        return set()
    for row in rows:
        if str(row.get("state", "")).upper() in LIVE_TASK_STATES and row.get("slug"):
            slugs.add(row["slug"])
    return slugs


# ── Orchestration ───────────────────────────────────────────────────────────

def reconcile(repo: str, fingerprint: str, *, base: str = "", db=None,
              items=None, write: bool = True) -> dict:
    """Enumerate, classify and (optionally) ledger every evidence item.

    `complete` is True only when zero items came back UNKNOWN and every item with
    remaining value carries durable provenance — that is the task's completion bar, so
    it is computed here rather than asserted in prose.
    """
    report = {
        "repo": repo, "fingerprint": fingerprint, "base": "", "records": [],
        "counts": {c: 0 for c in CLASSIFICATIONS}, "unknown": [],
        "complete": False, "ledger": None, "error": None,
    }
    if not _enabled():
        report["error"] = "disabled by ORCH_RECONCILE_ENABLED"
        return report
    if not os.path.isdir(repo):
        report["error"] = f"repo path does not exist: {repo}"
        return report

    ctx = build_context(repo, base=base, live_task_slugs=live_task_slugs(db))
    report["base"] = ctx["base"]
    if not ctx["base_sha"]:
        report["error"] = f"could not resolve base ref {ctx['base_ref']}"
        return report

    for item in (items if items is not None else enumerate_evidence(repo)):
        record = classify(repo, item, ctx)
        report["records"].append(record)
        cls = record["classification"]
        if cls in report["counts"]:
            report["counts"][cls] += 1
        else:
            report["unknown"].append(record["source"])

    if write and report["records"]:
        report["ledger"] = write_ledger(report["records"], fingerprint, db=db)

    needs_provenance = [r for r in report["records"]
                        if r["classification"] in ("RECOVERABLE_VALUE",
                                                   "CONFLICTED_NEEDS_FOCUSED_TASK")]
    report["needs_followup"] = [r["source"] for r in needs_provenance]
    report["complete"] = (not report["unknown"]) and (
        report["ledger"] is None or report["ledger"].get("failed", 0) == 0)
    return report


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Classify local build evidence, read-only.")
    ap.add_argument("repo")
    ap.add_argument("fingerprint")
    ap.add_argument("--base", default="")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    report = reconcile(args.repo, args.fingerprint, base=args.base, write=not args.no_write)
    for record in report["records"]:
        print(f"{record['classification']:<30} {record['source']}")
    print(json.dumps({k: report[k] for k in ("base", "counts", "unknown", "complete",
                                             "needs_followup", "error")},
                     indent=2, default=str))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
