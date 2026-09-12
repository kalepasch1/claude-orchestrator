"""A red suite from a saturated box does not earn an agent — but it still counts.

Measured from the merge train's own log, 2026-09-03: 168 gate results, EVERY ONE a
TESTFAIL, 144 of them (85%) taken over the 1.5 load/core threshold, median 2.13,
max 10.96. Three tasks failed at load/core 8–11 inside one forty-minute window and
each dispatched an agent to rewrite code because of a suite the train itself had
labelled "may be about the machine, not the code". Those agents add load. The next
suite fails the same way. That loop is why the fleet merged nothing for ninety
minutes.

Operator decision (Molly, 2026-09-03): "Strike, but skip the repair dispatch."

So the strike stands — remediation_count still increments, the card was already
retired, quarantine still counts it — and what is skipped is the AGENT. The task is
requeued plainly so the train re-gates it when the box is calm, rather than left in
TESTFAIL where nothing would ever retry it.
"""
import auto_remediate as ar
import merge_train as mt


def _task(**kw):
    base = {"id": "t1", "slug": "card-a", "state": "TESTFAIL", "note": "",
            "remediation_count": 0}
    base.update(kw)
    return base


# ── the decision ──────────────────────────────────────────────────────────────

def test_a_load_suspect_testfail_gets_no_agent(monkeypatch):
    monkeypatch.setattr(ar, "LOAD_SUSPECT_SKIP", True)
    monkeypatch.setattr(mt, "last_gate_was_load_suspect", lambda slug: True)
    assert ar._load_suspect_testfail(_task()) is True


def test_a_calm_box_testfail_still_gets_its_agent(monkeypatch):
    monkeypatch.setattr(ar, "LOAD_SUSPECT_SKIP", True)
    monkeypatch.setattr(mt, "last_gate_was_load_suspect", lambda slug: False)
    assert ar._load_suspect_testfail(_task()) is False


def test_only_testfail_is_affected(monkeypatch):
    """A BLOCKED or CONFLICT task never failed a suite, so load says nothing about it."""
    monkeypatch.setattr(ar, "LOAD_SUSPECT_SKIP", True)
    monkeypatch.setattr(mt, "last_gate_was_load_suspect", lambda slug: True)
    for state in ("BLOCKED", "CONFLICT", "QUEUED", ""):
        assert ar._load_suspect_testfail(_task(state=state)) is False, state


def test_it_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(ar, "LOAD_SUSPECT_SKIP", False)
    monkeypatch.setattr(mt, "last_gate_was_load_suspect", lambda slug: True)
    assert ar._load_suspect_testfail(_task()) is False


def test_an_unreadable_ledger_dispatches_as_before(monkeypatch):
    """When we cannot tell, behave exactly as before. The safe direction is the agent."""
    def boom(slug):
        raise RuntimeError("ledger unreadable")

    monkeypatch.setattr(ar, "LOAD_SUSPECT_SKIP", True)
    monkeypatch.setattr(mt, "last_gate_was_load_suspect", boom)
    assert ar._load_suspect_testfail(_task()) is False


def test_a_task_with_no_slug_is_not_matched(monkeypatch):
    monkeypatch.setattr(ar, "LOAD_SUSPECT_SKIP", True)
    assert mt.last_gate_was_load_suspect(None) is False
    assert mt.last_gate_was_load_suspect("") is False


# ── the strike still counts ───────────────────────────────────────────────────

def test_the_strike_is_not_suppressed():
    """The half of the decision that was NOT taken. remediation_count still rises,
    so quarantine still fires — only the agent is skipped."""
    import inspect
    source = inspect.getsource(ar.run) if hasattr(ar, "run") else inspect.getsource(ar)
    marker = source.index("_load_suspect_testfail(t)")
    window = source[max(0, marker - 1200):marker]
    assert '"remediation_count": rc + 1' in window, \
        "the strike must be applied before the agent is skipped"
    after = source[marker:marker + 700]
    assert "requeued += 1" in after, "the task must be requeued, not stranded in TESTFAIL"
    assert "repair_patch" not in after.split("continue")[0], \
        "no agentic repair may be dispatched on this path"


def test_the_requeue_says_why():
    """An operator reading the note must see this was a machine call, not a code call."""
    import inspect
    source = inspect.getsource(ar)
    assert "requeued without a repair agent" in source
    assert "saturated box" in source


# ── the ledger lookup itself ──────────────────────────────────────────────────

def test_the_most_recent_verdict_wins(monkeypatch, tmp_path):
    """A card that failed hot and was later re-gated calm must not stay suspect."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(mt, "GATE_LOAD_SUSPECT", 1.5)
    mt.record_gate_load("card-x", "p", "TESTFAIL", per_core=9.0)
    assert mt.last_gate_was_load_suspect("card-x") is True
    mt.record_gate_load("card-x", "p", "TESTFAIL", per_core=0.4)
    assert mt.last_gate_was_load_suspect("card-x") is False


def test_an_unknown_card_is_not_suspect(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    assert mt.last_gate_was_load_suspect("never-seen") is False
