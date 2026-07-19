"""Tests for rootcause_cluster.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from rootcause_cluster import (
    extract_signature, cluster_failures, get_recurring_patterns,
    generate_guard_rule, FailureRecord, FailureCluster,
)


def test_extract_capacity_signature():
    note = "capacity circuit: call cap: 510/500 per hour"
    assert extract_signature(note) == "capacity-exhaustion"


def test_extract_auth_signature():
    note = "Not logged in · Please run /login"
    assert extract_signature(note) == "auth-not-logged-in"


def test_extract_conflict_signature():
    note = "runner exception: HTTP Error 409: Conflict"
    assert extract_signature(note) == "git-conflict-409"


def test_extract_missing_spec():
    note = "Prompt contains only error messages with no real specification"
    assert extract_signature(note) == "missing-spec"


def test_extract_unknown_falls_back():
    sig = extract_signature("some totally novel error xyz")
    assert sig.startswith("unknown-")


def test_cluster_groups_by_signature():
    records = [
        FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap: 510/500"),
        FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap: 600/500"),
        FailureRecord(task_id="3", slug="c", state="BLOCKED", note="Not logged in · Please run /login"),
    ]
    clusters = cluster_failures(records)
    assert len(clusters) == 2
    cap_cluster = next(c for c in clusters if c.pattern_name == "capacity-exhaustion")
    assert cap_cluster.count == 2
    assert cap_cluster.is_recurring


def test_recurring_patterns_filters():
    records = [
        FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap"),
        FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap"),
        FailureRecord(task_id="3", slug="c", state="BLOCKED", note="Not logged in · Please run /login"),
    ]
    clusters = cluster_failures(records)
    recurring = get_recurring_patterns(clusters)
    assert len(recurring) == 1
    assert recurring[0].pattern_name == "capacity-exhaustion"


def test_guard_rule_generation():
    rule = generate_guard_rule("git-index-lock")
    assert "rm -f .git/index.lock" in rule

    rule = generate_guard_rule("unknown-pattern")
    assert "manual_review" in rule


def test_failure_record_auto_signature():
    rec = FailureRecord(task_id="1", slug="x", state="BLOCKED",
                        note="shelved after 6 remediations without merge")
    assert rec.error_signature == "remediation-cap"


def test_extract_remote_publish_auth():
    note = "remote-publish-failed: push to origin returned non-zero"
    assert extract_signature(note) == "remote-publish-auth"
