#!/usr/bin/env python3
"""stash_triage.py - read-only triage of a repo's stash list, addressed by SHA.

Section D of the beethoven audit addendum already computed the counts on Mac 1
(119 empty / 37 already-landed / 12 cleanly-recoverable / 120 conflicted). This module is
the reusable machinery behind that count, and it fixes the one thing the one-off shell
pass got wrong: `stash@{N}` indices SHIFT every time any stash is pushed or dropped, so a
recorded index silently points at a different stash later. Every record here carries the
stash COMMIT SHA, which is stable, and callers should address stashes by SHA.

Classes:
  empty           - the stash has no diff against its parent; nothing to recover
  already_landed  - the stash's content is already present in HEAD
  recoverable     - real content, applies cleanly to HEAD
  conflicted      - real content that no longer applies; needs judgment, one at a time

Everything here is read-only and fail-soft: it never pops, never drops, never writes to the
repo, and returns empty/defaulted values rather than raising.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

EMPTY = "empty"
ALREADY_LANDED = "already_landed"
RECOVERABLE = "recoverable"
CONFLICTED = "conflicted"

CLASSES = (EMPTY, ALREADY_LANDED, RECOVERABLE, CONFLICTED)

# Conflicted stashes touching these paths are the highest-value triage targets: they are the
# ones most likely to hold genuinely lost runner improvements.
PRIORITY_PREFIXES = ("runner/",)

TIMEOUT = int(os.environ.get("ORCH_STASH_TRIAGE_TIMEOUT", "60"))


def _git(repo: str, *args: str, stdin: Optional[bytes] = None):
    """Run a git command. Returns (rc, stdout, stderr); never raises."""
    try:
        r = subprocess.run(["git", "-C", repo] + list(args), input=stdin,
                           capture_output=True, timeout=TIMEOUT)
        return (r.returncode,
                (r.stdout or b"").decode("utf-8", "replace"),
                (r.stderr or b"").decode("utf-8", "replace"))
    except Exception as e:  # subprocess/OS/timeout - all fail-soft
        return 1, "", str(e)


def list_stashes(repo: str) -> List[Dict[str, str]]:
    """Every stash as {sha, ref, subject}. Empty list when there are none or on error.

    `ref` is the *current* stash@{N} spelling and is only useful for display — it is not
    stable. Address stashes by `sha`.
    """
    if not repo or not os.path.isdir(repo):
        return []
    rc, out, _ = _git(repo, "stash", "list", "--format=%H%x00%gd%x00%gs")
    if rc != 0:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\0")
        if len(parts) >= 3 and parts[0].strip():
            rows.append({"sha": parts[0].strip(), "ref": parts[1].strip(), "subject": parts[2].strip()})
    return rows


def stash_files(repo: str, sha: str) -> List[str]:
    """Paths touched by a stash. Empty list for an empty stash or on error."""
    if not repo or not sha:
        return []
    rc, out, _ = _git(repo, "stash", "show", "--name-only", "--format=", sha)
    if rc != 0:
        return []
    return [p for p in (l.strip() for l in out.splitlines()) if p]


def stash_patch(repo: str, sha: str) -> str:
    """Unified diff for a stash, or "" when empty/unavailable."""
    if not repo or not sha:
        return ""
    rc, out, _ = _git(repo, "stash", "show", "-p", "--format=", sha)
    return out if rc == 0 else ""


def _applies_cleanly(repo: str, patch: str) -> bool:
    if not patch.strip():
        return False
    rc, _, _ = _git(repo, "apply", "--check", "-", stdin=patch.encode("utf-8", "replace"))
    return rc == 0


def _already_landed(repo: str, patch: str) -> bool:
    """True when the patch is already present in the working tree (reverse-applies cleanly)."""
    if not patch.strip():
        return False
    rc, _, _ = _git(repo, "apply", "--check", "--reverse", "-",
                    stdin=patch.encode("utf-8", "replace"))
    return rc == 0


def is_priority(files: List[str]) -> bool:
    """True when any touched path is in the high-value triage set."""
    try:
        return any(str(f).startswith(PRIORITY_PREFIXES) for f in (files or []))
    except Exception:
        return False


def classify(repo: str, sha: str) -> Dict[str, Any]:
    """Classify one stash. Always returns a record; never raises."""
    record: Dict[str, Any] = {"sha": sha or "", "class": CONFLICTED, "files": [],
                              "priority": False, "reason": ""}
    try:
        files = stash_files(repo, sha)
        patch = stash_patch(repo, sha)
        record["files"] = files
        record["priority"] = is_priority(files)
        if not files and not patch.strip():
            record["class"] = EMPTY
            record["reason"] = "no diff against its parent"
            return record
        if _already_landed(repo, patch):
            record["class"] = ALREADY_LANDED
            record["reason"] = "content already present in the working tree"
            return record
        if _applies_cleanly(repo, patch):
            record["class"] = RECOVERABLE
            record["reason"] = "applies cleanly to HEAD"
            return record
        record["class"] = CONFLICTED
        record["reason"] = "no longer applies; needs judgment"
        return record
    except Exception as e:
        record["reason"] = "triage failed fail-soft: %s" % e
        return record


def triage(repo: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """Triage every stash in `repo`. Read-only. Returns counts + per-stash records."""
    result: Dict[str, Any] = {"repo": repo, "total": 0, "counts": {c: 0 for c in CLASSES},
                              "records": [], "priority_conflicted": 0}
    stashes = list_stashes(repo)
    if limit is not None and limit >= 0:
        stashes = stashes[:limit]
    result["total"] = len(stashes)
    for s in stashes:
        rec = classify(repo, s["sha"])
        rec["ref"] = s.get("ref", "")
        rec["subject"] = s.get("subject", "")
        result["records"].append(rec)
        result["counts"][rec["class"]] = result["counts"].get(rec["class"], 0) + 1
        if rec["class"] == CONFLICTED and rec.get("priority"):
            result["priority_conflicted"] += 1
    return result


def next_conflicted(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The single next conflicted stash to work, priority paths first.

    The audit is explicit that the conflicted set is worked ONE AT A TIME, so this returns one
    record, not a batch. None when there is nothing left to triage.
    """
    try:
        conflicted = [r for r in (report or {}).get("records", []) if r.get("class") == CONFLICTED]
        if not conflicted:
            return None
        conflicted.sort(key=lambda r: (0 if r.get("priority") else 1, -len(r.get("files") or [])))
        return conflicted[0]
    except Exception:
        return None


def recoverable_shas(report: Dict[str, Any]) -> List[str]:
    """Stable SHAs of the cleanly-recoverable set — what a recovery script should consume."""
    try:
        return [r["sha"] for r in (report or {}).get("records", [])
                if r.get("class") == RECOVERABLE and r.get("sha")]
    except Exception:
        return []


def summarize(report: Dict[str, Any]) -> str:
    """One-line human summary, safe on a malformed report."""
    try:
        c = (report or {}).get("counts", {})
        return ("%s stashes: %s empty · %s already-landed · %s recoverable · %s conflicted "
                "(%s touch %s)" % (
                    (report or {}).get("total", 0), c.get(EMPTY, 0), c.get(ALREADY_LANDED, 0),
                    c.get(RECOVERABLE, 0), c.get(CONFLICTED, 0),
                    (report or {}).get("priority_conflicted", 0), PRIORITY_PREFIXES[0]))
    except Exception:
        return "stash triage unavailable"


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Read-only stash triage (never pops, never drops).")
    p.add_argument("repo", nargs="?", default=os.getcwd())
    p.add_argument("--json", action="store_true", help="emit the full report as JSON")
    p.add_argument("--next", action="store_true", help="print the next conflicted stash to work")
    p.add_argument("--recoverable", action="store_true", help="print recoverable stash SHAs")
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args(argv)
    report = triage(a.repo, limit=a.limit)
    if a.json:
        print(json.dumps(report, indent=2))
    elif a.next:
        nxt = next_conflicted(report)
        print(json.dumps(nxt, indent=2) if nxt else "no conflicted stashes remaining")
    elif a.recoverable:
        for sha in recoverable_shas(report):
            print(sha)
    else:
        print(summarize(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
