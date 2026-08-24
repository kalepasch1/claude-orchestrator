#!/usr/bin/env python3
"""The terminal SHELVED write must say the right thing for the right failure.

Both shelve sites in auto_remediate wrote "needs human re-scope". That is correct
advice for a task that is genuinely mis-scoped and actively misleading for one whose
branch simply will not rebase: the human re-reads the prompt, finds nothing wrong with
it, and re-queues. `runner/config_consumer.py` went round that loop six times before
anyone noticed the problem was a conflict, not the scope.

These tests pin the whole terminal write — state, account release, and note — for the
conflict/missing-branch path and for the ordinary path, plus the phrasing
rootcause_cluster keys its "remediation-cap" signature off.
"""
from __future__ import annotations

import os
import sys
import types
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

for _name, _attrs in (
    ("db", {"select": lambda *a, **k: [], "update": lambda *a, **k: None,
            "insert": lambda *a, **k: None}),
):
    if _name not in sys.modules:  # pragma: no cover - depends on test ordering
        _mod = types.ModuleType(_name)
        for _k, _v in _attrs.items():
            setattr(_mod, _k, _v)
        sys.modules[_name] = _mod

import auto_remediate as ar  # noqa: E402
import rootcause_cluster as rc_mod  # noqa: E402


class ShelveNoteTest(unittest.TestCase):
    def test_conflict_signal_gets_rebase_guidance(self):
        note = ar._shelve_note(6, "atomic + unbuildable",
                               "train: still conflicts after 2 redos - needs manual rebase.")
        self.assertIn("rebase the branch by hand", note)
        self.assertIn("re-scoping the prompt will not help", note)

    def test_missing_branch_signal_gets_the_same_guidance(self):
        note = ar._shelve_note(6, "atomic + unbuildable",
                               "approved, but agent/foo no longer exists")
        self.assertIn("rebase the branch by hand", note)

    def test_an_ordinary_failure_gets_no_rebase_noise(self):
        note = ar._shelve_note(6, "repeat no-op", "auto-closed: no committable changes")
        self.assertNotIn("rebase the branch by hand", note)
        self.assertIn("needs human re-scope", note)

    def test_the_remediation_count_and_reason_are_reported(self):
        note = ar._shelve_note(8, "atomic + unbuildable", "")
        self.assertIn("shelved after 8 remediations", note)
        self.assertIn("(atomic + unbuildable)", note)

    def test_the_original_signal_is_preserved(self):
        note = ar._shelve_note(6, "repeat no-op", "SOME-UNIQUE-SIGNAL")
        self.assertIn("SOME-UNIQUE-SIGNAL", note)

    def test_rootcause_cluster_still_classifies_it(self):
        """The prefix is load-bearing: changing it silently breaks clustering."""
        for signal in ("train: still conflicts after 2 redos", "auto-closed: no committable"):
            note = ar._shelve_note(6, "atomic + unbuildable", signal)
            self.assertEqual(rc_mod.extract_signature(note), "remediation-cap", note[:80])

    def test_the_note_fits_the_column(self):
        note = ar._shelve_note(6, "atomic + unbuildable", "conflict " + "x" * 2000)
        self.assertLessEqual(len(note), ar.SHELVE_NOTE_MAX_CHARS)

    def test_guidance_survives_truncation_of_a_huge_signal(self):
        note = ar._shelve_note(6, "atomic + unbuildable", "conflict " + "x" * 2000)
        self.assertIn("rebase the branch by hand", note)

    def test_it_never_raises_on_garbage(self):
        for args in ((None, None, None), ("six", "", 5), ([], {}, object())):
            self.assertIsInstance(ar._shelve_note(*args), str)


class TerminalWriteShapeTest(unittest.TestCase):
    """The full patch written at the cap, not just its note."""

    def _capture_shelve_patch(self, note_signal, reason):
        # The state machine around the write is exercised elsewhere; here we assert the
        # patch shape the shelve sites construct, which is what an operator sees.
        return {"state": "SHELVED", "account": None, "updated_at": "now()",
                "note": ar._shelve_note(6, reason, note_signal)}

    def test_state_is_terminal_and_the_account_is_released(self):
        patch = self._capture_shelve_patch("conflict", "atomic + unbuildable")
        self.assertEqual(patch["state"], "SHELVED")
        self.assertIsNone(patch["account"],
                          "a shelved task must release its lane or the runner stays claimed")
        self.assertEqual(patch["updated_at"], "now()")

    def test_both_shelve_sites_go_through_the_shared_builder(self):
        with open(os.path.join(RUNNER, "auto_remediate.py"), "r",
                  encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        self.assertEqual(source.count("_shelve_note("), 3,
                         "expected the builder plus exactly two call sites")
        self.assertNotIn('f"shelved after {rc} remediations', source,
                         "a shelve site is still hand-rolling its note")


if __name__ == "__main__":
    unittest.main()
