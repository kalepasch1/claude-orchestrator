"""Guard: a test method inside a class must be able to run.

WHY THIS EXISTS
    `def test_x():` written inside a class is not a test — pytest collects it, calls it
    with the instance, and it dies with
    "test_x() takes 0 positional arguments but 1 was given" before the body ever executes.
    The file still LOOKS like coverage. It is counted, committed, and reviewed as coverage.
    It is not coverage.

    Measured 2026-08-12: 52 methods in runner/test_config_consumer.py, 47 in
    runner/test_config_consumption.py — 99 tests, 100% failing, permanently, in the files
    that were supposed to prove the config-consumption path works. Fixing them exposed a
    real bug (ConfigManager.to_dict() silently dropped every ORCH_* env override) that had
    been sitting behind the broken tests the whole time.

    A single missing `self` is trivially easy to write and impossible to notice in review,
    so it needs a mechanical guard rather than vigilance.

WHAT IS ALLOWED
    - @staticmethod def test_x():        — genuinely takes no arguments
    - @classmethod def test_x(cls):      — takes cls
    - def test_x(self, ...):             — normal bound method
    - module-level def test_x(...):      — plain pytest function
"""
import ast
import os
import unittest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_DIRS = (_RUNNER, os.path.join(_RUNNER, "tests"))


def _test_files():
    for d in SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("test_") and name.endswith(".py"):
                yield os.path.join(d, name)


def _decorator_names(node):
    names = set()
    for dec in getattr(node, "decorator_list", []):
        if isinstance(dec, ast.Name):
            names.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.add(dec.attr)
        elif isinstance(dec, ast.Call):
            fn = dec.func
            names.add(getattr(fn, "id", None) or getattr(fn, "attr", ""))
    return names


def unbound_test_methods(path):
    """[(class, method, line)] for test methods that cannot receive their instance."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except SyntaxError:
        return []          # a file that will not parse is a different failure
    bad = []
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test"):
                continue
            decs = _decorator_names(fn)
            if "staticmethod" in decs or "classmethod" in decs:
                continue
            args = fn.args
            if args.args or args.posonlyargs or args.vararg:
                continue
            bad.append((cls.name, fn.name, fn.lineno))
    return bad


class NoUnboundTestMethodsTest(unittest.TestCase):
    def test_every_test_method_can_receive_its_instance(self):
        offenders = []
        for path in _test_files():
            for cls, fn, line in unbound_test_methods(path):
                offenders.append(f"{os.path.relpath(path, _RUNNER)}:{line} "
                                 f"{cls}.{fn}() is missing `self`")
        self.assertEqual(
            offenders, [],
            "these test methods are collected but can never run:\n  "
            + "\n  ".join(offenders))

    def test_guard_flags_a_missing_self(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write("class TestX:\n    def test_a():\n        pass\n")
            path = fh.name
        try:
            self.assertEqual(unbound_test_methods(path), [("TestX", "test_a", 2)])
        finally:
            os.unlink(path)

    def test_guard_accepts_the_legitimate_shapes(self):
        import tempfile
        src = ("class TestX:\n"
               "    def test_bound(self):\n        pass\n"
               "    @staticmethod\n    def test_static():\n        pass\n"
               "    @classmethod\n    def test_cls(cls):\n        pass\n"
               "def test_module_level():\n    pass\n")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(src)
            path = fh.name
        try:
            self.assertEqual(unbound_test_methods(path), [])
        finally:
            os.unlink(path)

    def test_unparseable_file_is_not_an_offender(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write("class TestX(\n")
            path = fh.name
        try:
            self.assertEqual(unbound_test_methods(path), [])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
