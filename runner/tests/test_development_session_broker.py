"""Deterministic proofs for the development session broker (slice 1).

Uses a fake adapter so disconnect/resume, tool approval and pinning are all
exercised without a model provider, a network hop or a real worktree.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from development_session_broker import (  # noqa: E402
    Adapter,
    BrokerError,
    Capabilities,
    DevelopmentSessionBroker,
    Event,
    SessionState,
    in_vercel,
)

SHA = "a" * 40
REPO = "/repo"
WT = "/repo-wt/session-1"


class FakeAdapter(Adapter):
    """Scriptable adapter. `script` is the event stream start() emits."""

    def __init__(self, name="fake", script=None, **caps):
        defaults = dict(can_steer=True, can_resume=True, streams_events=True,
                        reports_cost=True)
        defaults.update(caps)   # caller overrides win, no duplicate-kwarg clash
        self._caps = Capabilities(name=name, **defaults)
        self.script = script if script is not None else [
            Event(0, "output", {"text": "hello"}),
        ]
        self.cancelled = False
        self.resumed_from = None

    def capabilities(self):
        return self._caps

    def start(self, session, prompt):
        return list(self.script)

    def steer(self, session, instruction):
        return [Event(session.last_seq + 1, "output", {"text": f"steered:{instruction}"})]

    def resume(self, session, after_seq):
        self.resumed_from = after_seq
        return [Event(after_seq + 1, "output", {"text": "resumed"})]

    def cancel(self, session):
        self.cancelled = True


def _broker(**kw):
    b = DevelopmentSessionBroker(env={}, **kw)
    return b


def _start(broker, adapter=None, permissions=(), **kw):
    adapter = adapter or FakeAdapter()
    broker.register(adapter)
    params = dict(adapter_name=adapter.capabilities().name, prompt="go",
                  repo_path=REPO, base_sha=SHA, worktree_path=WT,
                  permissions=permissions)
    params.update(kw)
    return broker.start(**params), adapter


# ------------------------------------------------------------------- discovery

def test_capability_discovery_lists_registered_adapters():
    b = _broker()
    b.register(FakeAdapter(name="cowork"))
    b.register(FakeAdapter(name="codex", can_resume=False))
    caps = b.discover()
    assert set(caps) == {"codex", "cowork"}
    assert caps["cowork"].can_resume is True
    assert caps["codex"].can_resume is False


def test_adapter_without_a_name_is_rejected():
    b = _broker()
    with pytest.raises(BrokerError):
        b.register(FakeAdapter(name=""))


def test_unsupported_operation_fails_before_running_anything():
    b = _broker()
    adapter = FakeAdapter(name="nosteer")
    adapter._caps = Capabilities(name="nosteer", can_steer=False, can_resume=False)
    session, _ = _start(b, adapter)
    with pytest.raises(BrokerError, match="does not support steer"):
        b.steer(session.session_id, "left")


# --------------------------------------------------------------------- pinning

def test_session_pins_an_exact_sha_and_isolated_worktree():
    b = _broker()
    session, _ = _start(b)
    assert session.base_sha == SHA
    assert session.worktree_path == WT
    assert session.worktree_path != session.repo_path


@pytest.mark.parametrize("bad", ["main", "HEAD", "abc123", "", None, "A" * 39])
def test_branch_names_and_short_shas_are_refused(bad):
    """A base that can move makes the session unreproducible."""
    b = _broker()
    with pytest.raises(BrokerError, match="40-char commit sha"):
        _start(b, base_sha=bad)


def test_uppercase_sha_is_normalised():
    b = _broker()
    session, _ = _start(b, base_sha="A" * 40)
    assert session.base_sha == "a" * 40


def test_worktree_must_differ_from_the_main_checkout():
    b = _broker()
    with pytest.raises(BrokerError, match="isolated worktree"):
        _start(b, worktree_path=REPO)


def test_missing_worktree_is_refused():
    b = _broker()
    with pytest.raises(BrokerError, match="isolated worktree"):
        _start(b, worktree_path="")


# ---------------------------------------------------------------------- vercel

@pytest.mark.parametrize("marker", ["VERCEL", "VERCEL_ENV", "VERCEL_URL", "NOW_BUILDER"])
def test_repository_tools_never_run_inside_vercel(marker):
    b = DevelopmentSessionBroker(env={marker: "1"})
    adapter = FakeAdapter()
    b.register(adapter)
    with pytest.raises(BrokerError, match="Vercel"):
        b.start(adapter_name="fake", prompt="go", repo_path=REPO,
                base_sha=SHA, worktree_path=WT)


def test_in_vercel_is_false_for_a_clean_environment():
    assert in_vercel({}) is False
    assert in_vercel({"CI": "1"}) is False


# ----------------------------------------------------------- event capture

def test_streamed_events_are_captured_in_order():
    b = _broker()
    script = [Event(i, "output", {"text": str(i)}) for i in range(4)]
    session, _ = _start(b, FakeAdapter(script=script))
    assert [e.seq for e in session.events] == [0, 1, 2, 3]


def test_cost_events_accumulate():
    b = _broker()
    script = [
        Event(0, "cost", {"usd": 0.5, "tokens": 100}),
        Event(1, "cost", {"usd": 0.25, "tokens": 50}),
    ]
    session, _ = _start(b, FakeAdapter(script=script))
    assert session.cost == {"usd": 0.75, "tokens": 150}


def test_non_numeric_cost_fields_are_ignored():
    b = _broker()
    session, _ = _start(b, FakeAdapter(script=[
        Event(0, "cost", {"usd": 1.0, "model": "claude-sonnet-5"}),
    ]))
    assert session.cost == {"usd": 1.0}


def test_artifacts_are_receipted():
    b = _broker()
    session, _ = _start(b, FakeAdapter(script=[
        Event(0, "artifact", {"path": "out.diff", "sha": "deadbeef"}),
    ]))
    assert session.artifacts == [{"path": "out.diff", "sha": "deadbeef"}]


def test_status_event_drives_terminal_state():
    b = _broker()
    session, _ = _start(b, FakeAdapter(script=[
        Event(0, "status", {"state": SessionState.COMPLETED}),
    ]))
    assert session.state == SessionState.COMPLETED


# ------------------------------------------------------------- tool approval

def test_tool_calls_are_denied_by_default():
    """Deny-by-default: a tool absent from permissions never runs."""
    b = _broker()
    session, _ = _start(b, FakeAdapter(script=[
        Event(0, "tool_call", {"tool": "bash"}),
    ]))
    assert session.denied_tools == ["bash"]
    assert all(e.kind != "tool_call" for e in session.events)


def test_denial_is_recorded_rather_than_silently_dropped():
    b = _broker()
    session, _ = _start(b, FakeAdapter(script=[Event(0, "tool_call", {"tool": "bash"})]))
    status = [e for e in session.events if e.kind == "status"]
    assert status and status[0].payload["denied_tool"] == "bash"


def test_allowlisted_tool_is_permitted():
    b = _broker()
    session, _ = _start(b, FakeAdapter(script=[
        Event(0, "tool_call", {"tool": "read_file"}),
    ]), permissions={"read_file"})
    assert session.denied_tools == []
    assert any(e.kind == "tool_call" for e in session.events)


def test_approval_hook_can_veto_an_allowlisted_tool():
    calls = []

    def approve(session, tool, payload):
        calls.append(tool)
        return False

    b = DevelopmentSessionBroker(env={}, approve_tool=approve)
    session, _ = _start(b, FakeAdapter(script=[
        Event(0, "tool_call", {"tool": "read_file"}),
    ]), permissions={"read_file"})
    assert calls == ["read_file"]
    assert session.denied_tools == ["read_file"]


def test_approval_hook_is_not_consulted_for_unpermitted_tools():
    """The allowlist is checked first, so the hook cannot widen permissions."""
    calls = []
    b = DevelopmentSessionBroker(
        env={}, approve_tool=lambda s, t, p: calls.append(t) or True
    )
    session, _ = _start(b, FakeAdapter(script=[Event(0, "tool_call", {"tool": "bash"})]))
    assert calls == []
    assert session.denied_tools == ["bash"]


# -------------------------------------------------- disconnect / resume / cancel

def test_resume_continues_after_the_last_captured_event():
    b = _broker()
    script = [Event(i, "output", {"text": str(i)}) for i in range(3)]
    session, adapter = _start(b, FakeAdapter(script=script))
    b.resume(session.session_id)
    assert adapter.resumed_from == 2
    assert [e.seq for e in session.events] == [0, 1, 2, 3]


def test_resume_from_an_explicit_cursor_is_honoured():
    b = _broker()
    session, adapter = _start(b, FakeAdapter(
        script=[Event(i, "output", {}) for i in range(3)]))
    b.resume(session.session_id, after_seq=0)
    assert adapter.resumed_from == 0


def test_resume_after_disconnect_loses_nothing_and_repeats_nothing():
    """The disconnect case: capture stops mid-stream, resume picks up exactly there."""
    b = _broker()
    session, adapter = _start(b, FakeAdapter(
        script=[Event(0, "output", {"text": "a"}), Event(1, "output", {"text": "b"})]))
    seqs_before = [e.seq for e in session.events]
    b.resume(session.session_id)
    seqs_after = [e.seq for e in session.events]
    assert seqs_after[: len(seqs_before)] == seqs_before   # nothing replayed
    assert seqs_after[-1] == seqs_before[-1] + 1           # nothing skipped


def test_cancel_marks_terminal_and_notifies_the_adapter():
    b = _broker()
    session, adapter = _start(b)
    b.cancel(session.session_id)
    assert session.state == SessionState.CANCELLED
    assert adapter.cancelled is True


def test_cancel_is_idempotent():
    b = _broker()
    session, adapter = _start(b)
    b.cancel(session.session_id)
    adapter.cancelled = False
    b.cancel(session.session_id)
    assert adapter.cancelled is False   # adapter not called a second time


def test_steer_after_cancel_is_refused():
    b = _broker()
    session, _ = _start(b)
    b.cancel(session.session_id)
    with pytest.raises(BrokerError, match="terminal state"):
        b.steer(session.session_id, "left")


def test_resume_after_completion_is_refused():
    b = _broker()
    session, _ = _start(b, FakeAdapter(script=[
        Event(0, "status", {"state": SessionState.COMPLETED}),
    ]))
    with pytest.raises(BrokerError, match="terminal state"):
        b.resume(session.session_id)


def test_unknown_session_is_an_error():
    b = _broker()
    with pytest.raises(BrokerError, match="unknown session"):
        b.get("nope")


def test_unregistered_adapter_is_an_error():
    b = _broker()
    with pytest.raises(BrokerError, match="no adapter registered"):
        b.start(adapter_name="ghost", prompt="go", repo_path=REPO,
                base_sha=SHA, worktree_path=WT)


def test_sessions_are_independent():
    b = _broker()
    adapter = FakeAdapter()
    b.register(adapter)
    common = dict(adapter_name="fake", prompt="go", repo_path=REPO,
                  base_sha=SHA)
    one = b.start(worktree_path="/repo-wt/one", **common)
    two = b.start(worktree_path="/repo-wt/two", **common)
    assert one.session_id != two.session_id
    b.cancel(one.session_id)
    assert two.state == SessionState.RUNNING
