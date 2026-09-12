#!/usr/bin/env python3
"""Smoke + behaviour tests for the prompt-bandit retrain entrypoint.

The task's named acceptance is "the evolved prompt is created, non-empty and parseable";
that is the first class here. The rest pin the retrain semantics that make the run worth
doing: raised exploration, a budget that holds promotion back, and a write path that
refuses to truncate a good prompt with a bad one.
"""
import os
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import prompt_bandit_retrain as pbr  # noqa: E402


class EvolveSmokeTests(unittest.TestCase):
    """The named acceptance: evolve writes a prompt that is non-empty and parseable."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = os.path.join(self._tmp.name, "prompts", "bandit_evolved.txt")

    def test_evolve_creates_the_prompt_file(self):
        outcome = pbr.evolve(max_iter=10, out_path=self.out, rng=random.Random(1))
        self.assertTrue(outcome["ok"], outcome.get("reason"))
        self.assertTrue(os.path.exists(self.out))

    def test_the_written_prompt_is_non_empty_and_parseable(self):
        pbr.evolve(max_iter=10, out_path=self.out, rng=random.Random(1))
        with open(self.out, encoding="utf-8") as handle:
            text = handle.read()
        self.assertTrue(text.strip())
        ok, reason = pbr.validate_prompt(text)
        self.assertTrue(ok, reason)

    def test_the_cli_round_trips_evolve_then_validate(self):
        self.assertEqual(pbr.main(["evolve", "--max-iter", "10", "--out", self.out]), 0)
        self.assertEqual(pbr.main(["validate-prompt", self.out]), 0)

    def test_the_prompt_records_the_retrain_that_produced_it(self):
        """Provenance: a prompt on disk must be traceable to its run."""
        pbr.evolve(max_iter=10, out_path=self.out, rng=random.Random(1))
        with open(self.out, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("retrain:", text)
        self.assertIn("epsilon=", text)


class ValidatePromptTests(unittest.TestCase):
    def test_rejects_the_empty_shapes(self):
        for bad in (None, "", "   ", "\n\n\t\n", 7, [], "too short"):
            ok, reason = pbr.validate_prompt(bad)
            self.assertFalse(ok, f"{bad!r} should be invalid")
            self.assertTrue(reason)

    def test_accepts_an_ordinary_prompt(self):
        ok, reason = pbr.validate_prompt("Implement the smallest change that passes tests.")
        self.assertTrue(ok, reason)


class RetrainSemanticsTests(unittest.TestCase):
    def test_defaults_match_the_spec(self):
        self.assertEqual(pbr.RETRAIN_EPSILON, 0.30)
        self.assertEqual(pbr.RETRAIN_BUDGET, 50)

    def test_decay_is_disabled_during_a_retrain(self):
        """Decaying epsilon mid-re-exploration reproduces the commitment being undone."""
        self.assertEqual(pbr.RETRAIN_DECAY, 0.0)

    def test_the_report_carries_the_parameters_it_ran_with(self):
        report = pbr.retrain(max_iter=5, rng=random.Random(2))
        self.assertTrue(report["ok"])
        self.assertEqual(report["epsilon"], 0.30)
        self.assertEqual(report["budget"], 50)
        self.assertEqual(report["iterations"], 5)

    def test_the_baseline_arm_is_always_present(self):
        report = pbr.retrain(max_iter=3, arms=["with_examples"], rng=random.Random(3))
        self.assertIn(pbr.BASELINE_ARM, report["arms"])

    def test_the_budget_prevents_promotion_on_a_short_run(self):
        """50 pulls required, 10 taken: nothing may be accepted."""
        report = pbr.retrain(max_iter=10, rng=random.Random(4))
        self.assertEqual(report["accepted"], [])

    def test_exploration_reaches_more_than_one_arm(self):
        report = pbr.retrain(max_iter=40, rng=random.Random(5))
        pulled = [a for a, n in (report["stats"].get("counts") or {}).items() if n > 0]
        self.assertGreater(len(pulled), 1)

    def test_zero_iterations_is_a_valid_no_op(self):
        report = pbr.retrain(max_iter=0, rng=random.Random(6))
        self.assertTrue(report["ok"])
        self.assertEqual(report["iterations"], 0)

    def test_a_retrain_does_not_disturb_the_live_singleton(self):
        """A retrain uses its own Bandit; abandoning it must not corrupt production."""
        import prompt_evolution_bandit as peb
        peb.reset()
        peb.select_action(["baseline", "other"], rng=random.Random(7))
        before = peb.stats().get("steps")
        pbr.retrain(max_iter=20, rng=random.Random(8))
        self.assertEqual(peb.stats().get("steps"), before)


class WriteSafetyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = os.path.join(self._tmp.name, "bandit_evolved.txt")

    def test_an_invalid_evolved_prompt_is_not_written(self):
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("PREVIOUS GOOD PROMPT that must survive a failed retrain.\n")
        outcome = pbr.evolve(max_iter=5, out_path=self.out, base_template="   ",
                             rng=random.Random(9))
        self.assertFalse(outcome["ok"])
        self.assertIn("rejected", outcome["reason"])
        with open(self.out, encoding="utf-8") as handle:
            self.assertIn("PREVIOUS GOOD PROMPT", handle.read())

    def test_a_failing_template_evolver_falls_back_rather_than_failing(self):
        with mock.patch.object(pbr.prompt_evolution, "evolve_template",
                               side_effect=RuntimeError("boom")):
            outcome = pbr.evolve(max_iter=5, out_path=self.out, rng=random.Random(10))
        self.assertTrue(outcome["ok"], outcome.get("reason"))
        self.assertTrue(outcome["prompt"].strip())

    def test_evolve_never_raises(self):
        outcome = pbr.evolve(max_iter=5, out_path="/proc/nonexistent/x/y.txt",
                             rng=random.Random(11))
        self.assertFalse(outcome["ok"])
        self.assertTrue(outcome["reason"])

    def test_validate_prompt_cli_reports_a_missing_file(self):
        self.assertEqual(pbr.main(["validate-prompt", os.path.join(self._tmp.name, "nope.txt")]), 1)


if __name__ == "__main__":
    unittest.main()


class AtomicPromptWriteTests(unittest.TestCase):
    """The live prompt template must survive a failed write.

    evolve()'s docstring promises a bad retrain "must leave the previous prompt in
    place rather than truncate it". validate_prompt enforces that for content. The
    write itself did not: open(path, "w") truncates on open, so an interruption
    between the truncate and the write left a zero-byte live template — the blank
    prompt the guard exists to prevent, by the one route it could not inspect.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "prompts", "bandit_evolved.txt")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.previous = "# The prompt that is live right now\nDo the smallest useful thing.\n"
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(self.previous)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read(self):
        with open(self.path, encoding="utf-8") as handle:
            return handle.read()

    def test_a_successful_write_replaces_the_file(self):
        pbr._write_atomically(self.path, "# new\nsomething useful\n")
        self.assertEqual(self._read(), "# new\nsomething useful\n")

    def test_a_write_that_dies_mid_flight_leaves_the_previous_prompt_intact(self):
        with mock.patch.object(pbr.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                pbr._write_atomically(self.path, "# half a prompt")
        self.assertEqual(self._read(), self.previous,
                         "the live prompt was truncated by a failed write")

    def test_a_failed_write_leaves_no_temp_file_behind(self):
        with mock.patch.object(pbr.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                pbr._write_atomically(self.path, "# half a prompt")
        leftovers = [n for n in os.listdir(os.path.dirname(self.path))
                     if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_an_interrupt_does_not_truncate_the_live_prompt(self):
        """KeyboardInterrupt is not an Exception. A bare `except Exception` here would
        let a Ctrl-C leak the temp file and, before this change, a truncated target."""
        with mock.patch.object(pbr.os, "replace", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                pbr._write_atomically(self.path, "# interrupted")
        self.assertEqual(self._read(), self.previous)
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.path))
                          if n.endswith(".tmp")], [])

    def test_the_temp_file_is_a_sibling_so_the_rename_cannot_cross_filesystems(self):
        seen = {}
        real_mkstemp = pbr.tempfile.mkstemp

        def spy(*args, **kwargs):
            seen["dir"] = kwargs.get("dir")
            return real_mkstemp(*args, **kwargs)

        with mock.patch.object(pbr.tempfile, "mkstemp", side_effect=spy):
            pbr._write_atomically(self.path, "# new prompt body\n")
        self.assertEqual(seen["dir"], os.path.dirname(self.path))

    def test_evolve_still_writes_through_the_atomic_path(self):
        out = pbr.evolve(max_iter=2, out_path=self.path, rng=random.Random(0))
        self.assertTrue(out["ok"], out.get("reason"))
        self.assertTrue(self._read().strip())

    def test_the_directory_is_created_when_missing(self):
        nested = os.path.join(self.tmp, "a", "b", "prompt.txt")
        pbr._write_atomically(nested, "# created\nwith parents\n")
        self.assertTrue(os.path.isfile(nested))
