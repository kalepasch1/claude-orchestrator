"""error_recovery.py — Enhanced error recovery strategies. Env gate: ORCH_ERROR_RECOVERY_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get("ORCH_ERROR_RECOVERY_ENABLED", "").lower() == "true"
def recover(error_type, context=None): return {"action": "skip"} if not ENABLED else {"action": "retry", "delay": 5}
