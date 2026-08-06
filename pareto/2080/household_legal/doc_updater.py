"""Apply regime-aware updates to household legal templates, and notify.

A jurisdiction changes a rule; the lease template a household relies on is now
out of date and nobody knows. This closes that loop: consume the event, patch
the template, tell the user what changed.

Fail-soft, but never silently: a failed update returns (False, original) and the
ORIGINAL template is handed back untouched. Returning a partially-rewritten
template on error would be worse than doing nothing at all — a user would sign
it believing it was updated.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import os
import sys

# '2080' is not a valid Python identifier, so this package cannot be imported by
# dotted path. The repo convention (see pareto/2080/contracts/test_contracts_smoke.py)
# is to put the directory on sys.path and import the module by bare name.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from regime_consumer import (  # noqa: E402
    consume_oracle_events,
    normalize_regime_event,
)

log = logging.getLogger(__name__)

Template = Union[str, Dict[str, Any]]

# Regime-specific clauses. Deliberately data, not branching logic, so adding a
# jurisdiction is a change to one table rather than to the update routine.
REGIME_CLAUSES: Dict[str, Dict[str, str]] = {
    "CA": {
        "notice_period": "California: 60 days written notice required for termination.",
        "deposit_cap": "California: security deposit capped at two months' rent.",
    },
    "NY": {
        "notice_period": "New York: 30 days written notice required for termination.",
        "deposit_cap": "New York: security deposit capped at one month's rent.",
    },
    "TX": {
        "notice_period": "Texas: 30 days written notice required for termination.",
    },
}


class DocumentUpdater:
    """Regime-aware updater for household legal templates."""

    def __init__(self, oracle: Any = None, notification_queue: Optional[List] = None):
        self.oracle = oracle
        # A caller-supplied queue lets a test observe notifications without
        # patching anything. Defaults to an in-process list for this phase.
        self.notification_queue: List[Dict[str, Any]] = (
            notification_queue if notification_queue is not None else []
        )

    # ── updates ──────────────────────────────────────────────────────────────

    def update_lease_template(
        self,
        regime_event: Any,
        template: Optional[Template] = None,
    ) -> Tuple[bool, Template]:
        """Apply `regime_event` to a lease template.

        Returns (success, updated_template). On ANY failure returns
        (False, the template exactly as supplied) — never a partial rewrite.
        """
        original: Template = template if template is not None else _default_template()
        try:
            event = normalize_regime_event(regime_event)
            if event is None:
                log.warning("doc_updater: unusable regime event; template unchanged")
                return False, original

            regime = event["jurisdiction"].upper()
            clauses = REGIME_CLAUSES.get(regime)
            if not clauses:
                # An unknown jurisdiction is NOT an error, but it is also not an
                # update. Saying so honestly beats returning success having
                # changed nothing.
                log.info("doc_updater: no clauses known for regime %s", regime)
                return False, original

            updated = self._apply_clauses(original, regime, clauses,
                                          event.get("effective_date", ""))
            return True, updated
        except Exception as exc:                               # fail-soft
            log.warning("doc_updater: update failed, template unchanged: %s", exc)
            return False, original

    def _apply_clauses(self, template: Template, regime: str,
                       clauses: Dict[str, str], effective_date: str) -> Template:
        if isinstance(template, dict):
            updated = dict(template)
            updated["regime"] = regime
            if effective_date:
                updated["effective_date"] = effective_date
            updated.setdefault("clauses", {})
            updated["clauses"] = {**dict(updated.get("clauses") or {}), **clauses}
            return updated

        lines = [f"{template}".rstrip(), "", f"--- {regime} REGIME CLAUSES ---"]
        if effective_date:
            lines.append(f"Effective: {effective_date}")
        for key in sorted(clauses):
            lines.append(f"[{key}] {clauses[key]}")
        return "\n".join(lines)

    # ── notification ─────────────────────────────────────────────────────────

    def fire_notification(self, user_id: str, change_summary: str) -> None:
        """Queue a notification for `user_id`. Never raises.

        A notification failure must not roll back or mask a successful document
        update — the document IS updated either way, and the right degradation
        is a logged warning, not a lost update.
        """
        try:
            entry = {
                "user_id": f"{user_id or ''}",
                "change_summary": f"{change_summary or ''}",
            }
            self.notification_queue.append(entry)
            log.info("doc_updater: queued notification for %s", entry["user_id"])
        except Exception as exc:                               # fail-soft
            log.warning("doc_updater: notification failed for %s: %s", user_id, exc)

    # ── end-to-end ───────────────────────────────────────────────────────────

    def process_jurisdiction(
        self,
        jurisdiction: str,
        user_id: str,
        template: Optional[Template] = None,
    ) -> Tuple[bool, Template]:
        """Pull events via the oracle, apply the first usable one, notify.

        Every oracle call goes through consume_oracle_events, so an oracle
        outage yields (False, original) rather than an exception.
        """
        events = consume_oracle_events(self.oracle, jurisdiction)
        if not events:
            return False, (template if template is not None else _default_template())

        ok, updated = self.update_lease_template(events[0], template)
        if ok:
            self.fire_notification(
                user_id,
                f"Lease template updated for {events[0]['jurisdiction']}"
                + (f" effective {events[0]['effective_date']}"
                   if events[0].get("effective_date") else ""),
            )
        return ok, updated


def _default_template() -> str:
    return "STANDARD RESIDENTIAL LEASE\nParties: {{landlord}} and {{tenant}}."
