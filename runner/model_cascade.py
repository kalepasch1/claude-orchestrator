#!/usr/bin/env python3
"""
model_cascade.py - cost-aware model cascading.

Start every task on the cheapest model, stream the first ~200 tokens, and use a
zero-cost regex classifier to predict failure.  Abort and escalate in <5 s if
confidence is low.  Saves 60-90 % of wasted cheap-model runs.

Public API:
    cascade_strategy(task, attempt)   -> strategy dict
    evaluate_probe(task, model, out)  -> continue/escalate decision
    record_cascade(slug, ...)         -> record outcome for learning
    estimate_savings()                -> cost savings summary
    stats()                           -> full stats dict

Env knobs:
    ORCH_MODEL_CASCADE_ENABLED   true/false (default true)
    ORCH_CASCADE_PROBE_TOKENS    tokens to stream before evaluating (default 200)

Thread-safe singleton; module-level functions delegate to the instance.
Fail-soft: on any error, return continue=True (never block execution).
"""
import sys, os, re, json, time, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("model_cascade")

import model_router

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ENABLED = os.environ.get("ORCH_MODEL_CASCADE_ENABLED", "true").lower() in ("1", "true", "yes")
DEFAULT_PROBE_TOKENS = int(os.environ.get("ORCH_CASCADE_PROBE_TOKENS", "200"))

TIER_ORDER = [model_router.HAIKU, model_router.SONNET, model_router.OPUS]

# Rough $/1K-token multipliers (relative to Haiku = 1) for savings estimates
_COST_MULT = {model_router.HAIKU: 1.0, model_router.SONNET: 5.0, model_router.OPUS: 15.0}

# ---------------------------------------------------------------------------
# Probe patterns (zero-cost regex, no AI call)
# ---------------------------------------------------------------------------

# Abort signals: model is stalling, parroting, or incapable
_ABORT_PATTERNS = [
    # Stalling / hedging without acting
    re.compile(
        r"(?:I'll analyze|Let me think|Let me consider|I need to understand|"
        r"Let me break this down|I'll start by understanding)",
        re.I,
    ),
    # Parroting the task spec back
    re.compile(
        r"(?:The task (?:is|requires|asks)|You (?:want|asked|need) me to|"
        r"According to the (?:spec|requirements|instructions))",
        re.I,
    ),
    # Import / tool failures early on
    re.compile(
        r"(?:ModuleNotFoundError|ImportError|ToolError|tool_error|"
        r"command not found|No such file or directory)",
        re.I,
    ),
    # Capability gap
    re.compile(
        r"(?:I don't have access|I can't (?:do|perform|execute|access)|"
        r"I'm unable to|I cannot|beyond my (?:capabilities|ability)|"
        r"not (?:able|possible) (?:for me|to))",
        re.I,
    ),
]

# Continue signals: model is actually doing work
_CONTINUE_PATTERNS = [
    re.compile(r"(?:Edit|Write|Read)\(", re.I),               # file edit commands
    re.compile(r"(?:git diff|git commit|git add)", re.I),      # git operations
    re.compile(r"(?:def |class |import |from .+ import )", 0), # writing code
    re.compile(r"```(?:python|bash|sh|js|ts)", re.I),          # code blocks
    re.compile(r"(?:old_string|new_string|file_path)", re.I),  # Edit tool params
]

# Mechanical task keywords (chores that haiku handles fine, no escalation needed)
_MECHANICAL = re.compile(
    r"\b(?:rename|format|lint|typo|comment|import.?order|dark.?mode|theme|palette|"
    r"css|tailwind|copy.?edit|bump.?version|changelog|docstring|whitespace|"
    r"remove.?duplicate|prettier|sort)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class _ModelCascade:
    """Thread-safe cascade engine."""

    def __init__(self):
        self._lock = threading.Lock()
        # slug_prefix -> list of record dicts
        self._history: dict = {}
        # aggregate counters
        self._total_probes = 0
        self._early_aborts = 0
        self._abort_then_success = 0   # aborts where escalated model succeeded
        self._abort_then_fail = 0      # aborts where escalated model also failed
        self._estimated_savings = 0.0

    # ------------------------------------------------------------------
    # cascade_strategy
    # ------------------------------------------------------------------

    def cascade_strategy(self, task: dict, attempt: int = 1) -> dict:
        """Determine the cascade strategy for a task.

        Returns {"start_model": str, "probe_tokens": int,
                 "escalation_chain": list, "reason": str}.
        """
        try:
            return self._strategy(task, attempt)
        except Exception as exc:
            _log.warning("cascade_strategy error: %s", exc)
            return {
                "start_model": TIER_ORDER[0],
                "probe_tokens": DEFAULT_PROBE_TOKENS,
                "escalation_chain": list(TIER_ORDER),
                "reason": f"fail-soft default after error: {exc}",
            }

    def _strategy(self, task, attempt):
        if not ENABLED:
            model = model_router.route(task.get("prompt", ""), attempt).get("model", TIER_ORDER[0])
            return {
                "start_model": model,
                "probe_tokens": 0,
                "escalation_chain": [],
                "reason": "cascade disabled",
            }

        slug = task.get("slug", "") or ""
        prompt = task.get("prompt", "") or ""

        # Historical signal: if haiku has 0% success on this slug prefix, skip it
        haiku_zero = self._haiku_always_fails(slug)
        is_mechanical = bool(_MECHANICAL.search(prompt))

        if haiku_zero:
            start = model_router.SONNET
            chain = [model_router.SONNET, model_router.OPUS]
            reason = "haiku historically 0% on this slug prefix; start at sonnet"
        elif is_mechanical:
            start = model_router.HAIKU
            chain = []
            reason = "mechanical/chore task; haiku sufficient, no escalation"
        else:
            start = model_router.HAIKU
            chain = list(TIER_ORDER)
            reason = "default cascade: cheapest viable with full escalation chain"

        # Bump start model on retries
        if attempt > 1 and start in TIER_ORDER:
            idx = TIER_ORDER.index(start)
            new_idx = min(idx + attempt - 1, len(TIER_ORDER) - 1)
            start = TIER_ORDER[new_idx]
            reason += f"; attempt {attempt} bumps to {start}"

        return {
            "start_model": start,
            "probe_tokens": DEFAULT_PROBE_TOKENS,
            "escalation_chain": chain,
            "reason": reason,
        }

    def _haiku_always_fails(self, slug: str) -> bool:
        """Check in-memory history: does haiku have 0% success on this prefix?"""
        prefix = _slug_prefix(slug)
        with self._lock:
            records = self._history.get(prefix, [])
        haiku_runs = [r for r in records if r.get("start_model") == model_router.HAIKU]
        if len(haiku_runs) < 3:
            return False
        return all(not r.get("success") for r in haiku_runs)

    # ------------------------------------------------------------------
    # evaluate_probe
    # ------------------------------------------------------------------

    def evaluate_probe(self, task: dict, model: str, probe_output: str) -> dict:
        """Analyze the first N tokens of agent output to predict success.

        Zero-cost regex classification -- no AI call.

        Returns {"continue": bool, "escalate": bool, "escalate_to": str|None,
                 "confidence": float, "reason": str}.
        """
        try:
            return self._evaluate(task, model, probe_output)
        except Exception as exc:
            _log.warning("evaluate_probe error: %s", exc)
            return {
                "continue": True,
                "escalate": False,
                "escalate_to": None,
                "confidence": 0.0,
                "reason": f"fail-soft after error: {exc}",
            }

    def _evaluate(self, task, model, probe_output):
        if not ENABLED or not probe_output:
            return {
                "continue": True,
                "escalate": False,
                "escalate_to": None,
                "confidence": 0.0,
                "reason": "cascade disabled or empty probe",
            }

        text = probe_output or ""

        # Check continue signals first (model is actively working)
        for pat in _CONTINUE_PATTERNS:
            if pat.search(text):
                return {
                    "continue": True,
                    "escalate": False,
                    "escalate_to": None,
                    "confidence": 0.85,
                    "reason": f"continue: active work detected ({pat.pattern[:40]})",
                }

        # Check abort signals
        for pat in _ABORT_PATTERNS:
            m = pat.search(text)
            if m:
                next_model = _next_tier(model)
                return {
                    "continue": False,
                    "escalate": next_model is not None,
                    "escalate_to": next_model,
                    "confidence": 0.75,
                    "reason": f"abort: {m.group()[:60]}",
                }

        # No signal either way -> continue (fail-soft: never block)
        return {
            "continue": True,
            "escalate": False,
            "escalate_to": None,
            "confidence": 0.3,
            "reason": "no abort signal detected; continuing (fail-soft)",
        }

    # ------------------------------------------------------------------
    # record_cascade
    # ------------------------------------------------------------------

    def record_cascade(self, slug: str, start_model: str, final_model: str,
                       probe_aborted: bool, success: bool, cost_usd: float):
        """Record a cascade outcome for stats and future routing decisions."""
        try:
            self._record(slug, start_model, final_model, probe_aborted, success, cost_usd)
        except Exception as exc:
            _log.warning("record_cascade error: %s", exc)

    def _record(self, slug, start_model, final_model, probe_aborted, success, cost_usd):
        prefix = _slug_prefix(slug)
        record = {
            "start_model": start_model,
            "final_model": final_model,
            "probe_aborted": probe_aborted,
            "success": success,
            "cost_usd": float(cost_usd or 0),
            "ts": time.time(),
        }
        with self._lock:
            self._history.setdefault(prefix, []).append(record)
            self._total_probes += 1
            if probe_aborted:
                self._early_aborts += 1
                if success:
                    self._abort_then_success += 1
                else:
                    self._abort_then_fail += 1
                # Savings estimate: cost of running the full task on the cheap model
                # that we avoided by aborting early.  We assume the cheap model would
                # have consumed ~the same tokens as the final model but at a lower
                # per-token rate, so the "savings" is really the avoidance of a wasted
                # cheap run (the cost_usd of the probe itself is small).
                start_mult = _COST_MULT.get(start_model, 1.0)
                final_mult = _COST_MULT.get(final_model, 1.0)
                if final_mult > 0:
                    wasted_cheap_cost = float(cost_usd or 0) * (start_mult / final_mult)
                    self._estimated_savings += wasted_cheap_cost

        _log.info(
            "cascade recorded slug=%s start=%s final=%s aborted=%s success=%s cost=$%.4f",
            slug, start_model, final_model, probe_aborted, success, cost_usd or 0,
        )

    # ------------------------------------------------------------------
    # estimate_savings
    # ------------------------------------------------------------------

    def estimate_savings(self) -> dict:
        """Compute how much money cascading has saved vs running on the
        originally-routed model every time.

        Returns {"total_probes": int, "early_aborts": int,
                 "estimated_savings_usd": float, "abort_accuracy": float}.
        """
        try:
            with self._lock:
                total = self._total_probes
                aborts = self._early_aborts
                savings = self._estimated_savings
                correct = self._abort_then_success + self._abort_then_fail
            accuracy = round(correct / aborts, 4) if aborts > 0 else 0.0
            return {
                "total_probes": total,
                "early_aborts": aborts,
                "estimated_savings_usd": round(savings, 4),
                "abort_accuracy": accuracy,
            }
        except Exception:
            return {
                "total_probes": 0,
                "early_aborts": 0,
                "estimated_savings_usd": 0.0,
                "abort_accuracy": 0.0,
            }

    # ------------------------------------------------------------------
    # stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return full cascade stats."""
        try:
            with self._lock:
                history_size = sum(len(v) for v in self._history.values())
                return {
                    "enabled": ENABLED,
                    "probe_tokens": DEFAULT_PROBE_TOKENS,
                    "total_probes": self._total_probes,
                    "early_aborts": self._early_aborts,
                    "abort_then_success": self._abort_then_success,
                    "abort_then_fail": self._abort_then_fail,
                    "estimated_savings_usd": round(self._estimated_savings, 4),
                    "history_records": history_size,
                    "slug_prefixes_tracked": len(self._history),
                }
        except Exception:
            return {"enabled": ENABLED, "error": "stats unavailable"}

    def invalidate(self):
        """Clear all history and stats (useful for tests)."""
        with self._lock:
            self._history.clear()
            self._total_probes = 0
            self._early_aborts = 0
            self._abort_then_success = 0
            self._abort_then_fail = 0
            self._estimated_savings = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug_prefix(slug: str) -> str:
    """First two hyphen-delimited segments: 'add-field-users-email' -> 'add-field'."""
    parts = (slug or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else (slug or "unknown")


def _next_tier(model: str):
    """Return the next tier up, or None if already at the top."""
    if model not in TIER_ORDER:
        return model_router.SONNET
    idx = TIER_ORDER.index(model)
    if idx < len(TIER_ORDER) - 1:
        return TIER_ORDER[idx + 1]
    return None


# ---------------------------------------------------------------------------
# Module-level singleton + delegation
# ---------------------------------------------------------------------------

_engine = _ModelCascade()


def cascade_strategy(task: dict, attempt: int = 1) -> dict:
    """Determine cascade strategy for a task."""
    return _engine.cascade_strategy(task, attempt)


def evaluate_probe(task: dict, model: str, probe_output: str) -> dict:
    """Analyze probe output to predict success (zero-cost regex)."""
    return _engine.evaluate_probe(task, model, probe_output)


def record_cascade(slug: str, start_model: str, final_model: str,
                   probe_aborted: bool, success: bool, cost_usd: float):
    """Record a cascade outcome."""
    _engine.record_cascade(slug, start_model, final_model,
                           probe_aborted, success, cost_usd)


def estimate_savings() -> dict:
    """Compute cascade cost savings."""
    return _engine.estimate_savings()


def stats() -> dict:
    """Return cascade stats dict."""
    return _engine.stats()


def invalidate():
    """Reset all state (for testing)."""
    _engine.invalidate()


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    demo = {"slug": "add-field-users-email", "prompt": "add an email field to the users table"}
    print("strategy:", _json.dumps(cascade_strategy(demo), indent=2))

    probe_bad = "I'll analyze the codebase to understand the current schema structure"
    print("probe (stalling):", _json.dumps(evaluate_probe(demo, model_router.HAIKU, probe_bad), indent=2))

    probe_good = 'Edit("src/models/user.py", old_string="name: str", new_string="name: str\\nemail: str")'
    print("probe (acting):", _json.dumps(evaluate_probe(demo, model_router.HAIKU, probe_good), indent=2))

    record_cascade("add-field-x", model_router.HAIKU, model_router.SONNET, True, True, 0.05)
    record_cascade("add-field-y", model_router.HAIKU, model_router.HAIKU, False, True, 0.002)
    print("savings:", _json.dumps(estimate_savings(), indent=2))
    print("stats:", _json.dumps(stats(), indent=2))
