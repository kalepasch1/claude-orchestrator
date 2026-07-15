import os
import sys
import types
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import parallel_dispatch


class ParallelDispatchVerificationTests(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CLAUDE_ORCH_HOME": self.runtime.name})
        self.env.start()
        self.task = {"id": "t1", "slug": "fast-fix", "project_id": "p", "kind": "bugfix",
                     "prompt": "Fix the bounded issue", "base_branch": "main"}
        self.swarm_calls = []
        def _run_swarm(**kw):
            self.swarm_calls.append(kw)
            return {"returncode": 0, "text": "diff --git a/a b/a\n",
                                     "cost_usd": 0.01, "input_tokens": 10,
                                     "output_tokens": 20, "coder": "test", "model": "m"}
        self.swarm = types.SimpleNamespace(
            run_swarm=_run_swarm,
            _budget_lock=mock.MagicMock(), _spend_log=[],
            PROVIDERS={"openai": {"key_env": "OPENAI_API_KEY", "models": {"mid": "gpt-test"}}},
            _provider_for_model=lambda _model: "openai",
        )
        self.ledger = types.SimpleNamespace(record_execution=lambda *_a, **_kw: None)
        self.assembler = types.SimpleNamespace(assemble=lambda body, **_kw: {"prompt": body})
        self.contract = types.SimpleNamespace(original_request=lambda prompt: prompt)

    def tearDown(self):
        self.env.stop()
        self.runtime.cleanup()

    def _project_select(self, table, *_args, **_kwargs):
        if table == "projects":
            return [{"id": "p", "name": "app", "repo_path": "/repo",
                     "test_cmd": "pytest", "default_base": "main"}]
        return []

    def test_done_requires_verified_artifact(self):
        verified = {"ok": True, "artifact_id": "a" * 64, "branch": "agent/fast-fix",
                    "wall_s": 1, "diff_bytes": 10}
        updates = []
        fabric = types.SimpleNamespace(materialize=lambda *_a, **_k: verified)
        with mock.patch.dict(sys.modules, {"swarm_executor": self.swarm, "patch_fabric": fabric,
                                           "value_ledger": self.ledger,
                                           "prompt_assembler": self.assembler, "pipeline_contract": self.contract}), \
             mock.patch.object(parallel_dispatch.db, "select", side_effect=self._project_select), \
             mock.patch.object(parallel_dispatch.db, "localize_repo_path", return_value="/repo"), \
             mock.patch.object(parallel_dispatch.db, "update", side_effect=lambda *a: updates.append(a)), \
             mock.patch.object(parallel_dispatch.db, "insert", return_value=[]):
            result = parallel_dispatch._dispatch_one_api(self.task)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(updates[-1][2]["state"], "DONE")
        self.assertIn("verify pass", updates[-1][2]["note"])
        self.assertFalse(self.swarm_calls[-1]["apply_diff"])
        self.assertTrue(self.swarm_calls[-1]["repo_cache"])

    def test_failed_verification_requeues_for_full_pipeline(self):
        fabric = types.SimpleNamespace(materialize=lambda *_a, **_k: {
            "ok": False, "stage": "test", "reason": "red build", "wall_s": 1
        })
        updates = []
        with mock.patch.dict(sys.modules, {"swarm_executor": self.swarm, "patch_fabric": fabric,
                                           "value_ledger": self.ledger,
                                           "prompt_assembler": self.assembler, "pipeline_contract": self.contract}), \
             mock.patch.object(parallel_dispatch.db, "select", side_effect=self._project_select), \
             mock.patch.object(parallel_dispatch.db, "localize_repo_path", return_value="/repo"), \
             mock.patch.object(parallel_dispatch.db, "update", side_effect=lambda *a: updates.append(a)), \
             mock.patch.object(parallel_dispatch.db, "insert", return_value=[]):
            result = parallel_dispatch._dispatch_one_api(self.task)
        self.assertEqual(result["status"], "requeued")
        self.assertEqual(updates[-1][2]["state"], "QUEUED")
        self.assertEqual(updates[-1][2]["force_coder"], "aider")
        self.assertIn("patch-fabric-fail:test", updates[-1][2]["note"])


if __name__ == "__main__":
    unittest.main()
