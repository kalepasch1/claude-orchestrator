"""Tests for web_console."""
import unittest


class TestWebConsole(unittest.TestCase):
    def test_syntax_check(self):
        import os, sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from syntax_guard import compile_runner_module
        # cwd-independent: the old literal "runner/web_console.py" only resolved from the
        # repo root and raised FileNotFoundError when the suite ran from runner/.
        compile_runner_module("web_console.py")

    def test_handler_class_exists(self):
        from runner.web_console import ConsoleHandler, start_console
        self.assertTrue(callable(start_console))

    def test_snapshot_cache_structure(self):
        from runner.web_console import _snapshot_cache
        self.assertIn("data", _snapshot_cache)
        self.assertIn("ts", _snapshot_cache)


if __name__ == "__main__":
    unittest.main()
