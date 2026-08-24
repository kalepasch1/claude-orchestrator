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
        """The property is RESTORABILITY, not membership of one hand-written dict.

        This used to assert `_faked_modules() <= _REAL_MODULES`, and had been failing:
        the suite fakes ~28 modules and the dict listed five. conftest now also EVICTS a
        stub that shadows a real runner/<name>.py, which restores it just as effectively
        and needs no list to maintain — so the check asks conftest what it can restore.
        """
        missing = {name for name in _faked_modules()
                   if not conftest.restorable(name)
                   and name not in conftest.SYNTHETIC_ONLY}
        self.assertEqual(
            missing,
            set(),
            "These modules are faked by tests but conftest can neither restore nor evict "
            "them, so the fake leaks into every module collected afterwards. Add them to "
            f"conftest._REAL_MODULES (or SYNTHETIC_ONLY if no real module exists): "
            f"{sorted(missing)}",
        )

    def test_synthetic_only_names_really_have_no_runner_module(self):
        """The exemption list must stay honest: a name here must have nothing to restore."""
        for name in conftest.SYNTHETIC_ONLY:
            self.assertFalse(
                os.path.isfile(os.path.join(os.path.dirname(TESTS_DIR), f"{name}.py")),
                f"{name} HAS a real runner module — it must not be exempted",
            )

    def test_a_stub_shadowing_a_real_module_is_evicted(self):
        """The concrete leak: model_policy faked, then a later real import of it."""
        import types

        sys.modules["model_policy"] = types.ModuleType("model_policy")
        conftest._restore_real_modules()
        self.assertNotIn(
            "model_policy", sys.modules,
            "the stub survived, so the next `from model_policy import ...` would fail "
            "with 'unknown location'",
        )
        from model_policy import revenue_keywords  # noqa: F401 - must import for real

    def test_eviction_leaves_unrelated_modules_alone(self):
        import types

        # Name assembled at runtime: a literal here would be picked up by the source
        # scanner in _faked_modules() and reported as a real unrestorable fake.
        name = "_not_a_runner" + "_module_xyz"
        sys.modules[name] = types.ModuleType(name)
        conftest._restore_real_modules()
        self.assertIn(name, sys.modules)
        del sys.modules[name]

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
