#!/usr/bin/env python3
"""Tests for owner_preference.py — owner taste learning from approval history."""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import owner_preference as op


def _mock_decisions(n_approved=8, n_denied=2, kind="material"):
    """Generate mock approval decisions."""
    rows = []
    for i in range(n_approved):
        rows.append({"id": f"a{i}", "kind": kind, "status": "approved",
                      "title": f"Improve {kind} feature {i}", "why": "High value improvement",
                      "value": "significant improvement", "risk": "low risk", "detail": ""})
    for i in range(n_denied):
        rows.append({"id": f"d{i}", "kind": kind, "status": "denied",
                      "title": f"Risky {kind} change {i}", "why": "Too dangerous",
                      "value": "minor improvement", "risk": "high breaking risk", "detail": ""})
    return rows
