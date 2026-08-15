"""Live-schema adapter tests for the JSON enqueue CLI."""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import enqueue_task


class EnqueueTaskLoaderTest(unittest.TestCase):
    def _spec(self, **overrides):
        value = {
            "project": "orchestrator",
            "slug": "improve-example",
            "prompt": "Implement the improvement with focused regression tests.",
            "proof": "runner/tests/test_example.py",
            "submitted_by_label": "Codex operator-directed remediation",
        }
        value.update(overrides)
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        with open(path, "w", encoding="utf-8") as target:
            json.dump(value, target)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_orchestrator_alias_creates_beethoven_task_with_proof_and_receipt(self):
        inserted = []

        def select(table, params):
            if table == "projects":
                return [{"id": "p1", "name": "beethoven", "repo_path": "/tmp/orch",
                         "default_base": "master"}]
            return []

        db = types.SimpleNamespace(
            select=select,
            insert=lambda table, row: inserted.append(row) or [{"id": "t1"}],
            update=lambda *args: None,
            test_trigger=lambda task_id: False,
        )
        contract = types.SimpleNamespace(
            wrap_prompt=lambda prompt, **kwargs: prompt,
            note=lambda note, **kwargs: note,
        )
        with patch.object(enqueue_task, "db", db), \
             patch.object(enqueue_task, "pipeline_contract", contract), \
             patch.object(enqueue_task.tests_first_gate, "split_if_needed",
                          side_effect=lambda task, repo_path=None: [task]):
            enqueue_task.main(self._spec())

        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0]["project_id"], "p1")
        self.assertEqual(inserted[0]["base_branch"], "master")
        self.assertIn("Proof: runner/tests/test_example.py", inserted[0]["prompt"])
        self.assertIn("[enqueue-intent:p1::improve-example::]", inserted[0]["note"])
        self.assertEqual(inserted[0]["submitted_by_label"],
                         "Codex operator-directed remediation")

    def test_open_equivalent_is_coalesced_and_recoverable_failure_requeued(self):
        updates = []

        def select(table, params):
            if table == "projects":
                return [{"id": "p1", "name": "beethoven", "repo_path": "/tmp/orch",
                         "default_base": "master"}]
            return [{"id": "old", "slug": "improve-example-slice-4", "state": "BLOCKED",
                     "attempt": 4, "note": ""}]

        db = types.SimpleNamespace(
            select=select,
            insert=lambda *args: self.fail("coalesced intent must not insert"),
            update=lambda table, match, change: updates.append((match, change)),
            test_trigger=lambda task_id: self.fail("coalesced intent must not trigger"),
        )
        contract = types.SimpleNamespace(
            wrap_prompt=lambda prompt, **kwargs: prompt,
            note=lambda note, **kwargs: note,
        )
        with patch.object(enqueue_task, "db", db), \
             patch.object(enqueue_task, "pipeline_contract", contract), \
             patch.object(enqueue_task.tests_first_gate, "split_if_needed",
                          side_effect=lambda task, repo_path=None: [task]):
            enqueue_task.main(self._spec())

        self.assertEqual(updates[0][0], {"id": "old"})
        self.assertEqual(updates[0][1]["state"], "QUEUED")
        self.assertEqual(updates[0][1]["attempt"], 0)

    def test_refused_insert_is_an_error_not_a_false_queued_report(self):
        def select(table, params):
            if table == "projects":
                return [{"id": "p1", "name": "beethoven", "repo_path": "/tmp/orch",
                         "default_base": "master"}]
            return []

        db = types.SimpleNamespace(
            select=select, insert=lambda *args: None, update=lambda *args: None,
            test_trigger=lambda task_id: False,
        )
        contract = types.SimpleNamespace(
            wrap_prompt=lambda prompt, **kwargs: prompt,
            note=lambda note, **kwargs: note,
        )
        with patch.object(enqueue_task, "db", db), \
             patch.object(enqueue_task, "pipeline_contract", contract), \
             patch.object(enqueue_task.tests_first_gate, "split_if_needed",
                          side_effect=lambda task, repo_path=None: [task]):
            with self.assertRaisesRegex(RuntimeError, "no receipt"):
                enqueue_task.main(self._spec())

    def test_stage_intake_is_canonical_deterministic_and_preserves_operator_origin(self):
        with tempfile.TemporaryDirectory() as intake:
            spec_path = self._spec(deps=["first"], material=False)
            first = enqueue_task.stage_intake(spec_path, intake_dir=intake)
            second = enqueue_task.stage_intake(spec_path, intake_dir=intake)
            self.assertEqual(first, second)
            with open(first, encoding="utf-8") as source:
                rendered = source.read()
            self.assertIn("PROJECT: beethoven", rendered)
            self.assertIn("submitted-by: Codex operator-directed remediation", rendered)
            self.assertIn("depends: [first]", rendered)
            self.assertIn("proof: runner/tests/test_example.py", rendered)


if __name__ == "__main__":
    unittest.main()
