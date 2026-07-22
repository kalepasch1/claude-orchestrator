"""predictive_branch.py — Predictive branch management. Env gate: ORCH_PREDICTIVE_BRANCH_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get("ORCH_PREDICTIVE_BRANCH_ENABLED", "").lower() == "true"
def predict_merge_success(branch_stats): return 0.5 if not ENABLED else min(1.0, branch_stats.get("pass_rate", 0))
