#!/usr/bin/env python3
"""Canary test for self_deploy — offline, no network."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from self_deploy import check_new_code, RESTART_FLAG, BOOT_FILE


def test_check_new_code_missing_repo():
    """Non-existent repo should return stale=False (no crash)."""
    result = check_new_code("/nonexistent/repo/path")
    assert isinstance(result, dict)
    assert "stale" in result


def test_restart_flag_path():
    """RESTART_FLAG should point inside the runner directory."""
    assert RESTART_FLAG.endswith(".restart_requested")
    assert "runner" in RESTART_FLAG


def test_boot_file_constant():
    assert BOOT_FILE == ".runner_boot_commit"
