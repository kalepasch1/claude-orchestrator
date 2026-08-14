"""Every handler named in periodic.JOBS must actually exist.

Root cause of the `cluster` crash loop (134 tracebacks, 33% of that job's failures):

    File "runner/periodic.py", line 703, in <module>
        "editorial": run_editorial,
    NameError: name 'run_editorial' is not defined

The JOBS table is built at module scope, so ONE undefined handler makes periodic.py
unimportable and takes down EVERY scheduled job, not just the one with the typo. The
failure surfaced only in .runtime/logs/<job>.err, which nothing was reading — hence
134 silent repeats.

This check is deliberately static (ast, no import, no env), so it fails fast in CI
even on a machine with no SUPABASE_URL, which is where the crash loop was invisible.
"""
import ast
import os

import pytest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERIODIC = os.path.join(RUNNER_DIR, "periodic.py")


def _tree():
    with open(PERIODIC) as fh:
        return ast.parse(fh.read(), filename=PERIODIC)


def _module_level_defs(tree):
    return {n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _jobs_dict(tree):
    """Return the ast.Dict assigned to the module-level name JOBS."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "JOBS":
                    return node.value
    return None


def test_jobs_table_exists():
    assert _jobs_dict(_tree()) is not None, "periodic.py no longer defines a JOBS dict literal"


def test_every_jobs_handler_is_defined():
    tree = _tree()
    jobs = _jobs_dict(tree)
    defined = _module_level_defs(tree)

    missing = []
    for key, value in zip(jobs.keys, jobs.values):
        # Only plain `name: handler` entries are checkable statically; lambdas,
        # attribute lookups and calls are left to the import-time guard.
        if not isinstance(value, ast.Name):
            continue
        if value.id not in defined:
            job_name = key.value if isinstance(key, ast.Constant) else ast.dump(key)
            missing.append(f"{job_name!r} -> {value.id}()")

    assert not missing, (
        "periodic.py JOBS references handlers that are never defined; importing periodic.py "
        "raises NameError and EVERY scheduled job dies, not just these:\n  "
        + "\n  ".join(missing))


def test_no_duplicate_job_keys():
    """A duplicated key silently shadows the earlier handler — the job runs the wrong code."""
    jobs = _jobs_dict(_tree())
    names = [k.value for k in jobs.keys if isinstance(k, ast.Constant)]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"duplicate JOBS keys shadow earlier handlers: {dupes}"


@pytest.mark.parametrize("job", ["cluster", "editorial"])
def test_crashloop_jobs_are_registered(job):
    """Regression pins for the two handlers involved in the 049e2f00 crash loop."""
    jobs = _jobs_dict(_tree())
    names = {k.value for k in jobs.keys if isinstance(k, ast.Constant)}
    assert job in names, f"{job!r} disappeared from the JOBS table"
