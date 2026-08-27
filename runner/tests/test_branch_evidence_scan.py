#!/usr/bin/env python3
"""Checking the tree when the task state claims a dependency is a dead end.

A task row is evidence ABOUT work; the repository is the work. When they
disagree the repository wins, and PHANTOM_UNVERIFIED is that disagreement named
out loud — "marked MERGED but no shipped code found" — recorded once by an audit
and never re-checked. Code lands after audits run.

Observed 2026-08-26: a recovery task was queued to redo
`...-implement-bootstrap-inj` on the strength of its state, while the module,
its 310-line test file and the intake hook were all merged on origin/master.
Redoing it would have duplicated shipped code.

The tests below pin the distinction the scan has to get right: a branch that
LANDED is evidence, a branch that merely EXISTS is not, and a decision somebody
made (SUPERSEDED, CLOSED) is not overturned by a branch at all.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_evidence_scan as scanner  # noqa: E402


def git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result


def make_repo(root):
    os.makedirs(root, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    with open(os.path.join(root, "README"), "w") as handle:
        handle.write("x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", "init")
    return root


def commit_on_branch(repo, branch, filename):
    git(repo, "checkout", "-q", "-b", branch)
    with open(os.path.join(repo, filename), "w") as handle:
        handle.write("work\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--no-verify", "-m", "work on " + branch)
    git(repo, "checkout", "-q", "main")


def task(slug, state="QUEUED", deps=None):
    return {"slug": slug, "state": state, "deps": deps or []}


class TestBranchLanded:
    def test_a_merged_branch_reports_landed(self):
        with tempfile.TemporaryDirectory() as raw_root:
            repo = make_repo(os.path.join(os.path.realpath(raw_root), "repo"))
            commit_on_branch(repo, "agent/shipped", "shipped.txt")
            git(repo, "merge", "-q", "--no-ff", "-m", "merge", "agent/shipped")

            evidence = scanner.branch_landed(repo, "shipped", "main")
            assert evidence is not None
            assert evidence["landed"] is True

    def test_an_unmerged_branch_reports_not_landed(self):
        # Existence is not shipping. Treating it as such is the same mistake in
        # the opposite direction.
        with tempfile.TemporaryDirectory() as raw_root:
            repo = make_repo(os.path.join(os.path.realpath(raw_root), "repo"))
            commit_on_branch(repo, "agent/pending", "pending.txt")

            evidence = scanner.branch_landed(repo, "pending", "main")
            assert evidence is not None
            assert evidence["landed"] is False

    def test_no_branch_at_all_reports_none(self):
        with tempfile.TemporaryDirectory() as raw_root:
            repo = make_repo(os.path.join(os.path.realpath(raw_root), "repo"))
            assert scanner.branch_landed(repo, "never-existed", "main") is None


class TestWhichDepsGetRechecked:
    def test_phantom_unverified_and_quarantined_are_rechecked(self):
        tasks = [
            task("waiter-a", deps=["phantom"]),
            task("waiter-b", deps=["parked"]),
            task("phantom", state="PHANTOM_UNVERIFIED"),
            task("parked", state="QUARANTINED"),
        ]
        assert set(scanner.blocking_deps(tasks)) == {"phantom", "parked"}

    def test_a_decision_somebody_made_is_not_rechecked(self):
        # A branch existing does not overrule "we decided to replace this".
        tasks = [
            task("waiter-a", deps=["replaced"]),
            task("waiter-b", deps=["shut"]),
            task("replaced", state="SUPERSEDED"),
            task("shut", state="CLOSED"),
        ]
        assert scanner.blocking_deps(tasks) == {}

    def test_a_live_or_finished_dep_is_not_rechecked(self):
        tasks = [
            task("waiter-a", deps=["running"]),
            task("waiter-b", deps=["done"]),
            task("running", state="RUNNING"),
            task("done", state="MERGED"),
        ]
        assert scanner.blocking_deps(tasks) == {}

    def test_only_queued_tasks_count_as_blocked(self):
        tasks = [
            task("waiter", state="RUNNING", deps=["phantom"]),
            task("phantom", state="PHANTOM_UNVERIFIED"),
        ]
        assert scanner.blocking_deps(tasks) == {}

    def test_every_dependent_of_one_dep_is_listed(self):
        tasks = [
            task("waiter-a", deps=["phantom"]),
            task("waiter-b", deps=["phantom"]),
            task("phantom", state="PHANTOM_UNVERIFIED"),
        ]
        assert scanner.blocking_deps(tasks)["phantom"] == ["waiter-a", "waiter-b"]

    def test_a_qualified_cross_project_dep_resolves_on_the_bare_slug(self):
        tasks = [
            task("waiter", deps=["beethoven:phantom"]),
            task("phantom", state="PHANTOM_UNVERIFIED"),
        ]
        assert "phantom" in scanner.blocking_deps(tasks)


class TestScan:
    def test_a_shipped_dep_is_separated_from_an_unmerged_one(self):
        with tempfile.TemporaryDirectory() as raw_root:
            repo = make_repo(os.path.join(os.path.realpath(raw_root), "repo"))
            commit_on_branch(repo, "agent/shipped", "shipped.txt")
            git(repo, "merge", "-q", "--no-ff", "-m", "merge", "agent/shipped")
            commit_on_branch(repo, "agent/pending", "pending.txt")

            tasks = [
                task("waiter-a", deps=["shipped"]),
                task("waiter-b", deps=["pending"]),
                task("waiter-c", deps=["nothing"]),
                task("shipped", state="PHANTOM_UNVERIFIED"),
                task("pending", state="PHANTOM_UNVERIFIED"),
                task("nothing", state="QUARANTINED"),
            ]
            result = scanner.scan(repo, base="main", tasks=tasks)

            assert [row["dep"] for row in result["shipped"]] == ["shipped"]
            assert [row["dep"] for row in result["unmerged"]] == ["pending"]
            assert [row["dep"] for row in result["no_branch"]] == ["nothing"]
            assert result["counts"] == {"shipped": 1, "unmerged": 1, "no_branch": 1}

    def test_the_report_names_who_is_blocked(self):
        with tempfile.TemporaryDirectory() as raw_root:
            repo = make_repo(os.path.join(os.path.realpath(raw_root), "repo"))
            commit_on_branch(repo, "agent/shipped", "shipped.txt")
            git(repo, "merge", "-q", "--no-ff", "-m", "merge", "agent/shipped")

            tasks = [
                task("waiter-a", deps=["shipped"]),
                task("waiter-b", deps=["shipped"]),
                task("shipped", state="PHANTOM_UNVERIFIED"),
            ]
            result = scanner.scan(repo, base="main", tasks=tasks)
            assert result["shipped"][0]["blocks"] == ["waiter-a", "waiter-b"]

    def test_nothing_blocked_gives_an_empty_report(self):
        with tempfile.TemporaryDirectory() as raw_root:
            repo = make_repo(os.path.join(os.path.realpath(raw_root), "repo"))
            result = scanner.scan(repo, base="main", tasks=[task("solo")])
            assert result["counts"] == {"shipped": 0, "unmerged": 0, "no_branch": 0}
