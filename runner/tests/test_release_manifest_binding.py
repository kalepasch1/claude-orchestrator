#!/usr/bin/env python3
"""Every release_manifest use site must bind the name in its own scope.

release_train imports release_manifest locally, inside the function that needs
it. That is fine until a *second* function calls it: the helper that re-verifies
gates after integrating prod called release_manifest.record_gate() without any
import in scope. The call raised NameError straight into an adjacent bare
`except Exception: pass`, so it failed silently — post-integration gates were
never recorded on any release, and nothing ever reported a problem.

The same undefined name also trips the anti-regression guard on every attempted
agent-branch merge, which strands branches and manufactures recovery tasks.

These tests are static (pyflakes + AST). A runtime test would not catch the bug,
because the bug's whole character is that it is swallowed at runtime.
"""
import ast
import os
import sys
import unittest

_RUNNER = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _RUNNER)

RELEASE_TRAIN = os.path.join(_RUNNER, "release_train.py")


def _tree():
    with open(RELEASE_TRAIN, "r", encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=RELEASE_TRAIN)


def _enclosing_functions(tree):
    """Map each function node to the set of names it binds locally."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = {a.arg for a in node.args.args}
        bound |= {a.arg for a in node.args.kwonlyargs}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for alias in sub.names:
                    bound.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(sub, ast.ImportFrom):
                for alias in sub.names:
                    bound.add(alias.asname or alias.name)
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                bound.add(sub.id)
            elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub is not node:
                bound.add(sub.name)
        out[node] = bound
    return out


class ReleaseManifestBindingTest(unittest.TestCase):
    def test_pyflakes_reports_no_undefined_names(self):
        """No undefined name anywhere in release_train.py."""
        try:
            from pyflakes.api import check
            from pyflakes.reporter import Reporter
        except ImportError:
            self.skipTest("pyflakes not installed")

        import io
        err = io.StringIO()
        with open(RELEASE_TRAIN, "r", encoding="utf-8") as fh:
            check(fh.read(), RELEASE_TRAIN, Reporter(io.StringIO(), err))
        undefined = [ln for ln in err.getvalue().splitlines() if "undefined name" in ln]
        self.assertEqual(undefined, [], "undefined names in release_train.py:\n" +
                         "\n".join(undefined))

    def test_every_release_manifest_call_has_it_in_scope(self):
        """release_manifest is bound in each function that dereferences it."""
        tree = _tree()
        bindings = _enclosing_functions(tree)
        offenders = []
        for fn, bound in bindings.items():
            uses = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name)
                and n.value.id == "release_manifest"
            ]
            if uses and "release_manifest" not in bound:
                offenders.append(f"{fn.name} (line {uses[0].lineno})")
        self.assertEqual(
            offenders, [],
            "release_manifest used without being imported in scope: " + ", ".join(offenders))

    def test_post_integration_gate_is_still_recorded(self):
        """The post-integration gate call must not be quietly deleted instead of fixed."""
        with open(RELEASE_TRAIN, "r", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn(
            '"post-integration"', src,
            "the post-integration release gate is no longer recorded — the fix for the "
            "NameError was to import the module, not to drop the gate")


if __name__ == "__main__":
    unittest.main()
