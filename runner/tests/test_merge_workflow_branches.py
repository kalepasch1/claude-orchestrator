"""Tests for merge_workflow_branches: end-to-end merge workflow integration."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from merge_workflow_branches import MergeWorkflowBranchManager, BranchCreationTask


class FakeResult:
    def __init__(self, success=True, reason="ok"):
        self.success = success
        self.reason = reason


def ok_creator(project_id, branch, base):
    return FakeResult(True, "created")


def fail_creator(project_id, branch, base):
    return FakeResult(False, "permission denied")


def detect_all_missing(project_id, branches):
    return branches  # all missing


def detect_none_missing(project_id, branches):
    return []


# --- Basic workflow ---

def test_approve_mr_queues_branches():
    mgr = MergeWorkflowBranchManager(detect_missing_fn=detect_all_missing)
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging", "prod"]}
    tasks = mgr.on_mr_approved(mr)
    assert len(tasks) == 2
    assert mgr.pending_count == 2

def test_approve_mr_no_missing():
    mgr = MergeWorkflowBranchManager(detect_missing_fn=detect_none_missing)
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    tasks = mgr.on_mr_approved(mr)
    assert len(tasks) == 0

def test_execute_creates_branches():
    mgr = MergeWorkflowBranchManager(
        detect_missing_fn=detect_all_missing,
        create_branch_fn=ok_creator,
    )
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    mgr.on_mr_approved(mr)
    executed = mgr.execute_pending()
    assert len(executed) == 1
    assert executed[0].status == "completed"
    assert "staging" in mgr.created_branches


# --- Deduplication ---

def test_no_duplicate_branches():
    """Two MRs needing same branch -> only created once."""
    mgr = MergeWorkflowBranchManager(
        detect_missing_fn=detect_all_missing,
        create_branch_fn=ok_creator,
    )
    mr1 = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    mr2 = {"project_id": "p1", "mr_id": "mr2", "target_branches": ["staging"]}

    tasks1 = mgr.on_mr_approved(mr1)
    assert len(tasks1) == 1

    # Before executing, second MR approved -> should dedup
    tasks2 = mgr.on_mr_approved(mr2)
    assert len(tasks2) == 0  # Already queued

def test_no_duplicate_after_creation():
    """After branch created, second MR skips it."""
    mgr = MergeWorkflowBranchManager(
        detect_missing_fn=detect_all_missing,
        create_branch_fn=ok_creator,
    )
    mr1 = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    mgr.on_mr_approved(mr1)
    mgr.execute_pending()

    mr2 = {"project_id": "p1", "mr_id": "mr2", "target_branches": ["staging"]}
    tasks2 = mgr.on_mr_approved(mr2)
    assert len(tasks2) == 0  # Already created


# --- End-to-end scenario ---

def test_e2e_two_mrs_one_branch():
    """Submit 2 MRs both needing staging; approve first, verify created;
    approve second, verify no error."""
    mgr = MergeWorkflowBranchManager(
        detect_missing_fn=detect_all_missing,
        create_branch_fn=ok_creator,
    )

    # First MR
    mr1 = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"],
            "base_branch": "main"}
    tasks1 = mgr.on_mr_approved(mr1)
    assert len(tasks1) == 1
    executed1 = mgr.execute_pending()
    assert executed1[0].status == "completed"
    assert "staging" in mgr.created_branches

    # Second MR
    mr2 = {"project_id": "p1", "mr_id": "mr2", "target_branches": ["staging"],
            "base_branch": "main"}
    tasks2 = mgr.on_mr_approved(mr2)
    assert len(tasks2) == 0  # Deduped
    assert mgr.pending_count == 0


# --- Error handling ---

def test_creation_failure():
    mgr = MergeWorkflowBranchManager(
        detect_missing_fn=detect_all_missing,
        create_branch_fn=fail_creator,
    )
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    mgr.on_mr_approved(mr)
    executed = mgr.execute_pending()
    assert executed[0].status == "failed"
    assert "staging" not in mgr.created_branches

def test_detection_error():
    def bad_detect(pid, branches):
        raise RuntimeError("detect error")
    mgr = MergeWorkflowBranchManager(detect_missing_fn=bad_detect)
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    tasks = mgr.on_mr_approved(mr)
    assert len(tasks) == 0

def test_no_create_fn():
    mgr = MergeWorkflowBranchManager(detect_missing_fn=detect_all_missing)
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    mgr.on_mr_approved(mr)
    executed = mgr.execute_pending()
    assert executed[0].status == "failed"

def test_creation_exception():
    def exploding_creator(pid, branch, base):
        raise RuntimeError("boom")
    mgr = MergeWorkflowBranchManager(
        detect_missing_fn=detect_all_missing,
        create_branch_fn=exploding_creator,
    )
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    mgr.on_mr_approved(mr)
    executed = mgr.execute_pending()
    assert executed[0].status == "failed"


# --- Queue state ---

def test_queue_state():
    mgr = MergeWorkflowBranchManager(
        detect_missing_fn=detect_all_missing,
        create_branch_fn=ok_creator,
    )
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["a", "b"]}
    mgr.on_mr_approved(mr)
    mgr.execute_pending()
    state = mgr.get_queue_state()
    assert state["total"] == 2
    assert state["by_status"]["completed"] == 2

def test_task_fields():
    t = BranchCreationTask("p1", "staging", "main", "mr1")
    assert t.project_id == "p1"
    assert t.branch_name == "staging"
    assert t.status == "pending"

def test_bool_creator():
    mgr = MergeWorkflowBranchManager(
        detect_missing_fn=detect_all_missing,
        create_branch_fn=lambda pid, b, base: True,
    )
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["staging"]}
    mgr.on_mr_approved(mr)
    executed = mgr.execute_pending()
    assert executed[0].status == "completed"

def test_without_detect_fn():
    """Without detect fn, all target branches are treated as missing."""
    mgr = MergeWorkflowBranchManager(create_branch_fn=ok_creator)
    mr = {"project_id": "p1", "mr_id": "mr1", "target_branches": ["a", "b"]}
    tasks = mgr.on_mr_approved(mr)
    assert len(tasks) == 2
