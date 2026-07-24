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
"""
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

# Modules with heavy or environment-dependent import side effects.
_SKIP = {"__init__", "conftest", "runner"}


def _module_names():
    for name in sorted(os.listdir(RUNNER)):
        if name.endswith(".py") and not name.startswith("_"):
            mod = name[:-3]
            if mod not in _SKIP:
                yield mod


class TestEveryRunnerModuleImports(unittest.TestCase):
    def test_no_module_fails_to_import_on_this_interpreter(self):
        broken = []
        for mod in _module_names():
            try:
                __import__(mod)
            except TypeError as e:
                # The PEP 604 signature: "unsupported operand type(s) for |"
                broken.append(f"{mod}: TypeError: {e}")
            except SyntaxError as e:
                broken.append(f"{mod}: SyntaxError: {e}")
            except Exception:
                # Import errors from missing optional deps / env are out of scope here;
                # we only police interpreter-level incompatibility.
                pass
        self.assertEqual(
            broken, [],
            "These modules cannot be imported on Python "
            f"{sys.version_info.major}.{sys.version_info.minor}. If it is a PEP 604 "
            "annotation (`X | None`), add `from __future__ import annotations`:\n  "
            + "\n  ".join(broken),
        )


if __name__ == "__main__":
    unittest.main()
