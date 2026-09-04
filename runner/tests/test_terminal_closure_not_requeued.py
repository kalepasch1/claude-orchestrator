#!/usr/bin/env python3
"""A BLOCKED closure is an answer. Deleting it costs a coder run to rediscover.

Measured on 2026-08-25: the tasks table held ZERO rows in state BLOCKED --
not few, zero -- while max(attempt) stood at 124. Five tasks closed BLOCKED
with named evidence returned to QUEUED within fourteen seconds, attempt
incremented and note replaced by "agentic-repair:rework".

That is a closed loop with a price. The database REQUIRES the evidence:
enforce_evidence_on_closure() rejects a DONE with no artifact_commit, and its
HINT prescribes the exact marker, "NO-ARTIFACT-JUSTIFIED: <reason>". The
remediation loop then erased it before an operator could read it and paid a
coder to rediscover the same missing artifact, over and over.

The sharpest instance is pinned below as
`test_evidence_prose_is_not_failure_signal`: one closure explained that
requirements.txt had "no duplicate package names and no conflicting pins" --
evidence that nothing was wrong -- and `_CONFLICT`, which is r"conflict",
matched it and requeued the task as a merge-conflict repair. The classifiers
read evidence prose as failure signal, so any explanation detailed enough to
be useful eventually contains a word that sends it back around. That is why
the gate runs before them rather than beside them.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import auto_remediate  # noqa: E402
import queue_janitor  # noqa: E402


class TerminalClosureIsRecognised(unittest.TestCase):
    def test_the_marker_the_database_prescribes(self):
        """enforce_evidence_on_closure()'s HINT names this exact string."""
        self.assertTrue(auto_remediate.is_terminal_closure(
            "NO-ARTIFACT-JUSTIFIED: no adapted dependency patch exists to reconstruct."))

    def test_the_marker_is_matched_mid_note(self):
        """Executors prefix their notes with an account tag."""
        self.assertTrue(auto_remediate.is_terminal_closure(
            "cowork-executor-v6.5: NO-ARTIFACT-JUSTIFIED — already implemented."))

    def test_the_executors_other_standard_phrasing(self):
        self.assertTrue(auto_remediate.is_terminal_closure(
            "cowork-executor-v6.5: BLOCKED — no code target, and the prompt is "
            "mis-assembled. MISSING: what prompt to add to the bandit."))

    def test_case_and_punctuation_do_not_matter(self):
        for note in ("no artifact justified: nothing to build",
                     "No-Artifact-Justified: nothing to build"):
            with self.subTest(note=note):
                self.assertTrue(auto_remediate.is_terminal_closure(note))

    def test_empty_and_none_are_not_closures(self):
        for note in (None, "", "   "):
            with self.subTest(note=note):
                self.assertFalse(auto_remediate.is_terminal_closure(note))


class RealFailuresStillGetRepaired(unittest.TestCase):
    """The gate must not become a way for any failure to escape remediation."""

    def test_a_genuine_empty_run_is_not_a_closure(self):
        self.assertFalse(auto_remediate.is_terminal_closure(
            "agent run failed: no committable changes"))

    def test_a_conflict_is_not_a_closure(self):
        self.assertFalse(auto_remediate.is_terminal_closure(
            "train: still conflicts after 4 redos - needs manual rebase"))

    def test_a_turn_limit_is_not_a_closure(self):
        self.assertFalse(auto_remediate.is_terminal_closure(
            "auto-remediate: retry after max_turns limit (1/3)"))

    def test_a_test_failure_is_not_a_closure(self):
        self.assertFalse(auto_remediate.is_terminal_closure(
            "verify: 8 failed, 90 passed in tests/test_routing.py"))

    def test_the_word_missing_alone_is_not_a_closure(self):
        """`missing` appears in ordinary failure text; it must not be enough."""
        self.assertFalse(auto_remediate.is_terminal_closure(
            "branch agent/foo is missing from origin"))
        self.assertFalse(auto_remediate.is_terminal_closure(
            "ERR_MODULE_NOT_FOUND: missing package 'vitest'"))


class EvidenceProseIsNotFailureSignal(unittest.TestCase):
    """The loop this fix closes, reproduced exactly."""

    def test_evidence_prose_is_not_failure_signal(self):
        note = ("cowork-executor-v6.5: NO-ARTIFACT-JUSTIFIED — requirements.txt "
                "and requirements-dev.txt contain ZERO duplicate package names "
                "and no conflicting pins, so a diff would be empty.")

        # The category regex still matches -- the word is right there. That is
        # precisely why order matters: the gate has to win.
        self.assertTrue(auto_remediate._CONFLICT.search(note),
                        "premise of this test changed; _CONFLICT no longer matches")
        self.assertTrue(auto_remediate.is_terminal_closure(note))

    def test_a_closure_explaining_it_produced_no_diff_is_held(self):
        """The janitor's second door, closed by the same rule.

        A NO-ARTIFACT closure routinely explains itself using the exact words
        the janitor scans for, so the empty-run marker matches and the note
        would be requeued from there instead.
        """
        note = ("cowork-executor-v6.5: NO-ARTIFACT-JUSTIFIED — the module is "
                "already green, so this run produced no committable changes.")

        self.assertTrue(any(m in note.lower()
                            for m in queue_janitor.EMPTY_RUN_MARKERS),
                        "premise of this test changed; no empty-run marker matches")
        self.assertFalse(queue_janitor._note_matches_empty(note))

    def test_the_janitor_still_repairs_a_real_empty_run(self):
        self.assertTrue(queue_janitor._note_matches_empty(
            "agent produced no committable changes"))

    def test_both_doors_answer_with_one_rule(self):
        """A second copy of this rule would drift, and drift silently."""
        note = "NO-ARTIFACT-JUSTIFIED: nothing to build; empty diff."

        self.assertTrue(auto_remediate.is_terminal_closure(note))
        self.assertFalse(queue_janitor._note_matches_empty(note))


class GateRunsBeforeTheClassifiers(unittest.TestCase):
    """Ordering is the fix. Pinned so a later edit cannot quietly undo it."""

    def test_gate_precedes_every_category_regex_in_the_loop(self):
        import inspect

        source = inspect.getsource(auto_remediate.run)
        gate = source.index("is_terminal_closure(note)")

        for name in ("_MAX_TURNS.search", "_TOO_LONG.search", "_PARKED.search",
                     "_CONFLICT.search", "_requires_human_hold(",
                     "rc >= HARD_CAP"):
            with self.subTest(classifier=name):
                self.assertLess(
                    gate, source.index(name),
                    f"{name} is checked before the terminal-closure gate; a "
                    f"closure containing its keyword will be requeued")

    def test_the_gate_reads_the_note_not_the_log_tail(self):
        """log_tail may quote the marker from a PREVIOUS cycle.

        The closure is what the executor decided, and that lives in the note.
        Reading `signal` would let stale output hold a genuinely failed run.
        """
        import inspect

        source = inspect.getsource(auto_remediate.run)
        line = next(l for l in source.splitlines()
                    if "is_terminal_closure(" in l and "def " not in l)

        self.assertIn("is_terminal_closure(note)", line)
        self.assertNotIn("signal", line)


if __name__ == "__main__":
    unittest.main()
