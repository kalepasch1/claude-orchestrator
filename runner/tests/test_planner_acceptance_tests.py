#!/usr/bin/env python3
"""Every independently-buildable shard the planner emits must carry its own concrete,
runnable acceptance test.

The planner's META prompt asks the model for one, but nothing enforced it: shards
arrived with no `proof`, or with "tests pass", which no runner can execute. A shard
without an acceptance test is not independently verifiable, which defeats the purpose
of splitting a build task into smaller subtasks at all.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner  # noqa: E402


class TestIsConcreteProof(unittest.TestCase):
    def test_runnable_command_is_concrete(self):
        self.assertTrue(planner._is_concrete_proof("python3 -m pytest runner/tests/test_x.py -q"))

    def test_missing_proof_is_not_concrete(self):
        for bad in (None, "", "   ", 42, [], {}):
            self.assertFalse(planner._is_concrete_proof(bad), bad)

    def test_hand_wave_phrases_are_not_concrete(self):
        for bad in ("tests pass", "Tests Pass.", "suite green", "manual verification",
                    "TBD", "n/a", "build passes"):
            self.assertFalse(planner._is_concrete_proof(bad), bad)


class TestDeriveAcceptanceTest(unittest.TestCase):
    def test_named_test_file_wins(self):
        t = {"file_scope": "runner/foo.py,runner/tests/test_foo.py", "prompt": ""}
        self.assertEqual(planner._derive_acceptance_test(t),
                         "python3 -m pytest runner/tests/test_foo.py -q")

    def test_source_file_maps_to_sibling_suite(self):
        t = {"file_scope": "runner/config_consumer.py", "prompt": ""}
        self.assertEqual(planner._derive_acceptance_test(t),
                         "python3 -m pytest runner/tests/test_config_consumer.py -q")

    def test_falls_back_to_default(self):
        t = {"file_scope": "", "prompt": "redesign the docs narrative"}
        self.assertEqual(planner._derive_acceptance_test(t), planner.DEFAULT_ACCEPTANCE_TEST)

    def test_bad_task_shape_falls_back_rather_than_raising(self):
        self.assertEqual(planner._derive_acceptance_test(object()),
                         planner.DEFAULT_ACCEPTANCE_TEST)


class TestEnsureAcceptanceTests(unittest.TestCase):
    def test_every_task_gets_a_proof(self):
        tasks = [
            {"slug": "contracts", "deps": []},
            {"slug": "a", "file_scope": "runner/a.py", "deps": ["contracts"]},
            {"slug": "b", "proof": "tests pass", "file_scope": "runner/tests/test_b.py"},
        ]
        out = planner.ensure_acceptance_tests(tasks)
        self.assertEqual(len(out), 3)
        for t in out:
            self.assertTrue(planner._is_concrete_proof(t["proof"]), t)

    def test_existing_concrete_proof_is_preserved(self):
        tasks = [{"slug": "a", "proof": "python3 -m unittest runner.tests.test_a -v",
                  "file_scope": "runner/a.py"}]
        out = planner.ensure_acceptance_tests(tasks)
        self.assertEqual(out[0]["proof"], "python3 -m unittest runner.tests.test_a -v")

    def test_vague_proof_is_replaced_with_something_runnable(self):
        tasks = [{"slug": "a", "proof": "suite green", "file_scope": "runner/a.py"}]
        out = planner.ensure_acceptance_tests(tasks)
        self.assertEqual(out[0]["proof"], "python3 -m pytest runner/tests/test_a.py -q")

    def test_empty_and_none_are_returned_unchanged(self):
        self.assertEqual(planner.ensure_acceptance_tests([]), [])
        self.assertIsNone(planner.ensure_acceptance_tests(None))

    def test_non_dict_entries_do_not_raise(self):
        tasks = ["junk", {"slug": "a", "file_scope": "runner/a.py"}]
        out = planner.ensure_acceptance_tests(tasks)
        self.assertEqual(out[1]["proof"], "python3 -m pytest runner/tests/test_a.py -q")

    def test_is_idempotent(self):
        tasks = [{"slug": "a", "file_scope": "runner/a.py"}]
        once = planner.ensure_acceptance_tests(tasks)[0]["proof"]
        twice = planner.ensure_acceptance_tests(tasks)[0]["proof"]
        self.assertEqual(once, twice)


class TestWiredIntoPlan(unittest.TestCase):
    def test_plan_calls_the_guarantee_last(self):
        """Regression guard: the pass must run AFTER every task-minting pass, or shards
        created by sharding/coarsening/golden-path can still escape without a proof."""
        import inspect
        src = inspect.getsource(planner.plan)
        self.assertIn("ensure_acceptance_tests(tasks)", src)
        self.assertLess(src.index("_apply_golden_path(tasks"),
                        src.index("ensure_acceptance_tests(tasks)"))


if __name__ == "__main__":
    unittest.main()
