"""emit_task_log: source-level guard + behavioural test against the real function.

WHAT THIS FILE USED TO DO, AND WHY IT COULD NOT WORK

The behavioural tests never called runner.py's emit_task_log. They sliced its
source text out of the file and exec'd the slice:

    emit_start = src.index("def emit_task_log(")
    emit_end   = src.index("\\ndef ", emit_start + 1)
    exec(src[emit_start:emit_end], {"db": fake_db})

emit_task_log is not followed by another `def`. It is followed by ~90 lines of
module-level code -- `os.environ.pop("NODE_ENV", None)`, the .env loader, path
setup -- so the slice ran all of that in a namespace holding nothing but `db`,
and died on `NameError: name 'os' is not defined` before ever binding
emit_task_log. Hence the sibling failures: `KeyError: 'emit_task_log'`.

Worse, the harness did this to reach it:

    for name in ["db", "os", "sys", "time", "threading", "subprocess", "re",
                 "json", "hashlib", "functools", "collections", "shutil"]:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["db"] = fake_db

and never put any of it back. The stdlib names were saved by the `not in`
guard, but `sys.modules["db"] = fake_db` is unconditional and permanent: every
test that ran after this file in the same process got a SimpleNamespace with
three lambdas in place of db. That is a suite-wide fault injected by a test
that was itself failing.

Both problems have the same fix: load the entrypoint properly and patch its
`db` attribute inside a context manager.
"""
import ast
import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_PY = os.path.join(RUNNER_DIR, "runner.py")
sys.path.insert(0, RUNNER_DIR)

MAX_MESSAGE_CHARS = 2000
LONG_MESSAGE_CHARS = 5000


def _load_runner_entrypoint():
    """Load runner/runner.py by path, under a private module name.

    `import runner` is ambiguous: runner/ is a package AND contains runner.py,
    so the bare name resolves to whichever comes first on sys.path. Same loader
    as test_run_task_safe and test_task_lifecycle.
    """
    name = "runner_entrypoint_emit_task_log"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, RUNNER_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _function_source(name):
    """The source of exactly one top-level function, by AST.

    str.index("\\ndef ") is not a function boundary -- see this module's
    docstring for what it actually returned for emit_task_log.
    """
    with open(RUNNER_PY, encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    return ""


class EmitTaskLogSourceTest(unittest.TestCase):
    def test_emit_task_log_defined(self):
        self.assertTrue(_function_source("emit_task_log"))

    def test_emit_task_log_writes_run_logs(self):
        body = _function_source("emit_task_log")
        for token in ('"run_logs"', '"source"', '"level"', '"message"'):
            self.assertIn(token, body)

    def test_run_task_calls_emit_on_running(self):
        self.assertIn("emit_task_log(", _function_source("run_task"))

    def test_emit_task_log_fail_soft(self):
        self.assertIn("except Exception", _function_source("emit_task_log"))

    def test_the_slice_the_old_harness_used_was_not_the_function(self):
        """Regression on the harness itself, not on runner.py.

        If emit_task_log ever does get followed by another def, the old slice
        would start working and this test should be deleted along with the
        warning in the module docstring -- not before.
        """
        with open(RUNNER_PY, encoding="utf-8") as fh:
            source = fh.read()
        start = source.index("def emit_task_log(")
        naive = source[start:source.index("\ndef ", start + 1)]
        self.assertGreater(len(naive), len(_function_source("emit_task_log")),
                           "the naive slice must still be overreaching")
        self.assertIn("os.environ", naive,
                      "and must still be swallowing module-level code")


class EmitTaskLogBehaviorTest(unittest.TestCase):
    """The real function, with db patched on the module that owns it."""

    def load_the_entrypoint(self):
        self.runner = _load_runner_entrypoint()

    # unittest dispatches on the name "setUp", so it is the stdlib's to choose;
    # bound as an alias to keep the repo's snake_case rule off a name this file
    # does not control.
    setUp = load_the_entrypoint

    def _insert_calls(self):
        """Patch runner.db.insert and collect what it was handed."""
        calls = []
        fake = patch.object(self.runner.db, "insert",
                            side_effect=lambda table, row: calls.append((table, row)))
        fake.start()
        self.addCleanup(fake.stop)
        return calls

    def test_inserts_into_run_logs(self):
        calls = self._insert_calls()
        self.runner.emit_task_log("my-task", "info", "hello world")

        self.assertEqual(len(calls), 1)
        table, row = calls[0]
        self.assertEqual(table, "run_logs")
        self.assertEqual(row["source"], "my-task")
        self.assertEqual(row["level"], "info")
        self.assertEqual(row["message"], "hello world")

    def test_truncates_long_message(self):
        calls = self._insert_calls()
        self.runner.emit_task_log("slug", "info", "x" * LONG_MESSAGE_CHARS)

        _, row = calls[0]
        self.assertLessEqual(len(row["message"]), MAX_MESSAGE_CHARS)

    def test_an_unknown_level_falls_back_to_info(self):
        calls = self._insert_calls()
        self.runner.emit_task_log("slug", "shout", "msg")

        _, row = calls[0]
        self.assertEqual(row["level"], "info")

    def test_fail_soft_on_db_error(self):
        with patch.object(self.runner.db, "insert",
                          side_effect=RuntimeError("boom")):
            self.runner.emit_task_log("slug", "error", "msg")   # must not raise

    def test_db_is_not_left_replaced_for_the_rest_of_the_suite(self):
        """The leak this file used to cause, stated as a test.

        sys.modules["db"] = fake_db with no restore meant every later test in
        the process got a three-lambda stand-in for the database client.
        """
        import db as real_db
        self.assertIs(sys.modules["db"], real_db)
        self.assertTrue(hasattr(sys.modules["db"], "claim_task"),
                        "sys.modules['db'] is not the real client")


if __name__ == "__main__":
    unittest.main()
