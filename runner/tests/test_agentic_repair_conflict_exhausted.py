"""A conflict the redo mechanism already gave up on must not be redone again.

merge_train.py retries a rebase conflict up to its redo cap and then parks the task:
"train: still conflicts after 4 redos - needs manual rebase. Conflicting files: ...".
That note is a CONCLUSION — but it is also failure evidence, so the repair path read it as
a reason to try again, re-queued the task, and handed it straight back to the redo
mechanism that had just given up, with the conflicting file set unchanged. Nothing between
one attempt and the next changes the conflict, so every extra round lands in the same
place. factory-unblock-improve-immediate-auto-merge-on-te-slice-4-fix-compilation-types
reached attempt 108 against a redo cap of 4 exactly this way.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agentic_repair as ar  # noqa: E402


EXHAUSTED = ("train: still conflicts after 4 redos - needs manual rebase. "
             "Conflicting files: web/server/utils/otc/compositePayoffCompiler.ts "
             "packages/darwin-kernel/src/passport/passport.ts")


def _task(note="", attempt=1, slug="some-task"):
    return {"id": "t1", "slug": slug, "note": note, "attempt": attempt,
            "remediation_count": 1, "prompt": "do the thing"}


class TestConflictExhausted:
    def test_the_merge_train_conclusion_is_recognised(self):
        assert ar.conflict_exhausted(_task(EXHAUSTED)) is True

    def test_it_is_recognised_from_the_signal_too(self):
        assert ar.conflict_exhausted(_task(), EXHAUSTED) is True

    @pytest.mark.parametrize("text", [
        "train: still conflicts after 12 redos",
        "needs manual rebase",
        "decided_by=merge-train:conflict-exhausted",
        "NEEDS MANUAL REBASE",
    ])
    def test_every_exhaustion_phrasing_counts(self, text):
        assert ar.conflict_exhausted(_task(text)) is True

    @pytest.mark.parametrize("text", [
        "rebase conflict, rebuild on fresh master (1/4)",
        "buildfail: tsc exited 2",
        "",
    ])
    def test_a_conflict_still_within_its_cap_is_not_exhausted(self, text):
        """Redoing IS useful while the cap has room — do not park those."""
        assert ar.conflict_exhausted(_task(text)) is False

    @pytest.mark.parametrize("task", [None, {}, "text", 7])
    def test_never_raises(self, task):
        ar.conflict_exhausted(task, "")


class TestRepairPatchExits(object):
    def test_an_exhausted_conflict_is_parked_not_requeued(self):
        patch = ar.repair_patch(_task(EXHAUSTED), EXHAUSTED, category="conflict")
        assert patch["state"] == "QUARANTINED"
        assert patch["account"] is None

    def test_the_note_asks_for_a_manual_rebase_and_names_the_files(self):
        patch = ar.repair_patch(_task(EXHAUSTED), EXHAUSTED, category="conflict")
        assert "MANUAL REBASE" in patch["note"]
        assert "passport.ts" in patch["note"]

    def test_it_exits_before_the_ceilings_so_no_further_rounds_are_spent(self):
        """Decidable from the signal — waiting for a counter costs guaranteed-futile rounds."""
        fresh = _task(EXHAUSTED, attempt=0)
        fresh["remediation_count"] = 0
        assert ar.repair_patch(fresh, EXHAUSTED, category="conflict")["state"] == "QUARANTINED"

    def test_it_is_deterministic_across_repeated_calls(self):
        task = _task(EXHAUSTED)
        first = ar.repair_patch(task, EXHAUSTED, category="conflict")
        second = ar.repair_patch(task, EXHAUSTED, category="conflict")
        assert first["state"] == second["state"] == "QUARANTINED"
        assert first["note"] == second["note"]

    def test_the_missing_branch_owner_path_terminates_too(self):
        """Same guard, reached through the missing-branch category."""
        patch = ar.repair_patch(_task(EXHAUSTED), EXHAUSTED, category="missing-branch")
        assert patch["state"] == "QUARANTINED"
        assert "missing-branch" in patch["note"]

    def test_an_operator_decision_still_wins(self):
        """Escalations are answered before everything, including this guard."""
        task = _task(EXHAUSTED)
        task["note"] = ar.OPERATOR_DECISION_PREFIX + " " + EXHAUSTED \
            if hasattr(ar, "OPERATOR_DECISION_PREFIX") else task["note"]
        patch = ar.repair_patch(task, EXHAUSTED, category="conflict")
        assert patch["state"] in ("QUARANTINED", "AWAITING_OPERATOR")


class TestUnrelatedRepairsUnaffected:
    def test_a_normal_buildfail_is_still_requeued(self):
        signal = "buildfail: tsc exited 2\n  src/foo.ts(3,1): error TS2304: Cannot find name 'x'"
        patch = ar.repair_patch(_task("agentic-repair:buildfail"), signal, category="buildfail")
        assert patch.get("state") != "QUARANTINED" or "MANUAL REBASE" not in patch.get("note", "")

    def test_a_conflict_under_its_cap_is_still_requeued(self):
        signal = "rebase conflict, rebuild on fresh master (2/4). Conflicting files: a.ts"
        patch = ar.repair_patch(_task("agentic-repair:conflict"), signal, category="conflict")
        assert "MANUAL REBASE" not in patch.get("note", "")
