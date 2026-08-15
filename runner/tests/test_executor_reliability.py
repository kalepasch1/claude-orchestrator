"""Executor reliability measurement -- shadow only, no control over any claim."""
import sys
import types

import pytest


@pytest.fixture
def rel(monkeypatch):
    fake = types.ModuleType("db")
    fake.tables = {"tasks": [], "agent_outcomes": [], "agent_reputation": [],
                   "routing_decisions": [], "projects": []}
    fake.updates = []
    fake.raise_on = set()

    def select(table, params=None):
        if table in fake.raise_on:
            raise RuntimeError("supabase unreachable")
        return [dict(r) for r in fake.tables.get(table, [])]

    def insert(table, row, upsert=False):
        if table in fake.raise_on:
            raise RuntimeError("supabase unreachable")
        fake.tables.setdefault(table, []).append(dict(row))
        return [dict(row)]

    def update(table, match, patch):
        fake.updates.append((table, dict(match), dict(patch)))
        return []

    fake.select, fake.insert, fake.update = select, insert, update
    monkeypatch.setitem(sys.modules, "db", fake)
    sys.modules.pop("executor_reliability", None)
    import executor_reliability
    monkeypatch.setattr(executor_reliability, "db", fake, raising=False)
    executor_reliability._fake = fake
    yield executor_reliability
    sys.modules.pop("executor_reliability", None)


def _outcome(rel, cls, kind, accepted, n=1, latency=1000):
    for i in range(n):
        rel._fake.tables["agent_outcomes"].append({
            "app": "beethoven", "task_slug": f"{cls}-{kind}-{accepted}-{i}",
            "role": kind, "provider": cls, "model": f"{cls}-{i}",
            "settlement": "DONE" if accepted else "BLOCKED",
            "accepted": accepted, "latency_ms": latency,
            "metadata": {"attempts": 1}})


# --------------------------------------------------------------- classing ---

@pytest.mark.parametrize("account,expected", [
    ("cowork-executor-v6-1786033329", "cowork-executor"),
    ("cowork-executor-12", "cowork-executor"),
    ("Mac.lan-57190", "Mac.lan"),
    ("Mandys-MacBook-Pro-441", "Mandys-MacBook-Pro"),
    ("agentic:claude-9912", "agentic:claude"),
    ("", "unassigned"),
    (None, "unassigned"),
    ("something-else", "other"),
])
def test_ephemeral_accounts_collapse_to_a_stable_class(rel, account, expected):
    assert rel.executor_class(account) == expected


# ------------------------------------------------------------ sample floor ---

def test_reputation_below_sample_floor_is_labelled_not_trusted(rel):
    _outcome(rel, "Mac.lan", "bugfix", True, n=2)

    table = rel.rollup_reputation(persist=False)
    stats = table[("Mac.lan", "bugfix")]

    assert stats["samples"] == 2
    assert stats["usable"] is False
    assert stats["evidence"] == "insufficient_evidence"


def test_best_executor_refuses_to_pick_on_thin_evidence(rel):
    _outcome(rel, "cowork-executor", "bugfix", True, n=3)

    table = rel.rollup_reputation(persist=False)
    pick, reason = rel.best_executor("bugfix", table)

    assert pick is None
    assert reason == "insufficient_evidence"


def test_best_executor_picks_the_more_reliable_class_above_the_floor(rel):
    _outcome(rel, "cowork-executor", "bugfix", True, n=21)
    _outcome(rel, "Mac.lan", "bugfix", False, n=25)

    table = rel.rollup_reputation(persist=False)
    pick, reason = rel.best_executor("bugfix", table)

    assert pick == "cowork-executor"
    assert reason == "per_kind"
    assert table[("cowork-executor", "bugfix")]["success_rate"] == 1.0
    assert table[("Mac.lan", "bugfix")]["success_rate"] == 0.0


def test_unseen_kind_falls_back_to_the_pooled_aggregate(rel):
    _outcome(rel, "cowork-executor", "build", True, n=25)

    table = rel.rollup_reputation(persist=False)
    pick, reason = rel.best_executor("a-kind-never-seen", table)

    assert pick == "cowork-executor"
    assert reason == "pooled_across_kinds"


# ------------------------------------------------------------- shadow only ---

def test_shadow_decision_never_writes_tasks_or_reorders_the_queue(rel):
    _outcome(rel, "cowork-executor", "bugfix", True, n=25)
    table = rel.rollup_reputation(persist=False)

    result = rel.record_shadow_decision(
        {"id": "t-1", "kind": "bugfix"}, table=table, actual_account="Mac.lan-99")

    assert result == {"actual": "Mac.lan", "shadow": "cowork-executor", "basis": "per_kind"}
    decisions = rel._fake.tables["routing_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["metadata"]["agreed"] is False
    assert decisions[0]["metadata"]["shadow_only"] is True
    # The hard requirement: no write to tasks at all.
    assert rel._fake.tables["tasks"] == []
    assert not any(table_name == "tasks" for table_name, _m, _p in rel._fake.updates)


def test_shadow_path_exception_never_affects_the_real_claim(rel):
    rel._fake.raise_on.add("routing_decisions")

    result = rel.record_shadow_decision({"id": "t-boom", "kind": "bugfix"}, table={})

    assert result is None, "a shadow failure must be swallowed, not raised"


def test_backfill_is_idempotent_and_skips_already_recorded_slugs(rel):
    rel._fake.tables["projects"] = [{"id": "p1", "name": "beethoven"}]
    rel._fake.tables["tasks"] = [{
        "id": "t-9", "slug": "already-done", "kind": "bugfix", "state": "DONE",
        "account": "cowork-executor-v6-1", "project_id": "p1", "attempt": 0,
        "created_at": "2026-08-06T10:00:00+00:00",
        "updated_at": "2026-08-06T10:00:05+00:00"}]

    assert rel.backfill_agent_outcomes() == 1
    row = rel._fake.tables["agent_outcomes"][0]
    assert row["provider"] == "cowork-executor"
    assert row["accepted"] is True
    assert row["latency_ms"] == 5000
    assert row["app"] == "beethoven"

    assert rel.backfill_agent_outcomes() == 0, "re-running must not duplicate rows"
    assert len(rel._fake.tables["agent_outcomes"]) == 1


# ----------------------------------------------------------------- report ---

def test_report_refuses_to_conclude_below_the_decision_threshold(rel):
    rel._fake.tables["routing_decisions"] = [
        {"task_id": "t", "reason": rel.SHADOW_REASON, "success": True,
         "metadata": {"shadow_executor_class": "cowork-executor", "agreed": True}}]

    report = rel.shadow_report(threshold=200)

    assert "1/200" in report
    assert "No routing change is justified" in report


def test_report_compares_agreement_and_flags_the_confound(rel):
    rel._fake.tables["routing_decisions"] = [
        {"task_id": f"t{i}", "reason": rel.SHADOW_REASON, "success": i % 2 == 0,
         "metadata": {"shadow_executor_class": "cowork-executor",
                      "agreed": i % 3 == 0}}
        for i in range(10)]

    report = rel.shadow_report(threshold=5)

    assert "decisions recorded        10" in report
    assert "agreed with reality" in report
    assert "counterfactual ceiling" in report
    assert "less loaded" in report, "the report must state what it cannot distinguish"
