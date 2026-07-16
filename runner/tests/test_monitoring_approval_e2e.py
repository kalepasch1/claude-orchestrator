"""End-to-end integration tests for monitoring + approval pipeline.

Tests the full change_approval_pipeline flow: enqueue -> monitor -> approve.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from approval_queue import ApprovalQueue
from queue_status_monitor import QueueStatusMonitor


class ChangeApprovalPipeline:
    """Integrates queue monitoring with approval workflow."""

    def __init__(self):
        self.monitor = QueueStatusMonitor()
        self.approval = ApprovalQueue()
        self._auto_decisions: dict = {}

    def submit_change(self, change_id: str, change_type: str,
                      summary: str, approvers=None):
        req = self.approval.enqueue_for_approval(
            change_id, change_type, summary, approvers
        )
        self.monitor.update_snapshot({"pending": self.approval.pending_count})
        return req

    def approve_change(self, change_id: str, approver: str, reason: str = ""):
        result = self.approval.approve(change_id, approver, reason)
        self.monitor.update_snapshot({"pending": self.approval.pending_count})
        return result

    def reject_change(self, change_id: str, approver: str, reason: str = ""):
        result = self.approval.reject(change_id, approver, reason)
        self.monitor.update_snapshot({"pending": self.approval.pending_count})
        return result

    def auto_decide(self, change_id: str, decision: str, reason: str = ""):
        """Auto-approve/reject based on policy."""
        if decision == "approve":
            return self.approve_change(change_id, "auto_policy", reason)
        elif decision == "reject":
            return self.reject_change(change_id, "auto_policy", reason)
        return False

    def get_final_status(self, change_id: str):
        req = self.approval._find(change_id)
        return req.status if req else None


# --- E2E tests ---

def test_e2e_submit_and_approve():
    p = ChangeApprovalPipeline()
    p.submit_change("c1", "deploy", "deploy v2", ["admin"])
    assert p.approval.pending_count == 1
    p.approve_change("c1", "admin", "lgtm")
    assert p.approval.pending_count == 0
    assert p.get_final_status("c1") == "approved"


def test_e2e_submit_and_reject():
    p = ChangeApprovalPipeline()
    p.submit_change("c1", "deploy", "risky deploy")
    p.reject_change("c1", "admin", "too risky")
    assert p.get_final_status("c1") == "rejected"


def test_e2e_multiple_changes():
    p = ChangeApprovalPipeline()
    p.submit_change("c1", "config", "update config")
    p.submit_change("c2", "deploy", "deploy v3")
    p.submit_change("c3", "schema", "add column")

    assert p.approval.pending_count == 3

    p.approve_change("c1", "admin")
    p.reject_change("c3", "dba", "needs review")

    assert p.approval.pending_count == 1
    assert p.get_final_status("c1") == "approved"
    assert p.get_final_status("c2") == "pending"
    assert p.get_final_status("c3") == "rejected"


def test_e2e_monitoring_tracks_changes():
    p = ChangeApprovalPipeline()
    p.submit_change("c1", "deploy", "v1")
    p.submit_change("c2", "deploy", "v2")
    p.approve_change("c1", "admin")

    history = p.monitor.get_status_history()
    assert len(history) >= 1


def test_e2e_auto_decision():
    p = ChangeApprovalPipeline()
    p.submit_change("c1", "config", "safe change")
    assert p.auto_decide("c1", "approve", "low risk") is True
    assert p.get_final_status("c1") == "approved"


def test_e2e_auto_reject():
    p = ChangeApprovalPipeline()
    p.submit_change("c1", "schema", "risky")
    assert p.auto_decide("c1", "reject", "high risk") is True
    assert p.get_final_status("c1") == "rejected"


def test_e2e_concurrent_changes():
    p = ChangeApprovalPipeline()
    for i in range(10):
        p.submit_change(f"c{i}", "deploy", f"change {i}")
    assert p.approval.pending_count == 10

    for i in range(0, 10, 2):
        p.approve_change(f"c{i}", "admin")
    assert p.approval.pending_count == 5


def test_e2e_attempt_double_approve():
    p = ChangeApprovalPipeline()
    p.submit_change("c1", "deploy", "x")
    assert p.approve_change("c1", "admin") is True
    assert p.approve_change("c1", "admin") is False


def test_e2e_nonexistent_change():
    p = ChangeApprovalPipeline()
    assert p.approve_change("nope", "admin") is False
    assert p.get_final_status("nope") is None


def test_e2e_full_pipeline_with_monitor():
    """Full accuracy test: submit, monitor, approve, verify history."""
    p = ChangeApprovalPipeline()

    # Submit
    p.submit_change("deploy-1", "deploy", "production deploy")
    p.submit_change("config-1", "config", "update env vars")

    # Verify monitoring state
    current = p.monitor.get_current()
    assert current is not None

    # Approve one, reject other
    p.approve_change("deploy-1", "lead", "tested in staging")
    p.reject_change("config-1", "ops", "wrong env")

    # Verify final states
    assert p.get_final_status("deploy-1") == "approved"
    assert p.get_final_status("config-1") == "rejected"
    assert p.approval.pending_count == 0

    # Verify decisions logged
    decisions = p.approval.get_decisions()
    assert len(decisions) == 2


def test_e2e_approver_assessment():
    """Verify approver info is correctly recorded."""
    p = ChangeApprovalPipeline()
    p.submit_change("c1", "deploy", "x", approvers=["alice", "bob"])
    p.approve_change("c1", "alice", "reviewed")

    decisions = p.approval.get_decisions()
    assert decisions[0]["decided_by"] == "alice"
    assert decisions[0]["reason"] == "reviewed"
