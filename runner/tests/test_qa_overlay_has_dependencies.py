#!/usr/bin/env python3
"""The branch-exact QA overlay must be able to RUN the suite it is judging.

WHAT HAPPENED (2026-08-30)
--------------------------
The first merge_train pass in three weeks reported 17 of 25 tomorrow cards as
TESTFAIL. Every single one carried the identical line:

    vitest.config.ts (1:325) [UNRESOLVED_IMPORT] Could not resolve 'vitest/config'

Not one test had run. _run_tests() built a branch-exact overlay and linked
node_modules from its parent only `if os.path.exists(src)` — but integration
worktrees are fresh checkouts with no node_modules, so nothing was linked, and
the suite was executed against an empty tree.

A gate that cannot start returns the same verdict as a gate that ran and found a
real defect. That is what made three weeks of stranded work look like three weeks
of bad work, and it is the property these tests exist to prevent.
"""
import os
import sys
import tempfile

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import merge_train  # noqa: E402


def _tree(root, *, with_modules):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "package.json"), "w") as handle:
        handle.write('{"name": "x", "devDependencies": {"vitest": "*"}}')
    if with_modules:
        os.makedirs(os.path.join(root, "node_modules", "vitest"), exist_ok=True)
    return root


def _no_prewarm(monkeypatch):
    """Force the fallback path: pretend dependency_prewarm is unusable."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "dependency_prewarm":
            raise ImportError("simulated: prewarm unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_overlay_gets_node_modules_from_a_warm_parent(monkeypatch):
    _no_prewarm(monkeypatch)
    monkeypatch.setattr(merge_train, "_ensure_node_deps",
                        lambda *a, **k: pytest_fail_if_called())
    with tempfile.TemporaryDirectory() as sandbox:
        parent = _tree(os.path.join(sandbox, "wt"), with_modules=True)
        overlay = _tree(os.path.join(sandbox, "overlay"), with_modules=False)
        merge_train._share_deps_into_overlay(parent, overlay)
        linked = os.path.join(overlay, "node_modules")
        assert os.path.exists(linked), "overlay ran with no node_modules"
        assert os.path.exists(os.path.join(linked, "vitest"))


def pytest_fail_if_called():
    raise AssertionError("should not have needed an in-place install")


def test_a_cold_parent_falls_through_to_installing_in_place(monkeypatch):
    """The exact 2026-08-30 shape: parent worktree has NO node_modules.

    Before the fix this silently did nothing and the suite ran against an empty
    tree. It must now reach the last-resort install rather than proceed blind.
    """
    _no_prewarm(monkeypatch)
    called = []
    monkeypatch.setattr(merge_train, "_ensure_node_deps",
                        lambda repo, cmd="": called.append(repo))
    with tempfile.TemporaryDirectory() as sandbox:
        parent = _tree(os.path.join(sandbox, "wt"), with_modules=False)
        overlay = _tree(os.path.join(sandbox, "overlay"), with_modules=False)
        merge_train._share_deps_into_overlay(parent, overlay, "npm test")
    assert called == [overlay], (
        "a cold parent must trigger an in-place install for the overlay, not a "
        "silent no-op")


def test_it_reaches_the_last_resort_even_when_the_parent_does_not_exist(monkeypatch):
    """This runs inside the merge path, so it must not crash before the fallback.

    A missing parent directory is the degenerate case — nothing to link from. The
    function must still get as far as the in-place install rather than throwing on
    a path that does not exist and failing an innocent card.
    """
    _no_prewarm(monkeypatch)
    reached = []
    monkeypatch.setattr(merge_train, "_ensure_node_deps",
                        lambda repo, cmd="": reached.append(repo))
    with tempfile.TemporaryDirectory() as sandbox:
        parent = os.path.join(sandbox, "does-not-exist")
        overlay = _tree(os.path.join(sandbox, "overlay"), with_modules=False)
        merge_train._share_deps_into_overlay(parent, overlay)
    assert reached == [overlay], "crashed before reaching the last-resort install"


def test_the_missing_dependency_retry_recognises_the_vite_wording():
    """The self-heal that should have caught this could not see the error.

    Node says "cannot find module". Vite/rollup — what actually runs a vitest
    suite — says "[UNRESOLVED_IMPORT] Could not resolve ...". The original four
    markers matched none of the 17 real failures.
    """
    import re
    source = open(os.path.join(RUNNER, "merge_train.py"), errors="replace").read()
    block = source[source.index("One retry after a forced install"):][:1200]
    markers = set(re.findall(r'"([a-z_ ]+)"', block))
    for wording in ("unresolved_import", "could not resolve",
                    "failed to resolve import", "cannot find module"):
        assert wording in markers, "retry cannot recognise %r" % wording


def test_the_install_budget_matches_its_own_docstring():
    """The docstring promised 900s; the code used 180s and timed out every install."""
    source = open(os.path.join(RUNNER, "merge_train.py"), errors="replace").read()
    assert 'MERGE_TRAIN_NPM_TOTAL_TIMEOUT", "900"' in source, (
        "the cumulative npm budget must match the 900s the docstring documents")
