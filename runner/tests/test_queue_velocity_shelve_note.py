"""A capacity decision and a broken build must not read the same.

`orch-cross-project-depends-fix-remaining-conflicts-redo-issues-with` sat SHELVED for over
60 minutes with the note "shelved by queue-velocity PID (low EV, integral too high)". A
factory-unblock task was then generated telling an executor to "diagnose the root cause
(build failure, merge conflict, flaky test, or a genuine blocker) and fix it — do not just
retry blindly, read the actual error".

There was no error to read. The task's own proof command,
`npm --prefix packages/darwin-kernel run test`, is green at 276/276. It had never been
attempted; the PID deprioritised it for capacity. The note did not say so, and did not
carry the numbers that caused it, so the only way to find that out was to run the whole
investigation — which is what this test exists to stop.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_velocity as qv  # noqa: E402


class TestShelveNoteContent:
    def test_it_carries_the_capacity_marker(self):
        note = qv.shelve_note({"confidence": 0.1})
        assert qv.CAPACITY_SHELVE_MARKER in note

    def test_it_says_plainly_that_nothing_failed(self):
        """The sentence that saves the next executor an entire investigation."""
        note = qv.shelve_note({"confidence": 0.1})
        assert "NOT a failure" in note
        assert "never attempted" in note

    def test_it_names_what_a_reader_would_otherwise_go_looking_for(self):
        note = qv.shelve_note({"confidence": 0.1})
        for absent in ("build error", "conflict", "flaky test"):
            assert absent in note

    def test_it_records_the_numbers_that_caused_the_decision(self):
        note = qv.shelve_note({"confidence": 0.12}, integral=5200, threshold=5000)
        assert "0.12" in note
        assert "5200" in note
        assert "5000" in note

    def test_it_says_what_to_do_next(self):
        note = qv.shelve_note({"confidence": 0.1})
        assert "Requeue" in note
        assert "pin" in note

    def test_a_missing_confidence_is_reported_as_unset_not_guessed(self):
        assert "EV/confidence=unset" in qv.shelve_note({})

    def test_the_numbers_are_omitted_cleanly_when_unknown(self):
        note = qv.shelve_note({"confidence": 0.1})
        assert "integral=" not in note
        assert "threshold=" not in note

    def test_the_note_fits_the_column(self):
        long_task = {"confidence": 0.1, "slug": "x" * 5000}
        assert len(qv.shelve_note(long_task, integral=1, threshold=2)) <= 900

    @pytest.mark.parametrize("task", [None, "text", 7, []])
    def test_a_malformed_task_never_raises(self, task):
        assert qv.CAPACITY_SHELVE_MARKER in qv.shelve_note(task)


class TestItIsDistinguishableFromAFailure:
    def test_a_remediation_loop_can_key_on_the_marker(self):
        capacity = qv.shelve_note({"confidence": 0.1})
        failure = "shelved after 5 remediations (atomic + unbuildable) — needs human re-scope"
        assert qv.CAPACITY_SHELVE_MARKER in capacity
        assert qv.CAPACITY_SHELVE_MARKER not in failure

    def test_the_old_opaque_wording_is_gone_from_the_source(self):
        src = open(qv.__file__, encoding="utf-8").read()
        assert "shelved by queue-velocity PID (low EV, integral too high)" not in src


class TestWiring:
    def test_the_shelver_writes_the_note(self):
        src = open(qv.__file__, encoding="utf-8").read()
        body = src[src.index("def _shelve_lowest_ev("):]
        body = body[:body.index("\ndef ")]
        assert "shelve_note(t, integral=integral, threshold=threshold)" in body

    def test_both_pid_actions_pass_the_numbers_through(self):
        """D-action and I-action both shelve; both must explain themselves."""
        src = open(qv.__file__, encoding="utf-8").read()
        calls = [ln for ln in src.splitlines() if "_shelve_lowest_ev(" in ln
                 and "def " not in ln]
        assert len(calls) >= 2
        for call in calls:
            assert "integral=integral" in call

    def test_the_shelver_still_accepts_a_bare_count(self):
        """Backward compatible: the extra context is optional."""
        import inspect
        sig = inspect.signature(qv._shelve_lowest_ev)
        assert sig.parameters["integral"].default is None
        assert sig.parameters["threshold"].default is None
