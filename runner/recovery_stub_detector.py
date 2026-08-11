#!/usr/bin/env python3
"""Detect recovery-intent stub branches — commits that carry no real work.

Why this exists
---------------
`patch_recovery.regenerate_from_intent()` is a last-resort path: when a branch is
missing and no patch, reflog entry or cache replay can rebuild it, it commits a
placeholder — a single `.recovery-intent-<slug>.txt` holding the slug, the patch
template id, a bag of intent keywords and the base branch — so the slug at least
has a branch again.

That placeholder is a *marker*, not a fix. The merge train, however, cannot tell
it apart from a real one-file change, so it verifies, merges and records the slug
as MERGED. The underlying task is then closed having shipped nothing, and the
audit trail says it shipped.

Audit finding that motivated this module (2026-08-11): the branch
`racefeed/agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2`
is exactly one commit, `c4ecfd53ca7b`, adding four lines to
`.recovery-intent-recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2.txt`
and nothing else. It is an ancestor of `origin/master`. The node-modules install
it was supposed to repair was never touched. A mainline scan across five repos
found the same shape on 630 commits.

What this module does
---------------------
Pure classification over data the caller supplies (commit subject, changed files,
diff). No git calls, no DB, no network — so it is cheap to run inside a gate and
trivial to test. `analyze_branch()` returns a verdict the merge train can act on:
`real`, `stub`, or `mixed` (a stub file rode along with genuine changes; keep the
change, strip the marker).

Fail-soft: every entry point returns a verdict on any input, including None.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Marker file that `patch_recovery.regenerate_from_intent` writes.
STUB_FILE = re.compile(r"(^|/)\.recovery-intent[-.].*\.txt$")
#: Commit subject the same function writes.
STUB_SUBJECT = re.compile(r"^\s*recovery-intent-stub\s*:", re.I)
#: Keys inside the marker file.
STUB_KEYS = ("recovery-intent:", "template:", "intent:", "base:")

VERDICT_REAL = "real"
VERDICT_STUB = "stub"
VERDICT_MIXED = "mixed"
VERDICT_EMPTY = "empty"


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _paths(files):
    out = []
    for f in files or []:
        p = _text(f).strip()
        if p:
            out.append(p)
    return out


def is_stub_path(path):
    """True when `path` is a recovery-intent marker file."""
    return bool(STUB_FILE.search(_text(path).strip()))


def is_stub_subject(subject):
    """True when a commit subject is the recovery-intent-stub subject line."""
    return bool(STUB_SUBJECT.match(_text(subject)))


def is_stub_body(body):
    """True when file contents look like a recovery-intent marker payload.

    Requires the slug key plus at least one other marker key, so an ordinary
    text file that merely mentions "intent:" is not misread as a stub.
    """
    text = _text(body).lower()
    if not text.strip():
        return False
    # Anchor to line starts: "intent:" is a substring of "recovery-intent:", so a
    # plain `in` test double-counts the same line and passes a one-key file.
    lines = [ln.strip() for ln in text.splitlines()]
    if not any(ln.startswith("recovery-intent:") for ln in lines):
        return False
    hit = {k for k in STUB_KEYS for ln in lines if ln.startswith(k)}
    return len(hit) >= 2


def classify_files(files):
    """Split changed paths into (stub_markers, substantive_paths)."""
    paths = _paths(files)
    markers = [p for p in paths if is_stub_path(p)]
    real = [p for p in paths if not is_stub_path(p)]
    return markers, real


def analyze_commit(subject=None, files=None, body=None):
    """Classify a single commit. Returns a verdict dict; never raises."""
    try:
        markers, real = classify_files(files)
        subject_hit = is_stub_subject(subject)
        body_hit = is_stub_body(body)
        if markers and real:
            verdict = VERDICT_MIXED
        elif markers or (subject_hit and not real) or (body_hit and not real):
            # A stub-subject commit whose file list was not captured is still a
            # stub — trusting "no files" here is how these reached mainline.
            verdict = VERDICT_STUB
        elif real:
            verdict = VERDICT_REAL
        else:
            verdict = VERDICT_EMPTY
        # A stub subject over genuinely changed files is still a stub-shaped
        # commit only if the sole change is the marker; otherwise trust files.
        reasons = []
        if markers:
            reasons.append(f"recovery-intent marker file(s): {', '.join(markers[:3])}")
        if subject_hit:
            reasons.append("commit subject is `recovery-intent-stub:`")
        if body_hit:
            reasons.append("file body carries recovery-intent marker keys")
        if verdict == VERDICT_REAL and not reasons:
            reasons.append(f"{len(real)} substantive file(s) changed")
        if verdict == VERDICT_EMPTY:
            reasons.append("no changed files reported")
        return {
            "verdict": verdict,
            "marker_files": markers,
            "substantive_files": real,
            "stub_subject": subject_hit,
            "stub_body": body_hit,
            "reasons": reasons,
        }
    except Exception:
        return {"verdict": VERDICT_EMPTY, "marker_files": [], "substantive_files": [],
                "stub_subject": False, "stub_body": False, "reasons": ["analysis failed"]}


def analyze_branch(commits):
    """Classify a branch from its commits.

    `commits` is an iterable of dicts with optional `subject`, `files`, `body`
    (the shape `git log --name-only` and `git show` naturally produce).

    A branch is `stub` when every non-empty commit on it is a stub, `mixed` when
    stub markers ride alongside real changes, `real` otherwise.
    """
    try:
        results = [analyze_commit(c.get("subject"), c.get("files"), c.get("body"))
                   for c in (commits or []) if isinstance(c, dict)]
        nonempty = [r for r in results if r["verdict"] != VERDICT_EMPTY]
        markers = sorted({p for r in results for p in r["marker_files"]})
        real = sorted({p for r in results for p in r["substantive_files"]})
        if not nonempty:
            verdict = VERDICT_EMPTY
        elif all(r["verdict"] == VERDICT_STUB for r in nonempty):
            verdict = VERDICT_STUB
        elif markers and real:
            verdict = VERDICT_MIXED
        else:
            verdict = VERDICT_REAL
        return {
            "verdict": verdict,
            "commits": len(results),
            "stub_commits": sum(1 for r in results if r["verdict"] == VERDICT_STUB),
            "marker_files": markers,
            "substantive_files": real,
            "mergeable_as_work": verdict in (VERDICT_REAL, VERDICT_MIXED),
            "reason": _branch_reason(verdict, markers, real),
        }
    except Exception:
        return {"verdict": VERDICT_EMPTY, "commits": 0, "stub_commits": 0,
                "marker_files": [], "substantive_files": [],
                "mergeable_as_work": False, "reason": "analysis failed"}


def _branch_reason(verdict, markers, real):
    if verdict == VERDICT_STUB:
        return ("every commit only adds a recovery-intent marker "
                f"({', '.join(markers[:2]) or 'no files'}); no work was done — "
                "do not record this slug as MERGED")
    if verdict == VERDICT_MIXED:
        return (f"{len(real)} substantive file(s) plus {len(markers)} leftover recovery-intent "
                "marker(s); merge the work and strip the marker")
    if verdict == VERDICT_EMPTY:
        return "no commits with changed files"
    return f"{len(real)} substantive file(s) changed; no recovery-intent markers"


def cleanup_paths(files):
    """Marker files safe to delete from a working tree before merge."""
    return classify_files(files)[0]


def gate(commits):
    """Merge-train gate. Returns (allow: bool, reason: str).

    Blocks a branch whose only content is a recovery-intent marker, so the slug
    stays open for a real implementation instead of closing as shipped.
    """
    result = analyze_branch(commits)
    return result["mergeable_as_work"], result["reason"]


def parse_git_log(stream_text, sentinel="\x00"):
    """Parse `git log --format='<sentinel>%s' --name-only` output into commits.

    A sentinel is required because git emits a blank line between the subject and
    the file list, so blank-line splitting silently drops every file name.
    """
    commits = []
    for chunk in _text(stream_text).split(sentinel):
        lines = [ln.rstrip() for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        commits.append({"subject": lines[0], "files": lines[1:]})
    return commits


if __name__ == "__main__":
    # Usage:
    #   git log --format='%x00%s' --name-only <base>..<head> | python3 recovery_stub_detector.py
    out = analyze_branch(parse_git_log(sys.stdin.read()))
    print(f"{out['verdict']}: {out['reason']}")
    sys.exit(0 if out["mergeable_as_work"] else 1)
