"""Guards the suite against cross-module sys.modules pollution.

Several test modules install synthetic control-plane modules at import time
(sys.modules["db"] = ModuleType("db")). Under pytest 8 the module body runs in
Module.collect(), AFTER pytest_pycollect_makemodule's post-yield restore — so the
fake leaked into every module imported later. Symptoms seen 2026-07-16:

  * `from db import redact_secrets` -> "cannot import name ... (unknown location)",
    which aborted collection of the WHOLE suite (silently breaking the merge gate).
  * a faked `log` leaked into test_log.py -> 7 failures that passed in isolation.

conftest restores these on collectstart. This test fails if a new fake is
introduced for a module conftest doesn't know how to restore.
"""
import importlib.util
import os
import re
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))


def _load_conftest():
    """pytest loads conftest.py under a private name, so import it by path."""
    spec = importlib.util.spec_from_file_location(
        "_conftest_under_test", os.path.join(TESTS_DIR, "conftest.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


conftest = _load_conftest()

_FAKE_RE = re.compile(r'sys\.modules\["([a-z_]+)"\]\s*=')


def _faked_modules():
    """Every module name any test module replaces in sys.modules."""
    found = set()
    for name in os.listdir(TESTS_DIR):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        with open(os.path.join(TESTS_DIR, name), encoding="utf-8") as f:
            found.update(_FAKE_RE.findall(f.read()))
    return found


class TestConftestRestoresEveryFake(unittest.TestCase):
    def test_every_faked_module_is_restorable(self):
        # Handled means restored to the real module OR cleared, for a name a test
        # invented and no real module backs. Both undo the pollution; only checking the
        # first left the synthetic names permanently unhandled and permanently red.
        handled = set(conftest._REAL_MODULES) | set(conftest._SYNTHETIC_ONLY_MODULES)
        missing = _faked_modules() - handled
        self.assertEqual(
            missing,
            set(),
            "These modules are faked by tests but conftest never restores them, so the "
            "fake leaks into every module collected afterwards. Add them to "
            f"conftest._REAL_MODULES (or _SYNTHETIC_ONLY_MODULES if no real module "
            f"backs the name): {sorted(missing)}",
        )

    def test_synthetic_only_fakes_are_cleared_not_left_behind(self):
        import types

        for name in conftest._SYNTHETIC_ONLY_MODULES:
            sys.modules[name] = types.ModuleType(name)
        conftest._restore_real_modules()
        for name in conftest._SYNTHETIC_ONLY_MODULES:
            self.assertNotIn(
                name, sys.modules,
                f"{name} has no real module to restore, so it must be removed; leaving "
                "the fake registered lets it outlive the test that installed it",
            )

    def test_real_modules_are_actual_modules_not_fakes(self):
        for name, mod in conftest._REAL_MODULES.items():
            self.assertTrue(
                getattr(mod, "__file__", None),
                f"conftest._REAL_MODULES[{name!r}] has no __file__ — it is itself a fake",
            )

    def test_restore_helper_reinstalls_all(self):
        import types

        for name in conftest._REAL_MODULES:
            sys.modules[name] = types.ModuleType(name)  # simulate a polluting test
        conftest._restore_real_modules()
        for name, real in conftest._REAL_MODULES.items():
            self.assertIs(sys.modules[name], real, f"{name} was not restored")


if __name__ == "__main__":
    unittest.main()
