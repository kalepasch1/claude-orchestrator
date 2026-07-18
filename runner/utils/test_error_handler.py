"""test_error_handler.py — Error handling for test runs. Env gate: ORCH_TEST_ERROR_HANDLER_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get("ORCH_TEST_ERROR_HANDLER_ENABLED", "").lower() == "true"
def handle_test_error(error, test_name): return {"handled": ENABLED, "test": test_name, "retry": ENABLED}
