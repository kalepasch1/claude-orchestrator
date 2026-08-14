"""No job function may be defined twice in runner/periodic.py.

FOUND 2026-08-14. `run_pipelineselftest` was defined twice: once in the job block where it
belongs, and again as the last ten lines of the file, appended after `main()`'s `sys.exit`
calls by a bad merge. Both copies were byte-identical, so nothing misbehaved — which is
exactly what makes it dangerous. Python binds the LAST definition, so the copy the JOBS
table actually dispatches was the stray one at EOF, and any future edit to the visible copy
in the job block would have been silently dead code. The pipeline self-test is the job that
notices when a machine goes quiet; a silently-dead edit there is the monitor failing at the
one thing it exists to do.

Generalised deliberately: this asserts the invariant for EVERY module-level def, not just
the one that happened to break, because the cause (conflict resolution appending a hunk past
the end of the file) is not specific to this function.
"""
import ast
import os
from collections import Counter

PERIODIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner", "periodic.py"
)


def _module_level_function_names(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def test_no_module_level_function_is_defined_twice():
    names = _module_level_function_names(PERIODIC)
    duplicates = sorted(n for n, count in Counter(names).items() if count > 1)
    assert duplicates == [], (
        f"runner/periodic.py defines these twice: {duplicates}. Python binds the last "
        "definition, so the earlier one is dead code no test would notice."
    )


def test_every_dispatched_job_resolves_to_exactly_one_definition():
    # The JOBS table is what actually gets dispatched, so its targets are the names that
    # matter most. Guard them explicitly as well as via the blanket check above.
    names = _module_level_function_names(PERIODIC)
    counts = Counter(names)
    for name in names:
        if name.startswith("run_"):
            assert counts[name] == 1, f"{name} is defined {counts[name]} times"


def test_the_pipeline_selftest_job_is_present_exactly_once():
    # Regression-pins the specific function that broke, so the fix cannot be reverted
    # quietly even if the generic check is ever relaxed.
    names = _module_level_function_names(PERIODIC)
    assert names.count("run_pipelineselftest") == 1
