#!/usr/bin/env python3
"""Reproducible stash triage (audit addendum §D).

The 315-stash triage on Mac 1 was hand-computed once, and recover_stashes.sh then hardcoded
the twelve recoverable ones as POSITIONAL refs (stash@{2}, stash@{37}, ... stash@{259}).
stash@{N} indexes the reflog, so dropping or creating any stash renumbers everything after it
— re-running that script against a shifted list silently recovers a different set than the
triage vetted. These tests pin the classification and pin that results are addressed by SHA.

Real throwaway git repos throughout: the questions are all "does this patch apply to HEAD",
and a mock would only test the mock.
"""
import os
import subprocess
import tempfile
import unittest

import stash_triage as st


def _run(*args, cwd, check=True):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=check)


def _write(repo, name, content):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(content)


def _commit(repo, msg):
    _run("git", "add", "-A", cwd=repo)
    _run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg, cwd=repo)


class _StashRepo(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "r")
        os.makedirs(self.repo)
        _run("git", "init", "-q", "-b", "master", cwd=self.repo)
        _write(self.repo, "a.txt", "base\n")
        _commit(self.repo, "base")

    def _stash(self, msg="wip"):
        _run("git", "stash", "push", "-q", "-m", msg, cwd=self.repo)


class TestClassification(_StashRepo):

    def test_recoverable_stash_applies_cleanly(self):
        _write(self.repo, "a.txt", "base\nnew work\n")
        self._stash()
        rep = st.triage(self.repo)
        self.assertEqual(rep["counts"][st.RECOVERABLE], 1, rep["counts"])
        self.assertEqual(rep["total"], 1)

    def test_already_landed_is_not_reported_as_conflicted(self):
        """The ordering that matters: landed content often fails a forward apply too, and
        calling it conflicted would send finished work back to a human for triage."""
        _write(self.repo, "a.txt", "base\nshipped later\n")
        self._stash()
        # The same content reaches HEAD by another route.
        _write(self.repo, "a.txt", "base\nshipped later\n")
        _commit(self.repo, "landed by another route")

        rep = st.triage(self.repo)
        self.assertEqual(rep["counts"][st.ALREADY_LANDED], 1, rep["counts"])
        self.assertEqual(rep["counts"][st.CONFLICTED], 0)

    def test_conflicted_stash_is_flagged_not_silently_dropped(self):
        _write(self.repo, "a.txt", "base\nstashed edit\n")
        self._stash()
        _write(self.repo, "a.txt", "totally different content\n")
        _commit(self.repo, "file moved on")

        rep = st.triage(self.repo)
        self.assertEqual(rep["counts"][st.CONFLICTED], 1, rep["counts"])
        self.assertEqual(len(rep["conflicted"]), 1)
        self.assertTrue(rep["conflicted"][0]["sha"])

    def test_no_stashes_is_an_empty_report_not_an_error(self):
        rep = st.triage(self.repo)
        self.assertEqual(rep["total"], 0)
        self.assertEqual(rep["counts"][st.CONFLICTED], 0)

    def test_runner_touching_conflicts_are_counted_separately(self):
        """76 of the 120 conflicted touched runner/ — that split drives triage priority."""
        os.makedirs(os.path.join(self.repo, "runner"))
        _write(self.repo, "runner/x.py", "print('v1')\n")
        _commit(self.repo, "add runner file")
        _write(self.repo, "runner/x.py", "print('stashed')\n")
        self._stash()
        _write(self.repo, "runner/x.py", "print('moved on')\n")
        _commit(self.repo, "runner file moved on")

        rep = st.triage(self.repo)
        self.assertEqual(rep["counts"][st.CONFLICTED], 1)
        self.assertEqual(rep["runner_conflicted"], 1)
        self.assertTrue(rep["conflicted"][0]["touches_runner"])


class TestReadOnly(_StashRepo):
    """recover_stashes.sh writes; this decides. It must never mutate anything."""

    def test_triage_leaves_the_stash_list_intact(self):
        for i in range(3):
            _write(self.repo, "a.txt", f"base\nedit {i}\n")
            self._stash(f"wip {i}")
        before = _run("git", "stash", "list", cwd=self.repo).stdout
        head_before = _run("git", "rev-parse", "HEAD", cwd=self.repo).stdout

        st.triage(self.repo)

        self.assertEqual(_run("git", "stash", "list", cwd=self.repo).stdout, before,
                         "triage popped or dropped a stash")
        self.assertEqual(_run("git", "rev-parse", "HEAD", cwd=self.repo).stdout, head_before)

    def test_triage_leaves_the_working_tree_clean(self):
        _write(self.repo, "a.txt", "base\nedit\n")
        self._stash()
        st.triage(self.repo)
        self.assertEqual(_run("git", "status", "--porcelain", cwd=self.repo).stdout, "",
                         "triage applied a patch into the working tree")


class TestStableAddressing(_StashRepo):
    """The bug recover_stashes.sh has: stash@{N} is positional and shifts under a drop."""

    def test_results_are_addressed_by_sha_not_by_index(self):
        _write(self.repo, "a.txt", "base\nkeep me\n")
        self._stash("keep")
        rep = st.triage(self.repo)
        self.assertTrue(rep["recoverable_shas"])
        for sha in rep["recoverable_shas"]:
            self.assertRegex(sha, r"^[0-9a-f]{40}$")

    def test_sha_still_identifies_the_stash_after_the_index_shifts(self):
        """Drop an OLDER stash and stash@{N} renumbers; the SHA does not move."""
        _write(self.repo, "a.txt", "base\nfirst\n")
        self._stash("first")
        _write(self.repo, "a.txt", "base\nsecond\n")
        self._stash("second")

        before = {s["subject"]: s["sha"] for s in st.list_stashes(self.repo)}
        target_subject = [s for s in before if "second" not in s] or list(before)
        # Drop the OLDEST entry, which renumbers the remaining one.
        _run("git", "stash", "drop", "-q", "stash@{1}", cwd=self.repo)
        after = {s["subject"]: s["sha"] for s in st.list_stashes(self.repo)}

        surviving = set(after.values())
        self.assertTrue(surviving)
        # Whatever survived kept its SHA — that identity is what a recovery step must use.
        for subject, sha in after.items():
            self.assertEqual(before.get(subject), sha,
                             "a surviving stash changed identity after a drop")
        self.assertTrue(target_subject)


class TestReportFormatting(_StashRepo):

    def test_report_renders_without_stashes(self):
        text = st.format_report(st.triage(self.repo))
        self.assertIn("total", text)

    def test_report_lists_conflicted_work(self):
        _write(self.repo, "a.txt", "base\nstashed\n")
        self._stash("wip: important")
        _write(self.repo, "a.txt", "different\n")
        _commit(self.repo, "moved on")
        text = st.format_report(st.triage(self.repo))
        self.assertIn("conflicted", text)
        self.assertIn("triage one at a time", text)

    def test_cli_runs_and_emits_json(self):
        import json
        _write(self.repo, "a.txt", "base\nx\n")
        self._stash()
        proc = subprocess.run(
            [os.sys.executable,
             os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(st.__file__))),
                          "runner", "stash_triage.py"),
             "--repo", self.repo, "--json"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        self.assertIn("counts", json.loads(proc.stdout))


class TestFailSoft(_StashRepo):

    def test_non_repo_path_returns_empty_rather_than_raising(self):
        rep = st.triage(self.tmp.name)  # a directory that is not a git repo
        self.assertEqual(rep["total"], 0)


if __name__ == "__main__":
    unittest.main()
