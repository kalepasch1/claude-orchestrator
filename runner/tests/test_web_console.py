"""Tests for web_console."""
import unittest


class TestWebConsole(unittest.TestCase):
    def test_syntax_check(self):
        import py_compile
        py_compile.compile("runner/web_console.py", doraise=True)

    def test_handler_class_exists(self):
        from runner.web_console import ConsoleHandler, start_console
        self.assertTrue(callable(start_console))

    def test_snapshot_cache_structure(self):
        from runner.web_console import _snapshot_cache
        self.assertIn("data", _snapshot_cache)
        self.assertIn("ts", _snapshot_cache)


if __name__ == "__main__":
    unittest.main()
