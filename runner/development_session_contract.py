#!/usr/bin/env python3
"""development_session_contract.py — the versioned contract for ONE portfolio-wide
development session fabric.

WHY THIS EXISTS. Codex/ChatGPT sandboxes, Claude Cowork, orchestrator-native coders and
thin product-app clients all drive "a development session", and each one currently means
something slightly different by it. There is no shared vocabulary for what state a
session is in, what an event looks like, which SHA a claim was proved against, or who
holds the write lease. The result is that two adapters can both believe they own a
session, and a closure can assert delivered work that nobody can reproduce.

WHAT THIS IS. Contracts ONLY: states, legal transitions, the append-only event envelope,
runner identity + lease fencing, proof receipts, steering decisions, adapter identity,
and schema/version compatibility. It EXTENDS the orchestrator (it is the vocabulary that
development_session_store.py already persists); it is NOT a parallel pipeline.

WHAT THIS IS NOT. No adapters, no UI, no transport, no database access. This module
imports nothing outside the standard library on purpose: every other layer may depend on
it, so it must never be the thing that fails to import.

DONE AND MERGED ARE NOT PRODUCTION STATES. A task marked DONE has a branch; a task marked
MERGED is on an integration branch. Neither means a user can reach the change. Only
DEPLOYED_AND_VERIFIED does. That distinction is encoded here (`is_production_state`)
rather than left to prose, because the fleet has repeatedly reported work as shipped on
the strength of a merge.

CONVENTIONS. Fail-soft: every public function returns a sensible default rather than
raising on bad input — validators return a Verdict, never an exception. Tunables are
ORCH_-prefixed env vars so they are fleet-pushable via fleet_control.py.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

#: Contract version. MAJOR changes are breaking; MINOR additions are backward compatible.
CONTRACT_VERSION = "1.0"

#: The oldest contract version a current reader still accepts. Rollout rule: a writer may
#: only emit a version a reader in the fleet can still parse, so this moves ONLY after
#: every host has been upgraded — never in the same release as the writer change.
MIN_SUPPORTED_VERSION = os.environ.get("ORCH_SESSION_CONTRACT_MIN_VERSION", "1.0")

#: Schema version of the persisted rows (development_sessions et al). Tracked separately
#: from CONTRACT_VERSION because the wire vocabulary and the table shape roll out at
#: different times: the migration lands first, the writer switches on afterwards.
SCHEMA_VERSION = int(os.environ.get("ORCH_SESSION_SCHEMA_VERSION", "2"))

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")


def parse_version(value: Any) -> Optional[Tuple[int, int]]:
    """Parse "MAJOR.MINOR". Returns None on anything unparseable — never raises."""
    if not isinstance(value, str):
        return None
    m = _VERSION_RE.match(value.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def is_compatible(writer_version: Any, reader_version: Any = CONTRACT_VERSION) -> bool:
    """Can a reader on `reader_version` safely consume a record written on
    `writer_version`?

    Rule: same MAJOR, and the writer's MINOR must not exceed the reader's. A newer MINOR
    may carry fields the reader does not know how to interpret; accepting it silently is
    how an unknown steering decision gets ignored and a session drifts.
    """
    w = parse_version(writer_version)
    r = parse_version(reader_version)
    floor = parse_version(MIN_SUPPORTED_VERSION)
    if not w or not r:
        return False
    if w[0] != r[0]:
        return False
    if floor and w < floor:
        return False
    return w[1] <= r[1]


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

CREATED = "CREATED"
PLANNING = "PLANNING"
PLAN_REVIEW = "PLAN_REVIEW"
EXECUTING = "EXECUTING"
VERIFYING = "VERIFYING"
INTEGRATING = "INTEGRATING"
RELEASING = "RELEASING"
DEPLOYED_AND_VERIFIED = "DEPLOYED_AND_VERIFIED"
BLOCKED = "BLOCKED"

#: Pinned, ordered. Adding a state is a MINOR bump; removing or renaming one is MAJOR.
STATES: Tuple[str, ...] = (
    CREATED, PLANNING, PLAN_REVIEW, EXECUTING, VERIFYING,
    INTEGRATING, RELEASING, DEPLOYED_AND_VERIFIED, BLOCKED,
)

#: Terminal states — no outbound transition except the explicit rollback path.
TERMINAL_STATES: Tuple[str, ...] = (DEPLOYED_AND_VERIFIED,)

#: The ONLY state that means a user can reach the change. DONE and MERGED are task-level
#: bookkeeping and are deliberately absent from STATES.
PRODUCTION_STATES: Tuple[str, ...] = (DEPLOYED_AND_VERIFIED,)

#: Task-level states that are routinely mistaken for "shipped". Named so the mistake can
#: be asserted against in tests instead of being re-litigated in review.
NON_PRODUCTION_TASK_STATES: Tuple[str, ...] = ("DONE", "MERGED")

#: Legal forward transitions. Any state may go to BLOCKED; BLOCKED returns only to the
#: state it came from, which is carried on the session as `blocked_from`.
_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    CREATED: (PLANNING, BLOCKED),
    PLANNING: (PLAN_REVIEW, BLOCKED),
    PLAN_REVIEW: (PLANNING, EXECUTING, BLOCKED),
    EXECUTING: (VERIFYING, BLOCKED),
    VERIFYING: (EXECUTING, INTEGRATING, BLOCKED),
    INTEGRATING: (VERIFYING, RELEASING, BLOCKED),
    RELEASING: (DEPLOYED_AND_VERIFIED, INTEGRATING, BLOCKED),
    DEPLOYED_AND_VERIFIED: (),
    BLOCKED: tuple(s for s in STATES if s not in (BLOCKED, DEPLOYED_AND_VERIFIED)),
}


def is_production_state(state: Any) -> bool:
    """True only for states that mean a user can reach the change.

    DONE and MERGED return False. This is the single assertion that stops "merged" from
    being reported as "shipped".
    """
    return isinstance(state, str) and state.strip().upper() in PRODUCTION_STATES


def allowed_transitions(state: Any) -> Tuple[str, ...]:
    """Legal next states. Unknown state -> empty tuple, never an exception."""
    if not isinstance(state, str):
        return ()
    return _TRANSITIONS.get(state.strip().upper(), ())


def can_transition(from_state: Any, to_state: Any) -> bool:
    """Fail-soft transition check. Unknown states are illegal, not permissive."""
    if not isinstance(to_state, str):
        return False
    return to_state.strip().upper() in allowed_transitions(from_state)


# ---------------------------------------------------------------------------
# Verdicts — validators report, they do not raise
# ---------------------------------------------------------------------------


class Verdict(tuple):
    """(ok, reasons). A tuple so callers can unpack it, with named access for clarity.

    Validators return one of these instead of raising: a contract module that throws on
    a malformed record from one adapter would take down every other adapter with it.
    """

    __slots__ = ()

    def __new__(cls, ok: bool, reasons: Optional[Sequence[str]] = None):
        return super().__new__(cls, (bool(ok), tuple(reasons or ())))

    @property
    def ok(self) -> bool:
        return self[0]

    @property
    def reasons(self) -> Tuple[str, ...]:
        return self[1]

    def __bool__(self) -> bool:
        return self[0]


OK = Verdict(True)


# ---------------------------------------------------------------------------
# Identity: adapter, runner, lease fencing
# ---------------------------------------------------------------------------

#: Adapters permitted to drive a session. An unrecognised adapter is not rejected —
#: it is recorded as-is and flagged, because silently dropping a session from an adapter
#: the fleet has not heard of loses the very evidence needed to add it.
KNOWN_ADAPTERS: Tuple[str, ...] = (
    "codex", "chatgpt", "claude-cowork", "claude-code",
    "orchestrator-native", "product-app", "unknown",
)

_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")


def normalize_adapter(adapter: Any) -> str:
    """Lowercase, trimmed adapter id. Anything unusable becomes "unknown"."""
    if not isinstance(adapter, str):
        return "unknown"
    value = adapter.strip().lower()
    if not value or not _IDENT_RE.match(value):
        return "unknown"
    return value


def validate_runner_identity(identity: Any) -> Verdict:
    """A runner identity must name a host and carry a monotonic generation.

    The generation is what makes a resumed session distinguishable from a zombie: the
    session keeps its id and takes a higher generation, so "who is writing right now" is
    answerable without guessing from timestamps.
    """
    reasons: List[str] = []
    if not isinstance(identity, dict):
        return Verdict(False, ("runner identity must be a mapping",))
    host = identity.get("host")
    if not isinstance(host, str) or not _IDENT_RE.match(host.strip() or " "):
        reasons.append("host missing or malformed")
    generation = identity.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        reasons.append("generation must be a non-negative int")
    adapter = identity.get("adapter")
    if adapter is not None and normalize_adapter(adapter) == "unknown" and adapter != "unknown":
        reasons.append(f"unrecognised adapter {adapter!r} (recorded, not rejected)")
    return Verdict(not reasons, reasons)


def fencing_token(session_id: Any, generation: Any) -> str:
    """Deterministic lease fencing token: "<session_id>:<generation>".

    A write carrying a token whose generation is lower than the session's current
    generation is stale and MUST be refused by the store. Comparing tokens rather than
    timestamps is the point — a paused laptop that wakes up with an old lease has a
    perfectly plausible clock and a provably stale generation.
    """
    sid = str(session_id or "").strip() or "unknown"
    try:
        gen = int(generation)
    except (TypeError, ValueError):
        gen = 0
    return f"{sid}:{max(gen, 0)}"


def is_fencing_token_current(token: Any, session_id: Any, current_generation: Any) -> bool:
    """True only if `token` names this session at the CURRENT generation or newer.

    Fail-soft and fail-CLOSED: an unparseable token is not current. Being permissive here
    would re-admit exactly the split-brain writer this token exists to fence off.
    """
    if not isinstance(token, str) or ":" not in token:
        return False
    sid, _, gen_part = token.rpartition(":")
    if sid.strip() != str(session_id or "").strip():
        return False
    try:
        return int(gen_part) >= int(current_generation)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# SHAs — base, artifact, release
# ---------------------------------------------------------------------------

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

#: The three SHAs every closure must be able to name. They are separate on purpose:
#: a change can be committed (artifact) onto one base and released from a different
#: tree, and conflating them is how "it merged" got reported as "it shipped".
SHA_FIELDS: Tuple[str, ...] = ("base_sha", "artifact_sha", "release_sha")


def is_sha(value: Any) -> bool:
    """Fail-soft hex-SHA check, 7-40 chars, lowercase."""
    return isinstance(value, str) and bool(_SHA_RE.match(value.strip().lower()))


def validate_shas(record: Any, require: Sequence[str] = ("base_sha", "artifact_sha")) -> Verdict:
    """Every named SHA must be present and well formed.

    `release_sha` is NOT required by default: it does not exist until RELEASING. It IS
    required to enter DEPLOYED_AND_VERIFIED — see `validate_closure`.
    """
    if not isinstance(record, dict):
        return Verdict(False, ("record must be a mapping",))
    reasons = []
    for field in require:
        if field not in SHA_FIELDS:
            reasons.append(f"unknown sha field {field!r}")
            continue
        if not is_sha(record.get(field)):
            reasons.append(f"{field} missing or not a hex sha")
    return Verdict(not reasons, reasons)


# ---------------------------------------------------------------------------
# Events — append-only, sequenced
# ---------------------------------------------------------------------------

#: Pinned event kinds. Adding one is a MINOR bump.
EVENT_KINDS: Tuple[str, ...] = (
    "session.created", "session.state_changed", "session.heartbeat",
    "plan.proposed", "plan.reviewed",
    "work.started", "work.progress", "work.completed",
    "proof.recorded", "steering.decided",
    "integration.started", "integration.completed",
    "release.started", "release.verified",
    "session.blocked", "session.rolled_back",
)

#: Required keys on every event envelope.
EVENT_REQUIRED: Tuple[str, ...] = (
    "session_id", "seq", "kind", "idempotency_key", "contract_version",
)


def validate_event(event: Any) -> Verdict:
    """Validate one append-only event envelope.

    `seq` is a DENSE per-session ordinal starting at 1, not a timestamp: it is what lets a
    reader detect a gap. `idempotency_key` is what makes an at-least-once transport safe —
    a redelivered event collides and is absorbed instead of being appended twice.
    """
    if not isinstance(event, dict):
        return Verdict(False, ("event must be a mapping",))
    reasons: List[str] = []
    for key in EVENT_REQUIRED:
        if key not in event or event.get(key) in (None, ""):
            reasons.append(f"missing {key}")
    seq = event.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        reasons.append("seq must be an int >= 1")
    kind = event.get("kind")
    if isinstance(kind, str) and kind not in EVENT_KINDS:
        reasons.append(f"unknown event kind {kind!r}")
    version = event.get("contract_version")
    if version is not None and not is_compatible(version):
        reasons.append(f"contract_version {version!r} incompatible with {CONTRACT_VERSION}")
    payload = event.get("payload", {})
    if payload is not None and not isinstance(payload, dict):
        reasons.append("payload must be a mapping when present")
    return Verdict(not reasons, reasons)


def next_seq(last_seq: Any) -> int:
    """The next dense ordinal. Fail-soft: junk high-water mark restarts at 1 rather than
    raising, because refusing to append is worse than appending at a recoverable ordinal.
    """
    try:
        value = int(last_seq)
    except (TypeError, ValueError):
        return 1
    return value + 1 if value >= 0 else 1


def find_seq_gaps(seqs: Iterable[Any]) -> Tuple[int, ...]:
    """Ordinals missing from a supposedly dense sequence. Empty tuple means no gaps.

    A gap means an event was lost in transit, which is the difference between a replay
    that reconstructs the session and one that quietly reconstructs a different session.
    """
    try:
        clean = sorted({int(s) for s in seqs
                        if isinstance(s, int) and not isinstance(s, bool) and s >= 1})
    except (TypeError, ValueError):
        return ()
    if not clean:
        return ()
    return tuple(n for n in range(1, clean[-1] + 1) if n not in set(clean))


# ---------------------------------------------------------------------------
# Proof receipts
# ---------------------------------------------------------------------------

#: What a proof receipt may claim. "asserted" exists so an unproven claim is RECORDED as
#: unproven rather than being dressed up as a test run; it never satisfies a closure.
PROOF_KINDS: Tuple[str, ...] = ("test", "build", "lint", "deploy-check", "asserted")

#: Proof kinds that actually prove something. `asserted` is deliberately excluded.
PROVING_KINDS: Tuple[str, ...] = ("test", "build", "lint", "deploy-check")

PROOF_REQUIRED: Tuple[str, ...] = ("kind", "command", "exit_code", "artifact_sha")


def validate_proof_receipt(receipt: Any) -> Verdict:
    """A proof receipt names the command that was run, its exit code, and the SHA it was
    run against.

    All three are required together. A receipt without an `artifact_sha` proves that
    something passed somewhere, which is not a claim anyone can reproduce.
    """
    if not isinstance(receipt, dict):
        return Verdict(False, ("receipt must be a mapping",))
    reasons: List[str] = []
    for key in PROOF_REQUIRED:
        if key not in receipt or receipt.get(key) in (None, ""):
            reasons.append(f"missing {key}")
    kind = receipt.get("kind")
    if isinstance(kind, str) and kind not in PROOF_KINDS:
        reasons.append(f"unknown proof kind {kind!r}")
    exit_code = receipt.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        reasons.append("exit_code must be an int")
    if not is_sha(receipt.get("artifact_sha")):
        reasons.append("artifact_sha missing or not a hex sha")
    command = receipt.get("command")
    if isinstance(command, str) and len(command.strip()) < 3:
        reasons.append("command too short to be reproducible")
    return Verdict(not reasons, reasons)


def is_passing_proof(receipt: Any) -> bool:
    """True only for a well-formed receipt of a PROVING kind that exited 0."""
    if not validate_proof_receipt(receipt).ok:
        return False
    return receipt.get("kind") in PROVING_KINDS and receipt.get("exit_code") == 0


# ---------------------------------------------------------------------------
# Steering decisions
# ---------------------------------------------------------------------------

STEERING_DECISIONS: Tuple[str, ...] = (
    "continue", "revise", "split", "abort", "escalate", "rollback",
)

#: Decisions that only a human owner may make. An adapter emitting one of these without
#: an owner actor is refused: the fleet must not be able to authorise its own escalation.
OWNER_ONLY_DECISIONS: Tuple[str, ...] = ("abort", "rollback", "escalate")


def validate_steering_decision(decision: Any) -> Verdict:
    """A steering decision names the decision, who made it, and why."""
    if not isinstance(decision, dict):
        return Verdict(False, ("decision must be a mapping",))
    reasons: List[str] = []
    value = decision.get("decision")
    if not isinstance(value, str) or value not in STEERING_DECISIONS:
        reasons.append(f"decision must be one of {STEERING_DECISIONS}")
        value = None
    actor = decision.get("actor")
    if not isinstance(actor, str) or not actor.strip():
        reasons.append("actor required")
        actor = ""
    if not isinstance(decision.get("rationale"), str) or not decision.get("rationale", "").strip():
        reasons.append("rationale required")
    if value in OWNER_ONLY_DECISIONS and decision.get("actor_kind") != "owner":
        reasons.append(f"{value!r} is owner-only; actor_kind must be 'owner'")
    return Verdict(not reasons, reasons)


# ---------------------------------------------------------------------------
# Closure — the gate that separates "merged" from "shipped"
# ---------------------------------------------------------------------------


def validate_closure(session: Any, proofs: Optional[Sequence[Any]] = None) -> Verdict:
    """May this session close in the state it claims?

    Closing as DEPLOYED_AND_VERIFIED requires all three SHAs AND at least one passing
    proof receipt of a proving kind. Closing in any other state requires only that the
    state be known. DONE/MERGED are rejected outright: they are task bookkeeping and were
    never session states, and accepting them is precisely how a branch got reported shipped.
    """
    if not isinstance(session, dict):
        return Verdict(False, ("session must be a mapping",))
    state = session.get("state")
    if isinstance(state, str) and state.strip().upper() in NON_PRODUCTION_TASK_STATES:
        return Verdict(False, (
            f"{state!r} is a task state, not a session state; "
            "a merge is not a deployment",))
    if not isinstance(state, str) or state.strip().upper() not in STATES:
        return Verdict(False, (f"unknown session state {state!r}",))
    state = state.strip().upper()
    if state != DEPLOYED_AND_VERIFIED:
        return OK

    reasons: List[str] = []
    sha_verdict = validate_shas(session, require=SHA_FIELDS)
    if not sha_verdict.ok:
        reasons.extend(sha_verdict.reasons)
    if not any(is_passing_proof(p) for p in (proofs or ())):
        reasons.append("no passing proof receipt; a deployment nobody verified is not verified")
    return Verdict(not reasons, reasons)


# ---------------------------------------------------------------------------
# Rollback + rollout
# ---------------------------------------------------------------------------

#: Rollback is a first-class transition, not an exception path: a session that shipped
#: something bad must be able to say so on the record. It reopens at INTEGRATING rather
#: than at CREATED, because the plan and the proofs are still valid — the release is not.
ROLLBACK_TARGET = INTEGRATING


def rollback(session: Any) -> Dict[str, Any]:
    """Return the session record as it should look after a rollback.

    Non-mutating and fail-soft: given junk it returns a minimal well-formed record rather
    than raising, so a rollback can never be blocked by the shape of the thing it rolls back.
    The release_sha is cleared (that release no longer stands) while base and artifact SHAs
    are preserved (that work still exists and must remain auditable).
    """
    base = dict(session) if isinstance(session, dict) else {}
    prior = base.get("state") if isinstance(base.get("state"), str) else None
    base.update({
        "state": ROLLBACK_TARGET,
        "release_sha": None,
        "rolled_back_from": prior,
        "rolled_back_at": base.get("rolled_back_at") or int(time.time()),
        "contract_version": CONTRACT_VERSION,
    })
    return base


def rollout_plan(writer_version: Any = CONTRACT_VERSION,
                 reader_version: Any = MIN_SUPPORTED_VERSION) -> Dict[str, Any]:
    """The backward-compatible rollout rules, as data rather than prose.

    Order matters and is the whole point: migration first (additive, nullable, defaulted),
    then readers that tolerate the new fields, then writers that emit them, and only then
    does MIN_SUPPORTED_VERSION move. Any other order strands a host that has not restarted.
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "min_supported_version": MIN_SUPPORTED_VERSION,
        "compatible": is_compatible(writer_version, CONTRACT_VERSION),
        "readers_can_parse_writer": is_compatible(writer_version, reader_version),
        "steps": (
            "1. apply the additive migration (nullable columns, defaults, no backfill)",
            "2. deploy readers that ignore unknown fields",
            "3. deploy writers that emit the new fields",
            "4. only then raise ORCH_SESSION_CONTRACT_MIN_VERSION",
        ),
        "rollback": (
            "writers revert first, then readers; the migration is left in place "
            "because dropping a column is not backward compatible"
        ),
    }
