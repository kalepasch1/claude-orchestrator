"""emit_task_log: source-level guard + behavioral test via db mock.

WHY THE HARNESS WAS REWRITTEN. The behavioral tests extracted source by index
arithmetic — `src[src.index("def set_state("):src.index("def emit_task_log(")…]` — which
silently assumed `set_state` is defined BEFORE `emit_task_log`. That order flipped
(emit_task_log is now near the top of runner.py), so the slice ran backwards, produced an
empty string, and every behavioral test died with `KeyError: 'emit_task_log'` — a green
production path reported as three failing tests. Functions are now located with `ast`, by
name, so the tests cannot break again when runner.py is reordered.
"""
import ast
import os
import sys
import types
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_PY = os.path.join(RUNNER_DIR, "runner.py")


def _source(path=RUNNER_PY):
    return open(path, encoding="utf-8").read()


def function_source(src, name):
    """Exact source of top-level `def name(...)`, located by ast — order-independent.

    Raises AssertionError naming the function when it is absent, which is a far more
    useful failure than a KeyError from an empty slice.
    """
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{name}() is not defined at module level in {RUNNER_PY}")


class EmitTaskLogSourceTest(unittest.TestCase):
    def setUp(self):
        self.src = _source()

    def test_emit_task_log_defined(self):
        self.assertTrue(function_source(self.src, "emit_task_log"))

    def test_emit_task_log_writes_run_logs(self):
        body = function_source(self.src, "emit_task_log")
        for field in ('"run_logs"', '"source"', '"level"', '"message"'):
            self.assertIn(field, body)

    def test_run_task_calls_emit_on_running(self):
        self.assertIn("emit_task_log(", function_source(self.src, "run_task"))

    def test_emit_task_log_fail_soft(self):
        self.assertIn("except Exception", function_source(self.src, "emit_task_log"))

    def test_extractor_is_order_independent(self):
        """The regression itself: both functions resolve whichever order they appear in."""
        src = _source()
        self.assertTrue(function_source(src, "emit_task_log").startswith("def emit_task_log("))
        self.assertTrue(function_source(src, "set_state").startswith("def set_state("))

    def test_extractor_names_a_missing_function(self):
        with self.assertRaises(AssertionError) as ctx:
            function_source("def a(): pass\n", "definitely_not_here")
        self.assertIn("definitely_not_here", str(ctx.exception))


class EmitTaskLogBehaviorTest(unittest.TestCase):
    """Verify emit_task_log calls db.insert and is fail-soft."""

    def _load_emit(self, insert):
        """Exec just emit_task_log against stub db/logging. Returns the callable."""
        fake_db = types.SimpleNamespace(
            insert=insert,
            update=lambda *a, **kw: None,
            select=lambda *a, **kw: [],
        )
        calls = []

        class _Logger:
            def __getattr__(self, _name):
                return lambda *a, **kw: calls.append(a)

        namespace = {
            "db": fake_db,
            "_log_mod": types.SimpleNamespace(get=lambda _n: _Logger()),
        }
        exec(function_source(_source(), "emit_task_log"), namespace)  # noqa: S102
        return namespace["emit_task_log"], calls

    def test_inserts_into_run_logs(self):
        inserted = []
        emit, _ = self._load_emit(lambda table, row: inserted.append((table, row)))
        emit("my-task", "info", "hello world")
        self.assertEqual(len(inserted), 1)
        table, row = inserted[0]
        self.assertEqual(table, "run_logs")
        self.assertEqual(row["source"], "my-task")
        self.assertEqual(row["level"], "info")
        self.assertEqual(row["message"], "hello world")

    def test_truncates_long_message(self):
        inserted = []
        emit, _ = self._load_emit(lambda table, row: inserted.append((table, row)))
        emit("slug", "info", "x" * 5000)
        _, row = inserted[0]
        self.assertLessEqual(len(row["message"]), 2000)

    def test_unknown_level_falls_back_to_info(self):
        inserted = []
        emit, _ = self._load_emit(lambda table, row: inserted.append((table, row)))
        emit("slug", "not-a-level", "msg")
        self.assertEqual(inserted[0][1]["level"], "info")

    def test_fail_soft_on_db_error(self):
        def boom(*a, **kw):
            raise RuntimeError("boom")
        emit, _ = self._load_emit(boom)
        emit("slug", "error", "msg")  # must not raise

    def test_logs_even_when_db_write_fails(self):
        def boom(*a, **kw):
            raise RuntimeError("boom")
        emit, calls = self._load_emit(boom)
        emit("slug", "error", "msg")
        self.assertTrue(calls, "the message must still reach the logger")


if __name__ == "__main__":
    unittest.main()
