#!/usr/bin/env python3
"""Canary: verify backlog audit + approval policy modules load and expose expected APIs."""
import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_missing_branch_audit_has_branch_exists():
    from missing_branch_audit import _branch_exists
    assert callable(_branch_exists)


def test_approval_policy_importable():
    mod = pytest.importorskip("approval_policy")
    assert hasattr(mod, "__file__")


def test_task_dedup_importable():
    mod = pytest.importorskip("task_dedup")
    assert hasattr(mod, "__file__")
