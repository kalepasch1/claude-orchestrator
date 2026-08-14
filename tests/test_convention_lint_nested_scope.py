"""
Regression tests for nested-scope attribution in convention_lint.py.

ast.walk() crosses function scope boundaries, so before this fix a `raise` inside a
nested helper was reported against its enclosing public function, and a nested
try/except was credited as the enclosing function's fail-soft handler. Both produced
false results on real modules (e.g. runner/dependency_release.py::build_release_graph).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from convention_lint import check_file


class TestNestedScopeAttribution(unittest.TestCase):
    """Nested functions own their own violations; enclosing functions do not inherit them."""

    def _fail_soft(self, code: str) -> list:
        """Return FAIL_SOFT_ERROR violations for a code snippet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                return [v for v in check_file(f.name) if v.rule == 'FAIL_SOFT_ERROR']
            finally:
                os.unlink(f.name)

    def test_nested_raise_not_attributed_to_enclosing_function(self):
        """A raise inside a nested helper must not flag the enclosing public function."""
        code = """
def build_graph(tasks):
    graph = {}

    def dfs(node):
        raise ValueError(node)

    return graph
"""
        violations = self._fail_soft(code)
        self.assertEqual([v.message for v in violations], [])

    def test_nested_function_is_not_reported_as_public(self):
        """Nested functions are not module-level, so they are never reported themselves."""
        code = """
def outer(data):
    def inner(x):
        raise KeyError(x)
    return inner
"""
        violations = self._fail_soft(code)
        self.assertEqual([v.message for v in violations], [])

    def test_nested_handler_does_not_excuse_enclosing_raise(self):
        """A try/except in a nested helper must not count as the enclosing fail-soft handler."""
        code = """
def outer(data):
    def inner(x):
        try:
            return x()
        except ValueError:
            return None
    raise RuntimeError("boom")
"""
        violations = self._fail_soft(code)
        self.assertEqual(len(violations), 1)
        self.assertIn('outer', violations[0].message)

    def test_module_level_raise_still_flagged(self):
        """The original rule still fires for an unguarded module-level function."""
        code = """
def parse(value):
    raise ValueError(value)
"""
        violations = self._fail_soft(code)
        self.assertEqual(len(violations), 1)
        self.assertIn('parse', violations[0].message)

    def test_nested_bare_except_pass_not_attributed_to_enclosing(self):
        """A bare `except: pass` inside a nested helper is not the enclosing function's."""
        code = """
def outer(data):
    def inner():
        try:
            return data()
        except:
            pass
    return inner
"""
        violations = self._fail_soft(code)
        self.assertEqual([v.message for v in violations], [])


if __name__ == '__main__':
    unittest.main()
