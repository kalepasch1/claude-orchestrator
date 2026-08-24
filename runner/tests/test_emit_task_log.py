"""emit_task_log: source-level guard + behavioral test via db mock.

runner.py cannot be imported in a test: it pulls ~150 sibling modules and runs
module-level side effects (env stripping, .env loading). So these tests read the
function out of the source and exec just that function.

Extraction is done with `ast`, not string.index() on "\\ndef ", because the naive
version was wrong in three ways and every behavioral test in this file was red:

  * it sliced from `def set_state(` to the end of `emit_task_log`, but set_state
    is defined ~240 lines AFTER emit_task_log, so the slice ran backwards and
    produced an empty string -> KeyError: 'emit_task_log';
  * "the next top-level def" is ~80 lines past the end of emit_task_log, so the
    slice swallowed module-level statements like `os.environ.pop("NODE_ENV")`
    -> NameError: name 'os' is not defined;
  * it overwrote sys.modules["db"] (and stubbed "os", "json", "time"...) for the
    whole process, leaking into every test that ran afterwards.

ast gives the function's exact line span, so the tests break only when
emit_task_log's behavior changes -- not when an unrelated line moves.
"""
import ast
import os
import types
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_PY = os.path.join(RUNNER_DIR, "runner.py")


def _read_source():
    with open(RUNNER_PY, encoding="utf-8") as fh:
        return fh.read()


def function_source(src, name):
    """Return the exact source of top-level function *name* in *src*."""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines = src.splitlines()
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f"top-level function {name}() not found in runner.py")


class EmitTaskLogSourceTest(unittest.TestCase):
    def setUp(self):
        self.src = _read_source()

    def test_emit_task_log_defined(self):
        self.assertIn("def emit_task_log(", self.src)

    def test_emit_task_log_writes_run_logs(self):
        body = function_source(self.src, "emit_task_log")
        self.assertIn('"run_logs"', body)
        self.assertIn('"source"', body)
        self.assertIn('"level"', body)
        self.assertIn('"message"', body)

    def test_run_task_calls_emit_on_running(self):
        self.assertIn("emit_task_log(", function_source(self.src, "run_task"))

    def test_emit_task_log_fail_soft(self):
        self.assertIn("except Exception", function_source(self.src, "emit_task_log"))


class FunctionSourceTest(unittest.TestCase):
    """The extractor itself, since the old string-slicing version silently
    returned the wrong text instead of failing."""

    def test_extracts_only_the_named_function(self):
        body = function_source(_read_source(), "emit_task_log")
        self.assertTrue(body.startswith("def emit_task_log("))
        self.assertNotIn("def set_state(", body)
        # The module-level statements that follow must not be swallowed.
        self.assertNotIn('os.environ.pop("NODE_ENV"', body)

    def test_extracted_source_is_self_contained(self):
        compile(function_source(_read_source(), "emit_task_log"), "<extract>", "exec")

    def test_missing_function_fails_loudly(self):
        with self.assertRaises(AssertionError):
            function_source("def other():\n    pass\n", "emit_task_log")


class EmitTaskLogBehaviorTest(unittest.TestCase):
    """Verify emit_task_log calls db.insert and is fail-soft."""

    def _load(self, insert):
        """Exec emit_task_log against a stub db/logger, no sys.modules writes."""
        calls = []
        logger = types.SimpleNamespace(
            debug=lambda *a: calls.append(("debug", a)),
            info=lambda *a: calls.append(("info", a)),
            warning=lambda *a: calls.append(("warning", a)),
            error=lambda *a: calls.append(("error", a)),
            critical=lambda *a: calls.append(("critical", a)),
        )
        namespace = {
            "db": types.SimpleNamespace(insert=insert),
            "_log_mod": types.SimpleNamespace(get=lambda _name: logger),
        }
        exec(function_source(_read_source(), "emit_task_log"), namespace)  # noqa: S102
        return namespace["emit_task_log"], calls

    def test_inserts_into_run_logs(self):
        inserted = []
        emit, _ = self._load(lambda table, row: inserted.append((table, row)))
        emit("my-task", "info", "hello world")
        self.assertEqual(len(inserted), 1)
        table, row = inserted[0]
        self.assertEqual(table, "run_logs")
        self.assertEqual(row["source"], "my-task")
        self.assertEqual(row["level"], "info")
        self.assertEqual(row["message"], "hello world")

    def test_truncates_long_message(self):
        inserted = []
        emit, _ = self._load(lambda table, row: inserted.append((table, row)))
        emit("slug", "info", "x" * 5000)
        self.assertLessEqual(len(inserted[0][1]["message"]), 2000)

    def test_unknown_level_falls_back_to_info(self):
        inserted = []
        emit, calls = self._load(lambda table, row: inserted.append((table, row)))
        emit("slug", "shout", "msg")
        self.assertEqual(inserted[0][1]["level"], "info")
        self.assertEqual(calls[0][0], "info")

    def test_level_selects_the_matching_logger_method(self):
        emit, calls = self._load(lambda table, row: None)
        emit("slug", "error", "msg")
        self.assertEqual(calls[0][0], "error")

    def test_fail_soft_on_db_error(self):
        def boom(table, row):
            raise RuntimeError("boom")

        emit, _ = self._load(boom)
        emit("slug", "error", "msg")  # must not raise


if __name__ == "__main__":
    unittest.main()
