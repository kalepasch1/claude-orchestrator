"""A task must not reach DONE with no evidence that anything happened."""
import sys
import types

import pytest


@pytest.fixture
def gate(monkeypatch):
    """done_evidence_gate wired to an in-memory fake of the tasks database."""
    fake = types.ModuleType("db")
    fake.tasks = {}
    fake.artifacts = []       # rows in task_artifacts (keyed by slug)
    fake.outcomes = []        # rows in outcomes (keyed by task_id)
    fake.alarms = []          # rows in orch_gate_alarms
    fake.raise_on_select = False

    def select(table, params=None):
        params = params or {}
        if fake.raise_on_select:
            raise RuntimeError("supabase unreachable")
        if table == "tasks":
            tid = (params.get("id") or "").replace("eq.", "")
            row = fake.tasks.get(tid)
            return [dict(row)] if row else []
        if table == "task_artifacts":
            slug = (params.get("slug") or "").replace("eq.", "")
            return [r for r in fake.artifacts if r.get("slug") == slug]
        if table == "outcomes":
            tid = (params.get("task_id") or "").replace("eq.", "")
            return [r for r in fake.outcomes if str(r.get("task_id")) == tid]
        if table == "orch_gate_alarms":
            tid = (params.get("verdict") or "").replace("eq.", "")
            return [r for r in fake.alarms
                    if str(r.get("verdict")) == tid and not r.get("resolved_at")]
        return []

    def insert(table, row, upsert=False):
        if table == "orch_gate_alarms":
            fake.alarms.append(dict(row))
        return [dict(row)]

    def update(table, match, patch):
        if table == "tasks":
            tid = match.get("id")
            fake.tasks.setdefault(tid, {}).update(patch)
        return []

    fake.select, fake.insert, fake.update = select, insert, update
    monkeypatch.setitem(sys.modules, "db", fake)
    sys.modules.pop("done_evidence_gate", None)
    import done_evidence_gate
    monkeypatch.setattr(done_evidence_gate, "db", fake, raising=False)
    monkeypatch.setattr(done_evidence_gate, "ENABLED", True, raising=False)
    done_evidence_gate._fake = fake
    yield done_evidence_gate
    sys.modules.pop("done_evidence_gate", None)


def _task(gate, task_id="t-1", **fields):
    row = {"id": task_id, "slug": f"slug-{task_id}", "kind": "bugfix",
           "state": "RUNNING", "note": "", "log_tail": "",
           "artifact_commit": "", "artifact_ref": ""}
    row.update(fields)
    gate._fake.tasks[task_id] = row
    return row


def test_done_with_task_artifacts_row_succeeds(gate):
    _task(gate, "t-artifact")
    gate._fake.artifacts.append({"slug": "slug-t-artifact", "commit_sha": "abc1234"})

    result = gate.guard("t-artifact", {"state": "DONE", "note": "implemented"})

    assert result["state"] == "DONE"
    assert result["note"] == "implemented"
    assert gate._fake.alarms == []


def test_done_with_non_empty_log_tail_succeeds(gate):
    _task(gate, "t-log", log_tail="pytest: 12 passed in 3.4s")

    result = gate.guard("t-log", {"state": "DONE", "note": "report written"})

    assert result["state"] == "DONE"
    assert gate._fake.alarms == []


def test_done_with_no_evidence_lands_in_phantom_unverified(gate):
    _task(gate, "t-empty", kind="toolchain-repair")

    result = gate.guard("t-empty", {"state": "DONE", "note": "looks done"})

    assert result["state"] == gate.FALLBACK_STATE == "PHANTOM_UNVERIFIED"
    assert "done_evidence_gate" in result["note"]
    # The note must name what was missing, not just say "no evidence".
    for expected in ("log_tail", "artifact_commit", "task_artifacts", "outcomes"):
        assert expected in result["note"]
    # The operator's original note is preserved alongside the refusal reason.
    assert "looks done" in result["note"]


def test_alarm_raised_once_and_not_duplicated_on_retry(gate):
    _task(gate, "t-alarm")

    gate.guard("t-alarm", {"state": "DONE", "note": "first"})
    assert len(gate._fake.alarms) == 1
    assert gate._fake.alarms[0]["kind"] == "evidence_missing"
    assert gate._fake.alarms[0]["gate"] == "done_evidence"
    assert gate._fake.alarms[0]["verdict"] == "t-alarm"

    gate.guard("t-alarm", {"state": "DONE", "note": "second"})
    assert len(gate._fake.alarms) == 1, "retry must not duplicate the open alarm"


def test_exception_inside_evidence_check_lets_transition_through(gate):
    _task(gate, "t-boom")
    gate._fake.raise_on_select = True

    result = gate.guard("t-boom", {"state": "DONE", "note": "fail-soft"})

    assert result["state"] == "DONE", "an over-eager guard must never block real work"
    assert result["note"] == "fail-soft"


def test_report_task_output_is_persisted_into_log_tail(gate):
    _task(gate, "t-report", kind="toolchain-repair")

    findings = "launchd PATH lacks /opt/homebrew/bin; node resolves only under a login shell."
    result = gate.guard("t-report", {"state": "DONE", "note": "diagnosed",
                                     "log_tail": findings})

    assert result["state"] == "DONE"
    assert gate._fake.tasks["t-report"]["log_tail"] == findings


def test_capture_report_log_truncates_and_never_overwrites(gate):
    _task(gate, "t-trunc", kind="recovery")

    gate.capture_report_log("t-trunc", "x" * 50, limit=10)
    assert gate._fake.tasks["t-trunc"]["log_tail"] == "x" * 10

    gate.capture_report_log("t-trunc", "a real later log", limit=100)
    assert gate._fake.tasks["t-trunc"]["log_tail"] == "x" * 10


def test_non_guarded_states_pass_through_untouched(gate):
    _task(gate, "t-blocked")

    for state in ("BLOCKED", "QUEUED", "MERGED", "QUARANTINED"):
        result = gate.guard("t-blocked", {"state": state, "note": "n"})
        assert result["state"] == state
    assert gate._fake.alarms == []
