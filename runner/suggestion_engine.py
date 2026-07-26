"""
suggestion_engine.py — AI-driven improvement suggestions for the Trojun Orchestrator Terminal.

Generates ranked suggestions after task completion based on patterns in the task history.
Integrates with model_gateway.complete() for AI-powered analysis.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)


class SuggestionCategory(str, Enum):
    PERFORMANCE = "performance"
    COST = "cost"
    RELIABILITY = "reliability"
    SECURITY = "security"
    CODE_QUALITY = "code_quality"
    TESTING = "testing"
    ARCHITECTURE = "architecture"


class ImpactMultiplier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EffortLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Suggestion:
    id: str
    title: str
    description: str
    category: SuggestionCategory
    impact: ImpactMultiplier
    effort: EffortLevel
    risk: RiskLevel
    score: float = 0.0
    task_slug: Optional[str] = None
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict:
        d = asdict(self)
        d['category'] = self.category.value
        d['impact'] = self.impact.value
        d['effort'] = self.effort.value
        d['risk'] = self.risk.value
        return d


# Score matrix: impact * effort_inverse * risk_inverse
_IMPACT_SCORES = {ImpactMultiplier.HIGH: 3, ImpactMultiplier.MEDIUM: 2, ImpactMultiplier.LOW: 1}
_EFFORT_SCORES = {EffortLevel.LOW: 3, EffortLevel.MEDIUM: 2, EffortLevel.HIGH: 1}
_RISK_SCORES = {RiskLevel.LOW: 3, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 1}


def _score(s: Suggestion) -> float:
    return (
        _IMPACT_SCORES[s.impact] * 4 +
        _EFFORT_SCORES[s.effort] * 2 +
        _RISK_SCORES[s.risk]
    )


def _heuristic_suggestions(task: dict) -> list[Suggestion]:
    """Generate heuristic suggestions from task metadata without calling an LLM."""
    suggestions = []
    slug = task.get("slug", "")
    state = task.get("state", "")
    cost = task.get("cost_usd") or 0
    kind = task.get("kind", "")
    cascade_confidence = task.get("cascade_confidence") or 0

    if state in ("TESTFAIL", "BUILDFAIL"):
        suggestions.append(Suggestion(
            id=f"s-testfix-{int(time.time())}",
            title="Add pre-flight test gate",
            description="Route tasks through a fast test suite before full execution to catch failures earlier.",
            category=SuggestionCategory.RELIABILITY,
            impact=ImpactMultiplier.HIGH,
            effort=EffortLevel.MEDIUM,
            risk=RiskLevel.LOW,
            task_slug=slug,
        ))

    if cost > 0.10:
        suggestions.append(Suggestion(
            id=f"s-cost-{int(time.time())}",
            title="Enable cascade model routing",
            description=f"Task cost ${cost:.4f} is above threshold. Cascade routing can save 60-90% by starting on cheap models.",
            category=SuggestionCategory.COST,
            impact=ImpactMultiplier.HIGH,
            effort=EffortLevel.LOW,
            risk=RiskLevel.LOW,
            task_slug=slug,
        ))

    if cascade_confidence > 0 and cascade_confidence < 0.6:
        suggestions.append(Suggestion(
            id=f"s-cascade-{int(time.time())}",
            title="Improve task decomposition for better cascade confidence",
            description="Low cascade confidence suggests tasks are too complex. Consider splitting into smaller subtasks.",
            category=SuggestionCategory.PERFORMANCE,
            impact=ImpactMultiplier.MEDIUM,
            effort=EffortLevel.MEDIUM,
            risk=RiskLevel.LOW,
            task_slug=slug,
        ))

    if kind in ("build", "feature") and not slug.startswith("test-"):
        suggestions.append(Suggestion(
            id=f"s-test-{int(time.time())}",
            title="Add automated test coverage for this feature",
            description="New features without test slugs risk regressions. Queue a parallel test task.",
            category=SuggestionCategory.TESTING,
            impact=ImpactMultiplier.MEDIUM,
            effort=EffortLevel.LOW,
            risk=RiskLevel.LOW,
            task_slug=slug,
        ))

    return suggestions


def generate_suggestions(task: dict, use_ai: bool = False) -> list[dict]:
    """
    Generate improvement suggestions for a completed task.

    Args:
        task: Task dict with keys: slug, state, cost_usd, kind, cascade_confidence, etc.
        use_ai: If True, attempt to call model_gateway for richer suggestions.

    Returns:
        List of suggestion dicts sorted by score (highest first).
    """
    suggestions = _heuristic_suggestions(task)

    if use_ai:
        try:
            import model_gateway
            prompt = f"""You are an orchestration improvement advisor. A task just completed with these metrics:
Slug: {task.get('slug')}
State: {task.get('state')}
Kind: {task.get('kind')}
Cost: ${task.get('cost_usd', 0):.4f}
Cascade confidence: {task.get('cascade_confidence', 'N/A')}

List 2-3 specific, actionable improvements as JSON: [{{"title": "...", "description": "...", "impact": "HIGH|MEDIUM|LOW", "effort": "low|medium|high", "category": "..."}}]
Only respond with the JSON array."""

            result = model_gateway.complete(
                prompt=prompt,
                model="claude-haiku",
                max_tokens=512,
                temperature=0.3,
            )
            ai_suggestions = json.loads(result.strip())
            for i, s in enumerate(ai_suggestions[:3]):
                suggestions.append(Suggestion(
                    id=f"s-ai-{int(time.time())}-{i}",
                    title=s.get("title", ""),
                    description=s.get("description", ""),
                    category=SuggestionCategory(s.get("category", "code_quality")),
                    impact=ImpactMultiplier(s.get("impact", "MEDIUM").upper()),
                    effort=EffortLevel(s.get("effort", "medium").lower()),
                    risk=RiskLevel.LOW,
                    task_slug=task.get("slug"),
                ))
        except Exception as e:
            log.debug("AI suggestion generation skipped: %s", e)

    # Score and sort
    for s in suggestions:
        s.score = _score(s)
    suggestions.sort(key=lambda s: s.score, reverse=True)

    return [s.to_dict() for s in suggestions[:5]]
