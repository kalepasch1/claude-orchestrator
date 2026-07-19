"""Live fleet rebalancing — monitor queue depth, reassign idle workers."""
import sys, os, json, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("fleet_rebalancer")
try:
    import db
except Exception:
    db = None

ENABLED = os.environ.get("ORCH_FLEET_REBALANCER_ENABLED", "true").lower() in ("true", "1", "yes")
THRESHOLD = int(os.environ.get("ORCH_REBALANCE_THRESHOLD", "5"))


class _Rebalancer:
    def __init__(self):
        self._lock = threading.Lock()
        self._activity = {}  # runner_id -> {"project_id", "task_id", "state", "ts"}
        self._last_task_ts = {}  # runner_id -> timestamp of last task assignment
        self._stats = {"rebalances": 0, "idle_redirects": 0, "assessments": 0}

    def assess_balance(self):
        if not ENABLED or not db:
            return {"balanced": True, "imbalances": [], "recommendations": []}
        try:
            # Queue depth per project
            queued = db.select("tasks", "state=eq.QUEUED&select=project_id")
            depth = {}
            for row in (queued or []):
                pid = row.get("project_id", "unknown")
                depth[pid] = depth.get(pid, 0) + 1

            # Active runners per project (from our activity tracker)
            active = {}
            now = time.time()
            with self._lock:
                for rid, info in self._activity.items():
                    if info.get("state") == "RUNNING" and now - info.get("ts", 0) < 600:
                        pid = info.get("project_id", "unknown")
                        active[pid] = active.get(pid, 0) + 1

            imbalances, recs = [], []
            all_pids = set(list(depth.keys()) + list(active.keys()))
            for pid in all_pids:
                q = depth.get(pid, 0)
                a = active.get(pid, 0) or 1
                ratio = q / a
                if ratio > THRESHOLD:
                    imbalances.append({"project_id": pid, "queued": q, "active": a, "ratio": ratio})

            # Find over-provisioned projects to steal from
            for imb in imbalances:
                for pid2 in all_pids:
                    if pid2 == imb["project_id"]:
                        continue
                    q2 = depth.get(pid2, 0)
                    a2 = active.get(pid2, 0)
                    if q2 < 2 and a2 > 0:
                        recs.append({
                            "action": "redirect",
                            "from_project": pid2,
                            "to_project": imb["project_id"],
                            "reason": f"queue ratio {imb['ratio']:.1f} vs {q2}/{a2}",
                        })
                        break

            with self._lock:
                self._stats["assessments"] += 1
            return {"balanced": len(imbalances) == 0, "imbalances": imbalances,
                    "recommendations": recs}
        except Exception as e:
            _log.debug("assess_balance failed: %s", e)
            return {"balanced": True, "imbalances": [], "recommendations": []}

    def rebalance(self, runner_id, current_projects):
        if not ENABLED:
            return {"action": "stay", "target_project": None, "reason": "disabled"}
        try:
            assessment = self.assess_balance()
            if assessment["balanced"]:
                return {"action": "stay", "target_project": None, "reason": "balanced"}
            for rec in assessment.get("recommendations", []):
                if rec.get("from_project") in [str(p) for p in current_projects]:
                    with self._lock:
                        self._stats["rebalances"] += 1
                    return {"action": "redirect", "target_project": rec["to_project"],
                            "reason": rec.get("reason", "queue imbalance")}
            return {"action": "stay", "target_project": None, "reason": "no redirect applicable"}
        except Exception:
            return {"action": "stay", "target_project": None, "reason": "error"}

    def register_activity(self, runner_id, project_id, task_id, state):
        with self._lock:
            self._activity[runner_id] = {
                "project_id": project_id, "task_id": task_id,
                "state": state, "ts": time.time()
            }
            if state in ("RUNNING",):
                self._last_task_ts[runner_id] = time.time()

    def idle_time(self, runner_id):
        with self._lock:
            last = self._last_task_ts.get(runner_id, time.time())
            return time.time() - last

    def stats(self):
        with self._lock:
            return dict(self._stats, enabled=ENABLED, tracked_runners=len(self._activity))


_rebalancer = _Rebalancer()

def assess_balance():
    try: return _rebalancer.assess_balance()
    except Exception: return {"balanced": True, "imbalances": [], "recommendations": []}

def rebalance(runner_id, current_projects):
    try: return _rebalancer.rebalance(runner_id, current_projects)
    except Exception: return {"action": "stay", "target_project": None, "reason": "error"}

def register_activity(runner_id, project_id, task_id, state):
    try: _rebalancer.register_activity(runner_id, project_id, task_id, state)
    except Exception: pass

def idle_time(runner_id):
    try: return _rebalancer.idle_time(runner_id)
    except Exception: return 0

def stats():
    try: return _rebalancer.stats()
    except Exception: return {"enabled": False}
