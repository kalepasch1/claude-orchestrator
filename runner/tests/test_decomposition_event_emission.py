#!/usr/bin/env python3
"""Emission tests: EVERY decomposition path must fire `decomposition_completed`.

The missing-branch bottleneck starts at decomposition time — children are inserted into the
queue before any agent branch exists. decomposition_events provisions agent/<slug> the
moment a decomposition completes, but only for decomposers that actually emit the event.

auto_decompose.decompose was wired (test_auto_decompose_events.py covers its numbered-items
path). bankruptcy_decompose.decompose was NOT: it inserts children and returns, so every
bankruptcy split still waited for branch_orchestrator's scan sweep. This file locks the
emission contract for both owners, so a third decomposer cannot be added silently unwired.

Nothing here touches git or the database: the provisioner is injected, db.insert is stubbed.
"""
import unittest
from unittest.mock import patch

from runner import auto_decompose, bankruptcy_decompose, decomposition_events


class RecordingProvisioner:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or set()

    def __call__(self, slug, repo_path, base_branch):
        self.calls.append((slug, repo_path, base_branch))
        if slug in self.fail_on:
            raise RuntimeError(f"cannot provision {slug}")
        return True

    @property
    def slugs(self):
        return [c[0] for c in self.calls]


NUMBERED_PROMPT = "Do the following:\n1. first thing\n2. second thing\n3. third thing\n"

FILE_PROMPT = (
    "Update `runner/alpha.py` and `runner/beta.py` and `runner/gamma.py` "
    "so the ledger reconciles.\n"
)

INTENT_PROMPT = (
    "Rework the settlement path so reconciliation is idempotent everywhere.\n"
    "- also make the retry budget configurable per rail and per project\n"
    "- then backfill the missing confirmations for the last seven days\n"
)


class EmissionTestCase(unittest.TestCase):
    def setUp(self):
        decomposition_events.invalidate()
        self.provisioner = RecordingProvisioner()
        decomposition_events._get_handler().provisioner = self.provisioner

    def tearDown(self):
        decomposition_events.invalidate()


class AutoDecomposeEmissionTest(EmissionTestCase):
    def test_file_scope_strategy_emits(self):
        # Strategy 2 (file-scope) was never covered; only numbered items were.
        with patch.object(auto_decompose, "_ENABLED", True), \
             patch.object(auto_decompose, "_MAX_FILES", 1):
            tasks = auto_decompose.decompose("parent", FILE_PROMPT,
                                             repo_path="/tmp/repo")
        self.assertGreater(len(tasks), 1)
        self.assertEqual(self.provisioner.slugs, [t["slug"] for t in tasks])

    def test_event_is_recorded_for_observability(self):
        with patch.object(auto_decompose, "_ENABLED", True):
            auto_decompose.decompose("parent", NUMBERED_PROMPT,
                                     repo_path="/tmp/repo")
        events = decomposition_events.recent_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["parent_slug"], "parent")
        self.assertGreater(events[0]["children"], 1)

    def test_base_branch_is_carried_to_the_provisioner(self):
        with patch.object(auto_decompose, "_ENABLED", True):
            auto_decompose.decompose("parent", NUMBERED_PROMPT,
                                     base_branch="orchestrator/dev",
                                     repo_path="/tmp/repo")
        self.assertTrue(all(c[2] == "orchestrator/dev"
                            for c in self.provisioner.calls))


class BankruptcyDecomposeEmissionTest(EmissionTestCase):
    """The gap this task exists to close."""

    def _decompose(self, prompt, **kw):
        task = {"id": "abcdef123456", "slug": "bankrupt-parent",
                "prompt": prompt, "project_id": "p1", "kind": "feature"}
        with patch.object(bankruptcy_decompose.db, "insert", return_value=[{"id": "x"}]), \
             patch.object(bankruptcy_decompose.db, "update", return_value=None):
            return bankruptcy_decompose.decompose(task, repo="/tmp/repo", **kw)

    def test_file_strategy_emits_and_provisions_every_child(self):
        subs = self._decompose(FILE_PROMPT)
        self.assertGreater(len(subs), 1)
        self.assertEqual(self.provisioner.slugs, [s["slug"] for s in subs])

    def test_intent_strategy_emits_and_provisions_every_child(self):
        subs = self._decompose(INTENT_PROMPT)
        self.assertGreater(len(subs), 1)
        self.assertEqual(self.provisioner.slugs, [s["slug"] for s in subs])

    def test_return_value_is_unchanged_by_emission(self):
        # Emission must be a side effect: callers keep the list they always got.
        subs = self._decompose(FILE_PROMPT)
        self.assertTrue(all(set(s) >= {"slug", "status"} for s in subs))

    def test_halving_strategy_produces_no_fan_out_event(self):
        subs = self._decompose("short prompt")
        self.assertLessEqual(len(subs), 1)
        self.assertEqual(self.provisioner.calls, [])

    def test_no_repo_means_no_provisioning_only_a_recorded_event(self):
        task = {"id": "abcdef123456", "slug": "bankrupt-parent",
                "prompt": FILE_PROMPT, "project_id": "p1"}
        with patch.object(bankruptcy_decompose.db, "insert", return_value=[{"id": "x"}]), \
             patch.object(bankruptcy_decompose.db, "update", return_value=None):
            bankruptcy_decompose.decompose(task)
        self.assertEqual(self.provisioner.calls, [])
        self.assertEqual(len(decomposition_events.recent_events()), 1)

    def test_base_branch_is_carried_through(self):
        self._decompose(FILE_PROMPT, base_branch="orchestrator/dev")
        self.assertTrue(all(c[2] == "orchestrator/dev"
                            for c in self.provisioner.calls))

    def test_emission_failure_never_breaks_decomposition(self):
        task = {"id": "abcdef123456", "slug": "bankrupt-parent",
                "prompt": FILE_PROMPT, "project_id": "p1"}
        with patch.object(bankruptcy_decompose.db, "insert", return_value=[{"id": "x"}]), \
             patch.object(bankruptcy_decompose.db, "update", return_value=None), \
             patch.object(decomposition_events, "on_decomposition_completed",
                          side_effect=RuntimeError("handler down")):
            subs = bankruptcy_decompose.decompose(task, repo="/tmp/repo")
        self.assertGreater(len(subs), 1)   # children still queued and returned

    def test_one_failing_child_does_not_stop_the_others(self):
        # slugs are deterministic from the parent id, so the failure can be targeted
        # without running the decomposition twice.
        doomed = "decomp-abcdef-1-alpha.py"
        decomposition_events.invalidate()
        p = RecordingProvisioner(fail_on={doomed})
        decomposition_events._get_handler().provisioner = p

        subs = self._decompose(FILE_PROMPT)
        self.assertIn(doomed, [s["slug"] for s in subs])

        event = decomposition_events.recent_events()[0]
        self.assertEqual([e["slug"] for e in event["errors"]], [doomed])
        self.assertEqual(len(event["provisioned"]), len(subs) - 1)


class EmitterParityTest(unittest.TestCase):
    """Both owners must keep the same contract, or one silently regresses."""

    def test_both_decomposers_expose_an_emitter(self):
        self.assertTrue(callable(auto_decompose._emit_decomposition))
        self.assertTrue(callable(bankruptcy_decompose._emit_decomposition))

    def test_both_guard_against_single_child_fan_out(self):
        decomposition_events.invalidate()
        p = RecordingProvisioner()
        decomposition_events._get_handler().provisioner = p
        auto_decompose._emit_decomposition("parent", [{"slug": "only"}],
                                           "/tmp/repo", "master")
        bankruptcy_decompose._emit_decomposition({"slug": "parent"},
                                                 [{"slug": "only"}], "/tmp/repo")
        self.assertEqual(p.calls, [])
        decomposition_events.invalidate()

    def test_bankruptcy_emitter_tolerates_none(self):
        self.assertEqual(
            bankruptcy_decompose._emit_decomposition({"slug": "p"}, None), [])


if __name__ == "__main__":
    unittest.main()
