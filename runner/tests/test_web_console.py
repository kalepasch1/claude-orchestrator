"""Tests for web_console."""
import unittest


class TestWebConsole(unittest.TestCase):
    def test_syntax_check(self):
        import os
        import py_compile
        # Resolve relative to this test file so the check passes regardless of
        # pytest's working directory (CI runs the suite from runner/).
        py_compile.compile(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web_console.py"),
            doraise=True,
        )

    def test_handler_class_exists(self):
        from runner.web_console import ConsoleHandler, start_console
        self.assertTrue(callable(start_console))

    def test_snapshot_cache_structure(self):
        from runner.web_console import _snapshot_cache
        self.assertIn("data", _snapshot_cache)
        self.assertIn("ts", _snapshot_cache)


if __name__ == "__main__":
    unittest.main()
