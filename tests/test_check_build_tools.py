#!/usr/bin/env python3
"""scripts/check-build-tools.sh — the native toolchain report.

The acceptance for this task is that `gcc --version`, `make --version` and (if needed)
`cmake --version` run successfully. Rather than assert that on whatever machine happens
to run the suite — which would make the test a property of the runner, not of the repo —
these tests assert the *checker's* contract:

  * required tools present  -> exit 0
  * a required tool missing -> exit 1, and the report names it
  * an optional tool missing -> still exit 0, reported but not fatal
  * every miss carries a platform-appropriate install command

The script installs nothing on purpose. A background agent must not mutate the
operator's system packages, so it prints the command and stops.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "check-build-tools.sh")


def run(args=(), path=None):
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True,
                          env=env, timeout=120)


class ScriptExistsTest(unittest.TestCase):
    def test_the_script_is_present_and_executable(self):
        self.assertTrue(os.path.isfile(SCRIPT))
        self.assertTrue(os.access(SCRIPT, os.X_OK), "should be chmod +x")

    def test_the_makefile_exposes_it(self):
        with open(os.path.join(REPO_ROOT, "Makefile"), encoding="utf-8") as handle:
            makefile = handle.read()
        self.assertIn("check-build-tools:", makefile)
        self.assertIn("scripts/check-build-tools.sh", makefile)
        self.assertIn("check-build-tools", makefile.split(".PHONY:")[1][:200])


class HappyPathTest(unittest.TestCase):
    def test_this_machine_has_every_required_tool(self):
        """cc, make, git and python3 are the four the fleet cannot run without."""
        result = run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("all required build tools present", result.stdout)

    def test_the_report_names_a_version_for_each_present_tool(self):
        result = run()
        for tool in ("cc", "make", "git", "python3"):
            self.assertRegex(result.stdout, rf"ok\s+{tool}\s+\S")

    def test_quiet_mode_prints_nothing_and_keeps_the_exit_code(self):
        result = run(["--quiet"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_bad_usage_exits_two(self):
        self.assertEqual(run(["--nonsense"]).returncode, 2)


class JsonOutputTest(unittest.TestCase):
    def setUp(self):
        result = run(["--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.payload = json.loads(result.stdout)

    def test_it_is_valid_json_with_the_documented_shape(self):
        self.assertIn("tools", self.payload)
        self.assertIn("missing_required", self.payload)
        self.assertIn("missing_optional", self.payload)

    def test_every_row_carries_the_fields_a_caller_needs(self):
        for row in self.payload["tools"]:
            self.assertEqual(
                {"tool", "required", "present", "version", "install", "why"},
                set(row))

    def test_the_required_set_is_the_four_the_fleet_cannot_run_without(self):
        required = {r["tool"] for r in self.payload["tools"] if r["required"]}
        self.assertEqual(required, {"cc", "make", "git", "python3"})

    def test_cmake_is_optional_not_required(self):
        """Nothing in this repo builds a native extension needing cmake, so a
        missing cmake must not fail a fleet machine that is otherwise fine."""
        cmake = next(r for r in self.payload["tools"] if r["tool"] == "cmake")
        self.assertFalse(cmake["required"])

    def test_the_counts_agree_with_the_rows(self):
        rows = self.payload["tools"]
        self.assertEqual(self.payload["missing_required"],
                         sum(1 for r in rows if r["required"] and not r["present"]))
        self.assertEqual(self.payload["missing_optional"],
                         sum(1 for r in rows if not r["required"] and not r["present"]))


class MissingToolTest(unittest.TestCase):
    """Run against an empty PATH containing only what bash itself needs."""

    def _sparse_path(self, keep):
        """A PATH directory holding symlinks to only the named tools."""
        tmp = tempfile.mkdtemp(prefix="toolcheck-")
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in keep:
            found = shutil.which(name)
            if found:
                os.symlink(found, os.path.join(tmp, name))
        return tmp

    def test_a_missing_required_tool_fails_and_is_named(self):
        path = self._sparse_path(["bash", "head", "uname", "tr", "printf",
                                  "make", "git", "python3"])  # no cc
        result = run(path=path)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("missing required", result.stdout)
        self.assertIn("cc", result.stdout)

    def test_a_missing_required_tool_gets_an_install_command(self):
        path = self._sparse_path(["bash", "head", "uname", "tr", "printf",
                                  "make", "git", "python3"])
        self.assertIn("install:", run(path=path).stdout)

    def test_a_missing_optional_tool_alone_does_not_fail(self):
        """cmake and pkg-config are already absent on this machine."""
        result = run()
        self.assertEqual(result.returncode, 0)
        if "missing optional" in result.stdout:
            self.assertIn("only some packages need these", result.stdout)


class NoMutationTest(unittest.TestCase):
    def test_the_script_never_installs_anything(self):
        with open(SCRIPT, encoding="utf-8") as handle:
            source = handle.read()
        body = source.split("install_hint()", 1)[1].split("}", 1)[1]
        for forbidden in ("apt-get install", "brew install", "dnf install",
                          "xcode-select --install"):
            self.assertNotIn(f"\n  {forbidden}", body,
                             "install commands may only be PRINTED, never executed")


if __name__ == "__main__":
    unittest.main()
