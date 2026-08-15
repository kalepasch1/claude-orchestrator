"""Subscription tier thresholds and escalation.

Decides whether a household's regime-change activity has outgrown its tier.
Pure: no I/O, no clock reads, no side effects — an escalation is a
RECOMMENDATION, never an automatic upgrade. Charging someone more because a
jurisdiction changed a rule is a decision a human makes.
"""
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# '2080' is not a valid Python identifier, so siblings are imported by bare name
# off sys.path — the same convention as regime_consumer.py and the tests.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from regime_consumer import normalize_regime_event  # noqa: E402

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


# --------------------------------------------------------------------------
# Remediation threshold + licensed-partner escalation
# --------------------------------------------------------------------------

# Regime-event kinds that count as a compliance BREACH rather than routine news.
# Kept as a literal set so widening the definition is a one-line change and
# never an edit to the decision logic below.
BREACH_KINDS: List[str] = [
    "breach",
    "violation",
    "non_compliance",
    "noncompliance",
    "enforcement",
    "penalty",
]

# Tiers whose remediation we are paid to perform IN HOUSE. Everything not named
# here is unpaid, and unpaid work must be handed to a licensed partner.
IN_HOUSE_TIERS: List[str] = ["standard", "premium"]


def _event_kind(event: Any) -> str:
    """Best-effort read of an event's kind. Never raises."""
    try:
        if isinstance(event, dict):
            raw = event.get("kind") or event.get("event_type") or event.get("type") or ""
        else:
            raw = (
                getattr(event, "kind", None)
                or getattr(event, "event_type", None)
                or getattr(event, "type", None)
                or ""
            )
        return f"{raw}".strip().lower()
    except Exception:
        return ""


def is_breach_event(event: Any) -> bool:
    """True only when the event is a trustworthy breach signal.

    Trust is established by `normalize_regime_event`, so a malformed or
    unattributable event returns False instead of raising — an oracle hiccup
    must not be able to manufacture (or suppress) an escalation by crashing.
    """
    try:
        if normalize_regime_event(event) is None:
            return False
        return _event_kind(event) in BREACH_KINDS
    except Exception:
        return False


class SubscriptionTierMonitor:
    """Routes breach remediation to the right side of the licensing line.

    A PAID tier gets in-house remediation: escalating them to an outside
    partner would be selling them something they have already bought. A FREE
    tier gets escalated to licensed partners, because remediating for them
    in house is unlicensed work performed on someone's behalf.

    Those two errors are not symmetric — the second one is the serious one —
    so the direction is encoded here rather than left configurable.
    """

    def __init__(self, partner_queue: Optional[Any] = None) -> None:
        # Injected sink so the escalation is observable in tests and so this
        # module performs no I/O of its own.
        self._partner_queue = partner_queue
        self.escalations: List[Dict[str, Any]] = []

    def check_remediation_threshold(
        self,
        user_subscription_tier: Optional[str],
        regime_event: Any,
    ) -> bool:
        """True when this user's breach must go to a licensed partner.

        Never raises: a malformed event reads as "no breach", which leaves the
        user exactly where they were rather than triggering a spurious handoff.
        """
        if not is_breach_event(regime_event):
            return False
        return normalize_tier(user_subscription_tier) not in IN_HOUSE_TIERS

    def escalate_to_licensed_partners(self, user_id: Any, case_summary: Any) -> None:
        """Hand a case to the licensed-partner queue. Fail-soft by design.

        A raising sink must not propagate: losing the escalation record is bad,
        but crashing the regime-consumer loop would stop every other household's
        processing too.
        """
        record = {
            "user_id": f"{user_id or ''}".strip(),
            "case_summary": f"{case_summary or ''}".strip(),
        }
        self.escalations.append(record)
        if self._partner_queue is None:
            return
        try:
            if callable(self._partner_queue):
                self._partner_queue(record)
            else:
                self._partner_queue.append(record)
        except Exception:
            # Deliberately swallowed: see docstring.
            pass

    def handle_regime_event(
        self,
        user_id: Any,
        user_subscription_tier: Optional[str],
        regime_event: Any,
        case_summary: Any = None,
    ) -> bool:
        """Check the threshold and escalate when it is crossed. Returns whether it escalated."""
        if not self.check_remediation_threshold(user_subscription_tier, regime_event):
            return False
        summary = case_summary
        if summary is None:
            normalized = normalize_regime_event(regime_event) or {}
            summary = (
                f"{normalized.get('jurisdiction', '')} "
                f"{normalized.get('rule_id', '')} "
                f"{normalized.get('description', '')}"
            ).strip()
        self.escalate_to_licensed_partners(user_id, summary)
        return True
