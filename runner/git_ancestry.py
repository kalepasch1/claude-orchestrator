#!/usr/bin/env python3
"""
git_ancestry.py — "is this commit actually in that release?", answered by git.

WHY
---
canonical_proof_ledger._live_release_for() looked for a release whose head IS the
task's artifact commit. That is right for a fleet that deploys branch heads, and
wrong for every repo that merges to a trunk and deploys the trunk.

smarter is the second kind. Measured 2026-08-23, after 419 real production
releases had been reconciled into the table: SIX task artifacts in the entire
history matched a live release by sha. Not six percent — six rows. Every other
MERGED task stopped at LEVEL_MERGED with "no release names this artifact commit
as its head", which was true, and useless: the work was in production, inside a
merge commit that necessarily has a different sha.

The right question is containment, and git already answers it exactly:

    git merge-base --is-ancestor <artifact> <release-head>

WHAT CONTAINMENT DOES AND DOES NOT PROVE
----------------------------------------
It proves the commit is reachable from the deployed head — the change was
integrated and shipped. It does NOT prove the behaviour survived: a commit can be
an ancestor of a release that later reverted it, and ancestry cannot see that.

That gap is exactly the one the ledger is already built to cover. Containment
establishes LEVEL_RELEASED — the code is out there. DEPLOYED_AND_VERIFIED
additionally requires a passing production journey, which exercises the behaviour
and fails if it was reverted. So this widens the level that describes
integration, and touches nothing about the level that describes delivery.

FAIL-CLOSED, EVERYWHERE
-----------------------
contains() returns True, False, or None, and None is not False. A missing object,
an unknown repo, a git error or an exhausted budget all yield None — "we could
not check" — and callers must not read that as containment. Answering False on a
failed check would be the more dangerous mistake in the other direction: it would
render an outage as an absence of shipped work.

BOUNDED
-------
Ancestry over thousands of artifacts against hundreds of releases is a lot of
subprocesses. Answers are memoised per (repo, head, candidate), object existence
is memoised per (repo, sha), and a hard call ceiling stops a pathological
projection from spinning. Past the ceiling every answer is None.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Total `git` invocations one oracle may make. Generous for a real projection,
#: finite for a broken one.
DEFAULT_CALL_CEILING = int(os.environ.get("ORCH_ANCESTRY_CALL_CEILING", "4000"))
#: Per-call timeout. An ancestry query on a warm repo is milliseconds; anything
#: near this is a repo problem, and a hung projection helps nobody.
DEFAULT_TIMEOUT_S = float(os.environ.get("ORCH_ANCESTRY_TIMEOUT_S", "10"))

UNKNOWN = None


def _norm(sha):
    return (str(sha) if sha is not None else "").strip().lower()


def _run_git(repo, args, timeout=DEFAULT_TIMEOUT_S):
    """(returncode, stdout) or (None, "") when git could not be run at all."""
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return None, ""


class AncestryOracle:
    """Answers containment questions against local clones, with a call budget.

    `repo_for` maps an orchestrator project name to a checkout path, and may
    return None for a project with no clone here — which yields UNKNOWN rather
    than a guess.
    """

    def __init__(self, repo_for, call_ceiling=DEFAULT_CALL_CEILING,
                 timeout=DEFAULT_TIMEOUT_S, run=None):
        self._repo_for = repo_for if callable(repo_for) else (lambda p: repo_for)
        self._ceiling = max(0, int(call_ceiling))
        self._timeout = timeout
        self._run = run or _run_git
        self._answers = {}
        self._present = {}
        self.calls = 0
        self.exhausted = False

    # ------------------------------------------------------------------ budget

    def _spend(self):
        if self.calls >= self._ceiling:
            self.exhausted = True
            return False
        self.calls += 1
        return True

    # ------------------------------------------------------------------ probes

    def _has_object(self, repo, sha):
        key = (repo, sha)
        if key in self._present:
            return self._present[key]
        if not self._spend():
            return UNKNOWN
        rc, _ = self._run(repo, ["cat-file", "-e", f"{sha}^{{commit}}"], self._timeout)
        # rc None means git itself did not run: unknown, and NOT "absent".
        present = UNKNOWN if rc is None else (rc == 0)
        self._present[key] = present
        return present

    def contains(self, head_sha, candidate_sha, project=None):
        """True if `candidate_sha` is reachable from `head_sha`. None if unknown.

        A commit trivially contains itself; that case is answered without git so
        the common exact match never spends budget.
        """
        head, candidate = _norm(head_sha), _norm(candidate_sha)
        if not head or not candidate:
            return UNKNOWN
        if head == candidate:
            return True

        repo = self._repo_for(project)
        if not repo or not os.path.isdir(os.path.join(str(repo), ".git")):
            return UNKNOWN

        key = (str(repo), head, candidate)
        if key in self._answers:
            return self._answers[key]

        # Both objects must be in THIS clone. A shallow or stale checkout that has
        # never fetched one of them cannot answer, and must say so.
        for sha in (candidate, head):
            present = self._has_object(repo, sha)
            if present is not True:
                self._answers[key] = UNKNOWN
                return UNKNOWN

        if not self._spend():
            self._answers[key] = UNKNOWN
            return UNKNOWN
        rc, _ = self._run(repo, ["merge-base", "--is-ancestor", candidate, head],
                          self._timeout)
        if rc == 0:
            answer = True
        elif rc == 1:
            answer = False
        else:
            # Any other exit -- including git failing to run -- is unknown.
            answer = UNKNOWN
        self._answers[key] = answer
        return answer

    def stats(self):
        return {"calls": self.calls, "ceiling": self._ceiling,
                "exhausted": self.exhausted,
                "cached_answers": len(self._answers)}


def repo_map_from_env(default_root=None):
    """project -> checkout path, from the fleet's usual layout.

    ORCH_REPO_ROOTS overrides, as `project=/path` pairs separated by commas.
    """
    explicit = {}
    for pair in (os.environ.get("ORCH_REPO_ROOTS") or "").split(","):
        if "=" in pair:
            name, path = pair.split("=", 1)
            explicit[name.strip()] = os.path.expanduser(path.strip())

    root = default_root or os.path.expanduser(
        os.environ.get("ORCH_REPO_ROOT", "~/Documents"))

    #: Orchestrator project name -> directory name, where they differ.
    aliases = {"beethoven": "beethoven/claude-orchestrator",
               "madeus": "beethoven/claude-orchestrator",
               "orchestrator": "beethoven/claude-orchestrator"}

    def repo_for(project):
        if not project:
            return None
        if project in explicit:
            return explicit[project]
        candidate = os.path.join(root, aliases.get(project, project))
        return candidate if os.path.isdir(os.path.join(candidate, ".git")) else None

    return repo_for
