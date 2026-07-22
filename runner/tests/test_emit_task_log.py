"""emit_task_log: source-level guard + behavioral test via db mock."""
import os
import sys
import types
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_PY = os.path.join(RUNNER_DIR, "runner.py")


class EmitTaskLogSourceTest(unittest.TestCase):
    def setUp(self):
        self.src = open(RUNNER_PY, encoding="utf-8").read()

    def test_emit_task_log_defined(self):
        self.assertIn("def emit_task_log(", self.src)

    def test_emit_task_log_writes_run_logs(self):
        fn_start = self.src.index("def emit_task_log(")
        next_def = self.src.index("\ndef ", fn_start + 1)
        body = self.src[fn_start:next_def]
        self.assertIn('"run_logs"', body)
        self.assertIn('"source"', body)
        self.assertIn('"level"', body)
        self.assertIn('"message"', body)

    def test_run_task_calls_emit_on_running(self):
        fn_start = self.src.index("def run_task(")
        next_def = self.src.index("\ndef ", fn_start + 1)
        body = self.src[fn_start:next_def]
        self.assertIn("emit_task_log(", body)

    def test_emit_task_log_fail_soft(self):
        fn_start = self.src.index("def emit_task_log(")
        next_def = self.src.index("\ndef ", fn_start + 1)
        body = self.src[fn_start:next_def]
        self.assertIn("except Exception", body)


class EmitTaskLogBehaviorTest(unittest.TestCase):
    """Verify emit_task_log calls db.insert and is fail-soft."""

    def _make_runner_module(self, inserted):
        """Load runner.py with db mocked out, capturing inserts."""
        fake_db = types.SimpleNamespace(
            insert=lambda table, row: inserted.append((table, row)),
            update=lambda *a, **kw: None,
            select=lambda *a, **kw: [],
        )
        mod = types.ModuleType("runner_under_test")
        mod.__file__ = RUNNER_PY
        # Minimal stubs so runner.py imports don't explode
        stubs = [
            "db", "os", "sys", "time", "threading", "subprocess", "re",
            "json", "hashlib", "functools", "collections", "shutil",
        ]
        for name in stubs:
            if name not in sys.modules:
                sys.modules[name] = types.ModuleType(name)
        sys.modules["db"] = fake_db
        # Exec only the set_state + emit_task_log definitions
        src = open(RUNNER_PY, encoding="utf-8").read()
        set_start = src.index("def set_state(")
        emit_start = src.index("def emit_task_log(")
        emit_end = src.index("\ndef ", emit_start + 1)
        snippet = src[set_start:emit_end]
        # Patch db reference
        namespace = {"db": fake_db}
        exec(snippet, namespace)  # noqa: S102
        return namespace

    def test_inserts_into_run_logs(self):
        inserted = []
        ns = self._make_runner_module(inserted)
        ns["emit_task_log"]("my-task", "info", "hello world")
        self.assertEqual(len(inserted), 1)
        table, row = inserted[0]
        self.assertEqual(table, "run_logs")
        self.assertEqual(row["source"], "my-task")
        self.assertEqual(row["level"], "info")
        self.assertEqual(row["message"], "hello world")

    def test_truncates_long_message(self):
        inserted = []
        ns = self._make_runner_module(inserted)
        ns["emit_task_log"]("slug", "info", "x" * 5000)
        _, row = inserted[0]
        self.assertLessEqual(len(row["message"]), 2000)

    def test_fail_soft_on_db_error(self):
        fake_db = types.SimpleNamespace(
            insert=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
            update=lambda *a, **kw: None,
        )
        import sys, types as t2
        sys.modules["db"] = fake_db
        src = open(RUNNER_PY, encoding="utf-8").read()
        emit_start = src.index("def emit_task_log(")
        emit_end = src.index("\ndef ", emit_start + 1)
        ns = {"db": fake_db}
        exec(src[emit_start:emit_end], ns)  # noqa: S102
        # Must not raise
        ns["emit_task_log"]("slug", "error", "msg")


if __name__ == "__main__":
    unittest.main()
