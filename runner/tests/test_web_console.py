"""Tests for web_console."""
import unittest


class TestWebConsole(unittest.TestCase):
    def test_syntax_check(self):
        import py_compile
        # Absolute path derived from THIS file. The literal "runner/web_console.py" only
        # resolved when pytest happened to run from the repo root; CI runs the runner
        # suite with working-directory: runner, where it raised FileNotFoundError —
        # so the syntax guard failed for a reason that had nothing to do with syntax.
        import os
        target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "web_console.py")
        py_compile.compile(target, doraise=True)

    def test_handler_class_exists(self):
        from runner.web_console import ConsoleHandler, start_console
        self.assertTrue(callable(start_console))

    def test_snapshot_cache_structure(self):
        from runner.web_console import _snapshot_cache
        self.assertIn("data", _snapshot_cache)
        self.assertIn("ts", _snapshot_cache)


if __name__ == "__main__":
    unittest.main()
