"""Tests for task_state_machine — automated state transitions."""
import unittest


class TestTaskStateMachine(unittest.TestCase):

    def test_valid_transitions(self):
        from runner.task_state_machine import is_valid_transition
        self.assertTrue(is_valid_transition("QUEUED", "RUNNING"))
        self.assertTrue(is_valid_transition("RUNNING", "DONE"))
        self.assertTrue(is_valid_transition("DONE", "MERGED"))
        self.assertTrue(is_valid_transition("RUNNING", "QUEUED"))  # retry
        self.assertTrue(is_valid_transition("BLOCKED", "QUEUED"))  # unblock

    def test_invalid_transitions(self):
        from runner.task_state_machine import is_valid_transition
        self.assertFalse(is_valid_transition("MERGED", "QUEUED"))  # terminal
        self.assertFalse(is_valid_transition("QUEUED", "DONE"))    # skip RUNNING
        self.assertFalse(is_valid_transition("QUEUED", "MERGED"))  # skip RUNNING+DONE

    def test_all_states_have_entries(self):
        from runner.task_state_machine import VALID_TRANSITIONS
        expected_states = {"QUEUED", "RUNNING", "DONE", "MERGED", "BLOCKED",
                           "TESTFAIL", "BUILDFAIL", "SHELVED", "DECOMPOSED", "QUARANTINED"}
        self.assertEqual(set(VALID_TRANSITIONS.keys()), expected_states)

    def test_merged_is_terminal(self):
        from runner.task_state_machine import VALID_TRANSITIONS
        self.assertEqual(len(VALID_TRANSITIONS["MERGED"]), 0)

    def test_syntax_check(self):
        import py_compile
        # Absolute path derived from THIS file. The literal "runner/task_state_machine.py" only
        # resolved when pytest happened to run from the repo root; CI runs the runner
        # suite with working-directory: runner, where it raised FileNotFoundError —
        # so the syntax guard failed for a reason that had nothing to do with syntax.
        import os
        target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "task_state_machine.py")
        py_compile.compile(target, doraise=True)


if __name__ == "__main__":
    unittest.main()
