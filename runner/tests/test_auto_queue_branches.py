"""Tests for auto_queue_branches."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from auto_queue_branches import (
    normalize_slug, is_duplicate, _token_similarity,
    discover_missing_branches, auto_queue_missing_branches, AutoQueueResult,
)

def test_normalize_slug_basic():
    assert normalize_slug("My-Task_Name") == "my-task-name"

def test_normalize_slug_strips_special():
    assert normalize_slug("---hello---world---") == "hello-world"

def test_normalize_slug_empty():
    assert normalize_slug("") == ""

def test_token_similarity_identical():
    assert _token_similarity("foo-bar-baz", "foo-bar-baz") == 1.0

def test_token_similarity_partial():
    assert 0.3 < _token_similarity("foo-bar-baz", "foo-bar-qux") < 0.8

def test_token_similarity_disjoint():
    assert _token_similarity("aaa-bbb", "ccc-ddd") == 0.0

def test_token_similarity_empty():
    assert _token_similarity("", "foo") == 0.0

def test_is_duplicate_exact():
    assert is_duplicate("my-task", {"my-task", "other-task"}) is True

def test_is_duplicate_normalized():
    assert is_duplicate("My_Task", {"my-task", "other"}) is True

def test_is_not_duplicate():
    assert is_duplicate("new-task", {"old-task", "other-thing"}) is False

def test_is_duplicate_near_match():
    assert is_duplicate("improve-branch-management-dedup", {"improve-branch-management-dedup-v2"}) is True

def test_discover_missing_basic():
    missing = discover_missing_branches(["agent/task-a", "agent/task-b", "agent/task-c"], {"task-a", "task-c"})
    assert missing == ["task-b"]

def test_discover_missing_no_prefix():
    assert discover_missing_branches(["feature/task-a", "main"], set()) == []

def test_discover_missing_all_queued():
    assert discover_missing_branches(["agent/x", "agent/y"], {"x", "y"}) == []

def test_discover_missing_empty():
    assert discover_missing_branches([], set()) == []

def test_auto_queue_success():
    enqueued = []
    result = auto_queue_missing_branches(
        {"proj1": {"name": "p1", "prefix": "agent/"}},
        get_branches_fn=lambda pid: ["agent/new-task"],
        get_queued_slugs_fn=lambda pid: set(),
        enqueue_fn=lambda pid, slug: (enqueued.append(slug), True)[1],
    )
    assert result.queued == ["new-task"]

def test_auto_queue_dedup_prevents():
    result = auto_queue_missing_branches(
        {"proj1": {"name": "p1", "prefix": "agent/"}},
        get_branches_fn=lambda pid: ["agent/existing-task"],
        get_queued_slugs_fn=lambda pid: {"existing-task"},
        enqueue_fn=lambda pid, slug: True,
    )
    assert len(result.queued) == 0

def test_auto_queue_mixed():
    result = auto_queue_missing_branches(
        {"proj1": {"name": "p1", "prefix": "agent/"}},
        get_branches_fn=lambda pid: ["agent/new-one", "agent/old-one"],
        get_queued_slugs_fn=lambda pid: {"old-one"},
        enqueue_fn=lambda pid, slug: True,
    )
    assert result.queued == ["new-one"]

def test_auto_queue_branch_error():
    result = auto_queue_missing_branches(
        {"proj1": {"name": "p1"}},
        get_branches_fn=lambda pid: (_ for _ in ()).throw(RuntimeError("git error")),
        get_queued_slugs_fn=lambda pid: set(),
        enqueue_fn=lambda pid, slug: True,
    )
    assert len(result.skipped_error) == 1

def test_auto_queue_enqueue_failure():
    result = auto_queue_missing_branches(
        {"proj1": {"name": "p1", "prefix": "agent/"}},
        get_branches_fn=lambda pid: ["agent/task-x"],
        get_queued_slugs_fn=lambda pid: set(),
        enqueue_fn=lambda pid, slug: False,
    )
    assert len(result.skipped_error) == 1

def test_auto_queue_self_dedup():
    result = auto_queue_missing_branches(
        {"proj1": {"name": "p1", "prefix": "agent/"}},
        get_branches_fn=lambda pid: ["agent/task-a", "agent/task-a"],
        get_queued_slugs_fn=lambda pid: set(),
        enqueue_fn=lambda pid, slug: True,
    )
    assert len(result.queued) == 1

def test_auto_queue_result_total():
    r = AutoQueueResult()
    r.queued = ["a", "b"]
    r.skipped_duplicate = ["c"]
    r.skipped_error = [{"error": "x"}]
    assert r.total_processed == 4
