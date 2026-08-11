"""Regression tests for the ChatGPT/Codex local-build queue bridge."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "chatgpt-bridge" / "local_build_audit.py"
SPEC = importlib.util.spec_from_file_location("local_build_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(audit)


class LocalBuildAuditTest(unittest.TestCase):
    def test_timestamped_failed_patch_uses_original_repo_prefix(self):
        targets = {
            "apparently": Path("/tmp/apparently"),
            "smarter": Path("/tmp/smarter"),
        }
        path = Path(
            "/tmp/chatgpt-dropbox/_failed/"
            "20260807-085521--smarter--apparently-framework-merge.patch"
        )
        self.assertEqual(audit.infer_artifact_project(path, targets), "smarter")

    def test_aliases_cover_legacy_app_names(self):
        targets = {
            "beethoven": Path("/tmp/orch"),
            "pareto-2080": Path("/tmp/2080"),
            "santas-secret-workshop": Path("/tmp/hisanta"),
            "illuminati": Path("/tmp/illuminati"),
        }
        self.assertEqual(
            audit.infer_artifact_project(Path("/tmp/claude-orchestrator--fix.patch"), targets),
            "beethoven",
        )
        self.assertEqual(
            audit.infer_artifact_project(Path("/tmp/2080--fix.patch"), targets), "pareto-2080"
        )
        self.assertEqual(
            audit.infer_artifact_project(Path("/tmp/hisanta--fix.patch"), targets),
            "santas-secret-workshop",
        )
        self.assertEqual(
            audit.infer_artifact_project(Path("/tmp/trojun--fix.patch"), targets), "illuminati"
        )

    def test_queue_registration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake, state = root / "intake", root / "state.json"
            groups = {"smarter": [{"kind": "artifact", "path": "/tmp/a.patch", "sha256": "abc"}]}
            first, duplicate = audit.queue_groups(groups, intake, state)
            self.assertEqual(len(first), 1)
            self.assertEqual(duplicate, [])
            second, duplicate = audit.queue_groups(groups, intake, state)
            self.assertEqual(second, [])
            self.assertEqual(len(duplicate), 1)
            files = list(intake.glob("*.md"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertIn("PROJECT: smarter", text)
            self.assertIn("RECOVERABLE_VALUE", text)
            saved = json.loads(state.read_text())
            self.assertEqual(len(saved["queued"]), 1)
            self.assertEqual(len(saved["evidence"]), 1)

    def test_evidence_level_registry_does_not_requeue_when_group_shrinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake, state = root / "intake", root / "state.json"
            a = {"kind": "artifact", "path": "/tmp/a.patch", "sha256": "a"}
            b = {"kind": "artifact", "path": "/tmp/b.patch", "sha256": "b"}
            c = {"kind": "artifact", "path": "/tmp/c.patch", "sha256": "c"}
            first, _ = audit.queue_groups({"smarter": [a, b]}, intake, state)
            self.assertEqual(len(first), 1)
            second, duplicates = audit.queue_groups({"smarter": [a]}, intake, state)
            self.assertEqual(second, [])
            self.assertEqual(len(duplicates), 1)
            third, _ = audit.queue_groups({"smarter": [a, c]}, intake, state)
            self.assertEqual(len(third), 1)
            rendered = Path(third[0]["intake"]).read_text()
            self.assertIn("/tmp/c.patch", rendered)
            self.assertNotIn("/tmp/a.patch", rendered)

    def test_scanner_ignores_its_own_intake_manifests(self):
        self.assertTrue(audit._is_scanner_output("intake/chatgpt-local-audit-smarter-a.md"))
        self.assertTrue(audit._is_scanner_output(
            "intake/processed/20260811-chatgpt-local-audit-smarter-a.md"
        ))
        self.assertFalse(audit._is_scanner_output("runner/intake_watcher.py"))

    def test_registry_writer_lock_is_exclusive_and_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            first = audit._acquire_run_lock(state)
            self.assertIsNotNone(first)
            self.assertIsNone(audit._acquire_run_lock(state))
            first.close()
            successor = audit._acquire_run_lock(state)
            self.assertIsNotNone(successor)
            successor.close()

    def test_large_ref_collections_are_digested_in_prompt(self):
        evidence = [{
            "kind": "orchestrator_rescue_refs",
            "repo": "/tmp/repo",
            "count": 100,
            "items": [{"ref": f"refs/orch-rescue/{n}", "sha": str(n)} for n in range(100)],
        }]
        rendered = audit._render_task("beethoven", evidence, "a" * 64)
        self.assertIn('"items_total": 100', rendered)
        self.assertIn('"items_digest":', rendered)
        self.assertNotIn("refs/orch-rescue/99", rendered)

    def test_tree_mtime_skips_protected_env_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env.example").write_text("not-read")
            (root / "code.py").write_text("print('ok')")
            self.assertGreater(audit._tree_newest_mtime(root), 0)


if __name__ == "__main__":
    unittest.main()
