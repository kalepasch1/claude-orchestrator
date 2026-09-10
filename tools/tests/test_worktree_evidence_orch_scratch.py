"""reconcile_worktree_evidence — the orchestrator's own scratch is not recoverable work.

`runner/worktree_identity.py` writes `.orch-worktree.json` into every agent
worktree. It is not in .gitignore, so `git status` reports it untracked, and the
base branch does not carry the path — which is exactly the shape the reconciler
reads as "authored work the base is missing".

GENERATED_HINTS already carried `/.orch/`, but that matches the DIRECTORY. The
marker lives at the worktree root, so it slipped past: a sweep of 86 evidence
items returned 30 RECOVERABLE_VALUE, and 23 of those were nothing but this one
file, once per worktree. Acting on that classification would have committed 23
copies of the orchestrator's own bookkeeping as recovered source.

This is the same defect as `is_own_task_scratch` one layer down — a reconcile
pass recovering the exhaust of the previous pass — so the tests below pin the
scratch list, and pin that legitimate work is still recognised, since an
over-broad exclusion loses real content and is the more expensive mistake.
"""
import os
import sys

import pytest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

rwe = pytest.importorskip("reconcile_worktree_evidence")


@pytest.mark.parametrize("path", [
    ".orch-worktree.json",
    ".recovery-intent-abc123.txt",
    ".deploy-canary",
    ".aider.chat.history.md",
])
def test_root_level_orch_scratch_is_generated(path):
    """The regression: these are root-level, so the `/.orch/` hint never saw them."""
    assert rwe.is_generated(path) is True


@pytest.mark.parametrize("path", [
    "runner/__pycache__/db.cpython-39.pyc",
    "runner/db.pyc",
    "web/node_modules/left-pad/index.js",
    ".pytest_cache/v/cache/lastfailed",
    ".orch/recovery-ledger-abc.json",
    ".DS_Store",
])
def test_previously_covered_artifacts_still_generated(path):
    """Widening the list must not have narrowed it."""
    assert rwe.is_generated(path) is True


@pytest.mark.parametrize("path", [
    "runner/db.py",
    "runner/tests/test_adaptive_budget.py",
    "docs/absorption/STATUS-20260817.md",
    "supabase/migrations/20260811160000_paused_host_release_guard_v2.sql",
    "CLAUDE.md",
    "requirements.txt",
])
def test_authored_work_is_not_generated(path):
    """The expensive mistake is dropping the only copy of something real."""
    assert rwe.is_generated(path) is False


def test_orch_prefix_does_not_swallow_real_paths():
    """`.orch-worktree.json` must not become a prefix match on unrelated paths.

    A hint list is substring-matched against '/' + path, so a sloppy entry can
    quietly exclude authored files that merely start the same way.
    """
    assert rwe.is_generated("orchestrator/config.py") is False
    assert rwe.is_generated("runner/orch_settings.py") is False
    assert rwe.is_generated("docs/.orch-worktree.json.md") is False
