"""
bot_factory.py — Pure module for building and evaluating expert bots.

Provides BotSpec dataclass and factory functions to validate, evaluate,
and admit bots into the runDetermination roster.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional

VALID_ROLES = ("authority", "discipline", "advisor", "adversary", "advocate", "reviewer")

MIN_EVAL = int(os.environ.get("BOT_FACTORY_MIN_EVAL", "5"))
CALIBRATION_FLOOR = float(os.environ.get("BOT_FACTORY_CALIBRATION_FLOOR", "0.6"))
PASS_RATE_FLOOR = float(os.environ.get("BOT_FACTORY_PASS_RATE_FLOOR", "0.7"))


@dataclass
class BotSpec:
    id: str
    role: Literal["authority", "discipline", "advisor", "adversary", "advocate", "reviewer"]
    target_app: str
    corpus_filter: Dict[str, Any]
    priors_tag: str
    competence: Dict[str, float] = field(default_factory=dict)
    authority: float = 0.5
    reliability: float = 0.5
    eval_set: List[Dict[str, Any]] = field(default_factory=list)


def _validate_spec(spec: BotSpec) -> None:
    """Raise ValueError if spec is invalid."""
    if spec.role not in VALID_ROLES:
        raise ValueError(f"Invalid role '{spec.role}'; must be one of {VALID_ROLES}")
    if not spec.corpus_filter:
        raise ValueError("corpus_filter must be non-empty")
    if len(spec.eval_set) < MIN_EVAL:
        raise ValueError(
            f"eval_set must have at least {MIN_EVAL} items, got {len(spec.eval_set)}"
        )


def run_eval(
    spec: BotSpec,
    invoker: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    """Run each eval issue through the injected invoker and score results.

    invoker(persona, issue) -> {stance, confidence, citations}
    Each eval item: {issue: ..., expected: ...}

    Returns {passed: int, total: int, calibration: float}.
    """
    persona = {
        "id": spec.id,
        "role": spec.role,
        "competence": spec.competence,
        "priors_tag": spec.priors_tag,
    }
    passed = 0
    total = len(spec.eval_set)
    confidence_sum = 0.0
    correct_confidence_sum = 0.0

    for item in spec.eval_set:
        result = invoker(persona, item["issue"])
        stance = result.get("stance", "")
        confidence = float(result.get("confidence", 0.0))
        confidence_sum += confidence

        if stance == item["expected"]:
            passed += 1
            correct_confidence_sum += confidence

    # Calibration: ratio of average confidence on correct answers vs overall avg confidence
    # High calibration = confident when right, not confident when wrong
    if total > 0 and confidence_sum > 0:
        avg_confidence = confidence_sum / total
        avg_correct_confidence = correct_confidence_sum / max(passed, 1)
        calibration = min(avg_correct_confidence / max(avg_confidence, 0.01), 1.0)
    else:
        calibration = 0.0

    return {"passed": passed, "total": total, "calibration": calibration}


def build_bot(
    spec: BotSpec,
    invoker: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate spec, run eval, and produce manifest + admission decision.

    Returns {manifest: dict, admission: str}.
    admission is 'admitted' only if calibration >= FLOOR and pass_rate >= FLOOR.
    """
    _validate_spec(spec)

    eval_result = run_eval(spec, invoker)
    pass_rate = eval_result["passed"] / max(eval_result["total"], 1)
    calibration = eval_result["calibration"]

    admitted = (
        calibration >= CALIBRATION_FLOOR and pass_rate >= PASS_RATE_FLOOR
    )

    manifest = {
        "id": spec.id,
        "role": spec.role,
        "competence": spec.competence,
        "authority": spec.authority,
        "reliability": spec.reliability,
        "priors_tag": spec.priors_tag,
        "corpus_filter": spec.corpus_filter,
    }

    return {
        "manifest": manifest,
        "admission": "admitted" if admitted else "gated",
        "eval": eval_result,
    }
