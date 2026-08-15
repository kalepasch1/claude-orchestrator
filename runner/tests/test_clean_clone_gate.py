"""clean_clone_gate: prove a pristine export catches drift a warm local build hides."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clean_clone_gate


def _repo(files, commit=None):
    root = tempfile.mkdtemp(prefix="ccg-test-")
    for rel, body in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body)
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add"] + (list(commit) if commit is not None else ["-A"]),
                   cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    return root


class CleanCloneGateTest(unittest.TestCase):

    def setUp(self):
        self.roots = []
        self.proof = MagicMock()
        self.proof.reusable_verification.return_value = None

    def tearDown(self):
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)

    def _make(self, files, commit=None):
        root = _repo(files, commit)
        self.roots.append(root)
        return root

    def test_export_tree_contains_only_committed_files(self):
        root = self._make({"a.txt": "a\n", "b.txt": "b\n"}, commit=["a.txt"])
        dest = tempfile.mkdtemp(prefix="ccg-export-")
        self.roots.append(dest)
        ok, err = clean_clone_gate.export_tree(root, "HEAD", dest)
        self.assertTrue(ok, err)
        self.assertTrue(os.path.isfile(os.path.join(dest, "a.txt")))
        self.assertFalse(os.path.isfile(os.path.join(dest, "b.txt")))
        self.assertFalse(os.path.isdir(os.path.join(dest, ".git")))

    def test_uncommitted_build_input_fails_even_though_local_build_passes(self):
        """The whole point: node_modules is warm and helper.mjs is on disk, but never committed."""
        root = self._make(
            {"package.json": json.dumps({"scripts": {"build": "node build.mjs"}}),
             "build.mjs": "import './helper.mjs';\nconsole.log('built');\n",
             "helper.mjs": "export const x = 1;\n"},
            commit=["package.json", "build.mjs"])
        local = subprocess.run(["node", "build.mjs"], cwd=root, capture_output=True)
        self.assertEqual(local.returncode, 0, "warm local build should pass")
        with patch.object(clean_clone_gate, "proof_graph", self.proof):
            result = clean_clone_gate.verify(root, "HEAD", "test")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["failed_step"], "build")
        self.assertIn("helper.mjs", result["log"])

    def test_fully_committed_tree_is_green_and_records_a_proof(self):
        root = self._make(
            {"package.json": json.dumps({"scripts": {"build": "node build.mjs"}}),
             "build.mjs": "console.log('built');\n"})
        with patch.object(clean_clone_gate, "proof_graph", self.proof):
            result = clean_clone_gate.verify(root, "HEAD", "test")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["cached"])
        self.assertTrue(self.proof.record_verification.called)

    def test_a_recorded_proof_is_reused_instead_of_rebuilding(self):
        root = self._make(
            {"package.json": json.dumps({"scripts": {"build": "node build.mjs"}}),
             "build.mjs": "console.log('built');\n"})
        self.proof.reusable_verification.return_value = {"success": True}
        with patch.object(clean_clone_gate, "proof_graph", self.proof):
            result = clean_clone_gate.verify(root, "HEAD", "test")
        self.assertTrue(result["ok"])
        self.assertTrue(result["cached"])
        self.assertFalse(self.proof.record_verification.called)

    def test_cache_key_is_the_tree_sha(self):
        root = self._make({"package.json": json.dumps({"scripts": {"build": "true"}})})
        tree = clean_clone_gate.tree_sha(root, "HEAD")
        self.assertEqual(len(tree), 40)
        self.assertNotEqual(tree, subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip())

    def test_install_command_prefers_npm_ci_when_the_lockfile_is_committed(self):
        root = self._make({"package.json": "{}\n", "package-lock.json": "{}\n"})
        self.assertIn("npm ci", clean_clone_gate.install_command(root, root, "HEAD", "."))

    def test_install_command_falls_back_when_no_lockfile_is_committed(self):
        root = self._make({"package.json": "{}\n", "package-lock.json": "{}\n"},
                          commit=["package.json"])
        self.assertEqual(clean_clone_gate.install_command(root, root, "HEAD", "."),
                         "npm install --no-audit --no-fund")

    def test_network_failure_is_inconclusive_not_red(self):
        root = self._make({"package.json": json.dumps({"scripts": {"build": "true"}}),
                           "vercel.json": json.dumps({"installCommand": "false"})})
        with patch.object(clean_clone_gate, "proof_graph", self.proof), \
             patch.object(clean_clone_gate, "_step",
                          return_value=(1, "npm ERR! request to https://registry.npmjs.org failed, ETIMEDOUT")):
            result = clean_clone_gate.verify(root, "HEAD", "test")
        self.assertIsNone(result["ok"])
        self.assertIn("inconclusive", result["skipped"])

    def test_gate_is_fail_closed_on_a_red_clean_clone(self):
        root = self._make(
            {"package.json": json.dumps({"scripts": {"build": "node build.mjs"}}),
             "build.mjs": "import './helper.mjs';\n",
             "helper.mjs": "export const x = 1;\n"},
            commit=["package.json", "build.mjs"])
        fake_db = MagicMock()
        fake_db.select.return_value = [{"name": "test", "repo_path": root, "prod_branch": "HEAD"}]
        with patch.object(clean_clone_gate, "db", fake_db), \
             patch.object(clean_clone_gate, "proof_graph", self.proof):
            ok, log = clean_clone_gate.gate("test", "HEAD")
        self.assertFalse(ok)
        self.assertIn("pristine export", log)

    def test_gate_does_not_block_when_the_run_is_inconclusive(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{"name": "test", "repo_path": "/nope/not/here"}]
        with patch.object(clean_clone_gate, "db", fake_db):
            ok, log = clean_clone_gate.gate("test")
        self.assertTrue(ok)
        self.assertIn("not on this machine", log)


if __name__ == "__main__":
    unittest.main()
