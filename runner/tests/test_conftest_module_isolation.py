"""Guards the suite against cross-module sys.modules pollution.

Several test modules install synthetic control-plane modules at import time
(sys.modules["db"] = ModuleType("db")). Under pytest 8 the module body runs in
Module.collect(), AFTER pytest_pycollect_makemodule's post-yield restore — so the
fake leaked into every module imported later. Symptoms seen 2026-07-16:

  * `from db import redact_secrets` -> "cannot import name ... (unknown location)",
    which aborted collection of the WHOLE suite (silently breaking the merge gate).
  * a faked `log` leaked into test_log.py -> 7 failures that passed in isolation.

conftest restores these on collectstart. This test fails if a new fake is
introduced that conftest has no way to undo.

WHAT THIS FILE USED TO ASSERT, AND WHY IT WAS ALWAYS RED. It required every
faked name to appear in conftest._REAL_MODULES, and it loaded conftest fresh by
path — so _REAL_MODULES held only its five seed entries and
_remember_real_modules() had never run. Ten faked names failed it permanently.

That contradicts conftest's own design twice over. The registry LEARNS: any
module living under runner/ is remembered the first time it is seen, and
conftest's comment says why the alternative was abandoned — the hand-maintained
list "was not in sync, and a list maintained by grep never will be", which is
how twelve names went unregistered and ~35 files passed alone and failed
in-suite. And a stub for a module that does NOT live under runner/ is left alone
on purpose; conftest names `requests` as the example, because such a stub
shadows nothing this suite owns.

So the assertion is rebuilt around what conftest can actually undo, which is the
property that matters:

  A. the name has a real runner/<name>.py behind it -> restorable, either from
     _REAL_MODULES or by _evict_stub_shadows() dropping the stub so the next
     import loads the real source;
  B. the name is synthetic and no such module exists anywhere -> nothing to
     restore;
  C. the name is a real module from OUTSIDE runner/ -> conftest does not own it,
     so the test must not replace it unconditionally at module scope.
"""
import ast
import importlib.util
import os
import re
import sys
import types
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, RUNNER_DIR)


def _load_conftest():
    """pytest loads conftest.py under a private name, so import it by path."""
    spec = importlib.util.spec_from_file_location(
        "_conftest_under_test", os.path.join(TESTS_DIR, "conftest.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


conftest = _load_conftest()

_FAKE_RE = re.compile(r'sys\.modules\["([a-z_][a-z0-9_]*)"\]\s*=')


def _test_files():
    for name in sorted(os.listdir(TESTS_DIR)):
        if name.startswith("test_") and name.endswith(".py"):
            yield os.path.join(TESTS_DIR, name)


def _faked_modules():
    """Every module name any test module replaces in sys.modules."""
    found = set()
    for path in _test_files():
        with open(path, encoding="utf-8") as fh:
            found.update(_FAKE_RE.findall(fh.read()))
    return found


def _is_runner_module(name):
    return os.path.isfile(os.path.join(RUNNER_DIR, name + ".py"))


def _exists_outside_runner(name):
    """True when the name resolves to a real module that is not ours."""
    if _is_runner_module(name):
        return False
    return _resolves_to_a_real_module(name)


def _parse(path):
    """AST for *path*, or None if it will not parse.

    A helper rather than a try/except around ast.parse inside the loop: the
    convention lint asks a handler to return a sensible default rather than
    swallow, and "None means unparseable" is that default stated once.
    """
    try:
        return ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, OSError):
        return None


def _resolves_to_a_real_module(name):
    """True when *name* imports to something. False for a synthetic name.

    find_spec raises for some malformed names and returns None for absent ones;
    both mean "not a real module", so the handler returns that rather than
    passing.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _unconditional_module_scope_fakes():
    """(file, name) for fakes installed at module scope with no guard.

    A fake inside a function, a `with`, a `try`, or an `if "<name>" not in
    sys.modules` is scoped or conditional and cannot clobber a real module the
    suite depends on. One at module scope with no guard can.
    """
    offenders = []
    for path in _test_files():
        tree = _parse(path)
        if tree is None:
            continue
        for node in tree.body:  # module scope only
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "modules"
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)):
                    offenders.append((os.path.basename(path), target.slice.value))
    return offenders


class TestConftestRestoresEveryFake(unittest.TestCase):
    def test_every_faked_runner_module_is_restorable(self):
        """Category A: conftest can undo a fake for every module we own.

        Asserted by DOING it — install a stand-in for each faked runner module,
        run the restore, and check none survives. A version of this that only
        re-checked the condition it had just filtered on would pass no matter
        what conftest did.
        """
        names = [n for n in sorted(_faked_modules()) if _is_runner_module(n)]
        self.assertTrue(names, "expected the suite to fake at least one runner module")
        saved = {n: sys.modules.get(n) for n in names}
        try:
            for n in names:
                sys.modules[n] = types.ModuleType(n)  # no __file__ -> a stand-in
            conftest._restore_real_modules()
            survivors = [n for n in names
                         if n in sys.modules
                         and not getattr(sys.modules[n], "__file__", None)]
            self.assertEqual(survivors, [],
                             "conftest left a stand-in in place for: %s" % survivors)
        finally:
            for n, mod in saved.items():
                if mod is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = mod

    def test_the_eviction_path_really_restores_an_unseeded_runner_module(self):
        """The half _REAL_MODULES cannot cover: a module nothing imported first.

        test_monthly_audit stubs model_policy at import time and nothing before
        it imports model_policy, so there is no real module to put back — the
        stub has to be evicted instead.
        """
        victims = [n for n in sorted(_faked_modules())
                   if _is_runner_module(n) and n not in conftest._REAL_MODULES]
        self.assertTrue(victims, "expected at least one learned-not-seeded fake")
        name = victims[0]
        saved = sys.modules.get(name)
        try:
            sys.modules[name] = types.ModuleType(name)  # no __file__ -> a stand-in
            conftest._restore_real_modules()
            still_fake = sys.modules.get(name)
            self.assertTrue(
                still_fake is None or getattr(still_fake, "__file__", None),
                f"{name} is still a stand-in after restore",
            )
        finally:
            if saved is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved

    def test_a_fake_for_a_module_outside_runner_is_never_unconditional(self):
        """Category C: conftest deliberately does not own these, so the test must.

        A `requests` stand-in installed only when requests is absent replaces
        nothing. One installed unconditionally at module scope would clobber the
        real library for every test collected afterwards, and conftest would not
        put it back.
        """
        bad = [(f, n) for f, n in _unconditional_module_scope_fakes()
               if _exists_outside_runner(n)]
        self.assertEqual(
            bad, [],
            "these replace a real non-runner module unconditionally at module "
            "scope, and conftest does not restore those — guard the assignment "
            f"or scope it to a fixture: {bad}",
        )

    def test_synthetic_names_really_are_synthetic(self):
        """Category B: names like _test_hot_mod shadow nothing, so nothing needs
        restoring. Checked rather than assumed — if one of them ever becomes a
        real module, it moves into category A or C and this stops being true."""
        synthetic = [n for n in sorted(_faked_modules())
                     if not _is_runner_module(n) and not _exists_outside_runner(n)]
        for name in synthetic:
            saved = sys.modules.pop(name, None)
            try:
                self.assertFalse(
                    _resolves_to_a_real_module(name),
                    f"{name} resolves to a real module — it is no longer synthetic",
                )
            finally:
                if saved is not None:
                    sys.modules[name] = saved

    def test_real_modules_are_actual_modules_not_fakes(self):
        for name, mod in conftest._REAL_MODULES.items():
            self.assertTrue(
                getattr(mod, "__file__", None),
                f"conftest._REAL_MODULES[{name!r}] has no __file__ — it is itself a fake",
            )

    def test_restore_helper_reinstalls_all(self):
        for name in conftest._REAL_MODULES:
            sys.modules[name] = types.ModuleType(name)  # simulate a polluting test
        conftest._restore_real_modules()
        for name, real in conftest._REAL_MODULES.items():
            self.assertIs(sys.modules[name], real, f"{name} was not restored")

    def test_the_registry_learns_a_runner_module_it_was_not_seeded_with(self):
        """The mechanism the old assertion ignored."""
        import task_state_machine  # noqa: F401  a real runner module
        conftest._remember_real_modules()
        self.assertIn("task_state_machine", conftest._REAL_MODULES)
        self.assertIs(conftest._REAL_MODULES["task_state_machine"],
                      sys.modules["task_state_machine"])


if __name__ == "__main__":
    unittest.main()
