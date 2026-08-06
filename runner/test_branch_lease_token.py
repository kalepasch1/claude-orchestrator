#!/usr/bin/env python3
"""Token normalization regressions for branch_lease (canary-codex-24).

The 2026-08 orchestrator feedback: legacy lease records carry only `p_token`;
the heartbeat/release paths read `lease["token"]`, so a legacy shape raised
KeyError inside the fail-soft handler and masked genuine lease loss. The
`_lease_token` helper normalizes both shapes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from branch_lease import _lease_token


def test_current_shape_token():
    assert _lease_token({"token": "abc"}) == "abc"


def test_legacy_shape_p_token():
    assert _lease_token({"p_token": "legacy"}) == "legacy"


def test_current_wins_over_legacy():
    assert _lease_token({"token": "new", "p_token": "old"}) == "new"


def test_empty_current_falls_back_to_legacy():
    assert _lease_token({"token": "", "p_token": "old"}) == "old"


def test_missing_both_returns_empty_string():
    assert _lease_token({}) == ""


def test_none_values_normalize_to_string():
    assert _lease_token({"token": None, "p_token": None}) == ""
