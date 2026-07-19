"""Parallel branch speculation — fork N strategies, pick winner."""
import sys, os, json, time, threading, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("branch_speculator")
try:
    import db
except Exception:
    db = None

ENABLED = os.environ.get("ORCH_BRANCH_SPECULATOR_ENABLED", "false").lower() in ("true", "1", "yes")
VARIANTS = int(os.environ.get("ORCH_SPECULATION_VARIANTS", "3"))

_STRATEGIES = [
    {
        "name": "conservative",
        "prompt_modifier": (
            "\n\n## Strategy: Conservative\n"
            "Make minimal changes. Modify as few files as possible. "
            "Prefer the simplest fix that passes all tests. "
            "Do not refactor or reorganize code beyond what the task requires.\n"
        ),
        "model_preference": "sonnet",
    },
    {
        "name": "aggressive",
        "prompt_modifier": (
            "\n\n## Strategy: Aggressive\n"
            "Refactor freely if it improves code quality. "
            "Create new files or modules if it improves architecture. "
            "Apply best practices even if the task doesn't explicitly ask for them.\n"
        ),
        "model_preference": "sonnet",
    },
    {
        "name": "creative",
        "prompt_modifier": (
            "\n\n## Strategy: Creative\n"
            "Consider alternative approaches. If the obvious fix doesn't work, "
            "try a completely different angle. Think about the problem from the "
            "user's perspective and consider edge cases others might miss.\n"
        ),
        "model_preference": "opus",
    },
]


class _Speculator:
    def __init__(self):
        self._lock = threading.Lock()
        self._stats = {"speculations_run": 0, "winners_picked": 0,
                        "strategy_wins": {"conservative": 0, "aggressive": 0, "creative": 0}}

    def should_speculate(self, task, attempt):
        if not ENABLED:
            return {"speculate": False, "variants": 0, "reason": "disabled"}
        kind = (task.get("kind") or "").lower()
        if kind in ("mechanical", "chore", "docs", "cleanup"):
            return {"speculate": False, "variants": 0, "reason": "mechanical task"}
        if attempt > 1:
            return {"speculate": False, "variants": 0, "reason": "not first attempt"}
        # Check failure history
        slug = task.get("slug", "")
        prefix = "-".join(slug.split("-")[:2])
        failures = 0
        if db:
            try:
                rows = db.select("outcomes",
                                 f"slug=like.{prefix}*&integrated=eq.false&limit=10")
                failures = len(rows) if rows else 0
            except Exception:
                pass
        if failures >= 2:
            return {"speculate": True, "variants": min(VARIANTS, 3),
                    "reason": f"{failures} prior failures for {prefix}"}
        complexity = task.get("_complexity", "")
        if complexity in ("complex", "very_complex"):
            return {"speculate": True, "variants": min(VARIANTS, 3),
                    "reason": f"complexity={complexity}"}
        return {"speculate": False, "variants": 0, "reason": "no speculation trigger"}

    def generate_strategies(self, task, prompt, repo_path):
        strategies = []
        for s in _STRATEGIES[:VARIANTS]:
            strategies.append({
                "name": s["name"],
                "prompt_modifier": s["prompt_modifier"],
                "model": s["model_preference"],
                "prompt": prompt + s["prompt_modifier"],
            })
        return strategies

    def pick_winner(self, results):
        if not results:
            return {"winner": None, "reason": "no results"}
        passed = [r for r in results if r.get("rc") == 0 or r.get("tests_ok")]
        if not passed:
            return {"winner": None, "reason": "no variant passed tests", "all_results": results}
        # Prefer smallest diff
        for r in passed:
            r.setdefault("diff_lines", len((r.get("diff", "") or "").splitlines()))
        passed.sort(key=lambda r: (r["diff_lines"], r.get("cost_usd", 0)))
        winner = passed[0]
        with self._lock:
            self._stats["winners_picked"] += 1
            name = winner.get("strategy", "unknown")
            if name in self._stats["strategy_wins"]:
                self._stats["strategy_wins"][name] += 1
        return {"winner": winner, "reason": f"smallest passing diff ({winner['diff_lines']} lines)",
                "all_results": results}

    def estimate_cost(self, task, num_variants):
        base = 0.05  # rough per-task cost
        est = base * num_variants
        slug = task.get("slug", "")
        prefix = "-".join(slug.split("-")[:2])
        failures = 0
        if db:
            try:
                rows = db.select("outcomes", f"slug=like.{prefix}*&integrated=eq.false&limit=10")
                failures = len(rows) if rows else 0
            except Exception:
                pass
        wasted = failures * base
        return {"estimated_usd": est, "worth_it": wasted > est, "prior_waste": wasted}

    def stats(self):
        with self._lock:
            return dict(self._stats, enabled=ENABLED, variants=VARIANTS)


_spec = _Speculator()

def should_speculate(task, attempt=1):
    try: return _spec.should_speculate(task, attempt)
    except Exception: return {"speculate": False, "variants": 0, "reason": "error"}

def generate_strategies(task, prompt, repo_path=""):
    try: return _spec.generate_strategies(task, prompt, repo_path)
    except Exception: return []

def pick_winner(results):
    try: return _spec.pick_winner(results)
    except Exception: return {"winner": None, "reason": "error"}

def estimate_cost(task, num_variants=3):
    try: return _spec.estimate_cost(task, num_variants)
    except Exception: return {"estimated_usd": 0, "worth_it": False}

def stats():
    try: return _spec.stats()
    except Exception: return {"enabled": False}
