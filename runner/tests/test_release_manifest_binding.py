#!/usr/bin/env python3
"""release_manifest must be resolvable everywhere release_train dereferences it.

THE ORIGINAL BUG. release_train imported release_manifest only LOCALLY, inside the
function that needed it. That is fine until a *second* function calls it: the helper
that re-verifies gates after integrating prod called release_manifest.record_gate()
with no import in scope. The call raised NameError straight into an adjacent bare
`except Exception: pass`, so it failed silently — post-integration gates were never
recorded on any release, and nothing ever reported a problem. The same undefined name
also tripped the anti-regression guard on every attempted agent-branch merge, which
stranded branches and manufactured recovery tasks.

WHY THE RULE CHANGED, 2026-09-02. This file asserted the fix as "every function that
dereferences the name must import it IN ITS OWN SCOPE". Since it was written, a
module-level `import release_manifest` was added at the top of release_train.py, which
resolves the name for every function in the file — so the local-import rule stopped
describing the requirement and started describing one particular way of meeting it.

That distinction is not academic. _release_value_gate was the one remaining function
without a local import, and adding one to satisfy this test broke
test_release_value_gate.py in two places: the local import SHADOWS the module attribute,
so the stub those tests install on release_train.release_manifest was bypassed and the
gate wrote to the real module. A rule that makes a codebase less testable to satisfy its
own letter is the wrong rule.

So the check is now the actual requirement — the name is bound in every scope that uses
it, module scope included — plus an explicit assertion that the module-level import
exists. Delete that import and the original local-binding protection re-arms for every
function, which is exactly the condition the first bug arose in.

These tests are static (pyflakes + AST). A runtime test would not catch the bug, because
the bug's whole character is that it is swallowed at runtime.
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

    def test_the_module_level_import_exists(self):
        """The binding every function relies on. Remove it and the rule below tightens."""
        tree = _tree()
        top = {alias.asname or alias.name.split(".")[0]
               for node in tree.body if isinstance(node, ast.Import)
               for alias in node.names}
        self.assertIn(
            "release_manifest", top,
            "release_train no longer imports release_manifest at module scope; every "
            "function that dereferences it now needs its own import, or the NameError "
            "this file exists to prevent comes back")

    def test_every_release_manifest_call_has_it_in_scope(self):
        """release_manifest is bound in each function that dereferences it."""
        tree = _tree()
        bindings = _enclosing_functions(tree)
        module_level = {alias.asname or alias.name.split(".")[0]
                        for node in tree.body if isinstance(node, ast.Import)
                        for alias in node.names}
        if "release_manifest" in module_level:
            # Module scope resolves the name for every function in the file. Requiring a
            # local import on top of it would shadow the patchable module attribute --
            # see this file's docstring.
            for fn in bindings:
                bindings[fn] = set(bindings[fn]) | {"release_manifest"}
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
