#!/usr/bin/env python3
"""
automerge_discard_guard.py - refuse (or record) auto-resolutions that silently
discard branch-original work.

THE SHAPE, measured 2026-08-06 over 59 auto-resolved merges on master since Aug 1:

    auto-resolved merges audited ................. 59
    discarded at least one branch edit ............  6  (10%)
    files with discarded edits ................... 28  (all .py)
    of those, edits already present in mainline ...  0
    of those, carrying BRANCH-ORIGINAL commits ... 28  (100%)

Every discard dropped work that existed nowhere else at merge time. The recurring
casualties were themselves fixes for silent work loss -- f01601e2 (restore stranded
session work), ef31027d (dropped helpers restored), 311d68e3 (restore corrupted
_run_tests/_try_semantic_merge), 9c3e7f7d (never silently drop an operator prompt),
4fe179c8 (stranded-commit rescue). The system has been eating the repairs for its
own eating problem.

WHY THE EXISTING GATES DO NOT SEE IT
  * regression_guard diffs the PRE-merge tree against the RESULT. In this shape the
    result is byte-identical to the mainline parent, so pre == post for every file
    and the diff is empty. It is structurally blind here, not merely unlucky.
  * divergent_authorship_guard runs on the two parents but fires on SYMBOL loss
    (add/add, same-symbol, union_merge_symbol_loss). A branch edit that changes a
    function BODY -- 9c3e7f7d is exactly that -- leaves every symbol name present on
    both sides, so no detector trips.
  * stub_guard looks for constant-return shadowing, a different shape again.

So this guard compares the RESULT against BOTH PARENTS, per file, and asks the only
question that matters: did we keep mainline's bytes verbatim while throwing away a
branch edit that exists nowhere else?

DELIBERATELY NOT IN SCOPE (see the task's non-goals): this does not change the merge
strategy, does not attempt smarter conflict resolution, and does not revert anything
historical. It is about VISIBILITY and REFUSAL. An auto-resolution that keeps the
branch side, or blends both, is none of this guard's business.

Entry points mirror divergent_authorship_guard / stub_guard exactly:
  gate(repo, p1, p2, result_ref="HEAD")   -> (ok, log)   fail-closed, merge path
  check_merge_commit(repo, merge_sha)     -> dict        post-hoc audit of a real merge
  audit_range(repo, rev_range)            -> dict        standing audit, any commit range

Structured JSONL goes to .runtime/logs/automerge-discard-guard.log, and every discard
record additionally lands in .runtime/logs/automerge-discard-records.log so a dropped
edit is recoverable (branch SHA + path + dropped commit SHAs) rather than invisible.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NAME = "automerge-discard-guard"

ENABLED = os.environ.get("ORCH_AUTOMERGE_DISCARD_GUARD", "true").strip().lower() in (
    "1", "true", "yes", "on")

# "refuse"  -> the merge is rejected and the branch left for human resolution (preferred).
# "record"  -> the merge proceeds but every discard is written to the record log first.
# Anything else is treated as "refuse": an unreadable policy must not soften the gate.
POLICY = os.environ.get("ORCH_AUTOMERGE_DISCARD_POLICY", "refuse").strip().lower()

BREAK_GLASS = os.environ.get(
    "ORCH_AUTOMERGE_DISCARD_BREAK_GLASS", "false").strip().lower() in (
    "1", "true", "yes", "on")

GIT_TIMEOUT = int(os.environ.get("ORCH_AUTOMERGE_DISCARD_GIT_TIMEOUT", "120"))
MAX_FILES = int(os.environ.get("ORCH_AUTOMERGE_DISCARD_MAX_FILES", "400"))

# Subject line written by auto_conflict_resolver / merge_train's semantic merge.
AUTO_SUBJECT = re.compile(r"\(auto-resolved(?:\s+\d+\s+file\(s\))?\)", re.I)

# Paths where "mainline won" is not a loss worth blocking a merge over: generated
# artifacts, lockfiles and vendored trees are reproduced by their generator, not by
# the branch author. Kept deliberately tight -- every entry is a hole in the guard.
_SKIP = re.compile(
    r"(^|/)(node_modules|\.git|dist|build|coverage|vendor|__pycache__|\.next|\.nuxt"
    r"|\.output|\.vercel|\.runtime|\.claude/worktrees)(/|$)"
    r"|(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|poetry\.lock|Cargo\.lock)$"
    r"|\.(snap|log)$")


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", ".runtime"))


def _log_event(event, logname=NAME):
    """Append one structured JSONL record to .runtime/logs/<logname>.log (fail-soft)."""
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", NAME)
    try:
        path = os.path.join(_home(), "logs")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, logname + ".log"), "a") as fh:
            fh.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass  # logging must never break the check
    return row


def _git(repo, *args, **kw):
    """Run git; return (rc, stdout, stderr). Fail-soft."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, errors="replace",
                           timeout=kw.get("timeout", GIT_TIMEOUT))
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


def _rev(repo, ref):
    rc, out, _ = _git(repo, "rev-parse", "--verify", "%s^{commit}" % ref)
    return out.strip() if rc == 0 else ""


def _blob_id(repo, ref, path):
    """The blob OID for path at ref, or None when the ref has no such path.

    Comparing OIDs rather than file contents is not an optimisation detail: it makes
    the comparison exact for binary files and immune to any decoding fallback, and it
    is what git itself considers "the same file".
    """
    rc, out, _ = _git(repo, "rev-parse", "--verify", "--quiet", "%s:%s" % (ref, path))
    oid = out.strip()
    return oid if rc == 0 and oid else None


def _is_ancestor(repo, maybe_ancestor, ref):
    rc, _, _ = _git(repo, "merge-base", "--is-ancestor", maybe_ancestor, ref)
    return rc == 0


# ---------------------------------------------------------------- core analysis

def analyze(repo, p1, p2, result_ref="HEAD"):
    """The audit, for one resolution. p1 = mainline parent, p2 = branch parent.

    Returns {"ok", "error", "base", "discards": [...], "considered": n}.

    A file is a DISCARD when all three hold:
      1. the branch changed it (base..p2), and the two parents disagree on it;
      2. the resolved blob is byte-identical to the MAINLINE parent; and
      3. at least one commit on base..p2 that touched it is NOT an ancestor of
         mainline -- i.e. the edit existed nowhere but on this branch.

    Condition 3 is what keeps the benign case quiet. A branch that was merely
    carrying mainline's own history contributes nothing new, mainline winning
    loses nothing, and a guard that shouted about it would be turned off inside a
    week. 0 of the 28 measured discards were that case; the check still has to be
    here, because the day it stops being 0 is the day the guard has to stay
    trusted.
    """
    out = {"ok": True, "error": "", "base": "", "discards": [], "considered": 0}

    sha1, sha2 = _rev(repo, p1), _rev(repo, p2)
    if not sha1 or not sha2:
        out["ok"] = False
        out["error"] = "unresolvable parent(s): %r -> %r, %r -> %r" % (p1, sha1, p2, sha2)
        return out

    rc, base_out, err = _git(repo, "merge-base", sha1, sha2)
    if rc != 0 or not base_out.strip():
        # No merge base => no way to know what the branch changed. Fail closed: an
        # unanswerable question is not a clean answer. (This is the exact hole that
        # was closed in divergent_authorship_guard's guard_error severity.)
        out["ok"] = False
        out["error"] = "no merge-base between %s and %s: %s" % (
            sha1[:8], sha2[:8], (err or "").strip()[:200])
        return out
    base = base_out.strip()
    out["base"] = base

    rc, changed, err = _git(repo, "diff", "--name-only", base, sha2)
    if rc != 0:
        out["ok"] = False
        out["error"] = "diff %s..%s failed: %s" % (base[:8], sha2[:8], (err or "")[:200])
        return out

    paths = [p for p in (ln.strip() for ln in changed.splitlines())
             if p and not _SKIP.search(p)]
    if len(paths) > MAX_FILES:
        # Truncating would mean reporting "clean" on files never examined.
        out["ok"] = False
        out["error"] = "too many changed files to audit (%d > %d)" % (
            len(paths), MAX_FILES)
        return out
    out["considered"] = len(paths)

    for path in paths:
        b_main = _blob_id(repo, sha1, path)
        b_branch = _blob_id(repo, sha2, path)
        if b_main == b_branch:
            continue                      # parents agree: nothing was chosen
        b_result = _blob_id(repo, result_ref, path)
        if b_result != b_main:
            continue                      # branch kept, or a genuine blend: allowed

        # Mainline's bytes survived verbatim and the branch's did not. Did the branch
        # actually contribute anything, or was it carrying mainline's own history?
        rc, revs, _ = _git(repo, "rev-list", "%s..%s" % (base, sha2), "--", path)
        if rc != 0:
            out["ok"] = False
            out["error"] = "rev-list failed for %s" % path
            return out
        touching = [c for c in (ln.strip() for ln in revs.splitlines()) if c]
        original = [c for c in touching if not _is_ancestor(repo, c, sha1)]
        if not original:
            continue                      # benign: the edit is already in mainline

        subjects = []
        for sha in original[:12]:
            rc, subj, _ = _git(repo, "log", "-1", "--format=%h %s", sha)
            subjects.append(subj.strip() if rc == 0 else sha[:8])

        out["discards"].append({
            "path": path,
            "branch_sha": sha2,           # reconstruction hint: `git show <sha>:<path>`
            "mainline_sha": sha1,
            "base_sha": base,
            "dropped_commits": original,
            "dropped_subjects": subjects,
            "recover": "git show %s:%s" % (sha2[:12], path),
        })

    return out


# ---------------------------------------------------------------- records

def record_discards(repo, result, *, merge_sha="", branch="", policy=None):
    """Write one durable record per discarded file. Returns the rows written.

    Called on BOTH policies. Under "refuse" the record is the evidence trail for why
    a merge was rejected; under "record" it is the only thing standing between a
    dropped edit and permanent invisibility. An EMPTY record is written too, when a
    resolution was audited and found clean -- that empty row is what lets a later
    reader distinguish "audited, nothing dropped" from "never audited", which is the
    distinction the whole task turns on.
    """
    rows = []
    for d in result.get("discards", []):
        rows.append(_log_event({
            "event": "discard",
            "repo": repo,
            "merge_sha": merge_sha,
            "branch": branch,
            "policy": policy or POLICY,
            **d,
        }, logname="automerge-discard-records"))
    if not rows:
        _log_event({
            "event": "audited_clean",
            "repo": repo,
            "merge_sha": merge_sha,
            "branch": branch,
            "considered": result.get("considered", 0),
        }, logname="automerge-discard-records")
    return rows


def summarize(result):
    """One-line human summary of an analyze() result."""
    ds = result.get("discards", [])
    if not ds:
        return "no branch-original work discarded (%d file(s) examined)" % (
            result.get("considered", 0))
    dropped = sum(len(d["dropped_commits"]) for d in ds)
    head = "; ".join(
        "%s (drops %s)" % (d["path"], ", ".join(c[:8] for c in d["dropped_commits"][:3]))
        for d in ds[:4])
    more = "" if len(ds) <= 4 else " (+%d more file(s))" % (len(ds) - 4)
    return ("auto-resolution would discard branch-original work in %d file(s), "
            "%d commit(s) dropped: %s%s" % (len(ds), dropped, head, more))


# ---------------------------------------------------------------- merge-path gate

def gate(repo, p1, p2, result_ref="HEAD", *, branch="", merge_sha=""):
    """(ok, log) for the merge path. FAIL-CLOSED.

    ok=False means: do not commit this resolution silently. Under the default
    "refuse" policy the caller rolls the merge back and preserves the branch. Under
    "record" the discards are written durably and the merge is allowed to proceed --
    which is a policy choice about who resolves the conflict, never a choice to let
    it vanish.
    """
    if not ENABLED:
        return True, "%s: disabled" % NAME
    try:
        result = analyze(repo, p1, p2, result_ref=result_ref)
    except Exception as exc:              # a crashing gate must never wave a merge through
        return False, "%s: guard error (fail-closed): %s: %s" % (
            NAME, type(exc).__name__, exc)

    if not result["ok"]:
        return False, "%s: audit incomplete (fail-closed): %s" % (NAME, result["error"])

    record_discards(repo, result, merge_sha=merge_sha, branch=branch)
    log = "%s: %s" % (NAME, summarize(result))
    _log_event({"event": "gate", "repo": repo, "branch": branch,
                "discards": len(result["discards"]),
                "considered": result["considered"], "policy": POLICY})

    if not result["discards"]:
        return True, log
    if BREAK_GLASS:
        return True, log + " [BREAK_GLASS: allowed]"
    if POLICY == "record":
        # Recorded, therefore recoverable, therefore not silent. Proceed.
        return True, log + " [policy=record: merged with discard record]"
    return False, log + " [policy=refuse: left for human resolution]"


def check_merge_commit(repo, merge_sha):
    """Post-hoc audit of one real merge commit. Returns analyze()'s shape plus meta."""
    rc, parents, _ = _git(repo, "log", "-1", "--format=%P", merge_sha)
    if rc != 0:
        return {"ok": False, "error": "unknown commit %s" % merge_sha,
                "discards": [], "considered": 0, "merge_sha": merge_sha}
    ps = parents.split()
    if len(ps) < 2:
        return {"ok": True, "error": "not a merge commit", "discards": [],
                "considered": 0, "merge_sha": merge_sha, "skipped": True}
    rc, subj, _ = _git(repo, "log", "-1", "--format=%s", merge_sha)
    result = analyze(repo, ps[0], ps[1], result_ref=merge_sha)
    result["merge_sha"] = merge_sha
    result["subject"] = subj.strip()
    result["auto_resolved"] = bool(AUTO_SUBJECT.search(subj or ""))
    return result


def audit_range(repo, rev_range, *, auto_only=True):
    """Audit every merge in a commit range. The standing, re-runnable tool.

    auto_only limits the sweep to `(auto-resolved)` subjects, which is the population
    the 6/59 measurement was taken over. Pass False to audit hand-merges too.
    """
    rc, out, err = _git(repo, "rev-list", "--merges", rev_range)
    if rc != 0:
        return {"ok": False, "error": (err or "").strip()[:300], "merges": [],
                "audited": 0, "with_discards": 0, "files": 0}

    merges, audited, with_discards, files, errors = [], 0, 0, 0, []
    for sha in (ln.strip() for ln in out.splitlines()):
        if not sha:
            continue
        res = check_merge_commit(repo, sha)
        if res.get("skipped"):
            continue
        if auto_only and not res.get("auto_resolved"):
            continue
        audited += 1
        if not res["ok"]:
            errors.append({"merge_sha": sha, "error": res["error"]})
        if res["discards"]:
            with_discards += 1
            files += len(res["discards"])
        merges.append(res)

    return {"ok": True, "error": "", "range": rev_range, "merges": merges,
            "audited": audited, "with_discards": with_discards, "files": files,
            "errors": errors}
