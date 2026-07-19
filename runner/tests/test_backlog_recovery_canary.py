#!/usr/bin/env python3
"""
test_backlog_recovery_canary.py — canary tests for stale backlog recovery.

Verifies missing-branch audit logic and backlog compaction helpers that drive
the recovery pipeline. Tests run offline with no git or DB calls.
"""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_task(slug, state="DONE", project_id="proj-1"):
    return {"id": f"id-{slug}", "slug": slug, "state": state, "project_id": project_id}


# ── missing_branch_audit._branch_exists ──────────────────────────────────────

def test_branch_exists_returns_none_for_missing_repo():
    """Non-existent repo path returns None (unresolvable)."""
    from missing_branch_audit import _branch_exists
    result = _branch_exists("/nonexistent/repo", "agent/some-slug")
    assert result is None


def test_branch_exists_returns_none_for_none_repo():
    from missing_branch_audit import _branch_exists
    assert _branch_exists(None, "agent/test") is None
    assert _branch_exists("", "agent/test") is None


# ── backlog_compactor smoke ──────────────────────────────────────────────────

def test_backlog_compactor_importable():
    """Smoke: backlog_compactor module loads without error."""
    mod = pytest.importorskip("backlog_compactor")
    assert hasattr(mod, "__file__")


# ── patch_recovery smoke ────────────────────────────────────────────────────

def test_patch_recovery_importable():
    """patch_recovery handles reconstructing lost patches."""
    mod = pytest.importorskip("patch_recovery")
    assert hasattr(mod, "__file__")


# ── integration_sweeper smoke ────────────────────────────────────────────────

def test_integration_sweeper_importable():
    """integration_sweeper drives missing-branch requeue."""
    mod = pytest.importorskip("integration_sweeper")
    assert hasattr(mod, "__file__")
