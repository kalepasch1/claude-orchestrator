import time
import runner

def test_long_trains_have_execution_leases_independent_of_cadence():
    assert runner._JOB_INTERVAL["merge_train.py"] == 60
    assert runner._JOB_MAX_RUNTIME["merge_train.py"] >= 3600
    assert runner._JOB_MAX_RUNTIME["releasetrain"] >= 3600

def test_snapshot_gate_is_present_before_fast_forward():
    source = open(__file__.replace('tests/test_periodic_execution_leases.py', 'merge_train.py'), encoding='utf-8').read()
    assert source.index('current_candidate_sha != candidate_sha') < source.index('if not _ff_base(repo, branch, base)')
