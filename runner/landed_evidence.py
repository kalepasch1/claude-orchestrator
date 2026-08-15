#!/usr/bin/env python3
"""landed_evidence.py — the ONE sound answer to "did this task's code actually land?"

WHY THIS MODULE EXISTS (2026-08-04, cowork forensic audit)
---------------------------------------------------------
A full-history audit of all 13,816 tasks marked MERGED found 10,584 (76.6%) with no
real code anywhere in the target repo. One of the three mechanisms was a *self-certifying
loop*: an agent's branch is GC'd before promotion -> a recovery task files a placeholder
`recovery-intent-stub: <slug>` commit -> a sweeper greps `git log` for the slug to decide
"did this land?" -> it matches its own stub -> the original task closes MERGED with no code.

A first fix filtered out lines containing "recovery-intent". Re-probing the FIXED code
against 400 slugs proven phantom by tree-level git ground truth, it STILL certified 117 of
them (29.2%), because grep-for-a-slug is unsound in three separate ways:

  1. SCAFFOLDING.  `agent: recover-missing-branch-<slug>-slice-1` and
     `Merge branch 'agent/recover-missing-branch-<slug>'` both mention <slug> and contain
     neither the word "recovery-intent" nor any of the work. The recovery attempt
     certifies the thing it was created to recover.
  2. SUBSTRING COLLISION.  The needle was truncated to 48 chars, so every slug >= 48 chars
     was matched by PREFIX. 5,900 of the MERGED slugs share a 48-char prefix with a
     sibling slice, so slice-1 landing certified slice-2..N as merged. Sibling slices
     certified each other.
  3. EMPTY COMMITS.  A commit that mentions the slug but changes nothing (an empty merge,
     a stub, a revert-of-a-revert) counted as evidence.

The sound predicate is: a commit that (a) names this slug at a token boundary, (b) is not
recovery scaffolding, and (c) actually changes the tree relative to its first parent.

It returns the EVIDENCE (a sha), not just a bool. Callers must persist that sha on the
task. A task moved to MERGED without a sha is, by construction, a phantom — which is
exactly what `merge_reconciliation.py` now alerts on.
"""
import os
import re
import subprocess

# Placeholder commits that NAME a slug at a token boundary while carrying none of its code.
#
# Deliberately narrow. It only needs to cover the `recovery-intent-stub: <slug>` shape,
# where the original slug really does appear at a boundary. The other scaffolding shapes
# (`Merge branch 'agent/recover-missing-branch-<slug>'`, `agent: rework-missing-branch-<slug>`)
# are already rejected by boundary matching, because there the slug is preceded by '-' and
# is therefore part of a DIFFERENT, longer slug.
#
# Keeping it narrow matters: a recovery task whose own slug legitimately begins with
# `recover-missing-branch-` can and does deliver real code, and a broad pattern silently
# discarded that evidence. Measured on 150 sampled merges proven real by tree-level git
# ground truth: 79.3% recall with the broad pattern, 100% with this narrow one — while
# false-certification of 400 proven-phantom slugs stays at 0%. Rejecting real merges would
# re-create the same phantom problem from the other direction.
SCAFFOLD_RE = re.compile(r"recovery-intent|placeholder commit|intent stub", re.I)

DEFAULT_TARGET_ENV = ("ORCH_STAGING_BRANCH", "ORCH_CODE_MERGE_TARGET")


def _git(repo, *args, timeout=90):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def exact_slug_re(slug):
    """Match *slug* only at a token boundary.

    Rejects `recover-missing-branch-<slug>` (preceded by '-') and `<slug>-slice-2`
    (followed by '-'), which are DIFFERENT tasks, while accepting `agent/<slug>`,
    `'<slug>'`, `<slug>:` and bare `<slug>`.
    """
    return re.compile(r"(?<![A-Za-z0-9._-])" + re.escape(slug) + r"(?![A-Za-z0-9._-])")


def target_refs(repo, extra=()):
    """Integration refs, most-canonical first. Only refs that exist are returned."""
    names = [os.environ.get(e) for e in DEFAULT_TARGET_ENV]
    names += ["orchestrator/dev", "dev", "main", "master"]
    names += list(extra or ())
    out, seen = [], set()
    for n in names:
        if not n or n in seen:
            continue
        seen.add(n)
        for ref in (f"origin/{n}", n):
            if ref in seen:
                continue
            seen.add(ref)
            if _git(repo, "rev-parse", "--verify", "--quiet", ref).returncode == 0:
                out.append(ref)
    return out


def _changes_tree(repo, sha, parents):
    """True when this commit's tree differs from its first parent's.

    Uses tree OIDs rather than a diff so merges are handled correctly and cheaply:
    a merge whose tree equals its first parent's brought in nothing.
    """
    if not parents:
        return True  # root commit
    a = _git(repo, "rev-parse", f"{sha}^{{tree}}").stdout.strip()
    b = _git(repo, "rev-parse", f"{parents[0]}^{{tree}}").stdout.strip()
    return bool(a) and bool(b) and a != b


def find_evidence(repo, slug, refs=None, max_scan=20000):
    """Return (sha, ref, subject) for a commit that genuinely delivers *slug*, else None.

    Sound by construction: boundary-exact slug reference, not recovery scaffolding, and
    actually changes the tree. Never truncates the slug.
    """
    if not repo or not slug or not os.path.isdir(repo):
        return None
    pat = exact_slug_re(slug)
    for ref in (refs if refs is not None else target_refs(repo)):
        try:
            # --grep is only a cheap PRE-FILTER; the authoritative test is `pat` below.
            # --fixed-strings so slugs are never read as regex.
            g = _git(repo, "log", f"-{max_scan}", "--fixed-strings", "--grep", slug,
                     "--format=%H%x02%P%x02%s%x02%B%x03", ref)
        except Exception:
            continue
        if g.returncode != 0 or not g.stdout.strip():
            continue
        for rec in g.stdout.split("\x03"):
            rec = rec.strip("\n")
            if not rec.strip():
                continue
            parts = rec.split("\x02", 3)
            if len(parts) < 4:
                continue
            sha, parents, subject, body = parts
            if SCAFFOLD_RE.search(body):
                continue
            if not pat.search(body):
                continue
            if not _changes_tree(repo, sha, parents.split()):
                continue
            return (sha, ref, subject.strip())
    return None


def has_landed(repo, slug, refs=None):
    """Boolean form. Prefer find_evidence() so the sha can be persisted on the task."""
    return find_evidence(repo, slug, refs=refs) is not None
