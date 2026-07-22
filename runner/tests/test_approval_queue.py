"""Tests for approval_queue."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from approval_queue import ApprovalQueue, ApprovalRequest

def test_enqueue():
    q = ApprovalQueue()
    req = q.enqueue_for_approval("c1", "deploy", "deploy v2")
    assert req.status == "pending"
    assert q.pending_count == 1

def test_approve():
    q = ApprovalQueue()
    q.enqueue_for_approval("c1", "deploy", "deploy v2")
    assert q.approve("c1", "admin", "looks good") is True
    assert q.pending_count == 0

def test_reject():
    q = ApprovalQueue()
    q.enqueue_for_approval("c1", "deploy", "risky")
    assert q.reject("c1", "admin", "too risky") is True
    assert q.pending_count == 0

def test_approve_nonexistent():
    q = ApprovalQueue()
    assert q.approve("nope", "admin") is False

def test_double_approve():
    q = ApprovalQueue()
    q.enqueue_for_approval("c1", "deploy", "x")
    q.approve("c1", "admin")
    assert q.approve("c1", "admin") is False  # Already decided

def test_get_pending():
    q = ApprovalQueue()
    q.enqueue_for_approval("c1", "a", "x")
    q.enqueue_for_approval("c2", "b", "y")
    q.approve("c1", "admin")
    pending = q.get_pending_approvals()
    assert len(pending) == 1
    assert pending[0].change_id == "c2"

def test_get_decisions():
    q = ApprovalQueue()
    q.enqueue_for_approval("c1", "a", "x")
    q.approve("c1", "admin", "ok")
    decisions = q.get_decisions()
    assert len(decisions) == 1
    assert decisions[0]["status"] == "approved"

def test_notification_called():
    notifications = []
    class Handler:
        def notify(self, req): notifications.append(req.change_id)
    q = ApprovalQueue(notification_handler=Handler())
    q.enqueue_for_approval("c1", "a", "x")
    assert notifications == ["c1"]

def test_notification_error_handled():
    class BadHandler:
        def notify(self, req): raise RuntimeError("fail")
    q = ApprovalQueue(notification_handler=BadHandler())
    q.enqueue_for_approval("c1", "a", "x")  # Should not crash
    assert q.pending_count == 1

def test_approval_request_fields():
    r = ApprovalRequest("c1", "deploy", "summary", ["admin"])
    assert r.change_id == "c1"
    assert r.approvers == ["admin"]
    assert r.decided_at is None

def test_decided_at_set():
    q = ApprovalQueue()
    q.enqueue_for_approval("c1", "a", "x")
    q.approve("c1", "admin")
    req = q._find("c1")
    assert req.decided_at is not None
