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
        src = open(RUNNER_PY, encoding="utf-8").read()

        # EXTRACT EACH FUNCTION INDEPENDENTLY. This used to slice
        # src[set_start:emit_end], which silently assumed set_state appears BEFORE
        # emit_task_log in runner.py. It does not — emit_task_log is at line 26 and
        # set_state at line 263 — so the slice ran backwards, produced an empty string,
        # and exec() built a namespace containing neither function. Every behavioural
        # test then failed with KeyError: 'emit_task_log', which reads like a missing
        # implementation and is actually a fixture that cannot survive a file reorder.
        # Module-level names the extracted functions close over. emit_task_log resolves
        # its logger per call via _log_mod.get(), which is what makes it testable here.
        class _Logger:
            def __getattr__(self, _name):
                return lambda *a, **kw: None

        namespace = {
            "db": fake_db,
            "_log_mod": types.SimpleNamespace(get=lambda _n: _Logger()),
            "os": os, "sys": sys, "time": __import__("time"), "json": __import__("json"),
        }
        for name in ("emit_task_log", "set_state"):
            snippet = self._extract_function(src, name)
            if not snippet:
                continue
            try:
                exec(snippet, namespace)  # noqa: S102
            except Exception:
                # A sibling function that needs more of runner.py's module scope must not
                # take out the one under test. Only emit_task_log is exercised here.
                continue
        return namespace

    @staticmethod
    def _extract_function(src, name):
        """Source of one top-level `def <name>(...)`, or "" when it is not defined.

        Ends at the next TOP-LEVEL def/class (column 0), so a nested def inside the
        function body does not truncate it early.
        """
        marker = f"def {name}("
        start = src.find(marker)
        if start < 0:
            return ""
        rest = src[start + len(marker):]
        offsets = [rest.find(f"\n{kw} ") for kw in ("def", "class")]
        ends = [o for o in offsets if o >= 0]
        end = (start + len(marker) + min(ends)) if ends else len(src)
        return src[start:end]

    def test_the_fixture_finds_the_function_regardless_of_file_order(self):
        """Guard the fixture itself: a backwards slice is silently empty."""
        ns = self._make_runner_module([])
        self.assertIn("emit_task_log", ns)
        self.assertTrue(callable(ns["emit_task_log"]))

    def test_the_extractor_is_order_independent(self):
        src = "def bbb():\n    return 2\n\n\ndef aaa():\n    return 1\n"
        self.assertIn("return 1", self._extract_function(src, "aaa"))
        self.assertIn("return 2", self._extract_function(src, "bbb"))

    def test_the_extractor_reports_a_missing_function_as_empty(self):
        self.assertEqual(self._extract_function("def a():\n    pass\n", "nope"), "")

    def test_a_nested_def_does_not_truncate_the_body(self):
        src = "def outer():\n    def inner():\n        pass\n    return inner\n\n\ndef after():\n    pass\n"
        body = self._extract_function(src, "outer")
        self.assertIn("return inner", body)
        self.assertNotIn("def after", body)

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
        sys.modules["db"] = fake_db
        # Reuse the shared fixture rather than re-slicing the source by hand — the ad-hoc
        # copy here missed the module-level names emit_task_log closes over (_log_mod,
        # os) and failed with NameError before it could ever reach the db call it exists
        # to test. One extractor, one namespace, one place to keep correct.
        ns = self._make_runner_module([])
        ns["db"] = fake_db
        # Must not raise
        ns["emit_task_log"]("slug", "error", "msg")


if __name__ == "__main__":
    unittest.main()
