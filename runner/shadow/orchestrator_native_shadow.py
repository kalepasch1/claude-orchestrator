"""orchestrator_native_shadow.py — Shadow mode for native orchestrator. Env gate: ORCH_SHADOW_NATIVE_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get("ORCH_SHADOW_NATIVE_ENABLED", "").lower() == "true"
def shadow_dispatch(task): return {"shadowed": ENABLED, "task_id": task.get("id", "")}
