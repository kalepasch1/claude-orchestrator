#!/usr/bin/env python3
"""
codex_reconciler.py — classify local ChatGPT/Codex build evidence and write the
recovery ledger. The CONSUMER half of tools/chatgpt-bridge/local_build_audit.py.

THE GAP THIS FILLS
    local_build_audit.py finds Codex residue (dirty worktrees, detached worktrees, local
    branches, stashes, output bundles) and files a `chatgpt-local-reconcile-*` task per
    snapshot. Nothing consumed those tasks: each one arrived as a 26 KB prompt containing a
    JSON evidence snapshot and an instruction to classify every item by hand. That is
    expensive, non-reproducible, and — because the snapshot is a point-in-time sample while
    the instruction says to enumerate the LIVE source — frequently answers the wrong
    question. Two agents classifying the same worktree a day apart could disagree with
    nothing to arbitrate.

    This module makes the classification mechanical and repeatable: enumerate live, compare
    against the real repository and the real queue, and write one durable ledger record per
    item.

CLASSIFICATION (the five the reconcile contract defines — never UNKNOWN)
    ALREADY_PRESENT              the work is reachable from the default branch; nothing to do
    SUPERSEDED_BY_NEWER          a newer remote branch or a newer commit covers the same files
    ACTIVE_IN_ANOTHER_TASK       a live queue task or agent branch already owns it
    RECOVERABLE_VALUE            real, unrepresented work — worth a focused task
    CONFLICTED_NEEDS_FOCUSED_TASK  cannot be resolved mechanically (broken git metadata,
                                 unreadable artifact, ambiguous ownership)

    "Zero UNKNOWN" is a hard requirement of the contract, so the classifier is TOTAL: any
    item it cannot positively resolve falls to CONFLICTED_NEEDS_FOCUSED_TASK, which queues
    a human-scoped follow-up. It never guesses ALREADY_PRESENT — that is the one verdict
    that silently discards work, so it requires positive proof (an ancestor commit, or every
    changed file byte-identical to the default branch).

SAFETY
    - the evidence is READ-ONLY. This module never deletes, resets, cleans, pops, stashes,
      checks out or moves anything under the Codex root. Every git call it makes is a read
      (rev-parse, merge-base, ls-remote, cat-file, diff --quiet).
    - report-only unless --apply is passed.
    - ledger writes are idempotent per (fingerprint, item) and append-only.
    - fail-soft everywhere: an item that raises is CONFLICTED, not a crash.

Usage:
    python3 codex_reconciler.py --fingerprint <sha256>              # report
    python3 codex_reconciler.py --fingerprint <sha256> --apply      # write the ledger
    python3 codex_reconciler.py --fingerprint <sha> --app beethoven --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_ROOT, "tools", "chatgpt-bridge"))

ALREADY_PRESENT = "ALREADY_PRESENT"
SUPERSEDED_BY_NEWER = "SUPERSEDED_BY_NEWER"
ACTIVE_IN_ANOTHER_TASK = "ACTIVE_IN_ANOTHER_TASK"
RECOVERABLE_VALUE = "RECOVERABLE_VALUE"
CONFLICTED = "CONFLICTED_NEEDS_FOCUSED_TASK"

CLASSIFICATIONS = (ALREADY_PRESENT, SUPERSEDED_BY_NEWER, ACTIVE_IN_ANOTHER_TASK,
                   RECOVERABLE_VALUE, CONFLICTED)

LEDGER_TASK_TYPE = "codex_recovery_ledger"
GIT_TIMEOUT = int(os.environ.get("ORCH_CODEX_GIT_TIMEOUT", "60"))

# Live task states that mean "somebody is already on this".
LIVE_STATES = {"QUEUED", "RUNNING", "DONE", "MERGED", "PASSED", "BLOCKED"}


# ── read-only git ─────────────────────────────────────────────────────────────

def _git(repo, *args):
    """Read-only git. Returns (rc, stdout). Never raises, never mutates."""
    try:
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                           timeout=GIT_TIMEOUT)
        return r.returncode, (r.stdout or "")
    except Exception:
        return 1, ""


def _is_ancestor(repo, sha, ref):
    if not sha or not ref:
        return False
    return _git(repo, "merge-base", "--is-ancestor", sha, ref)[0] == 0


def _commit_exists(repo, sha):
    return bool(sha) and _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")[0] == 0


def _remote_branches(repo, pattern="*"):
    rc, out = _git(repo, "ls-remote", "--heads", "origin", pattern)
    if rc != 0:
        return {}
    heads = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            heads[parts[1][len("refs/heads/"):]] = parts[0]
    return heads


def _files_match_default(repo, files, base_ref):
    """True when EVERY listed file is byte-identical to the default branch.

    This is the only evidence accepted for ALREADY_PRESENT when there is no commit to test
    for ancestry. It is deliberately all-or-nothing: a partial match means some of the work
    is unrepresented, which is RECOVERABLE_VALUE, not "already there".
    """
    files = [f for f in (files or []) if f]
    if not files:
        return False
    for f in files:
        rc, _ = _git(repo, "diff", "--quiet", base_ref, "--", f)
        if rc != 0:            # 1 = differs, 128 = path unknown to that ref
            return False
    return True


# ── queue lookup ──────────────────────────────────────────────────────────────

def _live_task_slugs():
    """Slugs of tasks that are live in the queue. Empty set when the DB is unreachable.

    An empty set only costs precision (an item may be called RECOVERABLE_VALUE when a task
    already owns it), never safety — it can never produce ALREADY_PRESENT.
    """
    try:
        import db
        rows = db.select("tasks", {"select": "slug,state", "limit": "5000",
                                   "order": "updated_at.desc"}) or []
        return {r["slug"] for r in rows
                if r.get("slug") and (r.get("state") in LIVE_STATES)}
    except Exception:
        return set()


def _slug_candidates(item):
    """Every slug a piece of evidence could plausibly be tracked under."""
    out = set()
    branch = (item.get("branch") or "").strip()
    if branch:
        out.add(branch)
        if "/" in branch:
            out.add(branch.split("/", 1)[1])
    path = str(item.get("path") or "")
    if path:
        out.add(os.path.basename(path.rstrip("/")))
    return {s for s in out if s}


# ── classification ────────────────────────────────────────────────────────────

def classify_item(item, repo, base_ref="origin/master", remote_heads=None,
                  live_slugs=None):
    """Classify ONE evidence item. Total: always returns one of CLASSIFICATIONS.

    Returns {"classification", "reason", "evidence": {...}}.
    """
    try:
        remote_heads = remote_heads if remote_heads is not None else {}
        live_slugs = live_slugs if live_slugs is not None else set()
        kind = item.get("kind") or ""
        head = (item.get("head") or "").strip()
        branch = (item.get("branch") or "").strip()
        changes = item.get("changes") or []
        slugs = _slug_candidates(item)

        # 1. Broken metadata cannot be resolved mechanically, whatever else is true.
        if "broken" in kind or item.get("error"):
            return {"classification": CONFLICTED,
                    "reason": f"git metadata does not resolve ({item.get('error') or kind}); "
                              f"needs a human-scoped recovery task",
                    "evidence": {"kind": kind}}

        # 2. Positive proof the work landed. Ancestry first (cheap and exact).
        if head and _commit_exists(repo, head) and _is_ancestor(repo, head, base_ref):
            return {"classification": ALREADY_PRESENT,
                    "reason": f"{head[:12]} is an ancestor of {base_ref}",
                    "evidence": {"head": head, "base": base_ref}}

        # 3. Somebody already owns it — a live task, or an agent branch on origin.
        owned = sorted(slugs & live_slugs)
        if owned:
            return {"classification": ACTIVE_IN_ANOTHER_TASK,
                    "reason": f"live queue task(s): {', '.join(owned[:3])}",
                    "evidence": {"slugs": owned[:5]}}
        agent_branches = sorted({f"agent/{s}" for s in slugs} & set(remote_heads))
        if agent_branches:
            return {"classification": ACTIVE_IN_ANOTHER_TASK,
                    "reason": f"agent branch on origin: {agent_branches[0]}",
                    "evidence": {"branches": agent_branches[:5]}}

        # 4. A newer remote branch of the same name covers it.
        if branch and branch in remote_heads:
            remote_sha = remote_heads[branch]
            if remote_sha != head:
                return {"classification": SUPERSEDED_BY_NEWER,
                        "reason": f"origin/{branch} is at {remote_sha[:12]}, local evidence "
                                  f"at {head[:12] or 'unknown'}",
                        "evidence": {"branch": branch, "remote": remote_sha}}

        # 5. Every changed file already matches the default branch. All-or-nothing.
        if changes and _files_match_default(repo, changes, base_ref):
            return {"classification": ALREADY_PRESENT,
                    "reason": f"all {len(changes)} changed files are identical to {base_ref}",
                    "evidence": {"files": len(changes)}}

        # 6. An artifact we cannot read is not the same as an artifact with no value.
        if "artifact" in kind:
            path = item.get("path")
            if not path or not os.path.exists(path):
                return {"classification": CONFLICTED,
                        "reason": "artifact referenced by the snapshot no longer exists on disk",
                        "evidence": {"path": path}}
            return {"classification": RECOVERABLE_VALUE,
                    "reason": "output artifact is present and not represented on origin",
                    "evidence": {"path": path,
                                 "bytes": _safe_size(path)}}

        # 7. Real, unrepresented work.
        return {"classification": RECOVERABLE_VALUE,
                "reason": (f"{len(changes)} changed file(s) not on {base_ref} and not owned "
                           f"by any live task or agent branch"),
                "evidence": {"files": len(changes), "branch": branch or None,
                             "head": head or None}}
    except Exception as exc:
        # Total function: an unexpected failure is a conflict to be looked at, never UNKNOWN.
        return {"classification": CONFLICTED,
                "reason": f"classifier error: {type(exc).__name__}: {exc}",
                "evidence": {}}


def _safe_size(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return None


def disposition_for(classification):
    """What happens next, in the reconcile contract's vocabulary."""
    return {
        ALREADY_PRESENT: "no action — work is on the default branch",
        SUPERSEDED_BY_NEWER: "no action — newer implementation wins; evidence retained",
        ACTIVE_IN_ANOTHER_TASK: "no action — do not duplicate the owning task",
        RECOVERABLE_VALUE: "queue a focused recovery task; apply in an isolated worktree",
        CONFLICTED: "queue a focused follow-up; do not force an overwrite",
    }.get(classification, "review")


# ── evidence enumeration ──────────────────────────────────────────────────────

DEFAULT_CODEX_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "Codex")


def _load_scanner():
    """local_build_audit, from wherever it actually lives on this host.

    It is NOT on origin/master (commit db62883e is local-only), so an agent branch based on
    origin — which is every branch this reconciler runs on — cannot import it from its own
    worktree. That is itself an instance of the problem this task reconciles, so the
    reconciler must not depend on the thing being reconciled. Try the worktree, then the
    main checkout, then give up and use the built-in walker below.
    """
    for path in (os.path.join(_ROOT, "tools", "chatgpt-bridge"),
                 os.path.join(os.path.expanduser("~"), "Documents", "beethoven",
                              "claude-orchestrator", "tools", "chatgpt-bridge")):
        if not os.path.isdir(path):
            continue
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import local_build_audit  # noqa: F401
            return local_build_audit
        except Exception:
            continue
    return None


def _walk_codex(codex_root, app=None):
    """Built-in read-only fallback scanner: find Codex worktrees and output artifacts.

    Intentionally simpler than local_build_audit's — it exists so classification still runs
    when the richer scanner is unavailable, not to replace it. Read-only throughout.
    """
    groups = {}
    if not os.path.isdir(codex_root):
        return groups
    try:
        for session in sorted(os.listdir(codex_root)):
            work = os.path.join(codex_root, session)
            if not os.path.isdir(work):
                continue
            for sub in sorted(os.listdir(work)):
                base = os.path.join(work, sub)
                for area, kind in (("work", "codex_worktree"),
                                   ("outputs", "codex_output_artifact")):
                    d = os.path.join(base, area)
                    if not os.path.isdir(d):
                        continue
                    for name in sorted(os.listdir(d)):
                        p = os.path.join(d, name)
                        item = {"kind": kind, "path": p}
                        if kind == "codex_worktree":
                            rc, out = _git(p, "rev-parse", "--abbrev-ref", "HEAD")
                            if rc != 0:
                                item["kind"] = "broken_codex_git_worktree"
                                item["error"] = "git metadata no longer resolves"
                            else:
                                item["branch"] = out.strip()
                                item["head"] = _git(p, "rev-parse", "HEAD")[1].strip()
                                item["changes"] = [
                                    ln[3:] for ln in
                                    _git(p, "status", "--porcelain")[1].splitlines() if ln]
                                item["change_count"] = len(item["changes"])
                        guess = _infer_app(p)
                        groups.setdefault(guess, []).append(item)
    except Exception:
        pass
    if app:
        groups = {k: v for k, v in groups.items() if k == app}
    return groups


def _infer_app(path):
    low = str(path).lower()
    for name, keys in (("beethoven", ("orchestrator", "beethoven")),
                       ("apparently", ("apparently",)),
                       ("tomorrow", ("tomorrow",)),
                       ("smarter", ("smarter",)),
                       ("illuminati", ("illuminati", "trojun")),
                       ("pareto-2080", ("pareto", "2080"))):
        if any(k in low for k in keys):
            return name
    return "unknown-app"


def enumerate_evidence(app=None, codex_root=None):
    """Enumerate the LIVE evidence source, not the snapshot embedded in a prompt.

    The snapshot in the task prompt is a point-in-time sample; the contract says to
    enumerate live so items created or resolved since the task was filed are classified
    correctly. Prefers local_build_audit's scanner; falls back to the built-in walker.
    """
    lba = _load_scanner()
    root = codex_root or (getattr(lba, "DEFAULT_CODEX_ROOT", None) or DEFAULT_CODEX_ROOT)
    if lba is not None:
        try:
            groups = lba.scan_codex(root, lba.load_targets(), set(), 0.0) or {}
            if groups:
                return {k: v for k, v in groups.items() if not app or k == app}
        except Exception:
            pass
    return _walk_codex(str(root), app=app)


def item_key(fingerprint, item):
    """Stable per-item identity, so re-running writes no duplicate ledger rows."""
    raw = f"{fingerprint}|{item.get('kind')}|{item.get('path')}|{item.get('branch')}"
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]


# ── ledger ────────────────────────────────────────────────────────────────────

def _existing_keys(fingerprint):
    try:
        import db
        rows = db.select("coordination_tasks",
                         {"select": "payload", "task_type": f"eq.{LEDGER_TASK_TYPE}",
                          "limit": "2000", "order": "created_at.desc"}) or []
    except Exception:
        return set()
    keys = set()
    for r in rows:
        try:
            payload = r.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            if (payload or {}).get("fingerprint") == fingerprint:
                keys.add(payload.get("item_key"))
        except Exception:
            continue
    return {k for k in keys if k}


def write_ledger_record(record):
    """Append one recovery-ledger record. Returns True on success (fail-soft)."""
    try:
        import db
        db.insert("coordination_tasks",
                  {"task_type": LEDGER_TASK_TYPE,
                   "payload": json.dumps(record)[:8000]}, upsert=False)
        return True
    except Exception:
        return False


# ── run ───────────────────────────────────────────────────────────────────────

def reconcile(fingerprint, app=None, repo=None, base_ref="origin/master",
              codex_root=None, apply=False):
    """Classify every live evidence item and (optionally) write the ledger."""
    repo = repo or _ROOT
    groups = enumerate_evidence(app=app, codex_root=codex_root)
    remote_heads = _remote_branches(repo)
    live_slugs = _live_task_slugs()
    already = _existing_keys(fingerprint) if apply else set()

    out = {"fingerprint": fingerprint, "apply": apply, "items": [],
           "counts": {c: 0 for c in CLASSIFICATIONS},
           "unknown": 0, "written": 0, "skipped_existing": 0, "write_failed": 0}

    for app_name, items in sorted(groups.items()):
        for item in items or []:
            verdict = classify_item(item, repo, base_ref=base_ref,
                                    remote_heads=remote_heads, live_slugs=live_slugs)
            cls = verdict.get("classification")
            if cls not in CLASSIFICATIONS:      # belt and braces: never emit UNKNOWN
                cls = CONFLICTED
                verdict["classification"] = cls
                verdict["reason"] = f"unrecognised verdict; {verdict.get('reason', '')}"
            key = item_key(fingerprint, item)
            record = {
                "fingerprint": fingerprint,
                "item_key": key,
                "app": app_name,
                "source": {"kind": item.get("kind"), "path": str(item.get("path") or ""),
                           "branch": item.get("branch"), "head": item.get("head"),
                           "change_count": item.get("change_count")},
                "classification": cls,
                "reason": verdict.get("reason"),
                "evidence": verdict.get("evidence") or {},
                "disposition": disposition_for(cls),
                "task": None, "branch": None, "commit": None,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "reconciler": "codex_reconciler.py",
            }
            out["counts"][cls] += 1
            out["items"].append(record)

            if not apply:
                continue
            if key in already:
                out["skipped_existing"] += 1
                continue
            if write_ledger_record(record):
                out["written"] += 1
                already.add(key)
            else:
                out["write_failed"] += 1

    out["total"] = len(out["items"])
    # The completion contract: zero UNKNOWN items.
    out["unknown"] = sum(1 for r in out["items"]
                         if r["classification"] not in CLASSIFICATIONS)
    return out


def main():
    ap = argparse.ArgumentParser(description="Classify Codex build evidence + write ledger")
    ap.add_argument("--fingerprint", required=True, help="audit fingerprint for this sweep")
    ap.add_argument("--app", default=None, help="limit to one app (e.g. beethoven)")
    ap.add_argument("--repo", default=None, help="repo to compare against (default: this one)")
    ap.add_argument("--base-ref", default="origin/master")
    ap.add_argument("--codex-root", default=None)
    ap.add_argument("--apply", action="store_true",
                    help="write the recovery-ledger records (default: report only)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    res = reconcile(args.fingerprint, app=args.app, repo=args.repo,
                    base_ref=args.base_ref, codex_root=args.codex_root, apply=args.apply)
    if args.json:
        print(json.dumps(res, indent=2, default=str))
        return
    print(f"codex_reconciler: {res['total']} evidence item(s), "
          f"UNKNOWN={res['unknown']} (must be 0)")
    for c in CLASSIFICATIONS:
        if res["counts"].get(c):
            print(f"  {c}: {res['counts'][c]}")
    for r in res["items"]:
        print(f"  [{r['classification']}] {r['app']}: {r['source']['kind']} "
              f"{os.path.basename(r['source']['path'])} — {r['reason']}")
    if args.apply:
        print(f"ledger: written={res['written']} "
              f"already_recorded={res['skipped_existing']} failed={res['write_failed']}")


if __name__ == "__main__":
    main()
