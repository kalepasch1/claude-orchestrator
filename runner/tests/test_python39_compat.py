"""Guard: every runner module must import under the interpreter the fleet actually runs.

2026-07-16: runner/provider_rate_tracker.py used PEP 604 (`int | None`) in function
signatures without `from __future__ import annotations`. PEP 604 in a signature is
evaluated at DEFINITION time, so on Python 3.9 (this fleet's interpreter) merely
importing the module raised TypeError. test_provider_rate_tracker.py therefore aborted
collection of the ENTIRE suite on orchestrator/dev — which is release_train's
verification gate — so nothing could be promoted dev -> master. master sat 13 days and
370 commits behind as a result.

A syntax feature that parses fine but explodes at import is exactly the kind of thing a
linter misses and a human reads straight past. This test imports every runner module.

IN A SUBPROCESS, as of 2026-08-25. It used to do the sweep in-process, and that made it
the single largest source of cross-test pollution in the suite:

  * It ran `sys.path.insert(0, RUNNER)` at module scope. With runner/ ahead of the repo
    root, the name `runner` resolves to the MODULE runner/runner.py rather than the
    package, so every later `from runner.X import Y` died with "No module named
    'runner.X'; 'runner' is not a package". This file sorts late in collection order, so
    it won the race against everything after it: 35 failures across six files
    (test_done_to_merged_conversion, test_route_consolidation,
    test_branch_recovery_validate_repository, test_task_state_machine,
    test_repo_access_healer, test_train_status_backfill), every one of which passed in
    isolation. conftest now repairs that ordering per test; this file no longer causes it.

  * It imported ~910 modules into the session, running every one of their import-time
    side effects — module-level caches, singletons, registries, sys.path edits of their
    own — into a process 700 other test files then share.

A subprocess is also the more honest question. "Can this module be imported on this
interpreter" means in a FRESH interpreter: in a process where 900 other modules are
already loaded, a module that would fail on its own can be carried by an import its
neighbour already completed.
"""
import json
import os
import subprocess
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Names that are not modules to sweep.
_SKIP = {"__init__", "conftest", "runner"}

_CHILD = r'''
import json, os, sys
runner = sys.argv[1]
sys.path.insert(0, runner)
skip = set(json.loads(sys.argv[2]))
broken = []
for name in sorted(os.listdir(runner)):
    if not name.endswith(".py") or name.startswith("_"):
        continue
    mod = name[:-3]
    if mod in skip:
        continue
    try:
        __import__(mod)
    except TypeError as exc:
        # The PEP 604 signature: "unsupported operand type(s) for |"
        broken.append("%s: TypeError: %s" % (mod, exc))
    except SyntaxError as exc:
        broken.append("%s: SyntaxError: %s" % (mod, exc))
    except Exception:
        # Import errors from missing optional deps / env are out of scope here;
        # we only police interpreter-level incompatibility.
        pass
print("---RESULT---")
print(json.dumps(broken))
'''


_SWEEP_CACHE = []


def _sweep():
    """Run the sweep once per session; both tests below read the same result."""
    if _SWEEP_CACHE:
        return _SWEEP_CACHE[0]
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, RUNNER, json.dumps(sorted(_SKIP))],
        capture_output=True, text=True, timeout=900, cwd=RUNNER,
    )
    _SWEEP_CACHE.append(proc)
    return proc


class TestEveryRunnerModuleImports(unittest.TestCase):
    def test_no_module_fails_to_import_on_this_interpreter(self):
        proc = _sweep()
        self.assertIn("---RESULT---", proc.stdout,
                      "the import sweep did not finish:\n%s" % proc.stderr[-2000:])
        broken = json.loads(proc.stdout.rsplit("---RESULT---", 1)[1].strip())
        self.assertEqual(
            broken, [],
            "These modules cannot be imported on Python "
            f"{sys.version_info.major}.{sys.version_info.minor}. If it is a PEP 604 "
            "annotation (`X | None`), add `from __future__ import annotations`:\n  "
            + "\n  ".join(broken),
        )

    def test_the_sweep_does_not_touch_this_process(self):
        """The regression guard for what this file used to do.

        If the sweep ever moves back in-process, `runner` stops being a package
        for every test module collected after this one.
        """
        import importlib
        before = list(sys.path)
        _sweep()  # cached; the point is that running it changed nothing here
        self.assertEqual(sys.path, before, "the sweep edited this process's sys.path")
        runner_mod = sys.modules.get("runner")
        if runner_mod is not None:
            self.assertTrue(
                hasattr(runner_mod, "__path__"),
                "`runner` is bound to runner/runner.py, not the package — "
                "`from runner.X import Y` will fail for every later test",
            )
        self.assertTrue(importlib.import_module("runner.task_state_machine"))


if __name__ == "__main__":
    unittest.main()
