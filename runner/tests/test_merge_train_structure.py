"""
test_merge_train_structure.py — structural guard on train_run()'s per-project worker.

Why this exists
---------------
On 2026-07-29 a half-landed refactor left train_run() with a bare
`for pid, group in by_project.items():` loop whose body referenced an undefined
`result` and returned mid-loop, while process_project_isolated() called a
process_project() that did not exist. Releases froze for three days because the
resulting NameError was swallowed per-project.

The fix was written twice. The first attempt was wiped by the fleet's own
stash/reset before it could be committed; the recovery task then ran 70+ times
without anything asserting the shape had been restored. Nothing in the existing
behavioural suite catches this class of defect, because the worker is a closure
inside train_run() and cannot be imported or called directly — a NameError in it
only surfaces at runtime, inside the per-project try/except.

So this guard is structural: it parses merge_train.py and asserts the intended
shape of the closure. It is deliberately AST-based rather than text-matching, so
it survives renames of locals, comment edits and reformatting, and fails only if
the actual defect returns.
"""

import ast
import os
import unittest

MERGE_TRAIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "merge_train.py"
)


def _parse():
    with open(MERGE_TRAIN_PATH, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=MERGE_TRAIN_PATH)


def _find_function(tree, name):
    """Top-level (or nested) function definition by name, or None."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _nested(fn, name):
    """A function defined directly inside `fn`, or None."""
    for node in ast.walk(fn):
        if isinstance(node, ast.FunctionDef) and node.name == name and node is not fn:
            return node
    return None


class TrainRunWorkerShape(unittest.TestCase):
    """The exact defect that froze releases for three days must not reappear."""

    @classmethod
    def setUpClass(cls):
        cls.tree = _parse()
        # train_run() is the branch-lease wrapper; the per-project worker lives in
        # the unleased body it delegates to.
        cls.train_run = _find_function(cls.tree, "train_run")
        cls.body = _find_function(cls.tree, "_train_run_unleased")

    def test_train_run_delegates_to_the_unleased_body(self):
        """
        train_run() must remain a thin lease wrapper around _train_run_unleased().
        If the two are ever collapsed or the delegation is dropped, the train either
        runs without its lease or does not run at all.
        """
        self.assertIsNotNone(self.train_run, "train_run() disappeared from merge_train.py")
        self.assertIsNotNone(
            self.body, "_train_run_unleased() disappeared from merge_train.py"
        )
        calls = {
            node.func.id
            for node in ast.walk(self.train_run)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn(
            "_train_run_unleased",
            calls,
            "train_run() no longer calls _train_run_unleased(); the lease wrapper and "
            "the train body have drifted apart",
        )

    def test_process_project_is_defined(self):
        """The worker must exist — process_project_isolated() calls it by name."""
        self.assertIsNotNone(
            _nested(self.body, "process_project"),
            "_train_run_unleased() no longer defines process_project(); process_project_isolated() "
            "would raise NameError for every project (2026-07-29 regression)",
        )

    def test_isolated_wrapper_is_defined_and_calls_the_worker(self):
        isolated = _nested(self.body, "process_project_isolated")
        self.assertIsNotNone(
            isolated, "_train_run_unleased() no longer defines process_project_isolated()"
        )
        calls = {
            node.func.id
            for node in ast.walk(isolated)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn(
            "process_project",
            calls,
            "process_project_isolated() must delegate to process_project(); without that "
            "call the per-project isolation wrapper does no work",
        )

    def test_worker_binds_result_before_returning_it(self):
        """
        The regression referenced `result` without ever assigning it. Assert the
        worker both assigns `result` and returns it, so a per-project summary is
        actually produced rather than a NameError swallowed by the wrapper.
        """
        worker = _nested(self.body, "process_project")
        self.assertIsNotNone(worker, "process_project() missing")

        assigns_result = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "result" for t in node.targets)
            for node in ast.walk(worker)
        )
        self.assertTrue(
            assigns_result,
            "process_project() never assigns `result` — this is the exact 2026-07-29 "
            "NameError that froze the release train",
        )

        returns_result = any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Name)
            and node.value.id == "result"
            for node in ast.walk(worker)
        )
        self.assertTrue(
            returns_result,
            "process_project() must return its `result` dict so the train body can "
            "aggregate per-project counts into the summary",
        )

    def test_worker_takes_a_single_item_argument(self):
        """
        The executor maps the worker over by_project.items(), so it must accept one
        (pid, group) tuple — not two positional args. A signature drift here fails
        only at runtime, inside the swallowing try/except.
        """
        worker = _nested(self.body, "process_project")
        args = worker.args
        self.assertEqual(
            len(args.args),
            1,
            "process_project() must take exactly one argument (the (pid, group) item "
            f"from by_project.items()); found {[a.arg for a in args.args]}",
        )
        self.assertFalse(args.vararg, "process_project() must not take *args")


if __name__ == "__main__":
    unittest.main()
