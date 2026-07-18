"""cowork_shadow.py — Shadow mode for cowork executor. Env gate: ORCH_SHADOW_COWORK_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get("ORCH_SHADOW_COWORK_ENABLED", "").lower() == "true"
def shadow_run(task): return {"shadowed": ENABLED, "task_id": task.get("id", "")}
