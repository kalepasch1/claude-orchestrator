"""intent_classifier.py — decide WHAT HAPPENED to a stranded change, with evidence.

## Scope of this module (read this before extending it)

The parent task asked for a full standing `recovery_engine.py` plus a tenth ledger. That
was blocked, correctly, on 2026-08-06: `runner/` already carries ELEVEN overlapping
recovery/ledger modules totalling ~3,100 lines (backlog_recovery, branch_fleet_recovery,
branch_recovery, branch_recovery_periodic, branch_recovery_tasks, db_recovery_sprint,
patch_recovery, phantom_recovery, stale_backlog_recovery, improvement_ledger,
merge_truth). Adding a twelfth engine blind would compound the sprawl that IS the
underlying defect, and deciding which of the eleven a new engine SUBSUMES is an operator
scope decision, not something to settle inside an unsupervised batch loop.

So this module implements only the part that is genuinely missing and genuinely additive:
**the four-way intent-first classification**, as a pure, observe-only function.

    IT DOES:      answer "what happened to this change, and what is the evidence"
    IT DOES NOT:  mutate task state, write a ledger, rebase, merge, push, or re-apply a
                  diff. It has no database import and no write path of any kind.

That boundary is deliberate. The census in the originating task attributes 10,598 phantom
merges to unsupervised bulk automation; the prompt itself specifies "observe-only mode
first". A classifier that only reports is safe to land now and is the prerequisite for any
engine an operator later authorises.

## Why classification must come before re-application

A branch cut in July may patch a function that has since been rewritten. Force-applying
that diff either conflicts or — the dangerous case — silently reverts newer work. That is
not hypothetical: auto-resolve already discarded branch-original edits in 6 of 59 merges.
The diff is *evidence* of intent, never the intent itself.

## The four verdicts

    ALREADY_SATISFIED     current prod already achieves the intent. Close it with the
                          evidence. Do NOT re-apply. Expected to be the common case, and
                          closing these cleanly is a success, not a failure.
    UNCHANGED_CONTEXT     nothing the branch touched has moved on prod. A rebase is
                          meaningful; route through the normal gates.
    CONTEXT_MOVED         the touched code has changed underneath. RE-IMPLEMENT the intent
                          against current prod. Do not port the stale diff.
    SUPERSEDED_OR_UNSAFE  quarantined/superseded, or re-applying would revert newer work.
                          Route to the operator with the conflict named. Never silently
                          reverse a prior decision.

    UNCLASSIFIABLE        git could not answer (missing repo, bad ref, timeout). Route to
                          the operator. Ambiguity is NEVER resolved by guessing — the same
                          three-valued discipline merge_truth.py uses for infra_error.

Reachability ("is this commit really on prod") is delegated to `merge_truth`, which already
owns that question. It is not reimplemented here.

## Operator use

    python3 runner/intent_classifier.py --repo /path/to/repo --branch agent/foo
    python3 runner/intent_classifier.py --repo /path/to/repo --branch agent/foo --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Verdicts
ALREADY_SATISFIED = "ALREADY_SATISFIED"
UNCHANGED_CONTEXT = "UNCHANGED_CONTEXT"
CONTEXT_MOVED = "CONTEXT_MOVED"
SUPERSEDED_OR_UNSAFE = "SUPERSEDED_OR_UNSAFE"
UNCLASSIFIABLE = "UNCLASSIFIABLE"

VERDICTS = (
    ALREADY_SATISFIED,
    UNCHANGED_CONTEXT,
    CONTEXT_MOVED,
    SUPERSEDED_OR_UNSAFE,
    UNCLASSIFIABLE,
)

# Task states that encode a decision a human or an earlier gate already made. Re-applying
# their code would silently reverse that decision, so they never reach the git analysis.
DECIDED_STATES = frozenset({"QUARANTINED", "SUPERSEDED", "ABANDONED", "REJECTED"})

_GIT_TIMEOUT_S = int(os.environ.get("ORCH_INTENT_GIT_TIMEOUT_S", "30") or 30)

# Generated, vendored and binary paths are excluded from "what did this branch touch".
# Including them is what produced the indefensible ~1.18M-line figure for the stranded set;
# a careful exclusion pass over the same branches gave 39,602 real source lines. Any number
# published from this module must use this filter and say so.
EXCLUDED_PATH_PARTS = (
    "node_modules/", "vendor/", "dist/", "build/", ".nuxt/", ".next/", "coverage/",
    "__pycache__/", ".venv/", "venv/", "site-packages/", ".git/",
)
EXCLUDED_SUFFIXES = (
    ".lock", ".min.js", ".min.css", ".map", ".pyc", ".so", ".dylib", ".dll", ".exe",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar", ".woff",
    ".woff2", ".ttf", ".eot", ".mp4", ".mov", ".wasm",
)
EXCLUDED_BASENAMES = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock",
    "composer.lock", "Gemfile.lock",
)


def is_source_path(path: str) -> bool:
    """Is this a real source file, as opposed to generated/vendored/binary noise?"""
    if not path:
        return False
    p = path.replace("\\", "/")
    if any(part in p for part in EXCLUDED_PATH_PARTS):
        return False
    if os.path.basename(p) in EXCLUDED_BASENAMES:
        return False
    return not p.endswith(EXCLUDED_SUFFIXES)


@dataclass
class Classification:
    """A verdict plus the evidence that justifies it.

    `evidence` is required to be non-empty for every verdict. An operator must be able to
    ask "what happened to improvement X" and get a straight answer, not a label.
    """
    verdict: str
    reason: str
    branch: str = ""
    prod_ref: str = ""
    merge_base: str = ""
    touched_files: list = field(default_factory=list)
    moved_files: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def needs_operator(self) -> bool:
        return self.verdict in (SUPERSEDED_OR_UNSAFE, UNCLASSIFIABLE)

    @property
    def should_reapply(self) -> bool:
        """Only UNCHANGED_CONTEXT may have its diff rebased. CONTEXT_MOVED must be
        re-implemented, and the other three must not be applied at all."""
        return self.verdict == UNCHANGED_CONTEXT

    def to_dict(self) -> dict:
        d = asdict(self)
        d["needs_operator"] = self.needs_operator
        d["should_reapply"] = self.should_reapply
        return d


def _git(repo, *args, timeout=None):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          timeout=timeout or _GIT_TIMEOUT_S)


def _git_ok(repo, *args):
    """Run git; return (stdout, None) or (None, error-string). Never raises."""
    try:
        r = _git(repo, *args)
    except subprocess.TimeoutExpired:
        return None, f"git {' '.join(args[:2])} timed out after {_GIT_TIMEOUT_S}s"
    except OSError as exc:
        return None, f"git {' '.join(args[:2])} failed: {exc}"
    if r.returncode:
        return None, f"git {' '.join(args[:2])} failed: {(r.stderr or '').strip()[-200:]}"
    return r.stdout, None


def _rev_parse(repo, ref):
    out, err = _git_ok(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if err:
        return None, f"{ref} does not resolve in {repo}"
    return out.strip(), None


def _resolve_prod_ref(repo, prod_branch):
    """Prefer origin/<prod_branch>, fall back to the local ref. Mirrors merge_truth."""
    for ref in (f"origin/{prod_branch}", prod_branch):
        sha, err = _rev_parse(repo, ref)
        if not err:
            return ref, sha, None
    return None, None, f"neither origin/{prod_branch} nor {prod_branch} resolves in {repo}"


def _changed_files(repo, frm, to):
    out, err = _git_ok(repo, "diff", "--name-only", f"{frm}..{to}")
    if err:
        return None, err
    return [f for f in (out or "").splitlines() if f.strip() and is_source_path(f)], None


def _is_ancestor(repo, sha, ref):
    """True if sha is reachable from ref. Returns (bool, err); err means 'cannot tell'."""
    try:
        r = _git(repo, "merge-base", "--is-ancestor", sha, ref)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"merge-base --is-ancestor failed: {exc}"
    if r.returncode == 0:
        return True, None
    if r.returncode == 1:
        return False, None
    return None, f"merge-base --is-ancestor errored: {(r.stderr or '').strip()[-200:]}"


def would_revert_newer_work(repo, branch, prod_branch="master"):
    """Would re-applying `branch` discard commits made on prod after the branch was cut?

    This is the auto-resolve defect, enforced. If prod has moved on in a file the branch
    also edits, a blind re-apply of the branch's version of that file reverts the newer
    edit. Returns (bool|None, list_of_files, err). None means "cannot tell".
    """
    prod_ref, _, err = _resolve_prod_ref(repo, prod_branch)
    if err:
        return None, [], err
    base, err = _git_ok(repo, "merge-base", branch, prod_ref)
    if err:
        return None, [], err
    base = base.strip()

    branch_files, err = _changed_files(repo, base, branch)
    if err:
        return None, [], err
    prod_files, err = _changed_files(repo, base, prod_ref)
    if err:
        return None, [], err

    overlap = sorted(set(branch_files) & set(prod_files))
    return bool(overlap), overlap, None


def classify(repo, branch, prod_branch="master", task_state=None, task_slug=None):
    """Classify one stranded change. Pure: reads git, mutates nothing.

    Order matters. A decided state is checked first so that a QUARANTINED or SUPERSEDED
    item can never be resurrected by a git heuristic.
    """
    slug = task_slug or branch

    if task_state and str(task_state).upper() in DECIDED_STATES:
        return Classification(
            verdict=SUPERSEDED_OR_UNSAFE, branch=branch,
            reason=(f"task state {task_state} records a decision already taken; "
                    f"re-applying would silently reverse it"),
            evidence={"task_state": task_state, "slug": slug, "checked": "task_state"},
        )

    if not os.path.isdir(repo):
        return Classification(
            verdict=UNCLASSIFIABLE, branch=branch,
            reason=f"repo path does not exist: {repo}",
            evidence={"repo": repo, "slug": slug},
        )

    branch_sha, err = _rev_parse(repo, branch)
    if err:
        return Classification(
            verdict=UNCLASSIFIABLE, branch=branch,
            reason=f"branch does not resolve: {err}",
            evidence={"repo": repo, "slug": slug, "git_error": err},
        )

    prod_ref, prod_sha, err = _resolve_prod_ref(repo, prod_branch)
    if err:
        return Classification(
            verdict=UNCLASSIFIABLE, branch=branch,
            reason=f"production branch unresolvable: {err}",
            evidence={"repo": repo, "slug": slug, "git_error": err},
        )

    # 1. Is the branch already reachable from prod? Then the intent landed.
    reachable, err = _is_ancestor(repo, branch_sha, prod_ref)
    if err:
        return Classification(
            verdict=UNCLASSIFIABLE, branch=branch, prod_ref=prod_ref,
            reason=f"cannot determine reachability: {err}",
            evidence={"repo": repo, "slug": slug, "git_error": err},
        )
    if reachable:
        return Classification(
            verdict=ALREADY_SATISFIED, branch=branch, prod_ref=prod_ref,
            reason=f"{branch_sha[:12]} is an ancestor of {prod_ref}; the change is on prod",
            evidence={"branch_sha": branch_sha, "prod_sha": prod_sha,
                      "check": "merge-base --is-ancestor", "slug": slug},
        )

    base, err = _git_ok(repo, "merge-base", branch, prod_ref)
    if err:
        return Classification(
            verdict=UNCLASSIFIABLE, branch=branch, prod_ref=prod_ref,
            reason=f"no merge-base between {branch} and {prod_ref}: {err}",
            evidence={"repo": repo, "slug": slug, "git_error": err},
        )
    base = base.strip()

    branch_files, err = _changed_files(repo, base, branch)
    if err:
        return Classification(
            verdict=UNCLASSIFIABLE, branch=branch, prod_ref=prod_ref, merge_base=base,
            reason=f"cannot diff branch against merge-base: {err}",
            evidence={"repo": repo, "slug": slug, "git_error": err},
        )

    # 2. The branch exists but changes no source file: nothing to recover.
    if not branch_files:
        return Classification(
            verdict=ALREADY_SATISFIED, branch=branch, prod_ref=prod_ref, merge_base=base,
            reason=("branch changes no source files once generated/vendored/binary paths "
                    "are excluded; there is nothing to re-apply"),
            evidence={"branch_sha": branch_sha, "prod_sha": prod_sha,
                      "filter": "is_source_path", "slug": slug},
        )

    prod_files, err = _changed_files(repo, base, prod_ref)
    if err:
        return Classification(
            verdict=UNCLASSIFIABLE, branch=branch, prod_ref=prod_ref, merge_base=base,
            reason=f"cannot diff prod against merge-base: {err}",
            evidence={"repo": repo, "slug": slug, "git_error": err},
        )

    moved = sorted(set(branch_files) & set(prod_files))

    # 3. Prod moved under files this branch edits. Re-applying reverts newer work — the
    #    exact defect auto-resolve already committed. Never rebase these silently.
    if moved:
        return Classification(
            verdict=CONTEXT_MOVED, branch=branch, prod_ref=prod_ref, merge_base=base,
            touched_files=branch_files, moved_files=moved,
            reason=(f"{len(moved)} of {len(branch_files)} touched file(s) changed on "
                    f"{prod_ref} since {base[:12]}; the stale diff must not be ported — "
                    f"re-implement the intent against current prod"),
            evidence={"branch_sha": branch_sha, "prod_sha": prod_sha,
                      "moved_files": moved, "slug": slug,
                      "would_revert_newer_work": True},
        )

    # 4. Context is intact. A rebase is meaningful; normal gates still apply.
    return Classification(
        verdict=UNCHANGED_CONTEXT, branch=branch, prod_ref=prod_ref, merge_base=base,
        touched_files=branch_files,
        reason=(f"none of the {len(branch_files)} touched file(s) changed on {prod_ref} "
                f"since {base[:12]}; rebase is safe to attempt through the normal gates"),
        evidence={"branch_sha": branch_sha, "prod_sha": prod_sha, "slug": slug},
    )


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Classify a stranded branch against current prod. Read-only.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--prod-branch", default="master")
    ap.add_argument("--task-state", default=None)
    ap.add_argument("--task-slug", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    c = classify(args.repo, args.branch, args.prod_branch, args.task_state, args.task_slug)

    if args.json:
        print(json.dumps(c.to_dict(), indent=2))
    else:
        print(f"{c.verdict}: {c.reason}")
        if c.moved_files:
            print(f"  moved: {', '.join(c.moved_files[:20])}")
        if c.needs_operator:
            print("  -> routes to operator; not auto-recoverable")
    return 0 if c.verdict != UNCLASSIFIABLE else 2


if __name__ == "__main__":
    sys.exit(main())
