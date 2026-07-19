"""Prompt A/B testing — systematically test prompt variants, converge on best."""
import sys, os, re, json, time, threading, hashlib, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("prompt_ab_test")
try:
    import db
except Exception:
    db = None

ENABLED = os.environ.get("ORCH_PROMPT_AB_TEST_ENABLED", "true").lower() in ("true", "1", "yes")
MIN_SAMPLES = int(os.environ.get("ORCH_AB_MIN_SAMPLES", "20"))

# Prompt variants to test
_VARIANTS = {
    "section_order": {
        "A": ["spec", "context", "precedent", "constraints", "mandate"],
        "B": ["context", "spec", "constraints", "precedent", "mandate"],
    },
    "instruction_style": {
        "A": "imperative",   # "Fix the bug in auth.py"
        "B": "descriptive",  # "The bug in auth.py needs to be fixed"
    },
    "example_count": {
        "A": 0,  # no examples
        "B": 1,  # one example
    },
    "constraint_placement": {
        "A": "before_spec",  # constraints first, then task
        "B": "after_spec",   # task first, then constraints
    },
}


class _ABTest:
    def __init__(self):
        self._lock = threading.Lock()
        self._results = {}  # (variant_name, variant_value) -> {"successes": int, "total": int}
        self._assignments = {}  # task_id -> {variant_name: variant_value}
        self._stats = {"experiments_run": 0, "variants_tested": 0, "winners_found": 0}

    def assign_variant(self, task_id, variant_name):
        """Assign a task to variant A or B for a given experiment."""
        if not ENABLED:
            return "A"
        with self._lock:
            existing = self._assignments.get(task_id, {}).get(variant_name)
            if existing:
                return existing
        # Use task_id hash for deterministic but evenly-split assignment
        h = hashlib.md5(f"{task_id}:{variant_name}".encode()).hexdigest()
        variant = "A" if int(h[:8], 16) % 2 == 0 else "B"
        with self._lock:
            self._assignments.setdefault(task_id, {})[variant_name] = variant
        return variant

    def get_variant_config(self, task_id):
        """Get all variant assignments for a task."""
        if not ENABLED:
            return {}
        config = {}
        for vname in _VARIANTS:
            v = self.assign_variant(task_id, vname)
            config[vname] = {"variant": v, "value": _VARIANTS[vname][v]}
        return config

    def apply_variant(self, prompt, task_id):
        """Apply A/B test variants to a prompt."""
        if not ENABLED:
            return prompt
        config = self.get_variant_config(task_id)
        # Apply constraint_placement variant
        cp = config.get("constraint_placement", {})
        if cp.get("variant") == "A" and cp.get("value") == "before_spec":
            # Move ## Constraints sections before ## Task Spec
            sections = re.split(r"(## [^\n]+\n)", prompt)
            constraints = []
            others = []
            for i, s in enumerate(sections):
                if "Constraint" in s or "constraint" in s:
                    constraints.append(s)
                    if i + 1 < len(sections):
                        constraints.append(sections[i + 1])
                else:
                    others.append(s)
            if constraints:
                prompt = "".join(constraints + others)
        with self._lock:
            self._stats["experiments_run"] += 1
        return prompt

    def record_outcome(self, task_id, success):
        """Record whether the task succeeded under its assigned variants."""
        if not ENABLED:
            return
        with self._lock:
            assignments = self._assignments.get(task_id, {})
            for vname, vvalue in assignments.items():
                key = (vname, vvalue)
                entry = self._results.setdefault(key, {"successes": 0, "total": 0})
                entry["total"] += 1
                if success:
                    entry["successes"] += 1

    def analyze(self):
        """Analyze A/B test results and find winners."""
        if not ENABLED:
            return {"experiments": [], "winners": []}
        experiments = []
        winners = []
        with self._lock:
            for vname in _VARIANTS:
                key_a = (vname, "A")
                key_b = (vname, "B")
                a = self._results.get(key_a, {"successes": 0, "total": 0})
                b = self._results.get(key_b, {"successes": 0, "total": 0})
                if a["total"] < MIN_SAMPLES or b["total"] < MIN_SAMPLES:
                    experiments.append({
                        "name": vname, "status": "collecting",
                        "a_rate": a["successes"] / max(a["total"], 1),
                        "b_rate": b["successes"] / max(b["total"], 1),
                        "a_total": a["total"], "b_total": b["total"],
                    })
                    continue
                rate_a = a["successes"] / a["total"]
                rate_b = b["successes"] / b["total"]
                winner = "A" if rate_a > rate_b else "B"
                diff = abs(rate_a - rate_b)
                significant = diff > 0.1  # 10% difference threshold
                exp = {
                    "name": vname, "status": "significant" if significant else "inconclusive",
                    "winner": winner if significant else None,
                    "a_rate": round(rate_a, 3), "b_rate": round(rate_b, 3),
                    "a_total": a["total"], "b_total": b["total"],
                    "lift": round(diff, 3),
                }
                experiments.append(exp)
                if significant:
                    winners.append({"variant": vname, "winner": winner,
                                    "value": _VARIANTS[vname][winner],
                                    "lift": round(diff, 3)})
                    self._stats["winners_found"] = len(winners)
        return {"experiments": experiments, "winners": winners}

    def stats(self):
        with self._lock:
            return dict(self._stats, enabled=ENABLED,
                        active_experiments=len(_VARIANTS),
                        total_observations=sum(v["total"] for v in self._results.values()))


_ab = _ABTest()

def assign_variant(task_id, variant_name):
    try: return _ab.assign_variant(task_id, variant_name)
    except Exception: return "A"

def get_variant_config(task_id):
    try: return _ab.get_variant_config(task_id)
    except Exception: return {}

def apply_variant(prompt, task_id):
    try: return _ab.apply_variant(prompt, task_id)
    except Exception: return prompt

def record_outcome(task_id, success):
    try: _ab.record_outcome(task_id, success)
    except Exception: pass

def analyze():
    try: return _ab.analyze()
    except Exception: return {"experiments": [], "winners": []}

def stats():
    try: return _ab.stats()
    except Exception: return {"enabled": False}
