#!/usr/bin/env python3
from __future__ import annotations
"""
prompt_evolution.py - Track which prompt structures lead to first-pass merges and
evolve templates automatically. The system learns to write better instructions for itself.

Records structural fingerprints of every prompt alongside its outcome (merged or not),
then computes which features (examples, file lists, constraints, test criteria, etc.)
are statistically correlated with first-pass integration. Uses that signal to evolve
the prompt template conservatively (at most 2 changes per cycle).

Usage:
    import prompt_evolution
    prompt_evolution.record_prompt_outcome(task, prompt_text, model, True, 0.12, 1)
    additions = prompt_evolution.get_evolved_additions(task, project)
    s = prompt_evolution.stats()

Env vars:
    ORCH_PROMPT_EVOLUTION_ENABLED  "true" (default) to enable recording/analysis
    ORCH_EVOLUTION_MIN_SAMPLES     minimum outcomes before analysis runs (default 50)
"""
import sys, os, json, time, threading, hashlib, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("prompt_evolution")
import db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ENABLED = os.environ.get("ORCH_PROMPT_EVOLUTION_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MIN_SAMPLES = int(os.environ.get("ORCH_EVOLUTION_MIN_SAMPLES", "50") or 50)
_ANALYSIS_TTL = 300  # cache analysis results for 5 minutes

# All structural features we extract and track
_FEATURE_NAMES = [
    "has_examples", "has_file_list", "has_constraints", "has_test_criteria",
    "has_build_mandate", "has_precedent", "has_spec_refinement",
]
_NUMERIC_FEATURES = ["word_count", "section_count"]


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------
def _extract_features(prompt_text):
    """Extract structural features from a prompt string.

    Returns a dict of bools and counts. Fail-soft: returns empty-ish dict on
    bad input rather than raising.
    """
    if not prompt_text:
        return {f: False for f in _FEATURE_NAMES} | {"word_count": 0, "section_count": 0}

    text = str(prompt_text)
    lower = text.lower()

    features = {
        "has_examples": bool(re.search(r"(example|e\.g\.|for instance|sample)", lower)),
        "has_file_list": bool(re.search(r"(files?:\s*\n|─|\bpath\b.*\n.*\bpath\b)", lower)),
        "has_constraints": bool(re.search(r"(constraint|must not|do not|avoid|never|require)", lower)),
        "has_test_criteria": bool(re.search(r"(test|assert|expect|verify|check that|should pass)", lower)),
        "has_build_mandate": bool(re.search(r"(must build|must compile|no errors|build succeed)", lower)),
        "has_precedent": bool(re.search(r"(precedent|prior merge|previous.*pattern|like we did)", lower)),
        "has_spec_refinement": bool(re.search(r"(spec|specification|refine|clarif)", lower)),
        "word_count": len(text.split()),
        "section_count": len(re.findall(r"^#{1,4}\s", text, re.MULTILINE)),
    }
    return features


def _slug_prefix(task):
    """Extract verb-noun prefix from a task's slug for grouping."""
    slug = ""
    if isinstance(task, dict):
        slug = task.get("slug", "") or ""
    elif isinstance(task, str):
        slug = task
    parts = slug.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else (slug or "unknown")


def _fingerprint(prompt_text):
    """Compute a stable structural fingerprint of the prompt."""
    features = _extract_features(prompt_text)
    canon = json.dumps(features, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
class _PromptEvolution:
    def __init__(self):
        self._lock = threading.Lock()
        self._analysis_cache = None   # (timestamp, result)
        self._stats = {
            "outcomes_tracked": 0,
            "evolutions_run": 0,
            "merge_rate_before": 0.0,
            "merge_rate_after": 0.0,
        }

    # -------------------------------------------------------------------
    # record_prompt_outcome
    # -------------------------------------------------------------------
    def record_prompt_outcome(self, task, prompt_text, model, integrated, cost_usd, attempt):
        """Store prompt structure fingerprint + outcome in memory and DB."""
        if not ENABLED:
            return
        try:
            features = _extract_features(prompt_text)
            prefix = _slug_prefix(task)
            fp = _fingerprint(prompt_text)

            row = {
                "slug_prefix": prefix,
                "fingerprint": fp,
                "features": json.dumps(features, default=str),
                "integrated": bool(integrated),
                "cost_usd": float(cost_usd or 0),
                "attempt": int(attempt or 1),
                "model": str(model or ""),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            db.insert("prompt_outcomes", row)

            with self._lock:
                self._stats["outcomes_tracked"] += 1
                # Invalidate analysis cache when new data arrives
                self._analysis_cache = None

            _log.info("recorded prompt outcome prefix=%s integrated=%s cost=%.3f",
                      prefix, integrated, cost_usd or 0)
        except Exception as exc:
            _log.debug("record_prompt_outcome failed (fail-soft): %s", exc)

    # -------------------------------------------------------------------
    # analyze_effectiveness
    # -------------------------------------------------------------------
    def analyze_effectiveness(self, min_samples=None):
        """Analyze which prompt features correlate with first-pass merges.

        Returns {"effective_features": [...], "ineffective_features": [...],
                 "recommendations": [...]}.
        Only runs when enough data exists (>= min_samples).
        """
        if not ENABLED:
            return {"effective_features": [], "ineffective_features": [],
                    "recommendations": ["prompt evolution disabled"]}

        ms = min_samples if min_samples is not None else MIN_SAMPLES

        # Check TTL cache
        with self._lock:
            if self._analysis_cache:
                ts, cached = self._analysis_cache
                if time.time() - ts < _ANALYSIS_TTL:
                    return cached

        try:
            rows = db.select("prompt_outcomes", {
                "select": "*",
                "order": "created_at.desc",
                "limit": "5000",
            }) or []
        except Exception as exc:
            _log.debug("analyze_effectiveness: DB read failed: %s", exc)
            return {"effective_features": [], "ineffective_features": [],
                    "recommendations": ["db unavailable"]}

        if len(rows) < ms:
            return {"effective_features": [], "ineffective_features": [],
                    "recommendations": [f"need {ms} samples, have {len(rows)}"]}

        # Parse features and group by presence/absence
        feature_stats = {}
        for fname in _FEATURE_NAMES:
            feature_stats[fname] = {
                "with_count": 0, "with_merged": 0,
                "without_count": 0, "without_merged": 0,
            }

        for row in rows:
            try:
                feat_raw = row.get("features", "{}")
                feats = json.loads(feat_raw) if isinstance(feat_raw, str) else (feat_raw or {})
                merged = bool(row.get("integrated"))
            except Exception:
                continue

            for fname in _FEATURE_NAMES:
                bucket = feature_stats[fname]
                if feats.get(fname):
                    bucket["with_count"] += 1
                    if merged:
                        bucket["with_merged"] += 1
                else:
                    bucket["without_count"] += 1
                    if merged:
                        bucket["without_merged"] += 1

        # Compute merge rates and impact
        effective = []
        ineffective = []
        recommendations = []

        for fname in _FEATURE_NAMES:
            s = feature_stats[fname]
            rate_with = (s["with_merged"] / s["with_count"]) if s["with_count"] >= 5 else None
            rate_without = (s["without_merged"] / s["without_count"]) if s["without_count"] >= 5 else None

            if rate_with is None or rate_without is None:
                continue

            impact = rate_with - rate_without
            entry = {
                "feature": fname,
                "merge_rate_with": round(rate_with, 3),
                "merge_rate_without": round(rate_without, 3),
                "impact": round(impact, 3),
                "sample_size": s["with_count"] + s["without_count"],
            }

            if impact > 0.05:
                effective.append(entry)
                recommendations.append(
                    f"prompts with {fname.replace('has_', '')} merge at "
                    f"{round(rate_with * 100)}% vs {round(rate_without * 100)}% without"
                )
            elif impact < -0.05:
                ineffective.append(entry)
                recommendations.append(
                    f"{fname.replace('has_', '')} correlates with LOWER merge rate: "
                    f"{round(rate_with * 100)}% vs {round(rate_without * 100)}% without"
                )

        # Sort by absolute impact
        effective.sort(key=lambda x: x["impact"], reverse=True)
        ineffective.sort(key=lambda x: x["impact"])

        result = {
            "effective_features": effective,
            "ineffective_features": ineffective,
            "recommendations": recommendations,
            "total_outcomes": len(rows),
        }

        with self._lock:
            self._analysis_cache = (time.time(), result)

        return result

    # -------------------------------------------------------------------
    # evolve_template
    # -------------------------------------------------------------------
    def evolve_template(self, current_template):
        """Evolve a prompt template based on analysis results.

        Conservative: changes at most 2 things per evolution cycle.
        Stores evolution history in prompt_evolution_log table.
        Returns the (possibly modified) template string.
        """
        if not ENABLED or not current_template:
            return current_template or ""

        try:
            analysis = self.analyze_effectiveness()
            effective = analysis.get("effective_features", [])
            ineffective = analysis.get("ineffective_features", [])

            if not effective and not ineffective:
                return current_template

            template = str(current_template)
            changes = []

            # Add sections for strongly effective features (max 1 addition)
            for feat in effective[:1]:
                fname = feat["feature"]
                if feat["impact"] < 0.10:
                    continue  # only act on strong signals

                section = _feature_to_section(fname)
                if section and section.lower() not in template.lower():
                    template = template.rstrip() + "\n\n" + section + "\n"
                    changes.append(f"added {fname} section (impact +{feat['impact']:.0%})")

            # Remove or soften ineffective features (max 1 removal)
            for feat in ineffective[:1]:
                if len(changes) >= 2:
                    break
                fname = feat["feature"]
                if feat["impact"] > -0.10:
                    continue  # only act on strong negative signals

                marker = _feature_to_marker(fname)
                if marker and marker.lower() in template.lower():
                    # Don't delete — add a note to de-emphasize
                    template = template + f"\n\n<!-- NOTE: {fname} may reduce merge rate -->\n"
                    changes.append(f"flagged {fname} (impact {feat['impact']:.0%})")

            # Log evolution
            if changes:
                self._log_evolution(changes, analysis)

            return template

        except Exception as exc:
            _log.debug("evolve_template failed (fail-soft): %s", exc)
            return current_template

    def _log_evolution(self, changes, analysis):
        """Store evolution record in DB."""
        try:
            row = {
                "changes": json.dumps(changes),
                "analysis_snapshot": json.dumps(analysis, default=str)[:4000],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            db.insert("prompt_evolution_log", row)
            with self._lock:
                self._stats["evolutions_run"] += 1
            _log.info("evolution logged: %s", "; ".join(changes))
        except Exception as exc:
            _log.debug("_log_evolution failed: %s", exc)

    # -------------------------------------------------------------------
    # get_evolved_additions
    # -------------------------------------------------------------------
    def get_evolved_additions(self, task, project):
        """Return prompt additions based on learned effective features for this task type.

        E.g. if test criteria boost merge rates for this slug prefix, returns
        a "## Required Tests: ..." section to append to the prompt.
        """
        if not ENABLED:
            return ""

        try:
            analysis = self.analyze_effectiveness()
            effective = analysis.get("effective_features", [])
            if not effective:
                return ""

            prefix = _slug_prefix(task)
            additions = []

            # Check if this task type has specific patterns
            try:
                rows = db.select("prompt_outcomes", {
                    "select": "features,integrated",
                    "slug_prefix": f"eq.{prefix}",
                    "limit": "200",
                }) or []
            except Exception:
                rows = []

            # Compute per-prefix feature effectiveness if enough data
            prefix_effective = set()
            if len(rows) >= 10:
                for fname in _FEATURE_NAMES:
                    w, wm, wo, wom = 0, 0, 0, 0
                    for r in rows:
                        try:
                            feats = json.loads(r.get("features", "{}")) if isinstance(r.get("features"), str) else (r.get("features") or {})
                            merged = bool(r.get("integrated"))
                        except Exception:
                            continue
                        if feats.get(fname):
                            w += 1
                            wm += int(merged)
                        else:
                            wo += 1
                            wom += int(merged)
                    if w >= 3 and wo >= 3:
                        rw = wm / w
                        rwo = wom / wo
                        if rw - rwo > 0.10:
                            prefix_effective.add(fname)

            # Use global effectiveness when prefix data is sparse
            if not prefix_effective:
                prefix_effective = {f["feature"] for f in effective if f["impact"] > 0.10}

            # Generate additions for missing effective features
            for fname in prefix_effective:
                section = _feature_to_addition(fname, prefix)
                if section:
                    additions.append(section)

            return "\n\n".join(additions[:3])  # cap at 3 additions

        except Exception as exc:
            _log.debug("get_evolved_additions failed (fail-soft): %s", exc)
            return ""

    # -------------------------------------------------------------------
    # stats
    # -------------------------------------------------------------------
    def stats(self):
        """Return tracking statistics."""
        with self._lock:
            s = dict(self._stats)

        # Enrich with live DB counts
        try:
            rows = db.select("prompt_outcomes", {"select": "integrated", "limit": "5000"}) or []
            s["outcomes_tracked"] = max(s["outcomes_tracked"], len(rows))
            if rows:
                merged = sum(1 for r in rows if r.get("integrated"))
                s["overall_merge_rate"] = round(merged / len(rows), 3)
        except Exception:
            pass

        try:
            evolutions = db.select("prompt_evolution_log", {"select": "id", "limit": "1000"}) or []
            s["evolutions_run"] = max(s["evolutions_run"], len(evolutions))
        except Exception:
            pass

        # Compute improvement if we have enough data
        try:
            analysis = self.analyze_effectiveness()
            effective = analysis.get("effective_features", [])
            if effective:
                s["top_feature"] = effective[0]["feature"]
                s["top_feature_impact"] = effective[0]["impact"]
        except Exception:
            pass

        return s


# ---------------------------------------------------------------------------
# Helper functions for template evolution
# ---------------------------------------------------------------------------
def _feature_to_section(fname):
    """Map a feature name to a template section to add."""
    sections = {
        "has_examples": "## Examples\nProvide concrete before/after examples of the change.",
        "has_file_list": "## Files to Modify\nList the specific files that need changes.",
        "has_constraints": "## Constraints\n- Must not break existing tests\n- Must not introduce new warnings",
        "has_test_criteria": "## Required Tests\nDescribe specific test cases that must pass.",
        "has_build_mandate": "## Build Requirement\nThe code must build successfully with zero errors.",
        "has_precedent": "## Precedent\nReference prior successful merges with similar patterns.",
        "has_spec_refinement": "## Specification\nClarify the exact behavior expected.",
    }
    return sections.get(fname, "")


def _feature_to_marker(fname):
    """Map a feature name to text that indicates its presence in a template."""
    markers = {
        "has_examples": "## examples",
        "has_file_list": "## files",
        "has_constraints": "## constraints",
        "has_test_criteria": "## required tests",
        "has_build_mandate": "## build requirement",
        "has_precedent": "## precedent",
        "has_spec_refinement": "## specification",
    }
    return markers.get(fname, "")


def _feature_to_addition(fname, prefix=""):
    """Generate a prompt addition for a specific effective feature."""
    additions = {
        "has_examples": "## Examples\nInclude at least one concrete example of the expected input/output or before/after.",
        "has_file_list": "## Files\nList all files that will be created or modified.",
        "has_constraints": "## Constraints\n- Must not break existing tests\n- Must maintain backward compatibility",
        "has_test_criteria": "## Required Tests\nInclude test cases that validate the change works correctly.",
        "has_build_mandate": "## Build\nThe result must build and pass all existing tests.",
        "has_precedent": "## Precedent\nFollow patterns established by prior successful merges.",
        "has_spec_refinement": "## Spec\nClarify edge cases and expected behavior precisely.",
    }
    return additions.get(fname, "")


# ---------------------------------------------------------------------------
# Singleton + module-level API
# ---------------------------------------------------------------------------
_instance = _PromptEvolution()


def record_prompt_outcome(task, prompt_text, model, integrated, cost_usd, attempt):
    """Store prompt structure fingerprint + outcome."""
    return _instance.record_prompt_outcome(task, prompt_text, model, integrated, cost_usd, attempt)


def analyze_effectiveness(min_samples=None):
    """Analyze which prompt features correlate with first-pass merges."""
    return _instance.analyze_effectiveness(min_samples)


def evolve_template(current_template):
    """Evolve a prompt template based on learned effectiveness data."""
    return _instance.evolve_template(current_template)


def get_evolved_additions(task, project):
    """Return prompt additions based on learned effective features."""
    return _instance.get_evolved_additions(task, project)


def stats():
    """Return tracking statistics."""
    return _instance.stats()
