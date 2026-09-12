"""repair_patch must never write the stub over a task's specification.

The "spec-lost" quarantine cause: a repair rewrites a task's prompt with
"Complete the task '<slug>'." — in_session_prompt's fallback — destroying the
real spec, so the task can never be completed and is quarantined.

repair_patch already refused to write the prompt when the caller had not
SELECTed the column. That guard is necessary and not sufficient: a row can carry
a `prompt` key whose value is NULL or empty (partial hydration, a failed
regeneration), and then original_prompt() returns "" and the fallback fires
anyway. The cause was still producing 28 quarantines a week with the
presence-only guard in place.

These tests pin the stronger contract: the stub string never appears in a patch
returned by repair_patch, under any input shape.
"""
import os
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import agentic_repair as ar  # noqa: E402


STUB = "Complete the task"
REAL_SPEC = "Add a --verify-phantom CLI mode to runner/integration_sweeper.py."


def _task(**over):
    task = {"id": "t1", "slug": "some-slug", "project_id": "p1", "attempt": 1}
    task.update(over)
    return task


class TestStubIsNeverWrittenBack:
    @pytest.mark.parametrize("value", [None, "", "   ", "\n\n"])
    def test_empty_prompt_value_is_not_overwritten_with_the_stub(self, value):
        """The hole the presence-only guard left open."""
        patch = ar.repair_patch(_task(prompt=value), "boom")
        assert "prompt" not in patch, (
            "an empty prompt must be left alone, not replaced with the stub")

    def test_absent_prompt_column_is_still_not_written(self):
        """The original guard: a narrow select must not trigger a rewrite."""
        patch = ar.repair_patch(_task(), "boom")
        assert "prompt" not in patch

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_stub_string_never_appears_in_the_patch(self, value):
        patch = ar.repair_patch(_task(prompt=value), "boom")
        assert STUB not in str(patch.get("prompt", ""))


class TestRealSpecStillRepaired:
    """The guard must not disable repair for tasks that do have a spec."""

    def test_real_prompt_is_rewritten(self):
        patch = ar.repair_patch(_task(prompt=REAL_SPEC), "boom")
        assert "prompt" in patch
        assert REAL_SPEC in patch["prompt"]

    def test_repair_directive_is_appended(self):
        patch = ar.repair_patch(_task(prompt=REAL_SPEC), "boom")
        assert ar.MARKER in patch["prompt"]

    def test_stub_is_not_introduced_alongside_a_real_spec(self):
        patch = ar.repair_patch(_task(prompt=REAL_SPEC), "boom")
        assert STUB not in patch["prompt"]

    def test_an_already_repaired_prompt_keeps_exactly_one_directive(self):
        once = ar.repair_patch(_task(prompt=REAL_SPEC), "boom")["prompt"]
        twice = ar.repair_patch(_task(prompt=once, attempt=2), "boom again")["prompt"]
        assert twice.count(ar.MARKER) == 1
        assert REAL_SPEC in twice

    def test_a_prompt_that_is_only_a_directive_is_left_alone(self):
        """Stripping it yields nothing, so there is no spec to preserve."""
        directive_only = "\n\n" + ar.MARKER + "\nRepair category: rework\n"
        patch = ar.repair_patch(_task(prompt=directive_only), "boom")
        assert "prompt" not in patch


class TestAttemptCounterUnaffected:
    """The prompt guard must not change the repair bookkeeping."""

    def test_attempt_still_advances(self):
        """A task with a real spec is requeued, and the counter moves."""
        patch = ar.repair_patch(_task(prompt=REAL_SPEC, attempt=3), "boom")
        assert patch["attempt"] == 4

    @pytest.mark.parametrize("prompt", [None, ""])
    def test_a_task_with_no_spec_is_parked_rather_than_advanced(self, prompt):
        """Not advancing the counter here is the point, not an oversight.

        This case used to be parametrized alongside REAL_SPEC and asserted
        attempt == 4 for all three. repair_patch now answers a promptless task
        with a terminal QUARANTINED patch instead: with no implementation spec
        there is nothing for a repair to converge on, so requeueing it only
        burns attempts toward the ceiling and buries the row. Asserting the
        counter still advances would pin exactly that burn.
        """
        patch = ar.repair_patch(_task(prompt=prompt, attempt=3), "boom")
        assert patch["state"] == "QUARANTINED"
        assert "attempt" not in patch, "a parked task must not have its counter advanced"
        assert "unspecified-prompt" in patch["note"]

    def test_attempt_advances_without_the_prompt_column(self):
        assert ar.repair_patch(_task(attempt=3), "boom")["attempt"] == 4
