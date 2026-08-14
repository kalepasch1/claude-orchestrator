#!/usr/bin/env python3
"""Escalation / human-decision records must survive the agentic repair pipeline.

Regression source: escalate-p1-queue-clearance-no-improvement-20260810-nk73, the standing
Guardrail-8 escalation, was pulled into agentic repair on 2026-08-11 — attempt bumped to 4 and
note rewritten to 'agentic-repair:rework' on a row whose only purpose was to be read by a human.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import agentic_repair as ar

NK73 = {
    "id": "b78b7bdb-2f07-45e3-8ce6-66e23d0b923f",
    "slug": "escalate-p1-queue-clearance-no-improvement-20260810-nk73",
    "state": "QUEUED",
    "attempt": 4,
    "remediation_count": 0,
    "prompt": "WHAT: the P1 queue-clearance playbook stopped improving. A human must decide.",
    "note": "agentic-repair:rework",
    "account": "runner-crashed-session",
}


class TestIsOperatorDecision:
    def test_escalate_prefix(self):
        assert ar.is_operator_decision({"slug": "escalate-anything"}) is True

    def test_human_decision_prefix(self):
        assert ar.is_operator_decision({"slug": "human-decision-p1-halt-bypassed"}) is True

    def test_ordinary_work_is_not(self):
        assert ar.is_operator_decision({"slug": "backlog-batch-beethoven-288ebe8"}) is False
        assert ar.is_operator_decision({"slug": "bugfix-escalate-later"}) is False

    def test_missing_or_empty_slug(self):
        assert ar.is_operator_decision({}) is False
        assert ar.is_operator_decision(None) is False
        assert ar.is_operator_decision({"slug": None}) is False


class TestRepairPatchRefusesOperatorDecisions:
    def test_prompt_is_not_rewritten(self):
        patch = ar.repair_patch(dict(NK73), "some failure signal")
        assert "prompt" not in patch

    def test_attempt_is_not_advanced(self):
        patch = ar.repair_patch(dict(NK73), "some failure signal")
        assert "attempt" not in patch

    def test_remediation_count_is_not_advanced(self):
        patch = ar.repair_patch(dict(NK73), "some failure signal")
        assert "remediation_count" not in patch

    def test_no_coder_is_assigned(self):
        patch = ar.repair_patch(dict(NK73), "some failure signal")
        assert "force_coder" not in patch
        assert "model" not in patch

    def test_stays_queued_and_visible(self):
        patch = ar.repair_patch(dict(NK73), "")
        assert patch["state"] == "QUEUED"
        assert patch["note"] == ar.AWAITING_OPERATOR_NOTE

    def test_stale_claim_is_released(self):
        """The one mutation worth making: don't leave it held by a dead session."""
        patch = ar.repair_patch(dict(NK73), "")
        assert patch["account"] is None

    def test_not_marked_terminal(self):
        """An escalation is deferred, not given up on — is_terminal() must stay False."""
        patch = ar.repair_patch(dict(NK73), "")
        assert ar.is_terminal(patch) is False

    def test_guard_precedes_the_repair_ceiling(self):
        """Even past GLOBAL_REPAIR_CEILING it is deferred, never QUARANTINED."""
        task = dict(NK73, remediation_count=ar.GLOBAL_REPAIR_CEILING + 5)
        patch = ar.repair_patch(task, "")
        assert patch["state"] == "QUEUED"
        assert patch["note"] == ar.AWAITING_OPERATOR_NOTE

    def test_guard_applies_to_every_category(self):
        for category in ("rework", "conflict", "buildfail", "legal", "missing-branch"):
            patch = ar.repair_patch(dict(NK73), "signal", category=category)
            assert patch["note"] == ar.AWAITING_OPERATOR_NOTE, category

    def test_prefer_non_claude_does_not_bypass(self):
        patch = ar.repair_patch(dict(NK73), "signal", prefer_non_claude=True)
        assert "force_coder" not in patch


class TestOrdinaryTasksUnaffected:
    def test_normal_task_still_repaired(self):
        task = {
            "slug": "bugfix-thing", "prompt": "fix the thing", "attempt": 1,
            "remediation_count": 1, "note": "buildfail: tsc exited 2",
        }
        patch = ar.repair_patch(task, "tsc exited 2")
        assert patch["state"] == "QUEUED"
        assert patch["attempt"] == 2
        assert patch["remediation_count"] == 2
        assert ar.MARKER in patch["prompt"]

    def test_normal_task_still_hits_the_ceiling(self):
        task = {
            "slug": "bugfix-thing", "prompt": "fix", "attempt": 3,
            "remediation_count": ar.GLOBAL_REPAIR_CEILING, "note": "buildfail",
        }
        patch = ar.repair_patch(task, "buildfail")
        assert patch["state"] == "QUARANTINED"
        assert ar.is_terminal(patch) is True


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
