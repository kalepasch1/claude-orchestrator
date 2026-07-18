"""distributed_test_runner.py — Test distribution across fleet. Env gate: ORCH_DISTRIBUTED_TESTS_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get("ORCH_DISTRIBUTED_TESTS_ENABLED", "").lower() == "true"
def distribute_tests(test_files, machines): return [test_files] if not ENABLED else [test_files[i::len(machines)] for i in range(len(machines))]
