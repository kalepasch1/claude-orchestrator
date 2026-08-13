#!/usr/bin/env python3
"""The clean-clone gate installed one package and built another.

Reported failure (`python3 runner/clean_clone_gate.py beethoven`):

    $ npm ci --no-audit --no-fund
    up to date in 2s
    $ npm --prefix web run build
    sh: nuxt: command not found

Diagnosis — case (b), works-on-my-machine drift, the class the gate exists to catch:

  * `_deploy_root()` answers "where is vercel.json" and returned `.`.
  * `install_command()` resolved the lockfile against THAT root. beethoven commits a
    root `package-lock.json` beside a root `package.json` with no dependencies at all,
    so `npm ci` succeeded in 2s having installed nothing.
  * `build_command()` delegates to `build_gate.detect_build_cmd()`, which scans every
    package root and correctly picked `web/` — the deployable Nuxt app.
  * Nothing reconciled the two. `web/node_modules` was never created, so `nuxt` was
    absent, and the log said `command not found` — which reads like a missing
    dependency and sent repair passes hunting for one.

Warm repos hide it entirely: `web/node_modules` already exists locally, so the
failure only ever appears from a pristine `git archive` export — and on Vercel.

The fix: resolve the install root from the BUILD command, not from vercel.json.

Run: python3 -m unittest runner.tests.test_clean_clone_gate_install_root -v
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import clean_clone_gate as gate


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(payload if isinstance(payload, str) else json.dumps(payload))


class _Repo:
    """A monorepo shaped exactly like beethoven: empty root package, app in web/."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        _write(os.path.join(root, "package.json"),
               {"name": "orchestrator", "private": True, "scripts": {"test": "pytest"}})
        _write(os.path.join(root, "package-lock.json"), {"lockfileVersion": 3})
        _write(os.path.join(root, "vercel.json"), {})
        _write(os.path.join(root, "web", "package.json"),
               {"name": "web", "scripts": {"build": "nuxt build"},
                "dependencies": {"nuxt": "^3.13.0"}})
        _write(os.path.join(root, "web", "package-lock.json"), {"lockfileVersion": 3})
        return root

    def __exit__(self, *exc):
        self.tmp.cleanup()


def _tracked(root):
    """Stand in for `git ls-tree`: report a path as committed iff it exists on disk."""
    def fake_git(repo, *args):
        if args and args[0] == "ls-tree":
            rel = args[-1]
            return (0, rel, "") if os.path.exists(os.path.join(root, rel)) else (0, "", "")
        return (0, "", "")
    return fake_git


class BuildRootTest(unittest.TestCase):
    def test_prefix_in_the_build_command_is_the_install_root(self):
        with _Repo() as root:
            with patch("build_gate.detect_build_cmd", return_value="npm --prefix web run build"):
                self.assertEqual(gate.build_root(root, "."), "web")

    def test_quoted_prefix_is_parsed(self):
        with _Repo() as root:
            with patch("build_gate.detect_build_cmd", return_value='npm --prefix "web" run build'):
                self.assertEqual(gate.build_root(root, "."), "web")

    def test_nonexistent_prefix_is_ignored(self):
        with _Repo() as root:
            with patch("build_gate.detect_build_cmd", return_value="npm --prefix nope run build"):
                self.assertEqual(gate.build_root(root, "."), ".")

    def test_no_prefix_keeps_the_deploy_root(self):
        with _Repo() as root:
            with patch("build_gate.detect_build_cmd", return_value="npm run build"):
                self.assertEqual(gate.build_root(root, "."), ".")

    def test_detection_failure_is_fail_soft(self):
        with _Repo() as root:
            with patch("build_gate.detect_build_cmd", side_effect=RuntimeError("boom")):
                self.assertEqual(gate.build_root(root, "."), ".")

    def test_empty_build_command_keeps_the_deploy_root(self):
        with _Repo() as root:
            with patch("build_gate.detect_build_cmd", return_value=""):
                self.assertEqual(gate.build_root(root, "."), ".")


class InstallCommandTargetsBuildRootTest(unittest.TestCase):
    def test_install_is_scoped_to_the_build_package(self):
        with _Repo() as root:
            with patch.object(gate, "_git", _tracked(root)):
                cmd = gate.install_command(root, root, "HEAD", ".", install_root="web")
        self.assertEqual(cmd, "npm ci --prefix web --no-audit --no-fund")

    def test_deploy_root_install_is_unchanged_when_roots_agree(self):
        # Regression guard: single-package repos must keep the exact old command.
        with _Repo() as root:
            with patch.object(gate, "_git", _tracked(root)):
                cmd = gate.install_command(root, root, "HEAD", ".", install_root=".")
        self.assertEqual(cmd, "npm ci --no-audit --no-fund")

    def test_install_root_defaults_to_rel_root(self):
        with _Repo() as root:
            with patch.object(gate, "_git", _tracked(root)):
                self.assertEqual(gate.install_command(root, root, "HEAD", "."),
                                 "npm ci --no-audit --no-fund")

    def test_vercel_install_command_still_wins(self):
        with _Repo() as root:
            _write(os.path.join(root, "vercel.json"), {"installCommand": "npm ci --workspaces"})
            with patch.object(gate, "_git", _tracked(root)):
                cmd = gate.install_command(root, root, "HEAD", ".", install_root="web")
        self.assertEqual(cmd, "npm ci --workspaces")

    def test_pnpm_runs_in_the_package_dir_since_it_has_no_prefix(self):
        with _Repo() as root:
            os.remove(os.path.join(root, "web", "package-lock.json"))
            _write(os.path.join(root, "web", "pnpm-lock.yaml"), "lockfileVersion: 9\n")
            with patch.object(gate, "_git", _tracked(root)):
                cmd = gate.install_command(root, root, "HEAD", ".", install_root="web")
        self.assertEqual(cmd, "cd web && pnpm install --frozen-lockfile")

    def test_lockless_package_falls_back_to_npm_install_with_prefix(self):
        with _Repo() as root:
            os.remove(os.path.join(root, "web", "package-lock.json"))
            with patch.object(gate, "_git", _tracked(root)):
                cmd = gate.install_command(root, root, "HEAD", ".", install_root="web")
        self.assertEqual(cmd, "npm install --prefix web --no-audit --no-fund")


class RegressionShapeTest(unittest.TestCase):
    """The reported failure, reproduced as a shape assertion."""

    def test_install_and_build_now_target_the_same_package(self):
        with _Repo() as root:
            build_cmd = "npm --prefix web run build"
            with patch("build_gate.detect_build_cmd", return_value=build_cmd), \
                 patch.object(gate, "_git", _tracked(root)):
                inst_root = gate.build_root(root, ".")
                install_cmd = gate.install_command(root, root, "HEAD", ".",
                                                   install_root=inst_root)
        self.assertIn("--prefix web", install_cmd)
        self.assertIn("--prefix web", build_cmd)

    def test_the_old_pairing_is_what_produced_command_not_found(self):
        # Documents the defect: a bare `npm ci` installs the empty root package,
        # leaving web/node_modules absent for a build that runs in web/.
        with _Repo() as root:
            with patch.object(gate, "_git", _tracked(root)):
                old = gate.install_command(root, root, "HEAD", ".", install_root=".")
        self.assertNotIn("web", old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
