import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_gate
import dependency_prewarm


class TestBuildGate(unittest.TestCase):
    def test_yarn_lock_falls_back_to_npm_when_yarn_missing(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "nuxt build"}}, f)
        with open(os.path.join(d, "yarn.lock"), "w") as f:
            f.write("")
        orig = build_gate.shutil.which
        try:
            build_gate.shutil.which = lambda name: None if name == "yarn" else orig(name)
            self.assertEqual(build_gate.detect_build_cmd(d), "npm run build")
        finally:
            build_gate.shutil.which = orig

    def test_uses_installed_pnpm_for_pnpm_lock(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"typecheck": "vue-tsc --noEmit"}}, f)
        with open(os.path.join(d, "pnpm-lock.yaml"), "w") as f:
            f.write("")
        orig = build_gate.shutil.which
        try:
            build_gate.shutil.which = lambda name: "/usr/local/bin/pnpm" if name == "pnpm" else None
            self.assertEqual(build_gate.detect_build_cmd(d), "pnpm typecheck")
        finally:
            build_gate.shutil.which = orig

    def test_dependency_prewarm_uses_npm_when_yarn_missing(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "nuxt build"}}, f)
        with open(os.path.join(d, "yarn.lock"), "w") as f:
            f.write("")
        orig = dependency_prewarm.shutil.which
        try:
            dependency_prewarm.shutil.which = lambda name: None if name == "yarn" else orig(name)
            manager, cmd = dependency_prewarm._manager(d)
            self.assertEqual(manager, "npm")
            self.assertEqual([os.path.basename(cmd[0]), cmd[1]], ["npm", "install"])
        finally:
            dependency_prewarm.shutil.which = orig

    def test_dependency_prewarm_cache_skips_warm_repo(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "echo ok"}}, f)
        os.makedirs(os.path.join(d, "node_modules"))
        self.assertTrue(dependency_prewarm.deps_ready(d))

    def test_dependency_prewarm_prefers_package_lock_when_multiple_locks_exist(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({}, f)
        for name in ("package-lock.json", "pnpm-lock.yaml"):
            with open(os.path.join(d, name), "w") as f:
                f.write("{}")
        with patch.object(dependency_prewarm.shutil, "which", return_value="/usr/bin/tool"):
            manager, cmd = dependency_prewarm._manager(d)
        self.assertEqual(manager, "npm")
        self.assertEqual(cmd[1], "ci")

    def test_detects_nested_web_build_when_root_has_no_package(self):
        d = tempfile.mkdtemp()
        web = os.path.join(d, "web")
        os.makedirs(web)
        with open(os.path.join(web, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "nuxt build"}}, f)
        self.assertEqual(build_gate.detect_build_cmd(d), "npm --prefix web run build")

    def test_stale_root_build_cmd_is_replaced_for_nested_package(self):
        d = tempfile.mkdtemp()
        web = os.path.join(d, "web")
        os.makedirs(web)
        with open(os.path.join(web, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "vite build"}}, f)
        fake_db = MagicMock()
        with patch.object(build_gate, "db", fake_db):
            cmd = build_gate.build_cmd_for({"name": "app", "build_cmd": "npm run build"}, d)
        self.assertEqual(cmd, "npm --prefix web run build")
        fake_db.update.assert_called_once()

    def test_dependency_prewarm_ensure_all_warms_nested_packages(self):
        d = tempfile.mkdtemp()
        web = os.path.join(d, "web")
        os.makedirs(web)
        with open(os.path.join(web, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "echo ok"}}, f)

        calls = []

        def fake_ensure(root, reason="prewarm", timeout=None):
            calls.append((root, reason))
            return {"ok": True, "skipped": "test"}

        with patch.object(dependency_prewarm, "ensure", side_effect=fake_ensure):
            res = dependency_prewarm.ensure_all(d, reason="test")
        self.assertTrue(res["ok"])
        self.assertEqual(calls[0][0], web)
        self.assertEqual(res["roots"][0]["root"], "web")

    def test_dependency_prewarm_requires_tsc_for_typescript_builds(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "tsc --noEmit"}}, f)
        os.makedirs(os.path.join(d, "node_modules", ".bin"))
        self.assertFalse(dependency_prewarm.deps_ready(d))
        with open(os.path.join(d, "node_modules", ".bin", "tsc"), "w") as f:
            f.write("#!/bin/sh\n")
        self.assertTrue(dependency_prewarm.deps_ready(d))

    def test_dependency_prewarm_retries_install_without_lifecycle_scripts(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "echo ok", "postinstall": "nuxt prepare"}}, f)
        with open(os.path.join(d, "package-lock.json"), "w") as f:
            f.write("{}")

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            p = MagicMock()
            p.stdout = ""
            p.stderr = "postinstall failed"
            p.returncode = 1
            if "--ignore-scripts" in cmd:
                install_root = kwargs["cwd"]
                os.makedirs(os.path.join(install_root, "node_modules", ".bin"))
                with open(os.path.join(install_root, "node_modules", ".bin", "nuxi"), "w") as f:
                    f.write("#!/bin/sh\n")
                p.returncode = 0
            return p

        with patch.object(dependency_prewarm, "_STAMP_DIR", tempfile.mkdtemp()), \
             patch.object(dependency_prewarm.subprocess, "run", side_effect=fake_run):
            res = dependency_prewarm.ensure(d, reason="test")
        self.assertTrue(res["ok"])
        self.assertTrue(res["ignored_scripts"])
        self.assertIn("--ignore-scripts", calls[-1])
        self.assertFalse(os.path.exists(os.path.join(d, "node_modules")))

    def test_dependency_snapshot_is_atomically_activated_in_worktree(self):
        d = tempfile.mkdtemp()
        worktree = tempfile.mkdtemp()
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "echo ok"}}, f)

        def fake_run(cmd, **kwargs):
            if cmd[0] == "cp":
                shutil.copytree(cmd[-2], cmd[-1])
                return MagicMock(returncode=0, stdout="", stderr="")
            os.makedirs(os.path.join(kwargs["cwd"], "node_modules"))
            p = MagicMock(returncode=0, stdout="", stderr="")
            return p

        with patch.object(dependency_prewarm, "_STAMP_DIR", tempfile.mkdtemp()), \
             patch.object(dependency_prewarm.subprocess, "run", side_effect=fake_run):
            res = dependency_prewarm.ensure(d, reason="test")
            linked = dependency_prewarm.link_shared_runtime(d, worktree)
        target = os.path.join(worktree, "node_modules")
        self.assertTrue(res["ok"])
        self.assertIn(target, linked)
        self.assertTrue(os.path.isdir(target))
        self.assertFalse(os.path.samefile(target, os.path.join(res["snapshot"], "node_modules")))

    def test_snapshot_stages_local_file_dependencies(self):
        d = tempfile.mkdtemp()
        local = os.path.join(d, "stubs", "shim")
        os.makedirs(local)
        with open(os.path.join(local, "package.json"), "w") as f:
            json.dump({"name": "shim", "version": "1.0.0"}, f)
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"dependencies": {"shim": "file:./stubs/shim"}}, f)
        target = tempfile.mkdtemp()
        copied = dependency_prewarm._copy_local_dependencies(d, target)
        self.assertEqual(copied, ["./stubs/shim"])
        self.assertTrue(os.path.isfile(os.path.join(target, "stubs", "shim", "package.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
