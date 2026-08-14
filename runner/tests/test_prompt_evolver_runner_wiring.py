#!/usr/bin/env python3
"""The prompt-evolution bandit was never reachable from the Claude interface.

`runner/prompt_evolver.py` is a UCB1 bandit over per-kind prompt TEMPLATES (base /
chain_of_thought / edit_first), complete with its own tests and documented reward
hygiene. A repo-wide grep found it imported by nothing: `runner.py` called only
`prompt_evolution.get_evolved_additions()`, which adds evolved SECTIONS to a
prompt and never chooses its SHAPE.

So no arm was ever pulled, no outcome was ever recorded, and the bandit could not
learn — the arms sat at n_trials=0 forever while the module's careful UCB1
exploration logic ran on nobody's behalf.

These pin the interface contract the wiring depends on, so a future refactor of
either side is caught here rather than by silence.

Run: python3 -m unittest runner.tests.test_prompt_evolver_runner_wiring -v
"""
import ast
import inspect
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import prompt_evolver

RUNNER_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "runner.py")


def _runner_source():
    with open(RUNNER_PY, errors="replace") as fh:
        return fh.read()


class WiringPresenceTest(unittest.TestCase):
    """runner.py must both select an arm and record its reward."""

    @classmethod
    def setUpClass(cls):
        cls.src = _runner_source()

    def test_runner_parses(self):
        ast.parse(self.src)  # the edit must not have broken the module

    def test_runner_selects_a_template(self):
        self.assertIn("prompt_evolver.select_template(", self.src)

    def test_runner_records_the_outcome(self):
        self.assertIn("prompt_evolver.record_outcome(", self.src)

    def test_selection_is_stashed_for_attribution(self):
        # Without this the record hook cannot know which arm was pulled.
        self.assertIn("_bandit_template_id", self.src)

    def test_both_hooks_are_fail_soft(self):
        # Every runner hook is wrapped; a bandit outage must not stop a task.
        for marker in ("hook prompt_evolver failed", "hook prompt_evolver.record failed"):
            self.assertIn(marker, self.src)

    def test_record_is_gated_on_a_selected_arm(self):
        # Crediting "base" for runs where selection failed would bias the bandit.
        self.assertIn('if t.get("_bandit_template_id")', self.src)


class InterfaceContractTest:
    """The exact call shapes runner.py now depends on."""


class SelectTemplateContractTest(unittest.TestCase):
    def setUp(self):
        prompt_evolver.invalidate()
        self.addCleanup(prompt_evolver.invalidate)

    def test_returns_prompt_and_template_id(self):
        with patch.object(prompt_evolver.db, "select", return_value=[]):
            prompt, tid = prompt_evolver.select_template("build", "BASE")
        self.assertIsInstance(prompt, str)
        self.assertIsInstance(tid, str)

    def test_base_arm_returns_the_prompt_unchanged(self):
        with patch.object(prompt_evolver.db, "select", return_value=[]):
            prompt, tid = prompt_evolver.select_template("build", "BASE")
        self.assertEqual((prompt, tid), ("BASE", "base"))

    def test_non_base_arm_tags_the_prompt(self):
        rows = [{"template_id": "base", "total_reward": 0.0, "n_trials": 5},
                {"template_id": "chain_of_thought", "total_reward": 0.0, "n_trials": 0},
                {"template_id": "edit_first", "total_reward": 0.0, "n_trials": 5}]
        with patch.object(prompt_evolver.db, "select", return_value=rows):
            prompt, tid = prompt_evolver.select_template("build", "BASE")
        self.assertEqual(tid, "chain_of_thought")           # untried arm scores +inf
        self.assertTrue(prompt.startswith("[template:chain_of_thought]"))
        self.assertIn("BASE", prompt)

    def test_db_failure_returns_the_base_prompt(self):
        with patch.object(prompt_evolver.db, "select", side_effect=RuntimeError("db down")):
            self.assertEqual(prompt_evolver.select_template("build", "BASE"), ("BASE", "base"))

    def test_the_prompt_is_never_lost(self):
        # runner.py assigns the result straight back to draft_prompt; returning an
        # empty string here would silently send an empty prompt to the model.
        for rows in ([], [{"template_id": "edit_first", "total_reward": 1.0, "n_trials": 1}]):
            with patch.object(prompt_evolver.db, "select", return_value=rows):
                prompt, _ = prompt_evolver.select_template("build", "BASE")
            self.assertIn("BASE", prompt)


class RecordOutcomeContractTest(unittest.TestCase):
    def setUp(self):
        prompt_evolver.invalidate()
        self.addCleanup(prompt_evolver.invalidate)

    def test_accepts_the_keywords_runner_passes(self):
        params = inspect.signature(prompt_evolver.record_outcome).parameters
        for name in ("kind", "template_id", "merged_first_try",
                     "deployed_verified", "artifact_commit"):
            self.assertIn(name, params)

    def test_bare_merge_claim_earns_nothing(self):
        rows = []
        with patch.object(prompt_evolver.db, "insert",
                          side_effect=lambda t, r, **k: rows.append(r)):
            prompt_evolver.record_outcome("build", "edit_first", merged_first_try=True,
                                          deployed_verified=False, artifact_commit="")
        self.assertEqual(rows[0]["total_reward"], 0.0)

    def test_first_try_merge_with_evidence_earns_partial_credit(self):
        rows = []
        with patch.object(prompt_evolver.db, "insert",
                          side_effect=lambda t, r, **k: rows.append(r)):
            prompt_evolver.record_outcome("build", "edit_first", merged_first_try=True,
                                          deployed_verified=False, artifact_commit="abc1234")
        self.assertEqual(rows[0]["total_reward"], 0.5)

    def test_a_trial_is_always_counted(self):
        rows = []
        with patch.object(prompt_evolver.db, "insert",
                          side_effect=lambda t, r, **k: rows.append(r)):
            prompt_evolver.record_outcome("build", "base", merged_first_try=False)
        self.assertEqual(rows[0]["n_trials"], 1)
        self.assertEqual(rows[0]["total_reward"], 0.0)

    def test_db_failure_is_swallowed(self):
        with patch.object(prompt_evolver.db, "insert", side_effect=RuntimeError("db down")):
            prompt_evolver.record_outcome("build", "base", merged_first_try=True)  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
