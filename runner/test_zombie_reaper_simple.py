#!/usr/bin/env python3
"""Simple test to debug zombie-reaper mocking issues."""
import sys
import os
import time
import datetime
import traceback
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# Import the runner.py module directly
import importlib.util
# LOADED UNDER A PRIVATE NAME, NOT "runner".
#
# This used to be `spec_from_file_location("runner", .../runner.py)` followed by
# `sys.modules["runner"] = runner`, at module scope and never undone. runner/ is
# BOTH a package and a directory containing runner.py, so installing the
# entrypoint under the bare name replaced the PACKAGE for every test collected
# afterwards -- and `from runner.X import Y` then fails with "runner is not a
# package". runner/tests/conftest.py carries a per-test fixture
# (_runner_stays_a_package) whose entire job is to undo this; the fix is to stop
# doing it. Same pattern as runner/tests/test_run_task_safe.py.
_ENTRYPOINT = "runner_entrypoint_zombie_reaper_simple"
_spec = importlib.util.spec_from_file_location(_ENTRYPOINT, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py"))
runner = importlib.util.module_from_spec(_spec)
sys.modules[_ENTRYPOINT] = runner
_spec.loader.exec_module(runner)


def test_debug_dead_runner_patch():
    """Debug test to see what's happening with mocks."""
    orig_time = runner._ZOMBIE_REAP_T
    runner._ZOMBIE_REAP_T = time.time() - 400

    with patch("runner.agentic_repair.repair_patch") as mock_repair, \
         patch("runner.db.select") as mock_select, \
         patch("runner.db.update") as mock_update:

        mock_repair.return_value = {"state": "QUEUED"}

        # Set up mock returns
        now = datetime.datetime.now(datetime.timezone.utc)
        task = {
            "id": "t1",
            "slug": "task-1",
            "state": "RUNNING",
            "account": "Mac.lan-5",
            "updated_at": (now - datetime.timedelta(minutes=1)).isoformat(),
        }

        heartbeat = {
            "runner_id": "Mac.lan-1",
            "hostname": "Mac.lan",
            "last_seen": (now - datetime.timedelta(seconds=30)).isoformat(),
        }

        mock_select.side_effect = [
            [task],
            [heartbeat],
        ]

        try:
            runner._reap_zombie_tasks()
            print(f"Mock repair called: {mock_repair.called}")
            print(f"Mock update called: {mock_update.called}")
            print(f"Mock repair call count: {mock_repair.call_count}")
            print(f"Mock update call count: {mock_update.call_count}")
            if mock_update.call_count > 0:
                print(f"Update call args: {mock_update.call_args}")
        except Exception as e:
            print(f"Exception during reap: {e}")
            traceback.print_exc()

    runner._ZOMBIE_REAP_T = orig_time


if __name__ == "__main__":
    test_debug_dead_runner_patch()
