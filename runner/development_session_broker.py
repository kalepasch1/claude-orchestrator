#!/usr/bin/env python3
"""development_session_broker.py — the single execution broker for dev sessions.

Slice 1 of the runner-backed development session broker: the adapter contract, the
session lifecycle, and the pinning rules. Real adapters (Cowork, Codex CLI /
app-server, the agentic coder, the model gateway) land in later slices; this slice
defines the shape they must satisfy and proves the lifecycle against a fake.

WHY A BROKER AT ALL: execution currently starts from several places with different
assumptions about where code runs and what it may touch. One broker means one place
that decides — and one place to audit.

TWO RULES THIS SLICE ENFORCES, because they are the ones that are expensive to
retrofit:

  1. EVERY session pins an exact repo + base SHA + isolated worktree. A session
     whose base is a branch NAME is unreproducible the moment that branch moves,
     and "it worked when the agent ran it" stops being checkable. Pinning is
     therefore a construction-time requirement, not a later validation.

  2. Repository tools NEVER run inside Vercel. Vercel builds are for building. A
     broker that would happily shell out to git from a serverless build is one
     misconfiguration away from mutating a repo from inside a deploy, so the
     environment check refuses at start() rather than trusting configuration.

Permissions are bounded by an explicit allowlist and tool calls are approved
through a caller-supplied hook — deny-by-default, so a new adapter cannot silently
widen what agents may do.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Env vars set by Vercel's build/runtime images. Presence of any means "we are
# inside a Vercel execution context" and repository tooling is refused.
_VERCEL_MARKERS = ("VERCEL", "VERCEL_ENV", "VERCEL_URL", "NOW_BUILDER")


class BrokerError(RuntimeError):
    """Raised when a session cannot be started or driven safely."""


class _Hold:
    """Sentinel an approval hook returns to PARK a tool call instead of deciding it.

    A distinct object rather than a string or None so it can never be confused with a
    truthy/falsy verdict: `bool(HOLD)` is never consulted, identity is.
    """

    def __repr__(self):  # pragma: no cover - debugging aid
        return "HOLD"


HOLD = _Hold()


class SessionState:
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"

    TERMINAL = frozenset({CANCELLED, COMPLETED, FAILED})


@dataclass(frozen=True)
class Capabilities:
    """What an adapter can actually do. Absent capability == not offered."""
    name: str
    can_steer: bool = False
    can_resume: bool = False
    can_cancel: bool = True
    streams_events: bool = False
    reports_cost: bool = False
    # An adapter that can be re-asked for the artifacts a session produced. Without it a
    # disconnect after the work landed but before the artifact event arrived loses the
    # receipt permanently, and the branch looks empty to the merge train.
    can_recover_artifacts: bool = False
    tools: frozenset = frozenset()

    def supports(self, capability: str) -> bool:
        return bool(getattr(self, capability, False))


@dataclass
class Event:
    """One streamed event from an adapter."""
    seq: int
    kind: str            # "output" | "tool_call" | "cost" | "artifact" | "status"
    payload: dict = field(default_factory=dict)


@dataclass
class Session:
    session_id: str
    adapter: str
    repo_path: str
    base_sha: str
    worktree_path: str
    permissions: frozenset
    state: str = SessionState.PENDING
    events: List[Event] = field(default_factory=list)
    cost: Dict[str, float] = field(default_factory=dict)
    artifacts: List[dict] = field(default_factory=list)
    denied_tools: List[str] = field(default_factory=list)
    # Every seq this session has already captured. A stream is not a reliable channel:
    # an adapter that reconnects, or one whose transport retries, replays events it
    # already sent. Appending them again double-counts cost and duplicates artifacts,
    # which is worse than losing them because the numbers still look plausible.
    seen_seqs: set = field(default_factory=set)
    # Tool call parked awaiting an out-of-band decision, plus the tail of the stream
    # that was not consumed while the hold is open.
    held_tool: Optional[dict] = None
    pending_events: List[Event] = field(default_factory=list)
    # Model usage telemetry, keyed by model name -> accumulated cost.
    models: Dict[str, float] = field(default_factory=dict)

    @property
    def last_seq(self) -> int:
        return max(self.seen_seqs) if self.seen_seqs else -1


class Adapter:
    """Interface every execution backend implements.

    Deliberately small. Anything an adapter cannot do it declares absent in
    `capabilities()`, rather than raising at call time — the broker checks the
    declaration first, so an unsupported operation fails predictably instead of
    halfway through a session.
    """

    def capabilities(self) -> Capabilities:  # pragma: no cover - interface
        raise NotImplementedError

    def start(self, session: Session, prompt: str) -> Iterable[Event]:  # pragma: no cover
        raise NotImplementedError

    def steer(self, session: Session, instruction: str) -> Iterable[Event]:  # pragma: no cover
        raise NotImplementedError

    def resume(self, session: Session, after_seq: int) -> Iterable[Event]:  # pragma: no cover
        raise NotImplementedError

    def cancel(self, session: Session) -> None:  # pragma: no cover
        return None

    def recover_artifacts(self, session: Session) -> Iterable[dict]:  # pragma: no cover
        """Artifacts this session produced, re-read from the backend of record.

        Only called when `capabilities().can_recover_artifacts` is true.
        """
        return ()


def in_vercel(env: Optional[dict] = None) -> bool:
    env = os.environ if env is None else env
    return any(env.get(marker) for marker in _VERCEL_MARKERS)


class DevelopmentSessionBroker:
    """Owns session lifecycle, pinning, permissions and event capture."""

    def __init__(
        self,
        approve_tool: Optional[Callable[[Session, str, dict], bool]] = None,
        env: Optional[dict] = None,
    ):
        self._adapters: Dict[str, Adapter] = {}
        self._sessions: Dict[str, Session] = {}
        # Deny-by-default: with no hook supplied, only allowlisted tools run.
        self._approve_tool = approve_tool
        self._env = env

    # ------------------------------------------------------------- registration

    def register(self, adapter: Adapter) -> Capabilities:
        caps = adapter.capabilities()
        if not caps.name:
            raise BrokerError("adapter capabilities must carry a name")
        self._adapters[caps.name] = adapter
        return caps

    def discover(self) -> Dict[str, Capabilities]:
        """Capability discovery: what can each registered adapter do."""
        return {name: a.capabilities() for name, a in sorted(self._adapters.items())}

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            raise BrokerError(f"unknown session {session_id}")
        return self._sessions[session_id]

    # -------------------------------------------------------------------- start

    def start(
        self,
        adapter_name: str,
        prompt: str,
        repo_path: str,
        base_sha: str,
        worktree_path: str,
        permissions: Iterable[str] = (),
        session_id: Optional[str] = None,
    ) -> Session:
        if in_vercel(self._env):
            raise BrokerError(
                "refusing to start a development session inside Vercel: repository "
                "tools must not run in a build/serverless context"
            )
        if adapter_name not in self._adapters:
            raise BrokerError(f"no adapter registered as {adapter_name!r}")
        if not _SHA_RE.match(str(base_sha or "").strip().lower()):
            raise BrokerError(
                f"base_sha must be a full 40-char commit sha, got {base_sha!r}; "
                "branch names are not reproducible"
            )
        if not worktree_path or worktree_path.rstrip("/") == str(repo_path).rstrip("/"):
            raise BrokerError(
                "session requires an isolated worktree distinct from the main checkout"
            )

        session = Session(
            session_id=session_id or uuid.uuid4().hex,
            adapter=adapter_name,
            repo_path=str(repo_path),
            base_sha=str(base_sha).lower(),
            worktree_path=str(worktree_path),
            permissions=frozenset(permissions),
        )
        self._sessions[session.session_id] = session
        session.state = SessionState.RUNNING
        self._consume(session, self._adapters[adapter_name].start(session, prompt))
        return session

    # ------------------------------------------------------------------ driving

    def steer(self, session_id: str, instruction: str) -> Session:
        session = self.get(session_id)
        adapter = self._require_capability(session, "can_steer", "steer")
        self._require_live(session, "steer")
        self._consume(session, adapter.steer(session, instruction))
        return session

    def resume(self, session_id: str, after_seq: Optional[int] = None) -> Session:
        session = self.get(session_id)
        adapter = self._require_capability(session, "can_resume", "resume")
        if session.state in SessionState.TERMINAL:
            raise BrokerError(
                f"cannot resume session in terminal state {session.state!r}"
            )
        # Resume from the last event actually captured, so a disconnect mid-stream
        # replays nothing the caller already saw and drops nothing it did not.
        cursor = session.last_seq if after_seq is None else after_seq
        session.state = SessionState.RUNNING
        self._consume(session, adapter.resume(session, cursor))
        return session

    def release(self, session_id: str, approved: bool) -> Session:
        """Decide a held tool call and drain the stream that was parked behind it.

        `approved=True` runs the held call and continues; `approved=False` records the
        denial and continues WITHOUT it. Either way the parked tail is consumed, so a
        hold delays a session rather than stranding it.
        """
        session = self.get(session_id)
        if not session.held_tool:
            raise BrokerError(f"session {session_id} has no held tool call")
        held = session.held_tool
        tail = session.pending_events
        session.held_tool = None
        session.pending_events = []
        if session.state == SessionState.PAUSED:
            session.state = SessionState.RUNNING
        if approved:
            self._record(session, Event(seq=held["seq"], kind="tool_call",
                                        payload=held["payload"]))
            session.events.append(Event(
                seq=held["seq"], kind="status",
                payload={"released_tool": held["tool"], "reason": "approved"}))
        else:
            session.denied_tools.append(held["tool"])
            session.events.append(Event(
                seq=held["seq"], kind="status",
                payload={"denied_tool": held["tool"], "reason": "approval refused"}))
        self._consume(session, tail)
        return session

    def recover_artifacts(self, session_id: str) -> List[dict]:
        """Re-read artifacts from the adapter and receipt any the stream lost.

        Returns only the NEWLY receipted ones. A disconnect between the work landing and
        the artifact event arriving otherwise loses the receipt permanently and the
        branch looks empty downstream. Re-receipting is idempotent: artifacts already
        held are matched by path and not duplicated.
        """
        session = self.get(session_id)
        adapter = self._adapters[session.adapter]
        if not adapter.capabilities().supports("can_recover_artifacts"):
            raise BrokerError(
                f"adapter {session.adapter!r} cannot recover artifacts")
        recovered = []
        for artifact in adapter.recover_artifacts(session) or ():
            if not isinstance(artifact, dict):
                continue
            if self._receipt(session, dict(artifact)):
                recovered.append(dict(artifact))
        return recovered

    def telemetry(self, session_id: str) -> dict:
        """Cost and model usage for a session, as the runner records it elsewhere."""
        session = self.get(session_id)
        return {
            "session_id": session.session_id,
            "adapter": session.adapter,
            "state": session.state,
            "base_sha": session.base_sha,
            "worktree_path": session.worktree_path,
            "events": len(session.events),
            "cost": dict(session.cost),
            "models": dict(session.models),
            "artifacts": len(session.artifacts),
            "denied_tools": list(session.denied_tools),
            "held_tool": (session.held_tool or {}).get("tool"),
        }

    def cancel(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session.state in SessionState.TERMINAL:
            return session
        # A cancel while a hold is open must drop the parked work, not leave it to be
        # released after the session is already dead.
        session.held_tool = None
        session.pending_events = []
        self._adapters[session.adapter].cancel(session)
        session.state = SessionState.CANCELLED
        return session

    # ----------------------------------------------------------------- internals

    def _require_capability(self, session: Session, capability: str, verb: str) -> Adapter:
        adapter = self._adapters[session.adapter]
        if not adapter.capabilities().supports(capability):
            raise BrokerError(
                f"adapter {session.adapter!r} does not support {verb}"
            )
        return adapter

    def _require_live(self, session: Session, verb: str) -> None:
        if session.state in SessionState.TERMINAL:
            raise BrokerError(
                f"cannot {verb} session in terminal state {session.state!r}"
            )

    def _tool_allowed(self, session: Session, tool: str, payload: dict) -> bool:
        """Back-compat boolean view of the verdict. HOLD reads as 'not allowed yet'."""
        return self._tool_verdict(session, tool, payload) is True

    def _tool_verdict(self, session: Session, tool: str, payload: dict):
        """True (run), False (deny) or HOLD (park until an operator decides).

        The permission allowlist is checked FIRST and is not overridable: a tool the
        session was never granted is denied outright, and the approval hook is never
        consulted for it. A hook that could widen the grant would make the bounded
        permission set advisory.
        """
        if tool not in session.permissions:
            return False
        if self._approve_tool is None:
            return True
        decision = self._approve_tool(session, tool, payload)
        if decision is HOLD:
            return HOLD
        return bool(decision)

    def _consume(self, session: Session, events: Iterable[Event]) -> None:
        """Capture a stream: dedupe by seq, enforce approval, park on a hold."""
        stream = list(events or [])
        for index, event in enumerate(stream):
            # DUPLICATE SUPPRESSION. Replays are normal on reconnect; capturing one
            # twice double-counts its cost and duplicates its artifact, which is worse
            # than dropping it because the totals still look plausible.
            if event.seq in session.seen_seqs:
                continue

            if event.kind == "tool_call":
                tool = event.payload.get("tool", "")
                verdict = self._tool_verdict(session, tool, event.payload)
                if verdict == HOLD:
                    # Park the call AND the rest of the stream. Consuming the tail while
                    # a decision is outstanding would let the work the tool gates run
                    # anyway, which makes the hold decorative.
                    session.held_tool = {"seq": event.seq, "tool": tool,
                                         "payload": dict(event.payload)}
                    session.pending_events = stream[index + 1:]
                    session.state = SessionState.PAUSED
                    session.seen_seqs.add(event.seq)
                    session.events.append(Event(
                        seq=event.seq, kind="status",
                        payload={"held_tool": tool, "reason": "awaiting approval"},
                    ))
                    return
                if not verdict:
                    session.denied_tools.append(tool)
                    session.seen_seqs.add(event.seq)
                    # Record the denial as a status event so the transcript shows
                    # what was attempted; a silently dropped tool call is
                    # indistinguishable from one that was never made.
                    session.events.append(Event(
                        seq=event.seq, kind="status",
                        payload={"denied_tool": tool, "reason": "not permitted"},
                    ))
                    continue
            self._record(session, event)

    def _record(self, session: Session, event: Event) -> None:
        """Append one already-approved, not-yet-seen event and fold in its telemetry."""
        session.seen_seqs.add(event.seq)
        session.events.append(event)
        if event.kind == "cost":
            model = event.payload.get("model")
            for key, value in event.payload.items():
                if key == "model" or not isinstance(value, (int, float)):
                    continue
                if isinstance(value, bool):
                    continue
                session.cost[key] = session.cost.get(key, 0) + value
            if isinstance(model, str) and model:
                spend = event.payload.get("usd")
                session.models[model] = session.models.get(model, 0.0) + (
                    float(spend) if isinstance(spend, (int, float))
                    and not isinstance(spend, bool) else 0.0)
        elif event.kind == "artifact":
            self._receipt(session, dict(event.payload))
        elif event.kind == "status":
            state = event.payload.get("state")
            if state in (SessionState.COMPLETED, SessionState.FAILED,
                         SessionState.PAUSED, SessionState.CANCELLED):
                session.state = state

    @staticmethod
    def _artifact_key(artifact: dict) -> str:
        """Identity of an artifact for receipt purposes: its path, else its whole body."""
        return str(artifact.get("path") or artifact.get("name") or sorted(artifact.items()))

    def _receipt(self, session: Session, artifact: dict) -> bool:
        """Record an artifact once. Returns True when it was new."""
        key = self._artifact_key(artifact)
        if any(self._artifact_key(a) == key for a in session.artifacts):
            return False
        session.artifacts.append(artifact)
        return True
