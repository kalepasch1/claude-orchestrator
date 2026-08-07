"""Subscription tier thresholds and escalation.

Decides whether a household's regime-change activity has outgrown its tier.
Pure: no I/O, no clock reads, no side effects — an escalation is a
RECOMMENDATION, never an automatic upgrade. Charging someone more because a
jurisdiction changed a rule is a decision a human makes.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

TIERS: List[str] = ["free", "standard", "premium"]

# Regime updates per period a tier covers before it is outgrown.
TIER_LIMITS: Dict[str, int] = {
    "free": 1,
    "standard": 10,
    "premium": 1_000_000,
}

# Jurisdictions whose complexity requires at least this tier.
JURISDICTION_FLOOR: Dict[str, str] = {
    "CA": "standard",
    "NY": "standard",
}


@dataclass
class TierEvaluation:
    current_tier: str
    recommended_tier: str
    escalate: bool
    usage: int
    limit: int
    reasons: List[str]


def normalize_tier(tier: Optional[str]) -> str:
    """Map any input to a known tier. Unknown input reads as the LOWEST tier.

    Failing upward would silently grant paid entitlements on a typo.
    """
    value = f"{tier or ''}".strip().lower()
    return value if value in TIER_LIMITS else "free"


def tier_rank(tier: Optional[str]) -> int:
    return TIERS.index(normalize_tier(tier))


def higher_tier(a: Optional[str], b: Optional[str]) -> str:
    return a if tier_rank(a) >= tier_rank(b) else b  # type: ignore[return-value]


def next_tier(tier: Optional[str]) -> str:
    rank = tier_rank(tier)
    return TIERS[min(rank + 1, len(TIERS) - 1)]


def evaluate_tier(
    current_tier: Optional[str],
    regime_update_count: int = 0,
    jurisdictions: Optional[List[str]] = None,
) -> TierEvaluation:
    """Recommend a tier for the observed usage. Never raises."""
    tier = normalize_tier(current_tier)
    limit = TIER_LIMITS[tier]
    reasons: List[str] = []

    try:
        usage = int(regime_update_count)
    except (TypeError, ValueError):
        usage = 0
    usage = max(0, usage)

    recommended = tier

    if usage > limit:
        recommended = higher_tier(recommended, next_tier(tier))
        reasons.append(f"{usage} regime update(s) exceeds the {tier} limit of {limit}")

    for jurisdiction in (jurisdictions or []):
        floor = JURISDICTION_FLOOR.get(f"{jurisdiction or ''}".strip().upper())
        if floor and tier_rank(tier) < tier_rank(floor):
            recommended = higher_tier(recommended, floor)
            reasons.append(f"jurisdiction {jurisdiction} requires at least {floor}")

    escalate = tier_rank(recommended) > tier_rank(tier)
    if not escalate:
        reasons.append(f"{tier} tier covers current usage ({usage}/{limit})")

    return TierEvaluation(
        current_tier=tier,
        recommended_tier=recommended,
        # An escalation is a recommendation for a human, never an auto-upgrade.
        escalate=escalate,
        usage=usage,
        limit=limit,
        reasons=reasons,
    )
