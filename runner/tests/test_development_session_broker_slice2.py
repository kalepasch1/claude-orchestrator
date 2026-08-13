#!/usr/bin/env python3
"""Development session broker, slice 2: duplicates, approval hold, artifact recovery.

Slice 1 built the lifecycle (pinning, permissions, streaming, disconnect/resume,
cancellation). This file covers the four remaining behaviours the spec names, each with
a deterministic fake adapter and no network, no git and no model:

  * DUPLICATED EVENTS   — a replayed seq must not be captured twice. Double-counted cost
                          and duplicated artifacts are worse than dropped ones, because
                          the totals still look plausible.
  * APPROVAL HOLD       — a tool call parked for an out-of-band decision pauses the
                          session and the stream BEHIND it, then release() drains it.
  * ARTIFACT RECOVERY   — a disconnect between the work landing and the artifact event
                          arriving must be recoverable from the adapter, idempotently.
  * COST/MODEL TELEMETRY— per-model spend is attributed, not just a cost total.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from development_session_broker import (  # noqa: E402
    HOLD, Adapter, BrokerError, Capabilities, DevelopmentSessionBroker, Event,
    SessionState,
)

SHA = "a" * 40
REPO = "/tmp/repo"
WT = "/tmp/repo-wt/session"


class ScriptedAdapter(Adapter):
    """Replays a fixed script. Optionally re-emits it to simulate a transport retry."""

    def __init__(self, name="scripted", script=None, resume_script=None,
                 artifacts=(), can_recover=False):
        self._name = name
        self._script = list(script or [])
        self._resume = list(resume_script or [])
        self._artifacts = list(artifacts)
        self._can_recover = can_recover
        self.cancelled = False
        self.recover_calls = 0

    def capabilities(self):
        return Capabilities(
            name=self._name, can_steer=True, can_resume=True, can_cancel=True,
            streams_events=True, reports_cost=True,
            can_recover_artifacts=self._can_recover,
            tools=frozenset({"write_file", "run_tests", "push"}),
        )

    def start(self, session, prompt):
        return list(self._script)

    def steer(self, session, instruction):
        return list(self._script)

    def resume(self, session, after_seq):
        return list(self._resume)

    def cancel(self, session):
        self.cancelled = True

    def recover_artifacts(self, session):
        self.recover_calls += 1
        return list(self._artifacts)


def _start(broker, adapter, permissions=("write_file",)):
    broker.register(adapter)
    return broker.start(adapter.capabilities().name, "do the thing", REPO, SHA, WT,
                        permissions=permissions)


class TestDuplicatedEvents:
    def test_a_replayed_event_is_captured_once(self):
        script = [Event(0, "output", {"text": "hello"}),
                  Event(1, "output", {"text": "world"})]
        adapter = ScriptedAdapter(script=script, resume_script=script)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        broker.resume(session.session_id)          # adapter replays the same seqs
        assert [e.seq for e in session.events] == [0, 1]

    def test_a_replayed_cost_event_is_not_double_counted(self):
        script = [Event(0, "cost", {"usd": 1.25, "tokens": 100})]
        adapter = ScriptedAdapter(script=script, resume_script=script)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        broker.resume(session.session_id)
        assert session.cost["usd"] == pytest.approx(1.25)
        assert session.cost["tokens"] == 100

    def test_a_replayed_artifact_is_receipted_once(self):
        script = [Event(0, "artifact", {"path": "runner/x.py", "sha": "deadbeef"})]
        adapter = ScriptedAdapter(script=script, resume_script=script)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        broker.resume(session.session_id)
        assert len(session.artifacts) == 1

    def test_new_events_after_a_replay_are_still_captured(self):
        adapter = ScriptedAdapter(
            script=[Event(0, "output", {"text": "a"})],
            resume_script=[Event(0, "output", {"text": "a"}),
                           Event(1, "output", {"text": "b"})])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        broker.resume(session.session_id)
        assert [e.seq for e in session.events] == [0, 1]

    def test_a_duplicate_within_a_single_stream_is_suppressed(self):
        adapter = ScriptedAdapter(script=[Event(0, "cost", {"usd": 1.0}),
                                          Event(0, "cost", {"usd": 1.0})])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert session.cost["usd"] == pytest.approx(1.0)

    def test_last_seq_is_the_high_water_mark_not_the_last_append(self):
        adapter = ScriptedAdapter(script=[Event(5, "output", {}), Event(2, "output", {})])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert session.last_seq == 5


class TestApprovalHold:
    def _held(self, decisions=None):
        script = [Event(0, "output", {"text": "before"}),
                  Event(1, "tool_call", {"tool": "write_file", "path": "x.py"}),
                  Event(2, "output", {"text": "after"}),
                  Event(3, "status", {"state": SessionState.COMPLETED})]
        adapter = ScriptedAdapter(script=script)
        broker = DevelopmentSessionBroker(approve_tool=lambda s, t, p: HOLD, env={})
        return broker, adapter, _start(broker, adapter)

    def test_a_held_tool_pauses_the_session(self):
        broker, adapter, session = self._held()
        assert session.state == SessionState.PAUSED
        assert session.held_tool["tool"] == "write_file"

    def test_the_stream_behind_the_hold_is_not_consumed(self):
        """Otherwise the work the tool gates runs anyway and the hold is decorative."""
        broker, adapter, session = self._held()
        assert [e.seq for e in session.events] == [0, 1]
        assert session.state != SessionState.COMPLETED

    def test_the_hold_is_visible_in_the_transcript(self):
        broker, adapter, session = self._held()
        assert session.events[-1].payload["held_tool"] == "write_file"

    def test_releasing_approved_runs_the_call_and_drains_the_tail(self):
        broker, adapter, session = self._held()
        broker.release(session.session_id, approved=True)
        kinds = [(e.seq, e.kind) for e in session.events]
        assert (1, "tool_call") in kinds
        assert session.state == SessionState.COMPLETED
        assert session.denied_tools == []

    def test_releasing_refused_skips_the_call_but_still_drains_the_tail(self):
        broker, adapter, session = self._held()
        broker.release(session.session_id, approved=False)
        assert "write_file" in session.denied_tools
        assert not [e for e in session.events if e.kind == "tool_call"]
        assert session.state == SessionState.COMPLETED

    def test_releasing_with_nothing_held_is_an_error(self):
        adapter = ScriptedAdapter(script=[Event(0, "output", {})])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        with pytest.raises(BrokerError):
            broker.release(session.session_id, approved=True)

    def test_a_hold_cannot_widen_the_permission_set(self):
        """An ungranted tool is denied outright; the hook is never asked about it."""
        asked = []
        adapter = ScriptedAdapter(
            script=[Event(0, "tool_call", {"tool": "push"})])
        broker = DevelopmentSessionBroker(
            approve_tool=lambda s, t, p: asked.append(t) or HOLD, env={})
        session = _start(broker, adapter, permissions=("write_file",))
        assert asked == []
        assert session.denied_tools == ["push"]
        assert session.held_tool is None

    def test_cancelling_a_held_session_drops_the_parked_work(self):
        broker, adapter, session = self._held()
        broker.cancel(session.session_id)
        assert session.state == SessionState.CANCELLED
        assert session.held_tool is None
        assert session.pending_events == []
        with pytest.raises(BrokerError):
            broker.release(session.session_id, approved=True)


class TestArtifactRecovery:
    def test_artifacts_lost_to_a_disconnect_are_recovered(self):
        adapter = ScriptedAdapter(
            script=[Event(0, "output", {"text": "worked"})],   # artifact event never arrived
            artifacts=[{"path": "runner/new.py", "sha": "abc"}],
            can_recover=True)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert session.artifacts == []
        recovered = broker.recover_artifacts(session.session_id)
        assert [a["path"] for a in recovered] == ["runner/new.py"]
        assert len(session.artifacts) == 1

    def test_recovery_is_idempotent(self):
        adapter = ScriptedAdapter(
            script=[Event(0, "artifact", {"path": "runner/new.py", "sha": "abc"})],
            artifacts=[{"path": "runner/new.py", "sha": "abc"}],
            can_recover=True)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert broker.recover_artifacts(session.session_id) == []
        assert broker.recover_artifacts(session.session_id) == []
        assert len(session.artifacts) == 1

    def test_only_the_newly_receipted_artifacts_are_returned(self):
        adapter = ScriptedAdapter(
            script=[Event(0, "artifact", {"path": "a.py"})],
            artifacts=[{"path": "a.py"}, {"path": "b.py"}],
            can_recover=True)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert [a["path"] for a in broker.recover_artifacts(session.session_id)] == ["b.py"]
        assert len(session.artifacts) == 2

    def test_an_adapter_without_the_capability_refuses_rather_than_pretending(self):
        adapter = ScriptedAdapter(script=[], can_recover=False)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        with pytest.raises(BrokerError):
            broker.recover_artifacts(session.session_id)

    def test_recovery_works_after_cancellation(self):
        """Artifacts a cancelled session already produced are still evidence."""
        adapter = ScriptedAdapter(script=[], artifacts=[{"path": "a.py"}], can_recover=True)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        broker.cancel(session.session_id)
        assert len(broker.recover_artifacts(session.session_id)) == 1

    def test_non_dict_artifacts_are_skipped_not_crashed_on(self):
        adapter = ScriptedAdapter(script=[], artifacts=["nope", None, {"path": "a.py"}],
                                  can_recover=True)
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert len(broker.recover_artifacts(session.session_id)) == 1


class TestCostAndModelTelemetry:
    def test_spend_is_attributed_per_model(self):
        adapter = ScriptedAdapter(script=[
            Event(0, "cost", {"model": "claude-haiku-4-5", "usd": 0.10}),
            Event(1, "cost", {"model": "claude-opus-5", "usd": 1.00}),
            Event(2, "cost", {"model": "claude-haiku-4-5", "usd": 0.05}),
        ])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert session.models["claude-haiku-4-5"] == pytest.approx(0.15)
        assert session.models["claude-opus-5"] == pytest.approx(1.00)
        assert session.cost["usd"] == pytest.approx(1.15)

    def test_the_model_name_is_not_summed_as_a_cost_field(self):
        adapter = ScriptedAdapter(script=[Event(0, "cost", {"model": "m", "usd": 1.0})])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert "model" not in session.cost

    def test_cost_without_a_model_still_totals(self):
        adapter = ScriptedAdapter(script=[Event(0, "cost", {"usd": 2.0})])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert session.cost["usd"] == pytest.approx(2.0)
        assert session.models == {}

    def test_booleans_are_not_treated_as_numbers(self):
        adapter = ScriptedAdapter(script=[Event(0, "cost", {"cached": True, "usd": 1.0})])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        assert "cached" not in session.cost

    def test_telemetry_reports_the_pinned_session_and_its_usage(self):
        adapter = ScriptedAdapter(script=[
            Event(0, "cost", {"model": "m", "usd": 0.5}),
            Event(1, "artifact", {"path": "a.py"}),
        ])
        broker = DevelopmentSessionBroker(env={})
        session = _start(broker, adapter)
        t = broker.telemetry(session.session_id)
        assert t["base_sha"] == SHA
        assert t["worktree_path"] == WT
        assert t["adapter"] == "scripted"
        assert t["models"] == {"m": pytest.approx(0.5)}
        assert t["artifacts"] == 1
        assert t["held_tool"] is None

    def test_telemetry_surfaces_a_held_tool(self):
        adapter = ScriptedAdapter(script=[Event(0, "tool_call", {"tool": "write_file"})])
        broker = DevelopmentSessionBroker(approve_tool=lambda s, t, p: HOLD, env={})
        session = _start(broker, adapter)
        assert broker.telemetry(session.session_id)["held_tool"] == "write_file"


class TestVercelRemainsIntakeOnly:
    def test_no_session_starts_in_a_vercel_context(self):
        adapter = ScriptedAdapter(script=[])
        broker = DevelopmentSessionBroker(env={"VERCEL_ENV": "production"})
        broker.register(adapter)
        with pytest.raises(BrokerError, match="Vercel"):
            broker.start("scripted", "p", REPO, SHA, WT)
