"""
artifact_evidence.py — what makes an artifact_commit *evidence* for a task.

P1 (2026-08-12). `tools/audit_merged_evidence.py` measured that 300 of 1169
MERGED / DEPLOYED_AND_VERIFIED tasks (25.7%) cite an artifact_commit that at
least one other task also cites. 47f26779 — two files changed — is the claimed
artifact of 32 distinct tasks; 4d1367d4 (2 files) of 15; 725b0b40 ("agent: qafix",
222 files) of 26; 54b69ee0 ("Merge all queued improvements", 402 files) of 6.
The commits are real. The *attribution* is not: a two-file commit cannot be the
deliverable of 32 tasks.

This module is the contract that makes the citation checkable. It is pure logic —
no DB, no network, only `git` reads through an injectable runner — so it can be
unit-tested and called from the merge train, the deployment terminal, and the
backfill CLI alike.

Four rules, one per precondition in the filing:

  R1  Only a verifier may set MERGED. `may_set_merged(actor_role, verdict)`
      refuses every executor-class actor outright, and refuses any verdict that
      did not resolve the sha in the target repo and confirm file overlap.
  R2  A citation must name its repo. `parse_citation` accepts the canonical
      "<repo>@<sha>" form and still reads the legacy bare sha, but reports the
      bare form as `repo_known=False` — unverifiable by construction, which is
      what let both earlier audits scope themselves wrong.
  R3  A commit claimed by N>1 tasks is justified for a given task only when the
      commit's changed-file set intersects that task's declared scope. Otherwise
      the commit is an integration commit: it belongs in `integration_commit`,
      and the task stays unverified on its own merits.
  R4  Backfill classifies; it never bulk-updates. `classify_claim` returns a
      verdict and `audit_row` renders the per-change record that must be written
      alongside any state change. An unaudited bulk state change is itself a
      tracked defect in this system.

Fail-soft throughout: an unreadable repo, a missing sha, or a malformed citation
yields an UNRESOLVABLE verdict, never an exception. A verdict that is not
JUSTIFIED never authorises MERGED, so failing to resolve fails closed.
"""

import os
import re
import subprocess

__all__ = [
    "CITATION_SEP", "EXECUTOR_ROLES", "VERIFIER_ROLES",
    "JUSTIFIED", "SOLE_CLAIMANT", "UNATTRIBUTED", "UNRESOLVABLE", "NO_CITATION",
    "parse_citation", "format_citation", "is_sha",
    "commit_files", "commit_exists", "declared_scope", "scope_overlap",
    "classify_claim", "may_set_merged", "audit_row", "is_executor",
]

CITATION_SEP = "@"

# Actor roles. Anything that produced the commit cannot also certify it.
EXECUTOR_ROLES = ("executor", "coder", "agent", "runner", "merge_train", "batch_fusion")
VERIFIER_ROLES = ("verifier", "deployment_terminal", "operator")

JUSTIFIED = "justified"          # sha resolves AND touches the task's declared scope
SOLE_CLAIMANT = "sole_claimant"  # only this task cites the commit, and it resolves
UNATTRIBUTED = "unattributed"    # shared commit, no overlap with this task's scope
UNRESOLVABLE = "unresolvable"    # bad citation, unreadable repo, or absent sha
NO_CITATION = "no_citation"      # artifact_commit empty

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
# Both sides tokenize on every non-alphanumeric boundary, so the slug
# "harden-merge-train-gate" and the path "runner/merge_train.py" agree on
# {merge, train}. Splitting only on hyphens (slug) or only on "/" and "."
# (path) would make those two never intersect.
_WORD_RE = re.compile(r"[a-z0-9]{3,}")

# Paths that overlap with everything and therefore prove nothing.
_GENERIC_PATH_PARTS = frozenset({
    "src", "lib", "app", "test", "tests", "runner", "tools", "server", "utils",
    "index", "main", "init", "__init__", "package", "readme", "docs", "doc",
})


def is_sha(value):
    """True for something shaped like an abbreviated-or-full git sha."""
    return bool(value) and isinstance(value, str) and bool(_SHA_RE.match(value.strip()))


def format_citation(repo, sha):
    """Render the canonical citation. Returns '' rather than a repo-less sha."""
    repo = (repo or "").strip()
    sha = (sha or "").strip()
    if not is_sha(sha):
        return ""
    if not repo:
        return ""
    return "{0}{1}{2}".format(repo, CITATION_SEP, sha)


def parse_citation(value):
    """Split an artifact_commit into (repo, sha, repo_known).

    Canonical: "beethoven@47f26779...". Legacy bare shas still parse, with
    repo_known=False — R2 exists because a bare sha cannot be probed against the
    right repo, and probing it against the wrong one is how the earlier audits
    reported phantom commits.
    """
    if not isinstance(value, str):
        return ("", "", False)
    text = value.strip()
    if not text:
        return ("", "", False)
    if CITATION_SEP in text:
        repo, _, sha = text.partition(CITATION_SEP)
        repo, sha = repo.strip(), sha.strip()
        if is_sha(sha):
            return (repo, sha, bool(repo))
        return ("", "", False)
    if is_sha(text):
        return ("", text, False)
    return ("", "", False)


def _git(repo_path, *args, **kwargs):
    runner = kwargs.get("runner")
    argv = ["git", "-C", repo_path] + list(args)
    if runner is not None:
        return runner(argv)
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except Exception:
        return None


def commit_exists(repo_path, sha, runner=None):
    """True only when the sha resolves to a commit object in THIS repo."""
    if not repo_path or not is_sha(sha) or not os.path.isdir(repo_path):
        if runner is None:
            return False
    result = _git(repo_path, "cat-file", "-e", "{0}^{{commit}}".format(sha), runner=runner)
    return bool(result) and getattr(result, "returncode", 1) == 0


def commit_files(repo_path, sha, runner=None):
    """Changed-file paths for a commit; empty tuple when unresolvable."""
    if not is_sha(sha):
        return ()
    result = _git(repo_path, "show", "--name-only", "--format=", sha, runner=runner)
    if not result or getattr(result, "returncode", 1) != 0:
        return ()
    out = getattr(result, "stdout", "") or ""
    return tuple(line.strip() for line in out.splitlines() if line.strip())


def declared_scope(task):
    """Path-ish and word-ish tokens a task declared it would touch.

    Drawn from slug, prompt and artifact_branch — the only scope signals the
    schema carries today. Generic tokens ('src', 'test', 'index') are dropped:
    they match every commit and would launder an integration commit into a
    justified one.
    """
    if not isinstance(task, dict):
        return frozenset()
    blob = " ".join(str(task.get(k) or "") for k in ("slug", "artifact_branch", "prompt"))
    tokens = set()
    for word in _WORD_RE.findall(blob.lower()):
        if word in _GENERIC_PATH_PARTS or word.isdigit():
            continue
        tokens.add(word)
    return frozenset(tokens)


def _path_tokens(path):
    tokens = set()
    for part in re.split(r"[/\\]", (path or "").lower()):
        part = part.strip()
        if not part:
            continue
        stem = part.rsplit(".", 1)[0] if "." in part else part
        # The whole stem ("merge_train") plus its pieces ("merge", "train") —
        # a slug may name either.
        for word in [stem] + _WORD_RE.findall(stem):
            if word in _GENERIC_PATH_PARTS or word.isdigit() or len(word) < 3:
                continue
            tokens.add(word)
    return tokens


def scope_overlap(changed_paths, scope):
    """Changed paths whose tokens intersect the task's declared scope."""
    if not changed_paths or not scope:
        return ()
    hits = []
    for path in changed_paths:
        if _path_tokens(path) & set(scope):
            hits.append(path)
    return tuple(hits)


def classify_claim(task, repo_path, claim_count=1, runner=None):
    """Classify one task's artifact_commit claim. Never raises.

    Returns a dict: verdict, sha, repo, repo_known, claim_count, changed_files,
    matched_files, detail. `claim_count` is how many tasks cite this same commit.
    """
    if not isinstance(task, dict):
        task = {}
    repo, sha, repo_known = parse_citation(task.get("artifact_commit"))
    verdict = {
        "slug": task.get("slug") or "",
        "task_id": task.get("id") or "",
        "sha": sha,
        "repo": repo,
        "repo_known": repo_known,
        "claim_count": int(claim_count or 1),
        "changed_files": (),
        "matched_files": (),
        "verdict": UNRESOLVABLE,
        "detail": "",
    }
    if not (task or {}).get("artifact_commit"):
        verdict["verdict"] = NO_CITATION
        verdict["detail"] = "task cites no artifact_commit"
        return verdict
    if not sha:
        verdict["detail"] = "artifact_commit is not a parseable citation"
        return verdict
    if not commit_exists(repo_path, sha, runner=runner):
        verdict["detail"] = "sha does not resolve to a commit in {0}".format(
            repo_path or "<no repo path>")
        return verdict

    files = commit_files(repo_path, sha, runner=runner)
    verdict["changed_files"] = files
    if verdict["claim_count"] <= 1:
        verdict["verdict"] = SOLE_CLAIMANT
        verdict["detail"] = "only claimant of a commit that resolves in its own repo"
        return verdict

    matched = scope_overlap(files, declared_scope(task))
    verdict["matched_files"] = matched
    if matched:
        verdict["verdict"] = JUSTIFIED
        verdict["detail"] = ("shared commit ({0} claimants) but touches {1} file(s) "
                             "in this task's declared scope").format(
                                 verdict["claim_count"], len(matched))
    else:
        verdict["verdict"] = UNATTRIBUTED
        verdict["detail"] = ("shared commit ({0} claimants) with no changed file in this "
                             "task's declared scope — record it as integration_commit and "
                             "leave the task unverified on its own merits").format(
                                 verdict["claim_count"])
    return verdict


def is_executor(actor_role):
    role = (actor_role or "").strip().lower()
    return any(role == r or role.startswith(r) for r in EXECUTOR_ROLES)


def may_set_merged(actor_role, verdict):
    """R1 gate. Returns (allowed, reason). Fails closed on anything unexpected."""
    role = (actor_role or "").strip().lower()
    if not role:
        return False, "no actor role supplied; MERGED requires an identified verifier"
    if is_executor(role):
        return False, ("actor '{0}' is an executor; an executor may not certify its own "
                       "work as MERGED (P1 R1)".format(role))
    if not any(role == r or role.startswith(r) for r in VERIFIER_ROLES):
        return False, "actor '{0}' is not a recognised verifier role".format(role)
    if not isinstance(verdict, dict):
        return False, "no evidence verdict supplied"
    name = verdict.get("verdict")
    if name == JUSTIFIED:
        return True, "sha resolves in the target repo and touches the task's declared scope"
    if name == SOLE_CLAIMANT:
        return True, "sha resolves in the target repo and no other task claims it"
    return False, "evidence verdict is '{0}': {1}".format(name, verdict.get("detail") or "")


def audit_row(verdict, actor_role, action, previous_state=None, new_state=None):
    """The record that MUST accompany any state change made from a verdict (R4)."""
    verdict = verdict if isinstance(verdict, dict) else {}
    return {
        "task_id": verdict.get("task_id") or "",
        "slug": verdict.get("slug") or "",
        "repo": verdict.get("repo") or "",
        "sha": verdict.get("sha") or "",
        "repo_known": bool(verdict.get("repo_known")),
        "claim_count": int(verdict.get("claim_count") or 0),
        "verdict": verdict.get("verdict") or UNRESOLVABLE,
        "detail": verdict.get("detail") or "",
        "matched_files": list(verdict.get("matched_files") or ()),
        "changed_file_count": len(verdict.get("changed_files") or ()),
        "actor_role": (actor_role or "").strip().lower(),
        "action": action,
        "previous_state": previous_state,
        "new_state": new_state,
    }
