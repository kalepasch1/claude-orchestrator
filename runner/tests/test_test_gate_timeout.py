#!/usr/bin/env python3
"""The test-gate clocks must outlast the suites they gate, and say so when they don't.

WHY THIS EXISTS (2026-08-26)
---------------------------
Two gates run this repo's suite. Both had a clock shorter than the suite.

  * production_push_guard used an inline default of 1800s. This repo's own suite
    measures ~2330s for 14,352 tests, so `subprocess.run(..., timeout=1800)` raised
    subprocess.TimeoutExpired -- UNCAUGHT, straight out of a pre-push hook. It
    blocked the push, which is correct, but it reported a Python traceback instead
    of the one fact that mattered: the clock was shorter than the suite, so nothing
    whatsoever had been learned about the code.

  * merge_train used 300s and returned `(False, "tests timed out after 300s")`,
    which its caller cannot distinguish from red tests. Every candidate for the
    largest repo the train gates was therefore rejected on the clock and recorded
    as a test failure.

A timeout and a red suite are different in kind. A red suite is a verdict. A
timeout is the ABSENCE of one, and the only two things that produce it -- a clock
set too low, or something hanging -- are both operator-actionable in a way "tests
failed" is not. These tests pin that distinction, the fail-soft parsing of both
env knobs, and the floor under both defaults.

Nothing here runs a real suite: the subprocess call is replaced.
"""
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import production_push_guard as guard  # noqa: E402

#: The measured runtime of this repo's suite, in seconds. Both defaults must clear
#: it -- that is the whole point of the constants, so assert on it directly.
MEASURED_SUITE_RUNTIME_S = 2330


def _timeout_raiser(seconds_seen):
    """A subprocess.run stand-in that always times out, recording the clock it got."""
    def _run(*args, **kwargs):
        seconds_seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(cmd="npm run test", timeout=kwargs.get("timeout"))
    return _run


class GateTimeoutParsingTest(unittest.TestCase):
    """_gate_timeout is fail-soft, like _task_timeout in runner.py."""

    def test_an_explicit_value_is_honoured(self):
        with patch.dict(os.environ, {"ORCH_TEST_GATE_TIMEOUT": "900"}):
            self.assertEqual(guard._gate_timeout(), 900)

    def test_absent_empty_and_unparseable_fall_back(self):
        for value in ("", "   ", "not-a-number", "1800s"):
            with patch.dict(os.environ, {"ORCH_TEST_GATE_TIMEOUT": value}):
                self.assertEqual(guard._gate_timeout(),
                                 guard.TEST_GATE_TIMEOUT_DEFAULT, repr(value))
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(guard._gate_timeout(), guard.TEST_GATE_TIMEOUT_DEFAULT)

    def test_a_non_positive_clock_is_not_taken_literally(self):
        """0 or -1 would time out every run instantly and read as unverifiable."""
        for value in ("0", "-1"):
            with patch.dict(os.environ, {"ORCH_TEST_GATE_TIMEOUT": value}):
                self.assertEqual(guard._gate_timeout(),
                                 guard.TEST_GATE_TIMEOUT_DEFAULT, value)

    def test_the_default_outlasts_this_repos_own_suite(self):
        self.assertGreater(guard.TEST_GATE_TIMEOUT_DEFAULT, MEASURED_SUITE_RUNTIME_S)


class TimeoutIsNotARedRunTest(unittest.TestCase):
    """An unfinished suite blocks the push, and says why."""

    def test_a_timeout_does_not_escape_as_an_exception(self):
        seen = []
        with patch.dict(os.environ, {"ORCH_TEST_GATE_TIMEOUT": "5"}), \
                patch.object(subprocess, "run", _timeout_raiser(seen)):
            result = guard._run_suite("/nonexistent", "npm run test")
        self.assertIsNone(result.returncode)
        self.assertEqual(result.seconds, 5)
        self.assertEqual(seen, [5])

    def test_returncode_none_is_never_mistaken_for_green(self):
        """`!= 0` is how the existing callers read a result; None must fail that."""
        self.assertNotEqual(guard._SuiteTimedOut(60).returncode, 0)

    def test_verify_tests_blocks_and_names_the_knob(self):
        with patch.object(guard, "detect_test_cmd", lambda repo: "npm run test"), \
                patch.object(guard.proof_graph, "reusable_verification", lambda *a, **k: False), \
                patch.object(guard, "_tree_is_exactly", lambda *a, **k: True), \
                patch.object(guard, "_run_suite", lambda repo, cmd: guard._SuiteTimedOut(1800)):
            ok, log = guard.verify_tests("/repo", "d2b3a549b9fd")
        self.assertFalse(ok)
        self.assertIn("ORCH_TEST_GATE_TIMEOUT", log)
        self.assertIn("1800", log)
        self.assertIn("NO verdict", log)

    def test_a_timeout_is_not_re_run(self):
        """The flake re-run separates machine from code. A timeout has neither to offer.

        Re-running would cost a second full clock to learn the same nothing, and on
        this repo that is another hour of a pre-push hook.
        """
        calls = []

        def _timing_out(repo, command):
            calls.append(command)
            return guard._SuiteTimedOut(1800)

        with patch.object(guard, "detect_test_cmd", lambda repo: "npm run test"), \
                patch.object(guard.proof_graph, "reusable_verification", lambda *a, **k: False), \
                patch.object(guard, "_tree_is_exactly", lambda *a, **k: True), \
                patch.object(guard, "_run_suite", _timing_out):
            guard.verify_tests("/repo", "d2b3a549b9fd")
        self.assertEqual(len(calls), 1, "a timeout must not trigger the flake re-run")

    def test_a_timeout_on_the_re_run_is_reported_as_a_timeout(self):
        """First red, second never finishes: the verdict is "no verdict", not "red"."""
        results = [
            type("Proc", (), {"returncode": 1, "stdout": "2 failed", "stderr": ""})(),
            guard._SuiteTimedOut(1800),
        ]

        with patch.object(guard, "detect_test_cmd", lambda repo: "npm run test"), \
                patch.object(guard.proof_graph, "reusable_verification", lambda *a, **k: False), \
                patch.object(guard, "_tree_is_exactly", lambda *a, **k: True), \
                patch.object(guard, "_wait_for_quiet_machine", lambda *a, **k: 0.0), \
                patch.object(guard, "_run_suite", lambda repo, cmd: results.pop(0)):
            ok, log = guard.verify_tests("/repo", "d2b3a549b9fd")
        self.assertFalse(ok)
        self.assertIn("NO verdict", log)


def _load_merge_train():
    """Load merge_train from its path, not by name.

    runner/ and runner/tests/ share basenames and sys.path is process-global under
    pytest, so `import merge_train` is a coin flip on which module answers. Same
    loader, same reasoning, as test_convention_rule_registry.py.
    """
    spec = importlib.util.spec_from_file_location(
        "merge_train_for_timeout_test", os.path.join(RUNNER, "merge_train.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


train = _load_merge_train()


class TreeDriftTest(unittest.TestCase):
    """A suite only attests the tree it ran against — at BOTH ends of the run."""

    def _verify_with(self, tree_states, proc):
        """Run verify_tests with the tree checks answering from TREE_STATES in order.

        The first answer is the PRE-run _tree_is_exactly; the rest are the
        POST-run _tracked_content_still_matches.
        """
        recorded = []
        answers = list(tree_states)

        def _tree(repo, commit):
            return answers.pop(0) if answers else True

        with patch.object(guard, "detect_test_cmd", lambda repo: "npm run test"), \
                patch.object(guard.proof_graph, "reusable_verification", lambda *a, **k: False), \
                patch.object(guard, "_tree_is_exactly", _tree), \
                patch.object(guard, "_tracked_content_still_matches", _tree), \
                patch.object(guard, "_wait_for_quiet_machine", lambda *a, **k: 0.0), \
                patch.object(guard.proof_graph, "record_verification",
                             lambda *a, **k: recorded.append(a)), \
                patch.object(guard, "_run_suite", lambda repo, cmd: proc):
            ok, log = guard.verify_tests("/repo", "d2b3a549b9fd")
        return ok, log, recorded

    def test_a_green_run_on_a_tree_that_moved_is_not_a_proof(self):
        """The defect: the pre-run check guaranteed nothing about a 40-minute run.

        An edit landing mid-run made the result describe a different tree, and the
        green verdict was RECORDED — so reusable_verification would later hand back
        a proof for a commit whose suite was never run against it.
        """
        green = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ok, log, recorded = self._verify_with([True, False], green)
        self.assertFalse(ok, "a green run on a drifted tree must not certify the commit")
        self.assertIn("changed WHILE the suite was running", log)
        self.assertEqual(recorded, [], "nothing may be recorded for a tree we did not test")

    def test_a_red_run_on_a_tree_that_moved_records_nothing_either(self):
        """A red verdict about the wrong tree is still a verdict about the wrong tree."""
        red = type("Proc", (), {"returncode": 1, "stdout": "1 failed", "stderr": ""})()
        ok, log, recorded = self._verify_with([True, False, False], red)
        self.assertFalse(ok)
        self.assertIn("changed WHILE the suite was running", log)
        self.assertEqual(recorded, [])

    def test_an_untracked_artifact_written_by_the_run_is_not_drift(self):
        """A suite that writes into its own repo must still be able to earn a proof.

        The first cut of this check reused _tree_is_exactly, whose `git status
        --porcelain` counts untracked files. That is right BEFORE the run and wrong
        after it: coverage output, junit.xml or a scratch file written by the test
        command is the command doing its job, and counting it would mean any such
        project could never earn a proof at all. Four tests in
        runner/test_production_push_guard.py — whose fixture suite writes a `.runs`
        counter — caught exactly that.
        """
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, True)
        for args in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        with open(os.path.join(repo, "tracked.txt"), "w") as handle:
            handle.write("original\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True,
                       capture_output=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                              capture_output=True, text=True).stdout.strip()

        self.assertTrue(guard._tracked_content_still_matches(repo, head))

        with open(os.path.join(repo, "coverage.xml"), "w") as handle:
            handle.write("<coverage/>\n")
        self.assertTrue(guard._tracked_content_still_matches(repo, head),
                        "an untracked artifact from the run is not drift")

        with open(os.path.join(repo, "tracked.txt"), "w") as handle:
            handle.write("edited mid-run\n")
        self.assertFalse(guard._tracked_content_still_matches(repo, head),
                         "an edited TRACKED file is exactly what this must catch")

    def test_a_stable_tree_still_records_its_proof(self):
        """The check must not block the ordinary case it sits in front of."""
        green = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        ok, _log, recorded = self._verify_with([True, True], green)
        self.assertTrue(ok)
        self.assertEqual(len(recorded), 1)


class MergeTrainTimeoutTest(unittest.TestCase):
    """The train's clock has the same shape and the same failure mode."""

    def test_the_default_outlasts_this_repos_own_suite(self):
        self.assertGreater(train.TEST_TIMEOUT_DEFAULT, MEASURED_SUITE_RUNTIME_S)

    def test_the_clock_is_fail_soft(self):
        for value in ("", "  ", "five", "0", "-30"):
            with patch.dict(os.environ, {"MERGE_TRAIN_TEST_TIMEOUT": value}):
                self.assertEqual(train._test_timeout(),
                                 train.TEST_TIMEOUT_DEFAULT, repr(value))

    def test_an_explicit_value_is_honoured(self):
        with patch.dict(os.environ, {"MERGE_TRAIN_TEST_TIMEOUT": "600"}):
            self.assertEqual(train._test_timeout(), 600)

    def test_a_timeout_is_reported_as_absent_not_red(self):
        with patch.dict(os.environ, {"MERGE_TRAIN_TEST_TIMEOUT": "7"}), \
                patch.object(train.subprocess, "run", _timeout_raiser([])):
            ok, detail = train._run_tests("/repo", "npm run test")
        self.assertFalse(ok)
        self.assertIn("NO verdict", detail)
        self.assertIn("MERGE_TRAIN_TEST_TIMEOUT", detail)


if __name__ == "__main__":
    unittest.main()
