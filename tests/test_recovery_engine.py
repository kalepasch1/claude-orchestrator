"""Tests for runner/recovery_engine.py — the intent-first recovery classifier.

The behaviours pinned here are the ones whose absence caused the incident this
system exists to prevent: force-applying a stale diff over newer work, closing
an item without evidence, and resolving ambiguity by guessing.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))

import recovery_engine as re_mod  # noqa: E402


def _task(**kw):
    base = {
        "id": "t1",
        "slug": "improve-thing",
        "prompt": "Add a retry budget to the settlement poller so a transient 502 does not drop the run.",
        "state": "PHANTOM_UNVERIFIED",
        "created_at": "2026-07-01T00:00:00Z",
    }
    base.update(kw)
    return base


def _world(**kw):
    return re_mod.WorldDiff(
        touched_files=kw.get("touched_files", ["server/poller.ts"]),
        moved_files=kw.get("moved_files", []),
        missing_files=kw.get("missing_files", []),
    )


class TestIntent:
    def test_recovers_the_goal_from_the_prompt(self):
        intent = re_mod.recover_intent(_task())
        assert "retry budget" in intent.goal
        assert intent.is_recoverable

    def test_strips_pipeline_boilerplate_from_the_goal(self):
        prompt = (
            "Make the exporter stream instead of buffering.\n"
            "## ORCHESTRATION PIPELINE CONTRACT\n"
            "- source: intake-dropbox\n"
            "- agentic coder: swarm:openai\n"
        )
        intent = re_mod.recover_intent(_task(prompt=prompt))
        assert intent.goal == "Make the exporter stream instead of buffering."
        assert "swarm:openai" not in intent.goal

    def test_captures_acceptance_criteria(self):
        prompt = "Do the thing.\nAcceptance: `npm test` exits 0 with no failures."
        intent = re_mod.recover_intent(_task(prompt=prompt))
        assert any("npm test" in a for a in intent.acceptance)

    def test_an_empty_prompt_is_not_recoverable(self):
        assert not re_mod.recover_intent(_task(prompt="")).is_recoverable


class TestClassification:
    def test_unchanged_context_rebases(self):
        r = re_mod.classify_recovery_item(
            _task(), re_mod.recover_intent(_task()), _world(),
            intent_already_satisfied=False,
        )
        assert r.classification == re_mod.UNCHANGED_CONTEXT
        assert r.evidence

    def test_moved_context_re_implements_rather_than_porting_the_diff(self):
        r = re_mod.classify_recovery_item(
            _task(), re_mod.recover_intent(_task()),
            _world(moved_files=["server/poller.ts"]),
            intent_already_satisfied=False,
        )
        assert r.classification == re_mod.CONTEXT_MOVED
        assert "re-implement" in r.evidence.lower()

    def test_a_deleted_file_also_counts_as_moved_context(self):
        r = re_mod.classify_recovery_item(
            _task(), re_mod.recover_intent(_task()),
            _world(missing_files=["server/poller.ts"]),
            intent_already_satisfied=False,
        )
        assert r.classification == re_mod.CONTEXT_MOVED

    def test_already_satisfied_closes_with_the_evidence(self):
        r = re_mod.classify_recovery_item(
            _task(), re_mod.recover_intent(_task()), _world(),
            intent_already_satisfied=True,
            satisfied_evidence="commit abc123 added the same retry budget",
        )
        assert r.classification == re_mod.ALREADY_SATISFIED
        assert "abc123" in r.evidence
