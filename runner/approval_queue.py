"""Manual approval queue and notification system.

Manages changes requiring human approval with an audit trail.
"""

import time
import logging
from typing import Dict, List, Any, Optional

log = logging.getLogger(__name__)


class ApprovalRequest:
    def __init__(self, change_id: str, change_type: str, summary: str,
                 approvers: Optional[List[str]] = None):
        self.change_id = change_id
        self.change_type = change_type
        self.summary = summary
        self.approvers = approvers or []
        self.status = "pending"
        self.decision_reason = ""
        self.decided_by = ""
        self.created_at = time.time()
        self.decided_at: Optional[float] = None


class ApprovalQueue:
    def __init__(self, notification_handler: Optional[Any] = None):
        self._queue: List[ApprovalRequest] = []
        self._notification_handler = notification_handler

    def enqueue_for_approval(self, change_id: str, change_type: str,
                             summary: str, approvers: Optional[List[str]] = None
                             ) -> ApprovalRequest:
        req = ApprovalRequest(change_id, change_type, summary, approvers)
        self._queue.append(req)
        if self._notification_handler:
            try:
                self._notification_handler.notify(req)
            except Exception as e:
                log.warning("Notification failed: %s", e)
        return req

    def approve(self, change_id: str, approver: str,
                reason: str = "") -> bool:
        req = self._find(change_id)
        if not req or req.status != "pending":
            return False
        req.status = "approved"
        req.decided_by = approver
        req.decision_reason = reason
        req.decided_at = time.time()
        return True

    def reject(self, change_id: str, approver: str,
               reason: str = "") -> bool:
        req = self._find(change_id)
        if not req or req.status != "pending":
            return False
        req.status = "rejected"
        req.decided_by = approver
        req.decision_reason = reason
        req.decided_at = time.time()
        return True

    def get_pending_approvals(self) -> List[ApprovalRequest]:
        return [r for r in self._queue if r.status == "pending"]

    def get_decisions(self, limit: int = 50) -> List[Dict[str, Any]]:
        decided = [r for r in self._queue if r.status != "pending"]
        return [{
            "change_id": r.change_id,
            "status": r.status,
            "decided_by": r.decided_by,
            "reason": r.decision_reason,
        } for r in decided[-limit:]]

    def _find(self, change_id: str) -> Optional[ApprovalRequest]:
        for r in self._queue:
            if r.change_id == change_id:
                return r
        return None

    @property
    def pending_count(self) -> int:
        return len(self.get_pending_approvals())
