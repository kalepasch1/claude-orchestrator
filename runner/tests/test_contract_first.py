"""Tests for contract-first verification in pipeline_contract and planner.
Run: python3 -m pytest runner/tests -q -k contract_first
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline_contract


class TestContractFirstVerify(unittest.TestCase):
    def test_valid_dag_with_test_task_in_deps(self):
        tasks = [
            {"slug": "contracts", "deps": []},
            {"slug": "foo-write-tests", "deps": ["contracts"]},
            {"slug": "foo", "deps": ["contracts", "foo-write-tests"]},
        ]
        result = pipeline_contract.verify_contract_first(tasks)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["errors"]), 0)
        self.assertIn("foo", result["verified"])

    def test_test_task_exists_but_not_in_deps(self):
        tasks = [
            {"slug": "contracts", "deps": []},
            {"slug": "bar-write-tests", "deps": ["contracts"]},
            {"slug": "bar", "deps": ["contracts"]},  # missing bar-write-tests
        ]
        result = pipeline_contract.verify_contract_first(tasks)
        self.assertFalse(result["ok"])
        self.assertTrue(any("bar" in e for e in result["errors"]))

    def test_no_test_task_is_ok(self):
        """Tasks without a sibling test task are not errors (TDD not required)."""
        tasks = [
            {"slug": "contracts", "deps": []},
            {"slug": "simple-fix", "deps": ["contracts"]},
        ]
        result = pipeline_contract.verify_contract_first(tasks)
        self.assertTrue(result["ok"])

    def test_contracts_task_skipped(self):
        tasks = [{"slug": "contracts", "deps": []}]
        result = pipeline_contract.verify_contract_first(tasks)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["verified"]), 0)

    def test_verify_with_repo_path_finds_test_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_dir = os.path.join(tmp, "runner", "tests")
            os.makedirs(test_dir)
            test_file = os.path.join(test_dir, "test_my_feature.py")
            with open(test_file, "w") as f:
                f.write("def test_something(): assert True\n")
            tasks = [{"slug": "my-feature", "deps": ["contracts"]}]
            result = pipeline_contract.verify_contract_first(tasks, repo_path=tmp)
            self.assertTrue(result["ok"])
            self.assertTrue(any("active" in v for v in result["verified"]))

    def test_verify_with_xfail_test_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_dir = os.path.join(tmp, "runner", "tests")
            os.makedirs(test_dir)
            test_file = os.path.join(test_dir, "test_my_feature.py")
            with open(test_file, "w") as f:
                f.write("import pytest\n@pytest.mark.xfail\ndef test_x(): assert False\n")
            tasks = [{"slug": "my-feature", "deps": ["contracts"]}]
            result = pipeline_contract.verify_contract_first(tasks, repo_path=tmp)
            self.assertTrue(any("xfail" in v for v in result["verified"]))


class TestContractFirstProofRewrite(unittest.TestCase):
    def test_empty_proof_rewritten(self):
        result = pipeline_contract.rewrite_proof_for_contract_first("", "foo-write-tests")
        self.assertIn("foo-write-tests", result)
        self.assertIn("passes", result)

    def test_generic_proof_rewritten(self):
        result = pipeline_contract.rewrite_proof_for_contract_first("tests pass", "bar-write-tests")
        self.assertIn("bar-write-tests", result)

    def test_specific_proof_preserved(self):
        proof = "python3 -m pytest runner/tests -k my_test exits 0"
        result = pipeline_contract.rewrite_proof_for_contract_first(proof, "x-write-tests")
        self.assertEqual(result, proof)


class TestContractFirstPlannerOutputShape(unittest.TestCase):
    """Verify that planner's _apply_tdd_gating produces the right shape."""

    def test_tdd_gated_task_gets_test_sibling(self):
        """When TDD gating is active, test task precedes code task in deps."""
        import planner
        import tdd_gate
        from unittest.mock import patch

        tasks = [
            {"slug": "contracts", "deps": [], "prompt": "Define interfaces"},
            {"slug": "build-widget", "deps": ["contracts"], "prompt": "Build the widget"},
        ]
        with patch.object(tdd_gate, "is_tdd_enabled", return_value=True), \
             patch.object(tdd_gate, "get_task_kinds", return_value=["build"]), \
             patch.object(tdd_gate, "is_tdd_gated", side_effect=lambda s: s != "contracts"):
            result = planner._apply_tdd_gating(tasks)

        slugs = [t["slug"] for t in result]
        self.assertIn("build-widget-write-tests", slugs)
        self.assertIn("build-widget", slugs)
        # Test task must come before code task
        test_idx = slugs.index("build-widget-write-tests")
        code_idx = slugs.index("build-widget")
        self.assertLess(test_idx, code_idx)
        # Code task must depend on test task
        code_task = result[code_idx]
        self.assertIn("build-widget-write-tests", code_task["deps"])
        # Code task should have rewritten proof
        self.assertIn("acceptance test", code_task.get("proof", ""))


if __name__ == "__main__":
    unittest.main()
