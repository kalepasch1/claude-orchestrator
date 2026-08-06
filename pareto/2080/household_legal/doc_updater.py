"""P4 — household legal: regime-aware document updates + notification.

When a jurisdiction changes a rule (a RegimeEvent from the P-phase regime oracle), the
household's lease template may need to change with it. This module applies that update and
tells the affected user what moved.

Two deliberate properties:

* **Fail-soft everywhere.** Every oracle call goes through `safe_consume_regime_event()`, and
  every public entry point returns a sensible default rather than raising. A rule feed that is
  slow, malformed, or not yet deployed must not take the household stack down — it must leave
  the template exactly as it was and say so.

* **No silent edits.** `update_lease_template` returns `(False, original)` when it cannot
  responsibly act. It never returns a partially-rewritten template, because a half-applied
  legal document is worse than an unchanged one.

`regime_consumer` is a sibling P-phase module that is not deployed yet. It is imported
defensively and a local equivalent is used until it lands, so P4 is testable and shippable on
its own rather than blocked behind another task.
"""
from __future__ import annotations

import copy
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONTRACTS = os.path.join(os.path.dirname(_HERE), "contracts")
if _CONTRACTS not in sys.path:
    # "2080" is not a valid Python identifier, so the package cannot be imported by dotted
    # path. Same approach the contracts smoke test uses.
    sys.path.insert(0, _CONTRACTS)

log = logging.getLogger(__name__)

try:  # pragma: no cover - exercised only once the sibling module lands
    from regime_consumer import safe_consume_regime_event as _sibling_consume
except Exception:  # ImportError today; any failure must degrade, not crash
    _sibling_consume = None


# A RegimeEvent may arrive as the contracts dataclass or as a plain dict, and the two spell
# jurisdiction differently ("jurisdiction" in contracts/autonomy.py, "regime" in the P4
# fixture). Accept both rather than making callers normalise.
_JURISDICTION_KEYS = ("jurisdiction", "regime", "state", "region")


def _as_dict(event: Any) -> Dict[str, Any]:
    """Coerce a RegimeEvent-like value to a plain dict. Never raises."""
    if event is None:
        return {}
    if isinstance(event, dict):
        return dict(event)
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(event):
            return asdict(event)
    except Exception:
        pass
    try:
        return dict(vars(event))
    except Exception:
        return {}


def _jurisdiction_of(event: Dict[str, Any]) -> str:
    for key in _JURISDICTION_KEYS:
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return ""


def safe_consume_regime_event(event: Any) -> Optional[Dict[str, Any]]:
    """The single door to the regime oracle. Returns a normalised event, or None.

    Delegates to the sibling `regime_consumer` when it is deployed. Returning None means "this
    event is not actionable" — callers must treat that as no-op, never as permission to guess.
    """
    try:
        if _sibling_consume is not None:
            consumed = _sibling_consume(event)
            if consumed is None:
                return None
            event = consumed
        normalised = _as_dict(event)
        if not normalised:
            return None
        jurisdiction = _jurisdiction_of(normalised)
        if not jurisdiction:
            # Without a jurisdiction there is no way to know which rules apply. Refusing here
            # is the whole point: applying a rule change to the wrong jurisdiction's lease is
            # a worse outcome than applying nothing.
            log.warning("regime event has no jurisdiction; ignoring: %r", normalised)
            return None
        normalised["jurisdiction"] = jurisdiction
        normalised.setdefault("effective_date", "")
        normalised.setdefault("rule_id", "")
        normalised.setdefault("description", "")
        return normalised
    except Exception as exc:  # fail-soft: an oracle problem is never fatal here
        log.warning("safe_consume_regime_event failed (%s); treating as no-op", exc)
        return None


DEFAULT_LEASE_TEMPLATE: Dict[str, Any] = {
    "jurisdiction": "",
    "clauses": [],
    "notice_period_days": 30,
    "revision": 0,
}


class DocumentUpdater:
    """Applies regime-aware updates to household legal documents and notifies the user.

    `notifier` is injectable so the notification path is observable in tests and can be swapped
    for a real queue later without touching this class.
    """

    def __init__(self, template: Optional[Any] = None,
                 notifier: Optional[Callable[[str, str], None]] = None) -> None:
        self.template = copy.deepcopy(template) if template is not None \
            else copy.deepcopy(DEFAULT_LEASE_TEMPLATE)
        self._notifier = notifier
        # Stands in for a real queue in this phase; also the audit trail tests assert on.
        self.notifications: List[Dict[str, str]] = []

    # -- P4 API ------------------------------------------------------------

    def update_lease_template(self, regime_event: Any) -> Tuple[bool, Any]:
        """Apply a regime change to the lease template.

        Returns `(success, template)`. On any failure the template returned is the ORIGINAL,
        unmodified — a partially-applied legal document is worse than an unchanged one.
        """
        original = copy.deepcopy(self.template)
        try:
            event = safe_consume_regime_event(regime_event)
            if not event:
                return False, original

            updated = copy.deepcopy(self.template)
            jurisdiction = event["jurisdiction"]

            if isinstance(updated, dict):
                updated["jurisdiction"] = jurisdiction
                updated["effective_date"] = event.get("effective_date", "")
                updated["revision"] = int(updated.get("revision") or 0) + 1
                clause = self._clause_for(event)
                clauses = list(updated.get("clauses") or [])
                # Idempotent: re-consuming the same event must not stack duplicate clauses.
                if clause not in clauses:
                    clauses.append(clause)
                updated["clauses"] = clauses
            else:
                # String templates: append the clause rather than attempting a rewrite we
                # cannot verify.
                updated = f"{updated}\n{self._clause_for(event)}".strip()

            self.template = updated
            return True, updated
        except Exception as exc:
            log.warning("update_lease_template failed (%s); template unchanged", exc)
            self.template = original
            return False, original

    def fire_notification(self, user_id: str, change_summary: str) -> None:
        """Queue a notification. Never raises — a failed notice must not undo a good update."""
        try:
            record = {"user_id": str(user_id or ""), "summary": str(change_summary or "")}
            self.notifications.append(record)
            if self._notifier is not None:
                self._notifier(record["user_id"], record["summary"])
            log.info("household_legal notification queued for %s: %s",
                     record["user_id"], record["summary"][:200])
        except Exception as exc:
            log.warning("fire_notification failed (%s); continuing", exc)

    def apply_and_notify(self, regime_event: Any, user_id: str) -> Tuple[bool, Any]:
        """Update, then notify only if something actually changed.

        Notifying on a no-op trains people to ignore the notifications.
        """
        ok, template = self.update_lease_template(regime_event)
        if ok:
            self.fire_notification(user_id, self.summarize(regime_event))
        return ok, template

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _clause_for(event: Dict[str, Any]) -> str:
        jurisdiction = event.get("jurisdiction", "")
        rule = event.get("rule_id") or event.get("description") or "regime update"
        effective = event.get("effective_date") or "unspecified date"
        return f"[{jurisdiction}] {rule} effective {effective}"

    @staticmethod
    def summarize(regime_event: Any) -> str:
        """Plain-language change summary. Always returns a string."""
        event = safe_consume_regime_event(regime_event) or {}
        if not event:
            return "No actionable regime change."
        return (f"Lease template updated for {event.get('jurisdiction', '')} "
                f"({event.get('rule_id') or event.get('description') or 'rule change'}), "
                f"effective {event.get('effective_date') or 'unspecified date'}.")
