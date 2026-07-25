import os
import time
from unittest.mock import patch

import runner


def test_merge_train_runtime_lease_is_independent_of_cadence():
    assert runner._JOB_INTERVAL["merge_train.py"] == 60
    assert runner._JOB_MAX_RUNTIME["merge_train.py"] >= 3600


def test_reaper_preserves_merge_train_inside_execution_lease():
    runner._PERIODIC_PIDS["merge_train.py"] = (4242, time.time() - 600)
    with patch.object(os, "kill") as kill:
        runner._reap_stale_periodic("merge_train.py", 60)
    kill.assert_called_once_with(4242, 0)
    assert "merge_train.py" in runner._PERIODIC_PIDS
    runner._PERIODIC_PIDS.pop("merge_train.py", None)
