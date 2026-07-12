#!/usr/bin/env python3
"""claim_affinity.py - soft affinity for multi-machine task claiming."""
import os, socket, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HOST = socket.gethostname()
def soft_affinity_sort(queued, local_repo_pids):
    if local_repo_pids is None: return queued
    if os.environ.get("ORCH_SOFT_AFFINITY", "true").lower() not in ("true", "1", "yes"): return queued
    local = [t for t in queued if t.get("project_id") in local_repo_pids]
    remote = [t for t in queued if t.get("project_id") not in local_repo_pids]
    if local: return local + remote
    if remote and os.environ.get("ORCH_SOFT_AFFINITY_FALLTHROUGH", "true").lower() in ("true", "1", "yes"):
        print(f"[claim_affinity] no local tasks on {HOST}, falling through to {len(remote)} remote tasks", flush=True)
        return remote
    return []
def affinity_score(task, local_repo_pids):
    if local_repo_pids is None: return 0
    return 0 if task.get("project_id") in local_repo_pids else 1
