"""A task below the EV floor is refused BEFORE the queue, so the PID never sees it.

The controller's integral accumulates from queue DEPTH. A low-value task that is admitted
and then removed has already pushed the integral up, and the I-action then shelves other
people's work to pay it back — windup caused by work that was never going to run. Refusing
admission costs the integral nothing, which is why the check belongs pre-queue.

The fail-soft direction is the load-bearing one: anything unreadable is ADMITTED. Wrongly
refusing real work is far worse than one extra low-value task, and an EV that could not be
parsed is not evidence of low value.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_velocity as qv  # noqa: E402


class TestTaskEv:
    @pytest.mark.parametrize("key", ["ev", "expected_value", "confidence"])
    def test_it_reads_the_recorded_value(self, key):
        assert qv.task_ev({key: 0.7}) == pytest.approx(0.7)

    def test_a_string_number_is_coerced(self):
        assert qv.task_ev({"ev": "0.5"}) == pytest.approx(0.5)

    def test_an_unscored_task_reports_none_not_zero(self):
        """None is not zero: unscored is not the same as judged worthless."""
        assert qv.task_ev({"slug": "x"}) is None

    @pytest.mark.parametrize("task", [None, "text", 7, [], {"ev": "many"}])
    def test_it_never_raises(self, task):
        qv.task_ev(task)


class TestAdmission:
    def test_a_task_below_the_floor_is_refused(self):
        admit, reason = qv.should_enqueue({"slug": "x", "ev": -1}, threshold=0.0)
        assert admit is False
        assert "not enqueued" in reason

    def test_the_floor_itself_is_refused(self):
        assert qv.should_enqueue({"ev": 0.0}, threshold=0.0)[0] is False

    def test_a_task_above_the_floor_is_admitted(self):
        assert qv.should_enqueue({"ev": 0.01}, threshold=0.0)[0] is True

    def test_the_threshold_is_configurable(self):
        assert qv.should_enqueue({"ev": 0.4}, threshold=0.5)[0] is False
        assert qv.should_enqueue({"ev": 0.6}, threshold=0.5)[0] is True

    def test_the_default_threshold_is_env_tunable(self):
        """ORCH_-prefixed per CLAUDE.md so fleet_control.py can push it."""
        assert isinstance(qv.LOW_EV_THRESHOLD, float)
        assert "ORCH_QV_LOW_EV_THRESHOLD" in open(qv.__file__, encoding="utf-8").read()

    def test_an_unscored_task_is_admitted(self):
        """Going live must not silently drop every task that was never scored."""
        admit, reason = qv.should_enqueue({"slug": "never-scored"})
        assert admit is True
        assert "not judged low-value" in reason

    def test_a_pinned_task_is_always_admitted(self):
        """Pinning is an operator instruction; the PID does not override it."""
        admit, reason = qv.should_enqueue({"ev": -99, "pinned": True}, threshold=0.0)
        assert admit is True
        assert "express lane" in reason

    @pytest.mark.parametrize("task", [None, "text", 7, []])
    def test_unreadable_input_is_admitted_not_refused(self, task):
        assert qv.should_enqueue(task)[0] is True

    def test_an_unparseable_ev_is_admitted(self):
        assert qv.should_enqueue({"ev": "very high"}, threshold=0.0)[0] is True


class TestAdmitLogs:
    def test_a_skip_is_logged_with_its_reason(self, capsys):
        assert qv.admit({"slug": "cheap", "ev": -1}, threshold=0.0) is False
        out = capsys.readouterr().out
        assert "pre-queue skip" in out
        assert "cheap" in out

    def test_an_admitted_task_logs_nothing(self, capsys):
        assert qv.admit({"slug": "good", "ev": 1.0}, threshold=0.0) is True
        assert capsys.readouterr().out == ""


class TestThePidNeverSeesASkip:
    def test_the_check_does_not_touch_the_controller_state(self, monkeypatch):
        """The whole point: a pre-queue skip must not move the integral."""
        touched = []
        monkeypatch.setattr(qv, "_save_state", lambda s: touched.append(s))
        monkeypatch.setattr(qv, "_load_state", lambda: {"integral": 41, "history": []})
        for _ in range(50):
            qv.should_enqueue({"slug": "cheap", "ev": -1}, threshold=0.0)
        assert touched == [], "admission must not write controller state"

    def test_the_integral_only_accumulates_from_depth(self):
        """Documents the invariant the skip relies on: never queued, never counted."""
        import ast
        src = open(qv.__file__, encoding="utf-8").read()
        fn = next(n for n in ast.parse(src).body
                  if isinstance(n, ast.FunctionDef) and n.name == "should_enqueue")
        # Look at NAMES the function actually references, not at text. The reason string
        # legitimately says "excluded from the PID integral" — that is the explanation
        # handed to an operator, and a substring check cannot tell it from a call.
        referenced = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        referenced |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        for forbidden in ("integral", "_save_state", "_load_state", "history", "db"):
            assert forbidden not in referenced, f"should_enqueue must not touch {forbidden}"

    def test_admission_is_pure_enough_to_call_anywhere(self, monkeypatch):
        def _boom(*_a, **_k):
            raise AssertionError("admission must not hit the database")

        monkeypatch.setattr(qv.db, "count", _boom, raising=False)
        monkeypatch.setattr(qv.db, "select", _boom, raising=False)
        assert qv.should_enqueue({"ev": 1.0})[0] is True
        assert qv.should_enqueue({"ev": -1.0})[0] is False
