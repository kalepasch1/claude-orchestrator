#!/usr/bin/env python3
"""
mutual_default_fund.py - Completeness-priced mutual default fund.

Non-custodial, mutualized loss-absorbing layer. No pooled custody, no fund entity.
Synthetic mechanism embedded in documentation/paper. Pricing by member credit and
completeness score.

Legal positioning: Internal administrative tool, non-custodial, purely computational.
"""
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from config_manager import ConfigManager

log = logging.getLogger(__name__)

config = ConfigManager(defaults={
    "MDF_ENABLED": False,
    "MDF_CONTRIBUTION_BPS": 10,
    "MDF_COMPLETENESS_WEIGHT": 1.0,
    "MDF_CREDIT_GATE_THRESHOLD": 700,
})


class MdfAuditLog:
    def __init__(self):
        self.entries = []

    def log_contribution(self, member_id: str, completeness: float, contribution_bps: float):
        self.entries.append({
            "event": "contribution_calculated",
            "member_id": member_id,
            "completeness": completeness,
            "contribution_bps": contribution_bps,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    def log_exclusion(self, member_id: str, reason: str):
        self.entries.append({
            "event": "member_excluded",
            "member_id": member_id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    def get_entries(self) -> list:
        return self.entries


def calculate_contribution_bps(completeness_score: float, base_bps: float = 10) -> float:
    """
    Calculate member contribution in basis points based on completeness score.

    Inverse relationship: lower completeness = higher contribution.
    At 100% completeness: 0 bps
    At 0% completeness: base_bps
    """
    if not (0 <= completeness_score <= 100):
        raise ValueError("Completeness score must be 0-100")

    contribution = base_bps * (1 - completeness_score / 100)
    return round(contribution, 2)


def meets_credit_threshold(credit_score: float, threshold: Optional[float] = None) -> bool:
    """Check if member credit qualifies for MDF participation."""
    if threshold is None:
        threshold = config.get("MDF_CREDIT_GATE_THRESHOLD", 700)
    return credit_score >= threshold


def apply_default_waterfall(
    margin_available: float,
    penalty_rate: float,
    member_count: int
) -> Dict[str, float]:
    """
    Apply default waterfall: defaulter margin → penalty → member assessments.

    Ensures defaulter bears primary loss, MDF is secondary loss-absorber.

    Args:
        margin_available: Margin amount available for loss absorption
        penalty_rate: Rate to apply as penalty (0 < rate <= 1)
        member_count: Number of members in pool (must be >= 2)

    Returns:
        Dict with defaulter_loss, penalty_amount, member_assessment
    """
    if margin_available < 0:
        raise ValueError("Margin must be non-negative")
    if not (0 < penalty_rate <= 1):
        raise ValueError("Penalty rate must be 0 < x <= 1")
    if member_count < 2:
        raise ValueError("Need at least 2 members")

    defaulter_loss = margin_available
    penalty_amount = margin_available * penalty_rate
    remaining_loss = max(0, margin_available - defaulter_loss - penalty_amount)
    member_assessment = remaining_loss / member_count if remaining_loss > 0 else 0

    return {
        "defaulter_loss": defaulter_loss,
        "penalty_amount": penalty_amount,
        "member_assessment": member_assessment,
    }


def validate_mdf_config(config_dict: Dict[str, Any]) -> bool:
    """Validate mutual default fund configuration."""
    assert config_dict.get("MDF_CONTRIBUTION_BPS", 0) >= 0, \
        "Contribution BPS must be non-negative"
    assert 0 < config_dict.get("MDF_COMPLETENESS_WEIGHT", 1.0) <= 10, \
        "Completeness weight must be positive"
    assert 0 <= config_dict.get("MDF_CREDIT_GATE_THRESHOLD", 0) <= 850, \
        "Credit threshold must be valid FICO range"
    return True


def should_include_member(credit_score: float, completeness_score: float) -> bool:
    """Determine if member qualifies for MDF inclusion."""
    if not meets_credit_threshold(credit_score):
        return False
    if completeness_score < 0 or completeness_score > 100:
        return False
    return True


def calculate_member_assessment(completeness_score: float, base_contribution: float) -> float:
    """Calculate member assessment based on completeness."""
    multiplier = 1 - (completeness_score / 100)
    return base_contribution * multiplier
