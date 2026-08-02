"""vercel_config_guard: the deploy-config bugs a local `npm run build` cannot catch.

Each test builds a throwaway git repo that reproduces one of the 2026-08-02 outages.
"""
import os
import subprocess
import sys
import tempfile
import shutil
import json
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import vercel_config_guard


def _repo(files, commit=None):
    """Create a git repo containing <files>; commit only <commit> (default: everything)."""
    root = tempfile.mkdtemp(prefix="vcg-test-")
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


class VercelConfigGuardTest(unittest.TestCase):

    def setUp(self):
        self.roots = []

    def tearDown(self):
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)

    def _make(self, files, commit=None):
        root = _repo(files, commit)
        self.roots.append(root)
        return root

    def _codes(self, root):
        result = vercel_config_guard.check_repo(root, "HEAD", "test")
        return [v["code"] for v in result["violations"]], result

    def test_npm_ci_without_committed_lockfile_blocks(self):
        """vigil: `npm ci` with package-lock.json on disk but never committed."""
        root = self._make(
            {"vercel.json": json.dumps({"installCommand": "npm ci", "buildCommand": "npm run build"}),
             "package.json": json.dumps({"scripts": {"build": "node build.mjs"}}),
             "build.mjs": "console.log(1)\n",
             "package-lock.json": '{"lockfileVersion": 3}\n'},
            commit=["vercel.json", "package.json", "build.mjs"])
        codes, result = self._codes(root)
        self.assertIn("lockfile_not_committed", codes)
        self.assertFalse(result["ok"])
        self.assertIn("never committed", " ".join(v["detail"] for v in result["violations"]))

    def test_committed_lockfile_is_clean(self):
        root = self._make(
            {"vercel.json": json.dumps({"installCommand": "npm ci", "buildCommand": "npm run build"}),
             "package.json": json.dumps({"scripts": {"build": "node build.mjs"}}),
             "build.mjs": "console.log(1)\n",
             "package-lock.json": '{"lockfileVersion": 3}\n'})
        codes, result = self._codes(root)
        self.assertEqual(codes, [])
        self.assertTrue(result["ok"])

    def test_vercelignore_stripping_a_build_input_blocks(self):
        """vigil: .vercelignore had `scripts/` while buildCommand ran scripts/release-gate.mjs."""
        root = self._make(
            {"vercel.json": json.dumps({"buildCommand": "npm run gate"}),
             "package.json": json.dumps({"scripts": {"gate": "node scripts/release-gate.mjs"}}),
             "scripts/release-gate.mjs": "console.log(1)\n",
             ".vercelignore": "scripts/\n"})
        codes, _ = self._codes(root)
        self.assertIn("build_input_vercelignored", codes)

    def test_vercelignore_negation_is_respected(self):
        """The real fix vigil shipped: re-include the one script the build needs."""
        root = self._make(
            {"vercel.json": json.dumps({"buildCommand": "npm run gate"}),
             "package.json": json.dumps({"scripts": {"gate": "node scripts/release-gate.mjs"}}),
             "scripts/release-gate.mjs": "console.log(1)\n",
             ".vercelignore": "scripts/\n!scripts/\n!scripts/release-gate.mjs\n"})
        codes, _ = self._codes(root)
        self.assertNotIn("build_input_vercelignored", codes)

    def test_output_directory_that_nothing_emits_blocks(self):
        """apparently-law: "build": "node --check foo.js" emitted nothing for outputDirectory."""
        root = self._make(
            {"vercel.json": json.dumps({"framework": None, "outputDirectory": "public",
                                        "buildCommand": "npm run build"}),
             "package.json": json.dumps({"scripts": {"check": "node --check contracts/hub.js",
                                                     "build": "npm run check && npm test",
                                                     "test": "node --test test/*.test.js"}}),
             "contracts/hub.js": "console.log(1)\n"})
        codes, _ = self._codes(root)
        self.assertIn("output_dir_never_built", codes)

    def test_output_directory_with_a_real_emitter_is_clean(self):
        root = self._make(
            {"vercel.json": json.dumps({"framework": None, "outputDirectory": "public",
                                        "buildCommand": "npm run build"}),
             "package.json": json.dumps({"scripts": {"check": "node --check contracts/hub.js",
                                                     "build": "npm run check && node scripts/build.mjs"}}),
             "scripts/build.mjs": "console.log(1)\n",
             "contracts/hub.js": "console.log(1)\n"})
        codes, _ = self._codes(root)
        self.assertNotIn("output_dir_never_built", codes)

    def test_missing_package_script_blocks(self):
        root = self._make(
            {"vercel.json": json.dumps({"buildCommand": "npm run nope"}),
             "package.json": json.dumps({"scripts": {"build": "node build.mjs"}}),
             "build.mjs": "console.log(1)\n"})
        codes, _ = self._codes(root)
        self.assertIn("missing_package_script", codes)

    def test_npm_builtin_is_not_mistaken_for_a_script(self):
        """pareto-2080 regression: `npm rebuild @prisma/engines` is a builtin, not `npm run rebuild`."""
        root = self._make(
            {"vercel.json": json.dumps({"buildCommand": "npm run build"}),
             "package.json": json.dumps({"scripts": {"build": "npm rebuild @prisma/engines; node build.mjs"}}),
             "build.mjs": "console.log(1)\n"})
        codes, _ = self._codes(root)
        self.assertNotIn("missing_package_script", codes)

    def test_resolve_chain_expands_and_terminates_on_cycles(self):
        scripts = {"a": "npm run b", "b": "npm run a && node x.mjs"}
        leaves, missing = vercel_config_guard.resolve_chain(scripts, "npm run a")
        self.assertEqual(missing, [])
        self.assertIn("node x.mjs", leaves)

    def test_emits_output_classification(self):
        self.assertFalse(vercel_config_guard.emits_output(
            ["node --check a.js", "node --test t.js", "eslint .", "echo hi"]))
        self.assertTrue(vercel_config_guard.emits_output(["node --check a.js", "next build"]))

    def test_gate_is_fail_closed_on_a_blocking_violation(self):
        root = self._make(
            {"vercel.json": json.dumps({"installCommand": "npm ci"}),
             "package.json": json.dumps({"scripts": {"build": "node build.mjs"}}),
             "build.mjs": "console.log(1)\n"})
        fake_db = MagicMock()
        fake_db.select.return_value = [{"name": "test", "repo_path": root, "prod_branch": "HEAD"}]
        with patch.object(vercel_config_guard, "db", fake_db):
            ok, log = vercel_config_guard.gate("test", "HEAD")
        self.assertFalse(ok)
        self.assertIn("lockfile_not_committed", log)

    def test_gate_skips_a_repo_that_is_not_on_this_machine(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{"name": "test", "repo_path": "/nope/not/here"}]
        with patch.object(vercel_config_guard, "db", fake_db):
            ok, log = vercel_config_guard.gate("test")
        self.assertTrue(ok)
        self.assertIn("skipped", log)


if __name__ == "__main__":
    unittest.main()
