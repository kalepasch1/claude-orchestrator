import os
import sys
import types
import unittest
from unittest.mock import patch

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

    def test_choose_coder_uses_fast_default_without_full_router_by_default(self):
        router = types.SimpleNamespace(pick=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("router called")))
        with patch.dict(sys.modules, {"agentic_coders": router}), \
             patch.dict(os.environ, {"ORCH_AGENTIC_REPAIR_DEFAULT_CODER": "ollama"}, clear=False):
            self.assertEqual(agentic_repair.choose_coder({"slug": "repair-me"}), "ollama")


if __name__ == "__main__":
    unittest.main()
