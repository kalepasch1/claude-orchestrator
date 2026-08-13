#!/usr/bin/env python3
"""The toolchain gate only ever looked at the repository ROOT.

Task acceptance was stated as: "the commands `make --version`, `cmake --version`,
`gcc --version` (and any other tool referenced in the project's build files) return
valid version strings without 'command not found'."

Making that checkable — rather than installing packages once by hand and hoping —
turned up the reason the check could not have been trusted: the probe scan was

    if not any(os.path.isfile(os.path.join(repo_path, f)) for f in probe["files"])

so a config file one directory down did not exist as far as the gate was concerned.
In this repo `nuxt.config.ts`, `tsconfig.json` and `package-lock.json` all live under
`web/`, so the nuxt, tsc and npm probes never fired: the gate reported a READY
toolchain for a tree whose actual build tools it had never looked at, and the first
task to run discovered the breakage instead — which is the exact outcome the gate
exists to prevent.

Same monorepo blindness as the `clean_clone_gate` install-root bug, and it has the
same existing remedy: `dependency_prewarm.package_roots()`.

Also adds cmake/cc probes, gated on a declared native build so a pure-JS project is
never redded for a compiler it does not invoke.

NOT DONE HERE: installing system packages. Mutating the operator's machine with
brew/apt is outside a repo change, and an unattended `brew install` is not something
this task should perform silently. The check names what is missing; installing it
remains an explicit operator action.

Run: python3 -m unittest runner.tests.test_toolchain_gate_prereqs -v
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

import toolchain_gate as tg


def _write(path, payload=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(payload if isinstance(payload, str) else json.dumps(payload))


class _Monorepo:
    """Root holds an app-less package.json; the real app is under web/."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        _write(os.path.join(root, "package.json"), {"name": "orchestrator"})
        _write(os.path.join(root, "web", "package.json"), {"name": "web"})
        _write(os.path.join(root, "web", "tsconfig.json"), {})
        _write(os.path.join(root, "web", "nuxt.config.ts"), "export default {}\n")
        return root

    def __exit__(self, *exc):
        self.tmp.cleanup()


def _probe(name):
    return next(p for p in tg.PROBES if p["name"] == name)


class ProbeRootsTest(unittest.TestCase):
    def test_repo_root_is_always_first(self):
        with _Monorepo() as root:
            self.assertEqual(tg._probe_roots(root)[0], root)

    def test_nested_package_roots_are_included(self):
        with _Monorepo() as root:
            roots = tg._probe_roots(root)
        self.assertTrue(any(r.endswith("/web") for r in roots), roots)

    def test_no_duplicate_roots(self):
        with _Monorepo() as root:
            roots = tg._probe_roots(root)
        self.assertEqual(len(roots), len(set(roots)))

    def test_package_roots_failure_is_fail_soft(self):
        with _Monorepo() as root:
            with patch("dependency_prewarm.package_roots", side_effect=RuntimeError("boom")):
                self.assertEqual(tg._probe_roots(root), [root])


class ProbeTargetTest(unittest.TestCase):
    def test_nested_tsconfig_is_found(self):
        with _Monorepo() as root:
            target = tg._probe_target(root, _probe("tsc"))
        self.assertIsNotNone(target, "tsconfig.json under web/ was invisible to the gate")
        self.assertTrue(target[0].endswith("/web"))
        self.assertEqual(target[1], "tsconfig.json")

    def test_nested_nuxt_config_is_found(self):
        with _Monorepo() as root:
            target = tg._probe_target(root, _probe("nuxt"))
        self.assertIsNotNone(target)
        self.assertEqual(target[1], "nuxt.config.ts")

    def test_root_config_still_wins_over_nested(self):
        with _Monorepo() as root:
            _write(os.path.join(root, "tsconfig.json"), {})
            target = tg._probe_target(root, _probe("tsc"))
        self.assertEqual(target[0], root)

    def test_undeclared_tool_has_no_target(self):
        with _Monorepo() as root:
            self.assertIsNone(tg._probe_target(root, _probe("cargo")))


class SystemPrereqProbeTest(unittest.TestCase):
    """cmake/cc are probed only when a native build is declared."""

    def test_cmake_and_cc_probes_exist(self):
        names = {p["name"] for p in tg.PROBES}
        self.assertIn("cmake", names)
        self.assertIn("cc", names)

    def test_make_probe_exists(self):
        self.assertEqual(_probe("make")["cmd"], ["make", "--version"])

    def test_pure_js_project_does_not_probe_a_compiler(self):
        with _Monorepo() as root:
            self.assertIsNone(tg._probe_target(root, _probe("cmake")))
            self.assertIsNone(tg._probe_target(root, _probe("cc")))

    def test_cmake_project_probes_both(self):
        with _Monorepo() as root:
            _write(os.path.join(root, "CMakeLists.txt"), "project(x)\n")
            self.assertIsNotNone(tg._probe_target(root, _probe("cmake")))
            self.assertIsNotNone(tg._probe_target(root, _probe("cc")))

    def test_binding_gyp_probes_the_compiler_only(self):
        with _Monorepo() as root:
            _write(os.path.join(root, "binding.gyp"), "{}")
            self.assertIsNone(tg._probe_target(root, _probe("cmake")))
            self.assertIsNotNone(tg._probe_target(root, _probe("cc")))


class CheckProjectTest(unittest.TestCase):
    def test_missing_tool_is_reported_with_its_declaring_file(self):
        with _Monorepo() as root:
            with patch.object(tg.subprocess, "run",
                              side_effect=FileNotFoundError("no such binary")):
                result = tg.check_project("p1", root)
        self.assertFalse(result["ready"])
        tools = {f["tool"]: f for f in result["failures"]}
        self.assertIn("tsc", tools, "the nested tsconfig probe never ran")
        self.assertEqual(tools["tsc"]["declared_by"], "tsconfig.json")
        self.assertEqual(tools["tsc"]["root"], "web")
        self.assertIn("not found in PATH", tools["tsc"]["error"])

    def test_healthy_toolchain_is_ready(self):
        class _Ok:
            returncode = 0
            stderr = b""
        with _Monorepo() as root:
            with patch.object(tg.subprocess, "run", return_value=_Ok()), \
                 patch("dependency_prewarm.deps_ready", return_value=True):
                result = tg.check_project("p1", root)
        self.assertTrue(result["ready"], result["failures"])

    def test_missing_repo_is_assumed_ok(self):
        self.assertEqual(tg.check_project("p1", "/nope/not/here"),
                         {"ready": True, "failures": []})

    def test_no_repo_path_is_assumed_ok(self):
        self.assertTrue(tg.check_project("p1", None)["ready"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
