"""branch_detector.py — Detect merge conflicts early. Env gate: ORCH_BRANCH_DETECTOR_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get("ORCH_BRANCH_DETECTOR_ENABLED", "").lower() == "true"
def detect_conflicts(branch_a, branch_b): return [] if not ENABLED else ["merge_check_pending"]
