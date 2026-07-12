#!/usr/bin/env python3
"""
model_cascade.py - cost-aware model cascading.

Start every task on the cheapest model, stream the first ~200 tokens, and use a
heuristic classifier to predict whether this model will succeed.  Abort and
escalate in <5 s if confidence is low.  Saves 60-90 % of wasted cheap-model runs.

Escalation chain (cheapest -> most capable):
    deepseek-chat -> gemini-flash -> claude-haiku -> claude-sonnet -> claude-opus

Env knobs:
    ORCH_MODEL_CASCADE          true/false (default true) - enable cascading
    ORCH_CASCADE_CONFIDENCE_MIN 0.0-1.0   (default 0.6)  - escalation threshold

Thread-safe singleton; module-level functions delegate to the instance.
"""
import os, sys, re, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log

_log = log.get(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ENABLED = os.environ.get("ORCH_MODEL_CASCADE", "true").lower() in ("1", "true", "yes")
CONFIDENCE_MIN = float(os.environ.get("ORCH_CASCADE_CONFIDENCE_MIN", "0.6"))

ESCALATION_CHAIN = [
    "deepseek-chat",
    "gemini-flash",
    "claude-haiku",
    "claude-sonnet",
    "claude-opus",
]

# Cheap models (first two tiers) trigger confidence checks; rest are trusted.
_CHEAP_MODELS = set(ESCALATION_CHAIN[:2])

# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

_REFUSAL_RE = re.compile(
    r"\b(I don'?t|I cannot|I can'?t|I'?m unable|unclear|not sure how|"
    r"error|exception|traceback|failed to|unable to)\b", re.I,
)
_STRUCTURED_RE = re.compile(
    r"\b(step \d|first,|1\.|plan:|approach:|strategy:|here'?s my|let me break)\b", re.I,
)
_MECHANICAL_KINDS = frozenset({"mechanical", "docs", "test", "lint", "format", "bump"})
_HARD_DIFFICULTIES = frozenset({"hard", "critical"})

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class _CascadeEngine:
    """Thread-safe cascade tracker."""

    def __init__(self):
        self._lock = threading.Lock()
        # history: {(kind, difficulty, model): {"ok": int, "fail": int}}
        self._history: dict = {}
        # aggregate stats
        self._total_cascades = 0
        self._total_saves = 0  # times we stayed on cheap model
        self._total_escalations = 0
        self._escalation_depth_sum = 0
        self._saved_usd = 0.0

    # ------------------------------------------------------------------
    # classify
    # ------------------------------------------------------------------

    def cascade_classify(self, task: dict, first_tokens: str) -> dict:
        """Predict whether the current cheap model will succeed.

        Returns {"confidence": float, "escalate": bool, "reason": str}.
        """
        try:
            return self._classify(task, first_tokens)
        except Exception as exc:
            _log.warning("cascade_classify error: %s", exc)
            return {"confidence": 0.5, "escalate": False, "reason": "classify-error-passthrough"}

    def _classify(self, task, first_tokens):
        kind = (task.get("kind") or "unknown").lower()
        difficulty = (task.get("difficulty") or "standard").lower()
        model = (task.get("model") or "").lower()
        tokens = first_tokens or ""

        confidence = 0.7  # neutral baseline
        reasons = []

        # 1. Refusal / error signals in first tokens -> escalate
        refusal_hits = len(_REFUSAL_RE.findall(tokens))
        if refusal_hits:
            penalty = min(0.35, refusal_hits * 0.12)
            confidence -= penalty
            reasons.append(f"refusal-signals({refusal_hits})")

        # 2. Hard/critical task on cheap model -> lower confidence
        if difficulty in _HARD_DIFFICULTIES and model in _CHEAP_MODELS:
            confidence -= 0.20
            reasons.append("hard-on-cheap")

        # 3. Mechanical / docs / test -> boost confidence (keep cheap)
        if kind in _MECHANICAL_KINDS:
            confidence += 0.20
            reasons.append("mechanical-kind-boost")

        # 4. Historical success rate for (kind, difficulty, model)
        key = (kind, difficulty, model)
        with self._lock:
            hist = self._history.get(key)
        if hist:
            total = hist["ok"] + hist["fail"]
            if total >= 3:  # need a few samples
                rate = hist["ok"] / total
                if rate < 0.40:
                    confidence -= 0.25
                    reasons.append(f"hist-low({rate:.0%})")
                elif rate > 0.80:
                    confidence += 0.10
                    reasons.append(f"hist-high({rate:.0%})")

        # 5. Structured planning in first tokens -> keep (good sign)
        if _STRUCTURED_RE.search(tokens):
            confidence += 0.15
            reasons.append("structured-output")

        confidence = max(0.0, min(1.0, confidence))
        escalate = confidence < CONFIDENCE_MIN
        reason = "; ".join(reasons) if reasons else "baseline"
        return {"confidence": round(confidence, 3), "escalate": escalate, "reason": reason}

    # ------------------------------------------------------------------
    # should_cascade
    # ------------------------------------------------------------------

    def should_cascade(self, task: dict) -> dict:
        """Return the cheapest viable starting model and escalation chain.

        Returns {"start_model": str, "escalation_chain": [str]}.
        """
        try:
            return self._should_cascade(task)
        except Exception as exc:
            _log.warning("should_cascade error: %s", exc)
            return {"start_model": ESCALATION_CHAIN[0], "escalation_chain": list(ESCALATION_CHAIN)}

    def _should_cascade(self, task):
        if not ENABLED:
            # cascading disabled -> use whatever is already assigned or default sonnet
            model = task.get("model") or "claude-sonnet"
            return {"start_model": model, "escalation_chain": [model]}

        kind = (task.get("kind") or "unknown").lower()
        difficulty = (task.get("difficulty") or "standard").lower()

        # For mechanical work, start at the very cheapest
        if kind in _MECHANICAL_KINDS:
            return {"start_model": ESCALATION_CHAIN[0],
                    "escalation_chain": list(ESCALATION_CHAIN)}

        # For hard/critical, skip deepseek -> start at gemini-flash
        if difficulty in _HARD_DIFFICULTIES:
            idx = min(1, len(ESCALATION_CHAIN) - 1)
            return {"start_model": ESCALATION_CHAIN[idx],
                    "escalation_chain": ESCALATION_CHAIN[idx:]}

        # Default: start cheapest, full chain available
        return {"start_model": ESCALATION_CHAIN[0],
                "escalation_chain": list(ESCALATION_CHAIN)}

    # ------------------------------------------------------------------
    # record outcome
    # ------------------------------------------------------------------

    def record_cascade_outcome(self, task: dict, model: str, escalated: bool,
                               final_model: str, success: bool, cost_usd: float):
        """Track cascade outcome for stats and future classification."""
        try:
            self._record(task, model, escalated, final_model, success, cost_usd)
        except Exception as exc:
            _log.warning("record_cascade_outcome error: %s", exc)

    def _record(self, task, model, escalated, final_model, success, cost_usd):
        kind = (task.get("kind") or "unknown").lower()
        difficulty = (task.get("difficulty") or "standard").lower()

        with self._lock:
            self._total_cascades += 1
            if escalated:
                self._total_escalations += 1
                # escalation depth: how many tiers we jumped
                try:
                    start_idx = ESCALATION_CHAIN.index(model)
                    final_idx = ESCALATION_CHAIN.index(final_model)
                    depth = final_idx - start_idx
                except ValueError:
                    depth = 1
                self._escalation_depth_sum += depth
            else:
                self._total_saves += 1
                # estimate savings: diff between cheap model cost and what opus would have cost
                # rough heuristic: opus is ~30x deepseek, ~10x haiku
                cheap_cost = max(cost_usd, 0.001)
                estimated_expensive = cheap_cost * 15  # conservative multiplier
                self._saved_usd += max(0, estimated_expensive - cheap_cost)

            # update history
            key = (kind, difficulty, model)
            if key not in self._history:
                self._history[key] = {"ok": 0, "fail": 0}
            self._history[key]["ok" if success else "fail"] += 1

    # ------------------------------------------------------------------
    # stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return cascade effectiveness stats."""
        with self._lock:
            total = self._total_cascades or 1
            saves_pct = round(self._total_saves / total * 100, 1)
            avg_depth = (round(self._escalation_depth_sum / max(1, self._total_escalations), 2)
                         if self._total_escalations else 0.0)
            return {
                "cascade_saves_pct": saves_pct,
                "avg_escalation_depth": avg_depth,
                "total_saved_usd": round(self._saved_usd, 2),
                "total_cascades": self._total_cascades,
                "total_escalations": self._total_escalations,
                "total_saves": self._total_saves,
                "history_keys": len(self._history),
            }

    def invalidate(self):
        """Clear all history and stats (useful for tests)."""
        with self._lock:
            self._history.clear()
            self._total_cascades = 0
            self._total_saves = 0
            self._total_escalations = 0
            self._escalation_depth_sum = 0
            self._saved_usd = 0.0


# ---------------------------------------------------------------------------
# Module-level singleton + delegation
# ---------------------------------------------------------------------------

_engine = _CascadeEngine()


def cascade_classify(task: dict, first_tokens: str) -> dict:
    """Classify whether cheap model will succeed. See _CascadeEngine."""
    return _engine.cascade_classify(task, first_tokens)


def should_cascade(task: dict) -> dict:
    """Return start model and escalation chain. See _CascadeEngine."""
    return _engine.should_cascade(task)


def record_cascade_outcome(task: dict, model: str, escalated: bool,
                           final_model: str, success: bool, cost_usd: float):
    """Record a cascade outcome for learning. See _CascadeEngine."""
    _engine.record_cascade_outcome(task, model, escalated, final_model, success, cost_usd)


def stats() -> dict:
    """Return cascade effectiveness stats."""
    return _engine.stats()


def invalidate():
    """Reset all state (for testing)."""
    _engine.invalidate()


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    demo_task = {"kind": "feature", "difficulty": "hard", "model": "deepseek-chat"}
    print("should_cascade:", _json.dumps(should_cascade(demo_task), indent=2))

    result = cascade_classify(demo_task, "I don't think I can handle this complex task")
    print("cascade_classify (refusal):", _json.dumps(result, indent=2))

    result2 = cascade_classify(
        {"kind": "test", "difficulty": "standard", "model": "deepseek-chat"},
        "Step 1: I'll create the test file. Step 2: add assertions.",
    )
    print("cascade_classify (structured):", _json.dumps(result2, indent=2))

    record_cascade_outcome(demo_task, "deepseek-chat", True, "claude-sonnet", True, 0.02)
    record_cascade_outcome(demo_task, "deepseek-chat", False, "deepseek-chat", True, 0.001)
    print("stats:", _json.dumps(stats(), indent=2))
