#!/usr/bin/env python3
"""Canary test: cwd-independent syntax guard (canary-claude-27 slice 3).

Core scenario: compile_runner_module() must give the same verdict from any working
directory. Edge cases: a genuinely broken module must still fail, a missing module must
raise FileNotFoundError, and no suite may reintroduce the cwd-relative literal path.
"""
import os
import py_compile
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, TESTS_DIR)
from syntax_guard import RUNNER_DIR as GUARD_RUNNER_DIR  # noqa: E402
from syntax_guard import compile_runner_module, runner_module_path  # noqa: E402


class RunnerModulePathTest(unittest.TestCase):

    def test_path_is_absolute_and_under_runner(self):
        p = runner_module_path("scoreboard.py")
        self.assertTrue(os.path.isabs(p))
        self.assertEqual(os.path.dirname(p), RUNNER_DIR)

    def test_guard_runner_dir_matches_this_tree(self):
        self.assertEqual(GUARD_RUNNER_DIR, RUNNER_DIR)

    def test_directory_component_is_ignored(self):
        """A caller passing "runner/scoreboard.py" must not double the runner/ segment."""
        self.assertEqual(runner_module_path("runner/scoreboard.py"),
                         runner_module_path("scoreboard.py"))


class CompileRunnerModuleTest(unittest.TestCase):

    GUARDED = ["branch_manager.py", "queue_monitor.py", "route_consolidation.py",
               "scoreboard.py", "session_launcher.py", "task_state_machine.py",
               "web_console.py"]

    def test_every_guarded_module_compiles(self):
        for mod in self.GUARDED:
            with self.subTest(module=mod):
                self.assertEqual(compile_runner_module(mod), runner_module_path(mod))

    def test_same_verdict_from_any_cwd(self):
        """The regression: this used to raise FileNotFoundError when cwd != repo root."""
        original = os.getcwd()
        try:
            for cwd in (RUNNER_DIR, TESTS_DIR, tempfile.gettempdir()):
                with self.subTest(cwd=cwd):
                    os.chdir(cwd)
                    compile_runner_module("scoreboard.py")
        finally:
            os.chdir(original)

    def test_missing_module_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            compile_runner_module("definitely_not_a_module_xyz.py")

    def test_broken_syntax_still_fails(self):
        """Edge case: the guard must not become a no-op that passes everything."""
        broken = os.path.join(RUNNER_DIR, "_syntax_guard_selftest_tmp.py")
        with open(broken, "w") as f:
            f.write("def broken(:\n")
        try:
            with self.assertRaises(py_compile.PyCompileError):
                compile_runner_module("_syntax_guard_selftest_tmp.py")
        finally:
            os.remove(broken)
            cache = os.path.join(RUNNER_DIR, "__pycache__")
            for stale in os.listdir(cache) if os.path.isdir(cache) else []:
                if stale.startswith("_syntax_guard_selftest_tmp."):
                    os.remove(os.path.join(cache, stale))


class NoCwdRelativeCompileTest(unittest.TestCase):

    def test_no_suite_uses_a_cwd_relative_compile_path(self):
        # Assembled at runtime so this guard file does not match its own needle.
        needle = 'py_compile' + '.compile("runner/'
        offenders = []
        for name in sorted(os.listdir(TESTS_DIR)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            if name == os.path.basename(__file__):
                continue
            with open(os.path.join(TESTS_DIR, name), encoding="utf-8") as f:
                if needle in f.read():
                    offenders.append(name)
        self.assertEqual(offenders, [], f"cwd-relative py_compile paths reintroduced: {offenders}")


if __name__ == "__main__":
    unittest.main()
