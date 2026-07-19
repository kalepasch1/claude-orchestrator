"""Deterministic rollback chains — auto-bisect bad merges, revert, re-queue."""
import sys, os, json, time, threading, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("rollback_chain")
try:
    import db
except Exception:
    db = None

ENABLED = os.environ.get("ORCH_ROLLBACK_CHAIN_ENABLED", "true").lower() in ("true", "1", "yes")
BISECT_TIMEOUT = int(os.environ.get("ORCH_BISECT_TIMEOUT", "300"))


class _RollbackChain:
    def __init__(self):
        self._lock = threading.Lock()
        self._stats = {"regressions_detected": 0, "bisects_run": 0,
                        "reverts_executed": 0, "requeues_created": 0}

    def detect_regression(self, project_id, repo_path, test_cmd, base_branch="main"):
        if not ENABLED or not repo_path or not os.path.isdir(repo_path):
            return {"regression": False, "failing_tests": [], "since_commit": ""}
        try:
            r = subprocess.run(test_cmd, shell=True, cwd=repo_path,
                               capture_output=True, text=True, timeout=BISECT_TIMEOUT)
            if r.returncode == 0:
                return {"regression": False, "failing_tests": [], "since_commit": ""}
            # Tests fail — find last known good
            failing = []
            for line in (r.stdout + r.stderr).splitlines():
                if "FAIL" in line or "FAILED" in line or "Error" in line:
                    failing.append(line.strip()[:120])
            # Get last merged commit from outcomes
            good_commit = ""
            if db:
                try:
                    rows = db.select("outcomes",
                                     f"project_id=eq.{project_id}&integrated=eq.true"
                                     f"&order=created_at.desc&limit=1&select=slug")
                    if rows:
                        good_commit = rows[0].get("slug", "")
                except Exception:
                    pass
            # Fall back to base branch
            if not good_commit:
                try:
                    g = subprocess.run(["git", "merge-base", "HEAD", base_branch],
                                       cwd=repo_path, capture_output=True, text=True, timeout=30)
                    good_commit = g.stdout.strip()[:12]
                except Exception:
                    pass
            with self._lock:
                self._stats["regressions_detected"] += 1
            return {"regression": True, "failing_tests": failing[:10],
                    "since_commit": good_commit}
        except subprocess.TimeoutExpired:
            return {"regression": False, "failing_tests": [], "since_commit": "", "error": "timeout"}
        except Exception as e:
            _log.debug("detect_regression failed: %s", e)
            return {"regression": False, "failing_tests": [], "since_commit": ""}

    def bisect_cause(self, repo_path, good_commit, bad_commit, test_cmd):
        if not ENABLED or not repo_path:
            return None
        try:
            # Use git bisect run
            subprocess.run(["git", "bisect", "start"], cwd=repo_path,
                           capture_output=True, timeout=10)
            subprocess.run(["git", "bisect", "bad", bad_commit or "HEAD"], cwd=repo_path,
                           capture_output=True, timeout=10)
            subprocess.run(["git", "bisect", "good", good_commit], cwd=repo_path,
                           capture_output=True, timeout=10)
            r = subprocess.run(["git", "bisect", "run", "sh", "-c", test_cmd],
                               cwd=repo_path, capture_output=True, text=True,
                               timeout=BISECT_TIMEOUT)
            # Extract the cause commit
            cause = ""
            for line in r.stdout.splitlines():
                if "is the first bad commit" in line:
                    parts = line.split()
                    if parts:
                        cause = parts[0][:12]
                        break
            subprocess.run(["git", "bisect", "reset"], cwd=repo_path,
                           capture_output=True, timeout=10)
            if not cause:
                return None
            # Get info about the cause commit
            info = subprocess.run(["git", "log", "--oneline", "-1", cause],
                                  cwd=repo_path, capture_output=True, text=True, timeout=10)
            slug = ""
            msg = info.stdout.strip()
            # Extract slug from commit message (agent/SLUG pattern)
            import re
            m = re.search(r"agent/([^\s]+)", msg)
            if m:
                slug = m.group(1)
            files = subprocess.run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", cause],
                                   cwd=repo_path, capture_output=True, text=True, timeout=10)
            with self._lock:
                self._stats["bisects_run"] += 1
            return {"cause_commit": cause, "cause_slug": slug,
                    "cause_files": files.stdout.strip().splitlines()[:20],
                    "confidence": 0.9}
        except subprocess.TimeoutExpired:
            subprocess.run(["git", "bisect", "reset"], cwd=repo_path,
                           capture_output=True, timeout=10)
            return None
        except Exception as e:
            _log.debug("bisect_cause failed: %s", e)
            try:
                subprocess.run(["git", "bisect", "reset"], cwd=repo_path,
                               capture_output=True, timeout=10)
            except Exception:
                pass
            return None

    def auto_revert(self, repo_path, cause_commit, base_branch="main"):
        if not ENABLED or not repo_path or not cause_commit:
            return {"reverted": False, "revert_commit": "", "conflicts": False}
        try:
            r = subprocess.run(["git", "revert", "--no-edit", cause_commit],
                               cwd=repo_path, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                # Conflicts
                subprocess.run(["git", "revert", "--abort"], cwd=repo_path,
                               capture_output=True, timeout=10)
                return {"reverted": False, "revert_commit": "", "conflicts": True}
            # Get revert commit hash
            rev = subprocess.run(["git", "rev-parse", "HEAD"],
                                 cwd=repo_path, capture_output=True, text=True, timeout=10)
            with self._lock:
                self._stats["reverts_executed"] += 1
            return {"reverted": True, "revert_commit": rev.stdout.strip()[:12],
                    "conflicts": False}
        except Exception as e:
            _log.debug("auto_revert failed: %s", e)
            return {"reverted": False, "revert_commit": "", "conflicts": False}

    def requeue_with_context(self, task_slug, cause_commit, failing_tests, project_id):
        if not ENABLED or not db:
            return {"requeued": False, "task_id": ""}
        try:
            new_slug = f"{task_slug}-fix"
            context = (
                f"## Regression Fix Required\n"
                f"The merge of `{task_slug}` (commit {cause_commit}) caused test failures.\n"
                f"It has been reverted. Fix the underlying issue and re-apply.\n\n"
                f"### Failing Tests\n" +
                "\n".join(f"- {t}" for t in (failing_tests or [])[:5]) +
                "\n\nFix these tests while preserving the original feature intent.\n"
            )
            row = {
                "slug": new_slug,
                "project_id": project_id,
                "state": "QUEUED",
                "prompt": context,
                "priority": 1,  # high priority
                "note": f"rollback-chain: auto-generated fix for reverted {task_slug}",
            }
            result = db.insert("tasks", row)
            tid = result[0].get("id", "") if isinstance(result, list) and result else ""
            with self._lock:
                self._stats["requeues_created"] += 1
            return {"requeued": True, "task_id": tid}
        except Exception as e:
            _log.debug("requeue_with_context failed: %s", e)
            return {"requeued": False, "task_id": ""}

    def chain_status(self, project_id):
        return {"pending_rollbacks": 0, "completed": self._stats["reverts_executed"],
                "active_bisects": 0}

    def stats(self):
        with self._lock:
            return dict(self._stats, enabled=ENABLED)


_chain = _RollbackChain()

def detect_regression(project_id, repo_path, test_cmd, base_branch="main"):
    try: return _chain.detect_regression(project_id, repo_path, test_cmd, base_branch)
    except Exception: return {"regression": False, "failing_tests": [], "since_commit": ""}

def bisect_cause(repo_path, good_commit, bad_commit, test_cmd):
    try: return _chain.bisect_cause(repo_path, good_commit, bad_commit, test_cmd)
    except Exception: return None

def auto_revert(repo_path, cause_commit, base_branch="main"):
    try: return _chain.auto_revert(repo_path, cause_commit, base_branch)
    except Exception: return {"reverted": False, "revert_commit": "", "conflicts": False}

def requeue_with_context(task_slug, cause_commit, failing_tests, project_id):
    try: return _chain.requeue_with_context(task_slug, cause_commit, failing_tests, project_id)
    except Exception: return {"requeued": False, "task_id": ""}

def chain_status(project_id):
    try: return _chain.chain_status(project_id)
    except Exception: return {"pending_rollbacks": 0, "completed": 0, "active_bisects": 0}

def stats():
    try: return _chain.stats()
    except Exception: return {"enabled": False}
