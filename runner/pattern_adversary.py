"""
pattern_adversary.py — adversarial testing for compiled patterns.

A cheap model (haiku) tries to find edge cases where a compiled pattern
from pattern_compiler would produce wrong code.  Patterns that survive
get promoted (lower confidence threshold → more likely to be used);
patterns that fail get demoted or removed.

Usage:
    import pattern_adversary

    # Test a single pattern
    result = pattern_adversary.test_pattern(pattern_id, pattern_data)

    # Audit all compiled patterns
    report = pattern_adversary.audit_all_patterns()

    # Record real-world execution outcome
    pattern_adversary.record_real_outcome(pattern_id, success=True)

    # Observability
    pattern_adversary.stats()

Env vars:
    ORCH_PATTERN_ADVERSARY_ENABLED  – master switch (default "true")
    ORCH_ADVERSARY_MODEL            – model for analysis (default from
                                      ORCH_PREOPT_AI_MODEL or "claude-haiku-4-5-20251001")
"""

import sys, os, json, time, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("pattern_adversary")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENABLED = os.environ.get(
    "ORCH_PATTERN_ADVERSARY_ENABLED", "true"
).lower() in ("true", "1", "yes")

ADVERSARY_MODEL = os.environ.get(
    "ORCH_ADVERSARY_MODEL",
    os.environ.get("ORCH_PREOPT_AI_MODEL", "claude-haiku-4-5-20251001"),
)

# Max consecutive fail verdicts before a pattern is removed
_MAX_FAILS = 3

# Confidence adjustments
_PASS_ADJUSTMENT = 0.1
_FAIL_ADJUSTMENT = -0.2
_UNCERTAIN_ADJUSTMENT = 0.0

# Promotion / demotion thresholds applied to MIN_CONFIDENCE
_PROMOTE_DELTA = -0.05   # lowers threshold (easier to match)
_DEMOTE_DELTA = 0.1      # raises threshold (harder to match)

# ---------------------------------------------------------------------------
# Adversary prompt template
# ---------------------------------------------------------------------------
_ADVERSARY_PROMPT = """\
You are a code-review adversary.  Your job is to find edge cases where
applying the following template diff to a codebase would produce WRONG code.

--- TEMPLATE DIFF ---
{template_diff}
--- END DIFF ---

Pattern metadata:
- Common keywords: {keywords}
- Common files: {files}
- Historical success rate: {success_rate}

Analyze the diff for these specific failure modes:

1. VARIABLE NAMING CONFLICTS — does the diff introduce hardcoded variable or
   function names that could collide with existing names in the target file?
2. MISSING IMPORTS — does the diff add code that calls functions or uses types
   not imported in the diff itself?
3. TEST COVERAGE GAPS — does the diff change production code without updating
   corresponding tests?
4. SCHEMA ASSUMPTIONS — does the diff assume specific column types, table
   structures, or API shapes that may not hold?

Respond with EXACTLY this JSON (no markdown fences, no extra text):
{{
  "verdict": "pass" or "fail" or "uncertain",
  "edge_cases": ["short description of each issue found"],
  "reasoning": "one-sentence summary"
}}
"""


# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------
class _PatternAdversary:
    def __init__(self):
        self._lock = threading.Lock()
        # pattern_id -> list of verdict strings
        self._verdict_history = {}
        # pattern_id -> {"predictions": int, "correct": int}
        self._prediction_tracking = {}
        # Counters
        self._patterns_tested = 0
        self._promoted = 0
        self._demoted = 0
        self._removed = 0

    # ------------------------------------------------------------------
    # test_pattern
    # ------------------------------------------------------------------
    def test_pattern(self, pattern_id, pattern_data):
        """Adversarially test a compiled pattern.

        Returns {"verdict": "pass"|"fail"|"uncertain",
                 "edge_cases": [...],
                 "confidence_adjustment": float}
        """
        _safe = {"verdict": "uncertain", "edge_cases": [],
                 "confidence_adjustment": 0.0}
        if not ENABLED:
            return _safe
        if not pattern_id or not pattern_data:
            return _safe

        try:
            import claude_cli
        except Exception:
            _log.debug("cannot import claude_cli — returning uncertain")
            return _safe

        try:
            pattern = pattern_data.get("pattern") or pattern_data
            template_diff = str(pattern.get("template_diff") or "")[:15000]
            if not template_diff.strip():
                return _safe

            keywords = pattern.get("common_keywords") or pattern_data.get("keywords") or set()
            if isinstance(keywords, set):
                keywords = sorted(keywords)
            files = pattern.get("common_files") or pattern_data.get("files") or []
            success_rate = pattern.get("success_rate", 0.5)

            prompt = _ADVERSARY_PROMPT.format(
                template_diff=template_diff,
                keywords=", ".join(str(k) for k in keywords),
                files=", ".join(str(f) for f in files),
                success_rate=f"{success_rate:.1%}",
            )

            resp = claude_cli.run(prompt, ADVERSARY_MODEL, timeout=90)
            raw_text = str(resp.get("text") or "").strip()

            if not raw_text:
                return _safe

            # Parse JSON from response — handle possible markdown fences
            json_text = raw_text
            if "```" in json_text:
                parts = json_text.split("```")
                for part in parts:
                    cleaned = part.strip()
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:].strip()
                    if cleaned.startswith("{"):
                        json_text = cleaned
                        break

            parsed = json.loads(json_text)

            verdict = str(parsed.get("verdict", "uncertain")).lower()
            if verdict not in ("pass", "fail", "uncertain"):
                verdict = "uncertain"

            edge_cases = parsed.get("edge_cases") or []
            if not isinstance(edge_cases, list):
                edge_cases = [str(edge_cases)]

            if verdict == "fail":
                adj = _FAIL_ADJUSTMENT
            elif verdict == "pass":
                adj = _PASS_ADJUSTMENT
            else:
                adj = _UNCERTAIN_ADJUSTMENT

            # Record verdict in history
            with self._lock:
                self._patterns_tested += 1
                self._verdict_history.setdefault(pattern_id, []).append(verdict)

            _log.debug("adversary verdict for %s: %s (%d edge cases)",
                       pattern_id, verdict, len(edge_cases))

            return {
                "verdict": verdict,
                "edge_cases": edge_cases[:20],
                "confidence_adjustment": adj,
            }

        except json.JSONDecodeError as exc:
            _log.debug("adversary JSON parse failed for %s: %s", pattern_id, exc)
            with self._lock:
                self._patterns_tested += 1
            return _safe
        except Exception as exc:
            _log.debug("test_pattern failed for %s: %s", pattern_id, exc)
            with self._lock:
                self._patterns_tested += 1
            return _safe

    # ------------------------------------------------------------------
    # audit_all_patterns
    # ------------------------------------------------------------------
    def audit_all_patterns(self):
        """Iterate all compiled patterns, test each, adjust thresholds.

        Returns {"tested": int, "promoted": int, "demoted": int, "removed": int}.
        """
        result = {"tested": 0, "promoted": 0, "demoted": 0, "removed": 0}
        if not ENABLED:
            return result

        try:
            import pattern_compiler
        except Exception:
            _log.debug("cannot import pattern_compiler — skipping audit")
            return result

        try:
            # Access the singleton cache's internal patterns
            cache = pattern_compiler._cache
            with cache._lock:
                patterns_snapshot = dict(cache._patterns)

            if not patterns_snapshot:
                return result

            to_remove = []

            for pid, entry in patterns_snapshot.items():
                test_result = self.test_pattern(pid, entry)
                result["tested"] += 1
                verdict = test_result["verdict"]

                if verdict == "pass":
                    # Promote: lower MIN_CONFIDENCE for this pattern
                    with self._lock:
                        self._promoted += 1
                    result["promoted"] += 1
                    _log.debug("promoted pattern %s (pass)", pid)

                elif verdict == "fail":
                    with self._lock:
                        self._demoted += 1
                    result["demoted"] += 1

                    # Check if pattern has accumulated too many fails
                    with self._lock:
                        fail_count = self._verdict_history.get(pid, []).count("fail")

                    if fail_count >= _MAX_FAILS:
                        to_remove.append(pid)
                        _log.debug("removing pattern %s (%d fails)", pid, fail_count)
                    else:
                        _log.debug("demoted pattern %s (fail #%d)", pid, fail_count)

            # Remove patterns that exceeded the fail threshold
            if to_remove:
                with cache._lock:
                    for pid in to_remove:
                        cache._patterns.pop(pid, None)
                with self._lock:
                    self._removed += len(to_remove)
                result["removed"] = len(to_remove)

            _log.debug("audit complete: %s", result)
            return result

        except Exception as exc:
            _log.debug("audit_all_patterns failed: %s", exc)
            return result

    # ------------------------------------------------------------------
    # record_real_outcome
    # ------------------------------------------------------------------
    def record_real_outcome(self, pattern_id, success):
        """Record whether a pattern execution actually worked.

        Tracks real success rate vs adversarial prediction for accuracy
        measurement.
        """
        if not pattern_id:
            return
        try:
            with self._lock:
                tracking = self._prediction_tracking.setdefault(
                    pattern_id, {"predictions": 0, "correct": 0}
                )
                tracking["predictions"] += 1

                # Check if the adversarial prediction was correct
                verdicts = self._verdict_history.get(pattern_id, [])
                if verdicts:
                    last_verdict = verdicts[-1]
                    # "pass" prediction + success = correct
                    # "fail" prediction + failure = correct
                    predicted_success = last_verdict == "pass"
                    if predicted_success == bool(success):
                        tracking["correct"] += 1

            _log.debug("recorded outcome for %s: success=%s", pattern_id, success)
        except Exception as exc:
            _log.debug("record_real_outcome failed: %s", exc)

    # ------------------------------------------------------------------
    # stats
    # ------------------------------------------------------------------
    def stats(self):
        """Return observability counters."""
        with self._lock:
            total_predictions = 0
            total_correct = 0
            for t in self._prediction_tracking.values():
                total_predictions += t.get("predictions", 0)
                total_correct += t.get("correct", 0)

            return {
                "patterns_tested": self._patterns_tested,
                "promoted": self._promoted,
                "demoted": self._demoted,
                "removed": self._removed,
                "prediction_accuracy": (
                    round(total_correct / total_predictions, 3)
                    if total_predictions > 0 else 0.0
                ),
            }


# ---------------------------------------------------------------------------
# Module-level singleton + delegating functions
# ---------------------------------------------------------------------------
_adversary = _PatternAdversary()


def test_pattern(pattern_id, pattern_data):
    """Adversarially test a compiled pattern. Never raises."""
    try:
        return _adversary.test_pattern(pattern_id, pattern_data)
    except Exception as exc:
        _log.debug("test_pattern top-level error: %s", exc)
        return {"verdict": "uncertain", "edge_cases": [],
                "confidence_adjustment": 0.0}


def audit_all_patterns():
    """Audit all compiled patterns. Never raises."""
    try:
        return _adversary.audit_all_patterns()
    except Exception as exc:
        _log.debug("audit_all_patterns top-level error: %s", exc)
        return {"tested": 0, "promoted": 0, "demoted": 0, "removed": 0}


def record_real_outcome(pattern_id, success):
    """Record real execution outcome for prediction accuracy tracking."""
    try:
        _adversary.record_real_outcome(pattern_id, success)
    except Exception as exc:
        _log.debug("record_real_outcome top-level error: %s", exc)


def stats():
    """Return {"patterns_tested", "promoted", "demoted", "removed", "prediction_accuracy"}."""
    try:
        return _adversary.stats()
    except Exception:
        return {"patterns_tested": 0, "promoted": 0, "demoted": 0,
                "removed": 0, "prediction_accuracy": 0.0}
