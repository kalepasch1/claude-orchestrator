"""The merge train must blame the branch that owns the conflicting hunk.

`git rebase base branch` replays every commit reachable from the branch and not
from base. When a branch merged other agent branches in, that includes their
commits — and a conflict raised while replaying one of THOSE is reported
against whichever branch is currently being rebased.

The train then rebuilt that task and tried again. Three dropbox tasks reached
attempts 61, 36 and 134 on one identical error:

    train: still conflicts after 4 redos - needs manual rebase.
    Conflicting files: packages/darwin-kernel/src/passport/passport.ts.

At least one of them (agent commit ae4f5f7d64) touches exactly one file,
tests/test_lease_night_config_divergence.py. It could never have resolved a
passport.ts conflict; 14 other unmerged agent branches modify that file. Each
redo burned a full agent run to arrive back at the same message.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(repo, *args):
    return subprocess.run(("git", "-C", repo) + args,
                          capture_output=True, text=True, check=True).stdout


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path) or repo, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)
    run(repo, "add", rel)


def commit(repo, message):
    subprocess.run(
        ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "--no-verify", "-m", message],
        check=True, capture_output=True, text=True)


class ConflictAttributionTestCase(unittest.TestCase):
    """Exercises the pure helpers; no DB, no network, no train run."""

    @classmethod
    def setUpClass(cls):
        import merge_train
        cls.mt = merge_train

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        run(self.repo, "init", "-q", "-b", "master")
        write(self.repo, "passport.ts", "export const a = 'base'\n")
        write(self.repo, "unrelated.py", "x = 1\n")
        commit(self.repo, "base")

    def tearDown(self):
        self._tmp.cleanup()

    def test_own_paths_are_the_branch_contribution(self):
        run(self.repo, "checkout", "-q", "-b", "agent/mine")
        write(self.repo, "mine.py", "y = 2\n")
        commit(self.repo, "my work")
        run(self.repo, "checkout", "-q", "master")
        self.assertEqual(
            self.mt._branch_own_paths(self.repo, "agent/mine", "master"),
            {"mine.py"})

    def test_a_conflict_in_a_file_the_branch_never_touched_is_foreign(self):
        """The passport.ts shape, reduced."""
        run(self.repo, "checkout", "-q", "-b", "agent/innocent")
        write(self.repo, "only_mine.py", "y = 2\n")
        commit(self.repo, "touches one unrelated file")
        run(self.repo, "checkout", "-q", "master")
        self.assertTrue(self.mt._conflict_is_foreign(
            self.repo, "agent/innocent", "master", "passport.ts"))

    def test_a_conflict_in_a_file_the_branch_owns_is_not_foreign(self):
        """The guard must not stop legitimate redos."""
        run(self.repo, "checkout", "-q", "-b", "agent/guilty")
        write(self.repo, "passport.ts", "export const a = 'branch'\n")
        commit(self.repo, "edits passport")
        run(self.repo, "checkout", "-q", "master")
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/guilty", "master", "passport.ts"))

    def test_a_mixed_conflict_set_is_not_foreign(self):
        """One owned path is enough to make the redo worth attempting."""
        run(self.repo, "checkout", "-q", "-b", "agent/mixed")
        write(self.repo, "unrelated.py", "x = 2\n")
        commit(self.repo, "edits unrelated")
        run(self.repo, "checkout", "-q", "master")
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/mixed", "master", "passport.ts\nunrelated.py"))

    def test_uncertain_attribution_falls_back_to_redo(self):
        """No detail, or an empty branch diff: redo is the cheaper mistake."""
        run(self.repo, "checkout", "-q", "-b", "agent/empty")
        run(self.repo, "checkout", "-q", "master")
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/empty", "master", ""))
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/empty", "master", "passport.ts"))
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/missing-branch", "master", "passport.ts"))

    # ── test-failure attribution ────────────────────────────────────────────
    # The same hole on the other gate. Tests run against the REBASED candidate,
    # which carries every commit replayed onto it, so a suite broken by another
    # branch in the overlay fails here and is reported against whoever is being
    # integrated.

    REAL_TAIL = (
        "overlay:e09cb823ef52 }\n\n"
        "stdout | server/utils/__tests__/tracing.test.ts > tracing.withSpan > "
        "nests parent → child via parentSpanId\n"
        '[span] {"traceId":"eedcfbd8ff24ccfbbc640d2a23bc654f","spanId":"198bdb\n'
    )

    def test_failing_test_files_parses_the_real_train_log(self):
        self.assertEqual(
            self.mt._failing_test_files(self.REAL_TAIL),
            {"server/utils/__tests__/tracing.test.ts"})

    def test_a_source_file_in_a_stack_trace_is_not_a_failing_suite(self):
        tail = "at buildSpan (server/utils/tracing.ts:41:9)\n  in helpers/format.js\n"
        self.assertEqual(self.mt._failing_test_files(tail), set())

    def test_python_and_spec_shapes_are_recognised(self):
        got = self.mt._failing_test_files(
            "FAILED runner/tests/test_lease_night_config_divergence.py::T::t\n"
            "FAIL app/foo.spec.ts\n")
        self.assertIn("runner/tests/test_lease_night_config_divergence.py", got)
        self.assertIn("app/foo.spec.ts", got)

    def test_a_failure_in_a_suite_the_branch_never_touched_is_foreign(self):
        """The live case: a triage/tooling branch failed on tracing.test.ts."""
        run(self.repo, "checkout", "-q", "-b", "agent/triage-only")
        write(self.repo, "tools/triage.py", "x = 1\n")
        commit(self.repo, "tooling only")
        run(self.repo, "checkout", "-q", "master")
        self.assertTrue(self.mt._testfail_is_foreign(
            self.repo, "agent/triage-only", "master", self.REAL_TAIL))

    def test_a_failure_in_a_suite_the_branch_owns_is_not_foreign(self):
        """The guard must never hide a branch breaking its own tests."""
        run(self.repo, "checkout", "-q", "-b", "agent/owns-tracing")
        write(self.repo, "server/utils/__tests__/tracing.test.ts", "// edited\n")
        commit(self.repo, "edits the tracing suite")
        run(self.repo, "checkout", "-q", "master")
        self.assertFalse(self.mt._testfail_is_foreign(
            self.repo, "agent/owns-tracing", "master", self.REAL_TAIL))

    def test_one_owned_failing_suite_among_several_is_not_foreign(self):
        run(self.repo, "checkout", "-q", "-b", "agent/partly")
        write(self.repo, "runner/tests/test_mine.py", "def test_x():\n    pass\n")
        commit(self.repo, "adds one suite")
        run(self.repo, "checkout", "-q", "master")
        tail = self.REAL_TAIL + "FAILED runner/tests/test_mine.py::test_x\n"
        self.assertFalse(self.mt._testfail_is_foreign(
            self.repo, "agent/partly", "master", tail))

    def test_an_unparseable_log_falls_back_to_the_normal_path(self):
        run(self.repo, "checkout", "-q", "-b", "agent/whatever")
        write(self.repo, "src/x.py", "x = 1\n")
        commit(self.repo, "work")
        run(self.repo, "checkout", "-q", "master")
        for tail in ("", "exit status 1", "Killed: 9"):
            self.assertFalse(self.mt._testfail_is_foreign(
                self.repo, "agent/whatever", "master", tail), repr(tail))

    def test_owners_names_the_branches_that_really_modify_the_file(self):
        for name, path in (("agent/owner-a", "passport.ts"),
                           ("agent/owner-b", "passport.ts"),
                           ("agent/bystander", "unrelated.py")):
            run(self.repo, "checkout", "-q", "-b", name, "master")
            write(self.repo, path, f"// {name}\n")
            commit(self.repo, f"edit from {name}")
        run(self.repo, "checkout", "-q", "master")

        # _conflict_owners scans remote-tracking refs; this fixture has none, so
        # assert the underlying attribution it is built on instead.
        for name in ("agent/owner-a", "agent/owner-b"):
            self.assertIn("passport.ts",
                          self.mt._branch_own_paths(self.repo, name, "master"))
        self.assertNotIn("passport.ts",
                         self.mt._branch_own_paths(self.repo, "agent/bystander", "master"))


if __name__ == "__main__":
    unittest.main()
