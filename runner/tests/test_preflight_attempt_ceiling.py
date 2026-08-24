"""The attempt ceiling has to be enforced on something a requeue cannot rewrite.

factory-unblock-improve-immediate-auto-merge-on-te-slice-4-fix-compilation-types reached
ATTEMPT 108 against ORCH_PREFLIGHT_HARD_CEILING=12. The ceiling itself worked — but its
claim-time enforcement ran through the task NOTE: preflight quarantines with a note
starting "preflight:", and should_skip_note keeps such a task from being claimed.

A note is mutable. Every agentic-repair requeue (rework / orphaned-running /
missing-branch) overwrites it with directive text containing none of SKIP_NOTE_PATTERNS,
so the skip evaporated and the task was claimable again — reject, rewrite, reclaim, 108
times. The attempt COUNT survives a requeue, so the ceiling is now read from that.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import preflight_filter as pf  # noqa: E402


REPAIR_NOTE = ("This is not a fresh requeue. Continue the same implementation to "
               "completion. Preserve any useful prior work, inspect the existing "
               "branch/worktree/artifacts first, and fix the root cause.")


class TestExhaustedAttempts:
    def test_a_task_past_the_ceiling_is_exhausted(self):
        assert pf.exhausted_attempts({"attempt": 108}) == 108

    def test_the_boundary_attempt_is_exhausted(self):
        assert pf.exhausted_attempts({"attempt": 12}) == 12

    def test_a_task_below_the_ceiling_is_not(self):
        assert pf.exhausted_attempts({"attempt": 11}) == 0

    def test_a_fresh_task_is_not(self):
        assert pf.exhausted_attempts({"attempt": 0}) == 0
        assert pf.exhausted_attempts({}) == 0

    def test_the_ceiling_is_env_tunable(self, monkeypatch):
        monkeypatch.setenv("ORCH_PREFLIGHT_HARD_CEILING", "3")
        assert pf.exhausted_attempts({"attempt": 3}) == 3
        assert pf.exhausted_attempts({"attempt": 2}) == 0

    def test_a_junk_ceiling_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("ORCH_PREFLIGHT_HARD_CEILING", "not-a-number")
        assert pf.exhausted_attempts({"attempt": 12}) == 12

    @pytest.mark.parametrize("attempt", [None, "many", [], {}])
    def test_an_unreadable_attempt_is_not_exhausted(self, attempt):
        """Fail-soft: never refuse real work because a field was unreadable."""
        assert pf.exhausted_attempts({"attempt": attempt}) == 0

    @pytest.mark.parametrize("task", [None, "text", 7, []])
    def test_a_malformed_task_never_raises(self, task):
        assert pf.exhausted_attempts(task) == 0


class TestShouldSkipTask:
    def test_a_quarantine_note_still_skips(self):
        assert pf.should_skip_task({"note": "preflight: exhausted 4 attempts"}) is True

    def test_the_repair_loop_note_no_longer_rescues_an_exhausted_task(self):
        """The exact 108-attempt shape: rewritten note, unrewritable attempt count."""
        assert pf.should_skip_task({"note": REPAIR_NOTE, "attempt": 108}) is True

    def test_the_same_note_below_the_ceiling_is_still_claimable(self):
        """A genuine repair requeue must keep working — this is not a blanket block."""
        assert pf.should_skip_task({"note": REPAIR_NOTE, "attempt": 3}) is False

    def test_a_clean_fresh_task_is_claimable(self):
        assert pf.should_skip_task({"note": "auto-queued", "attempt": 0}) is False

    @pytest.mark.parametrize("task", [None, {}, "text", 7])
    def test_a_malformed_task_is_not_skipped(self, task):
        assert pf.should_skip_task(task) is False


class TestAgreementWithDispatchTimeCheck:
    def test_claim_time_and_dispatch_time_use_the_same_ceiling(self, monkeypatch):
        """Two guards disagreeing about "exhausted" is how a task slips between them."""
        monkeypatch.setenv("ORCH_PREFLIGHT_HARD_CEILING", "5")
        task = {"attempt": 5, "prompt": "x" * 2000, "note": REPAIR_NOTE}
        assert pf.should_skip_task(task) is True
        assert "hard ceiling" in pf.preflight_check(task)

    def test_a_substantial_prompt_below_the_ceiling_passes_both(self, monkeypatch):
        monkeypatch.setenv("ORCH_PREFLIGHT_HARD_CEILING", "12")
        task = {"attempt": 5, "note": REPAIR_NOTE,
                "prompt": "Fix the handler in server/utils/foo.ts and add a test. " * 20}
        assert pf.should_skip_task(task) is False
        assert pf.preflight_check(task) == ""
