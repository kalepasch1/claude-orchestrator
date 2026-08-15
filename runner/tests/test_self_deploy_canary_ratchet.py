"""The self-deploy canary must remain bounded, passable, and fail closed.

The fleet grew to 8,599+ tests. Running all of them under a fixed 900-second restart gate
timed out, so successfully merged code still never became running code. The replacement
collects the full suite but executes only critical and change-matched behavioral tests.
"""
import os
import sys
import tempfile
import subprocess
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import self_deploy as sd


def test_gate_no_longer_executes_the_entire_suite():
    src = open(sd.__file__, encoding="utf-8").read()
    assert '["python3", "-m", "pytest", "runner/tests", "-q"]' not in src
    assert '"--collect-only"' in src


def test_gate_has_independent_bounded_timeouts():
    assert sd.CANARY_TIMEOUT > 0
    assert sd.CANARY_COLLECTION_TIMEOUT > 0
    assert sd.CANARY_MAX_CHANGED_TESTS > 0


def test_timeout_fails_closed():
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)
    with tempfile.TemporaryDirectory() as d:
        with patch.object(sd, "_changed_files", return_value=[]), \
             patch.object(subprocess, "run", _boom):
            assert sd.canary_gate(d, "aaa", "bbb") is False


def test_changed_test_cap_is_deterministic():
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for i in range(sd.CANARY_MAX_CHANGED_TESTS + 5):
            rel = f"runner/test_changed_{i:03d}.py"
            path = os.path.join(d, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
            paths.append(rel)
        selected = sd._selected_tests(d, list(reversed(paths)))
    assert len(selected) == sd.CANARY_MAX_CHANGED_TESTS
    assert selected == sorted(paths)[:sd.CANARY_MAX_CHANGED_TESTS]
