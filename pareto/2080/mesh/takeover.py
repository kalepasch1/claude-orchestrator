"""Aging-parent graduated takeover via a reverse trust-ratchet.

A guardian does not seize a parent's authority in one step. The ratchet walks
the parent DOWN one tier at a time — UNLIMITED_WITH_RECEIPTS -> CAPPED ->
APPROVAL_ONLY — so a premature or mistaken takeover costs one tier, not the
whole household.

FAILS CLOSED: a takeover by someone without a `guardian_of` edge to the holder
returns the budget UNCHANGED. Denial is never silent — it is logged and
reported through :func:`takeover_with_reason`.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Iterable

from passport import _contracts, has_authority_over

log = logging.getLogger(__name__)

#: Strictly decreasing order of authority. Index 0 is the most authority.
_TIER_ORDER = ("unlimited_with_receipts", "capped", "approval_only")

#: Cap applied when a holder is ratcheted down into CAPPED.
DEFAULT_CAPPED_USD = float(500)


def _tier_value(tier: Any) -> str:
    """Normalize an AuthorityTier or bare string to its value."""
    value = getattr(tier, "value", tier)
    return value.strip().lower() if isinstance(value, str) else ""


def _tier_from_value(value: str) -> Any:
    """Rebuild an AuthorityTier from its value, or return the bare string."""
    if _contracts is not None and hasattr(_contracts, "AuthorityTier"):
        try:
            return _contracts.AuthorityTier(value)
        except Exception:  # pragma: no cover - defensive
            pass
    return value


def _tier_index(budget: Any) -> int:
    """Position of ``budget`` in :data:`_TIER_ORDER`; -1 if unrecognized."""
    try:
        return _TIER_ORDER.index(_tier_value(getattr(budget, "tier", None)))
    except (ValueError, AttributeError):
        return -1


def _with_tier(budget: Any, index: int) -> Any:
    """Copy ``budget`` at tier ``index``, adjusting the cap to match."""
    value = _TIER_ORDER[index]
    cap = {
        "unlimited_with_receipts": float(getattr(budget, "cap_usd", 0.0) or 0.0),
        "capped": DEFAULT_CAPPED_USD,
        "approval_only": 0.0,
    }[value]
    try:
        return replace(budget, tier=_tier_from_value(value), cap_usd=cap)
    except Exception:  # not a dataclass - fall back to a shallow copy
        import copy

        clone = copy.copy(budget)
        clone.tier = _tier_from_value(value)
        clone.cap_usd = cap
        return clone


class HouseholdReverseRatchet:
    """A :class:`ReverseTrustRatchet` bound to a household passport mesh.

    Satisfies the contracts Protocol: ``takeover(budget, guardian_id)`` and
    ``release(budget)``.
    """

    def __init__(self, passports: Iterable[Any] | None = None):
        self._passports = list(passports or [])

    # -- Protocol surface -------------------------------------------------

    def takeover(self, budget: Any, guardian_id: str) -> Any:
        """Ratchet ``budget`` down one tier. Unchanged if not authorized."""
        return self.takeover_with_reason(budget, guardian_id)[0]

    def release(self, budget: Any) -> Any:
        """Restore the holder one tier. Unchanged at the top tier."""
        try:
            index = _tier_index(budget)
            if index <= 0:
                return budget
            return _with_tier(budget, index - 1)
        except Exception as exc:
            log.warning("takeover: release failed (%s); leaving budget unchanged", exc)
            return budget


    # -- Reportable form --------------------------------------------------

    def takeover_with_reason(self, budget: Any, guardian_id: str) -> tuple[Any, str]:
        """``(budget, reason)``. Reason explains any refusal in plain language.

        FAILS CLOSED — every early return hands back the ORIGINAL budget.
        """
        try:
            if budget is None:
                return budget, "denied: no budget supplied"
            if not isinstance(guardian_id, str) or not guardian_id.strip():
                return budget, "denied: no guardian identified"

            guardian = guardian_id.strip()
            holder = getattr(budget, "holder_id", "") or ""
            if not isinstance(holder, str) or not holder.strip():
                return budget, "denied: budget has no holder"
            holder = holder.strip()

            if guardian == holder:
                return budget, "denied: a holder cannot take over from themselves"

            if not has_authority_over(self._passports, guardian, holder):
                log.warning(
                    "takeover: %s has no guardian_of edge to %s; denying",
                    guardian, holder,
                )
                return budget, f"denied: {guardian} is not a guardian of {holder}"

            index = _tier_index(budget)
            if index < 0:
                return budget, "denied: unrecognized authority tier"
            if index >= len(_TIER_ORDER) - 1:
                return budget, "no-op: holder is already at the lowest tier"

            return _with_tier(budget, index + 1), (
                f"granted: {holder} ratcheted "
                f"{_TIER_ORDER[index]} -> {_TIER_ORDER[index + 1]} by {guardian}"
            )
        except Exception as exc:
            log.warning("takeover: failed (%s); denying", exc)
            return budget, f"denied: takeover errored ({exc})"


def graduated_takeover(
    passports: Iterable[Any], budget: Any, guardian_id: str, steps: int = 1
) -> Any:
    """Apply up to ``steps`` ratchet steps. Stops at the first refusal."""
    ratchet = HouseholdReverseRatchet(passports)
    current = budget
    for _ in range(max(0, int(steps or 0))):
        nxt, reason = ratchet.takeover_with_reason(current, guardian_id)
        if not reason.startswith("granted"):
            break
        current = nxt
    return current
