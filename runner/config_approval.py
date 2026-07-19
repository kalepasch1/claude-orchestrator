#!/usr/bin/env python3
"""
config_approval.py - AI-driven configuration change approval system.

Evaluates configuration changes by risk score, auto-approves low-risk
changes (cosmetic, display preferences), and flags high-risk changes
(tokens, secrets, auth settings) for manual review.  Every decision
is logged to an audit trail via the db module.
"""

import os
import re
import sys
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class Decision(Enum):
    AUTO_APPROVED = "auto_approved"
    MANUAL_REVIEW = "manual_review"
    DENIED = "denied"


@dataclass
class ConfigChange:
    key: str
    old_value: Optional[str]
    new_value: Optional[str]
    requester: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ApprovalDecision:
    change: ConfigChange
    decision: Decision
    risk_score: float          # 0.0 (no risk) .. 1.0 (critical)
    reason: str
    decided_by: str = "config-approval-ai"
    decided_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Risk patterns
# ---------------------------------------------------------------------------

# Keys whose names match these patterns are considered high-risk.
HIGH_RISK_PATTERNS: list[re.Pattern] = [
    re.compile(r"(pat|token|secret|api_key|password|credential|auth)", re.I),
    re.compile(r"(private_key|signing_key|encryption_key)", re.I),
    re.compile(r"(database_url|db_password|connection_string)", re.I),
    re.compile(r"(webhook_secret|jwt_secret|session_secret)", re.I),
]

MEDIUM_RISK_PATTERNS: list[re.Pattern] = [
    re.compile(r"(rate_limit|max_retries|timeout|concurrency)", re.I),
    re.compile(r"(allowed_origins|cors|ip_whitelist|ip_allowlist)", re.I),
    re.compile(r"(feature_flag|rollout|experiment)", re.I),
    re.compile(r"(log_level|debug_mode|verbose)", re.I),
]

# Keys matching these are cosmetic / low-risk -- safe to auto-approve.
LOW_RISK_PATTERNS: list[re.Pattern] = [
    re.compile(r"(display_name|label|title|description|color|theme)", re.I),
    re.compile(r"(timezone|locale|language|date_format)", re.I),
    re.compile(r"(page_size|default_sort|ui_)", re.I),
]

# Thresholds
AUTO_APPROVE_CEILING = 0.3   # score <= this -> auto-approve
MANUAL_REVIEW_FLOOR = 0.7    # score >= this -> manual review required
# Between ceiling and floor -> auto-approve with logged caution.


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_key(key: str) -> float:
    """Score based on the config key name alone."""
    for pat in HIGH_RISK_PATTERNS:
        if pat.search(key):
            return 0.9
    for pat in MEDIUM_RISK_PATTERNS:
        if pat.search(key):
            return 0.5
    for pat in LOW_RISK_PATTERNS:
        if pat.search(key):
            return 0.1
    return 0.4  # unknown keys get a moderate baseline


def _score_value_delta(old_value: Optional[str], new_value: Optional[str]) -> float:
    """Extra risk if the new value looks like a secret or the change is drastic."""
    bump = 0.0
    if new_value and re.search(r"(ghp_|sk-|xox[bpas]-|AKIA)", new_value):
        bump += 0.3  # value looks like a real credential
    if old_value is None and new_value is not None:
        bump += 0.05  # adding a new key
    if old_value is not None and new_value is None:
        bump += 0.1  # deleting a key
    return bump


def compute_risk_score(change: ConfigChange) -> float:
    """Return a risk score in [0.0, 1.0]."""
    score = _score_key(change.key) + _score_value_delta(change.old_value, change.new_value)
    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

def evaluate_change(change: ConfigChange) -> ApprovalDecision:
    """Evaluate a config change and return an approval decision.

    Low-risk changes are auto-approved.  High-risk changes are flagged
    for manual review.  All decisions are logged to the audit trail.
    """
    risk = compute_risk_score(change)

    if risk <= AUTO_APPROVE_CEILING:
        decision = Decision.AUTO_APPROVED
        reason = f"Low-risk config change (score={risk:.2f}); auto-approved."
    elif risk >= MANUAL_REVIEW_FLOOR:
        decision = Decision.MANUAL_REVIEW
        reason = f"High-risk config change (score={risk:.2f}); requires manual review."
    else:
        decision = Decision.AUTO_APPROVED
        reason = f"Moderate-risk config change (score={risk:.2f}); auto-approved with caution."

    result = ApprovalDecision(
        change=change,
        decision=decision,
        risk_score=risk,
        reason=reason,
    )

    _log_decision(result)
    return result


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def _log_decision(ad: ApprovalDecision) -> None:
    """Persist an approval decision to the audit trail."""
    try:
        payload = {
            "key": ad.change.key,
            "requester": ad.change.requester,
            "decision": ad.decision.value,
            "risk_score": ad.risk_score,
            "reason": ad.reason,
            "decided_by": ad.decided_by,
            "old_value_redacted": _redact(ad.change.old_value),
            "new_value_redacted": _redact(ad.change.new_value),
        }
        db.log(
            kind="config_approval",
            blob=json.dumps(payload),
        )
    except Exception:
        # Never let audit logging break the approval flow.
        pass


def _redact(value: Optional[str], visible: int = 4) -> Optional[str]:
    """Show only the first few characters of a value for audit logs."""
    if value is None:
        return None
    if len(value) <= visible:
        return value
    return value[:visible] + "***"
