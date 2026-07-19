import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agentic_repair


class AgenticRepairTest(unittest.TestCase):
    def test_repair_patch_preserves_same_task_and_injects_failure_context(self):
        task = {
            "id": "t1",
            "slug": "fix-build",
            "prompt": "Fix the build failure.",
            "remediation_count": 2,
            "attempt": 1,
        }
        with patch.object(agentic_repair, "choose_coder", return_value="ollama"):
            patch_row = agentic_repair.repair_patch(
                task,
                "npm run build failed: missing import",
                category="buildfail",
                directive="Fix the build and rerun it.",
            )

        self.assertEqual(patch_row["state"], "QUEUED")
        self.assertEqual(patch_row["force_coder"], "ollama")
        self.assertEqual(patch_row["remediation_count"], 3)
        self.assertIn(agentic_repair.MARKER, patch_row["prompt"])
        self.assertIn("This is not a fresh requeue", patch_row["prompt"])
        self.assertIn("missing import", patch_row["prompt"])
        self.assertIn("agentic-repair:buildfail", patch_row["note"])

    def test_choose_coder_env_override_takes_priority(self):
        router = types.SimpleNamespace(pick=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("router called")))
        with patch.dict(sys.modules, {"agentic_coders": router}), \
             patch.dict(os.environ, {"ORCH_AGENTIC_REPAIR_DEFAULT_CODER": "deepseek"}, clear=False):
            self.assertEqual(agentic_repair.choose_coder({"slug": "repair-me"}), "deepseek")

    def test_choose_coder_falls_back_to_claude_not_ollama_when_router_unavailable(self):
        """Closing the unsafe path: if the router is missing and no env var is set,
        we must NOT fall back to 'ollama' (which can timeout and wedge the repair queue)."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("ORCH_AGENTIC_REPAIR_DEFAULT_CODER", "ORCH_REPAIR_CODER_FALLBACK")}
        with patch.dict(sys.modules, {"agentic_coders": None}, clear=False), \
             patch.dict(os.environ, env, clear=True):
            result = agentic_repair.choose_coder({"slug": "repair-me"})
        self.assertEqual(result, "claude", "fallback must be 'claude', not 'ollama'")

    def test_choose_coder_fallback_configurable_via_env(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("ORCH_AGENTIC_REPAIR_DEFAULT_CODER", "ORCH_REPAIR_CODER_FALLBACK")}
        env["ORCH_REPAIR_CODER_FALLBACK"] = "deepseek"
        with patch.dict(sys.modules, {"agentic_coders": None}, clear=False), \
             patch.dict(os.environ, env, clear=True):
            result = agentic_repair.choose_coder({"slug": "repair-me"})
        self.assertEqual(result, "deepseek")

    def test_repair_prompt_includes_agentic_artifacts_when_available(self):
        task = {
            "id": "t2",
            "slug": "add-widget",
            "prompt": "Add a new widget.",
        }
        fake_artifacts = MagicMock()
        fake_artifacts.get_artifacts.return_value = {
            "commit_sha": "abc1234",
            "touched_files": '["src/widget.py", "tests/test_widget.py"]',
            "patch_diff": "diff --git a/src/widget.py b/src/widget.py\n+# new widget",
        }
        with patch.dict(sys.modules, {"task_artifacts": fake_artifacts}):
            prompt = agentic_repair.repair_prompt(task, "some failure", "Fix it.", category="testfail")

        self.assertIn("Agentic analysis artifacts from prior run:", prompt)
        self.assertIn("src/widget.py", prompt)
        self.assertIn("abc1234", prompt)
        self.assertIn("diff --git", prompt)
        self.assertIn("Failure context:", prompt)
        self.assertIn("some failure", prompt)

    def test_repair_prompt_is_unchanged_when_no_artifacts(self):
        task = {
            "id": "t3",
            "slug": "new-feature",
            "prompt": "Implement new feature.",
        }
        fake_artifacts = MagicMock()
        fake_artifacts.get_artifacts.return_value = None
        with patch.dict(sys.modules, {"task_artifacts": fake_artifacts}):
            prompt = agentic_repair.repair_prompt(task, "build failed", "Fix the build.", category="buildfail")

        self.assertNotIn("Agentic analysis artifacts", prompt)
        self.assertIn("Failure context:", prompt)
        self.assertIn("build failed", prompt)
        self.assertIn(agentic_repair.MARKER, prompt)

    def test_agentic_artifacts_context_is_fail_soft_on_import_error(self):
        with patch.dict(sys.modules, {"task_artifacts": None}):
            result = agentic_repair._agentic_artifacts_context("some-slug")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
