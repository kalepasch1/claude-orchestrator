#!/usr/bin/env python3
"""Governed zero-copy federation: leases, capabilities, quotas, recovery.

``hivemind_v15.ZeroCopyFederation`` publishes packed fractal keys into a ring
buffer and hands back a read-only ``memoryview``.  That is a genuine zero-copy
read, and it has one property that makes it unsafe to hand to another app:

    the ring wraps, and a view handed out earlier then silently starts
    returning a *different* app's bytes, with no error

which this module demonstrates in a test rather than asserting in prose.  A
borrowed view is only sound if the borrower can tell that its slot has been
recycled, so every publish here returns a :class:`Lease` carrying a generation
counter, and reading through a stale lease raises instead of returning wrong
bytes.

The rest of proposal 6 is governance the base class does not attempt:
capabilities per app, tenant boundaries, consent and redaction before anything
is published, per-app quotas, a schema/version header on every envelope, a
timeout on request/response exchange, and crash recovery that discards torn
slots rather than parsing them.

**On "zero copy" across hosts.**  A shared ring removes a copy between
processes on ONE machine.  It does not remove a network boundary, and pretending
otherwise is how data ends up leaving a host unencrypted.  :func:`publish_remote`
refuses to operate without an explicit secure transport.
"""
from __future__ import annotations

import hashlib
import json
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

try:  # pragma: no cover - import shape depends on caller
    from hivemind_v15 import FLEET_APPS, HolographicMemory, canonical_app
except ImportError:  # pragma: no cover
    from .hivemind_v15 import FLEET_APPS, HolographicMemory, canonical_app  # type: ignore


ENVELOPE_SCHEMA = "v15fed"
ENVELOPE_VERSION = 1
HEADER = "!IIQ"                     # payload length, generation, publisher hash
HEADER_SIZE = struct.calcsize(HEADER)
SLOT = 1024


class FederationError(RuntimeError):
    """Base class for every refusal in this module."""


class StaleLease(FederationError):
    """The slot behind a borrowed view was recycled; the bytes are not yours."""


class AclDenied(FederationError):
    """The app lacks the capability it tried to exercise."""


class QuotaExceeded(FederationError):
    """The app exhausted its publish budget for the current window."""


class SchemaMismatch(FederationError):
    """The envelope was written by an incompatible schema or version."""


class ExchangeTimeout(FederationError):
    """A correlated result did not arrive inside the deadline."""


class InsecureTransport(FederationError):
    """A cross-host publish was attempted without a secure transport."""


class Capability:
    PUBLISH = "publish"
    QUERY = "query"
    READ_RESULTS = "read_results"

    ALL = (PUBLISH, QUERY, READ_RESULTS)


@dataclass
class Grant:
    """What one app may do, and whose data it consented to share."""

    app: str
    capabilities: Set[str] = field(default_factory=set)
    shares_with: Set[str] = field(default_factory=set)   # consent, explicit
    redact_fields: Set[str] = field(default_factory=set)
    publish_quota: Optional[int] = None

    def allows(self, capability: str) -> bool:
        return capability in self.capabilities

    def consents_to(self, reader: str) -> bool:
        reader = canonical_app(reader)
        return reader == self.app or reader in self.shares_with or "*" in self.shares_with


@dataclass(frozen=True)
class Lease:
    """A borrowed slot plus the generation that made it valid."""

    slot: int
    generation: int
    publisher: str
    length: int
    issued_at: float


@dataclass
class Telemetry:
    views_handed_out: int = 0
    bytes_viewed: int = 0
    copies_made: int = 0
    bytes_copied: int = 0
    stale_reads: int = 0
    publishes: int = 0
    publish_seconds: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["mean_publish_us"] = (self.publish_seconds / self.publishes * 1e6) if self.publishes else 0.0
        d["note"] = ("copies_made counts every time a caller materialised bytes; a view "
                     "handed out is not a copy until it is read into memory")
        return d


def redact(payload: Any, fields: Set[str]) -> Any:
    """Drop consented-away fields before anything reaches a shared buffer."""
    if not fields or not isinstance(payload, dict):
        return payload
    return {k: ("[redacted]" if k in fields else v) for k, v in payload.items()}


def _publisher_hash(app: str) -> int:
    return int.from_bytes(hashlib.blake2b(canonical_app(app).encode(), digest_size=8).digest(), "big")


class GovernedFederation:
    """Ring-buffer federation with leases, ACLs, quotas and recovery."""

    def __init__(self, memory: Optional[HolographicMemory] = None, slots: int = 64,
                 slot_size: int = SLOT) -> None:
        self.memory = memory or HolographicMemory()
        self.slots = slots
        self.slot_size = slot_size
        self._ring = bytearray(slot_size * slots)
        self._generation: List[int] = [0] * slots
        self._cursor = 0
        self._grants: Dict[str, Grant] = {}
        self._quota_used: Dict[str, int] = {}
        self._results: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self.telemetry = Telemetry()

    # -- governance ------------------------------------------------------
    def grant(self, app: str, capabilities: Sequence[str] = Capability.ALL,
              shares_with: Sequence[str] = (), redact_fields: Sequence[str] = (),
              publish_quota: Optional[int] = None) -> Grant:
        app = canonical_app(app)
        unknown = set(capabilities) - set(Capability.ALL)
        if unknown:
            raise ValueError(f"unknown capabilities: {sorted(unknown)}")
        g = Grant(app=app, capabilities=set(capabilities),
                  shares_with={canonical_app(a) if a != "*" else "*" for a in shares_with},
                  redact_fields=set(redact_fields), publish_quota=publish_quota)
        with self._lock:
            self._grants[app] = g
        return g

    def _require(self, app: str, capability: str) -> Grant:
        g = self._grants.get(canonical_app(app))
        if g is None:
            raise AclDenied(f"{canonical_app(app)} has no grant")
        if not g.allows(capability):
            raise AclDenied(f"{g.app} lacks capability {capability!r}")
        return g

    # -- publish ---------------------------------------------------------
    def publish(self, app: str, payload: Any) -> Lease:
        """Redact, quota-check and write one envelope; return a lease, not a view."""
        started = time.perf_counter()
        grant = self._require(app, Capability.PUBLISH)
        body = redact(payload, grant.redact_fields)
        envelope = {"schema": ENVELOPE_SCHEMA, "version": ENVELOPE_VERSION,
                    "app": grant.app, "body": body}
        raw = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > self.slot_size - HEADER_SIZE:
            raise ValueError(f"envelope of {len(raw)}B exceeds slot capacity")

        with self._lock:
            used = self._quota_used.get(grant.app, 0)
            if grant.publish_quota is not None and used >= grant.publish_quota:
                raise QuotaExceeded(f"{grant.app} used {used}/{grant.publish_quota} publishes")
            self._quota_used[grant.app] = used + 1

            slot = self._cursor % self.slots
            self._cursor += 1
            self._generation[slot] += 1
            generation = self._generation[slot]
            start = slot * self.slot_size
            struct.pack_into(HEADER, self._ring, start, len(raw), generation,
                             _publisher_hash(grant.app))
            self._ring[start + HEADER_SIZE:start + HEADER_SIZE + len(raw)] = raw
            self.telemetry.publishes += 1
            self.telemetry.publish_seconds += time.perf_counter() - started
            return Lease(slot=slot, generation=generation, publisher=grant.app,
                         length=len(raw), issued_at=time.time())

    # -- borrow ----------------------------------------------------------
    def view(self, reader: str, lease: Lease) -> memoryview:
        """Borrow the slot without copying.  Raises if the slot was recycled."""
        self._require(reader, Capability.QUERY)
        publisher_grant = self._grants.get(lease.publisher)
        if publisher_grant is None or not publisher_grant.consents_to(reader):
            raise AclDenied(f"{lease.publisher} has not consented to share with {canonical_app(reader)}")
        with self._lock:
            if self._generation[lease.slot] != lease.generation:
                self.telemetry.stale_reads += 1
                raise StaleLease(
                    f"slot {lease.slot} moved from generation {lease.generation} to "
                    f"{self._generation[lease.slot]}; the bytes behind this view are not yours")
            start = lease.slot * self.slot_size
            length, generation, _ = struct.unpack_from(HEADER, self._ring, start)
            if generation != lease.generation:
                raise StaleLease(f"slot {lease.slot} header generation drifted")
            self.telemetry.views_handed_out += 1
            self.telemetry.bytes_viewed += length
            return memoryview(self._ring)[start + HEADER_SIZE:start + HEADER_SIZE + length].toreadonly()

    def read(self, reader: str, lease: Lease) -> Dict[str, Any]:
        """Materialise an envelope (this IS a copy, and is counted as one)."""
        with self.view(reader, lease) as borrowed:
            raw = bytes(borrowed)
        self.telemetry.copies_made += 1
        self.telemetry.bytes_copied += len(raw)
        envelope = json.loads(raw)
        if envelope.get("schema") != ENVELOPE_SCHEMA:
            raise SchemaMismatch(f"unknown schema {envelope.get('schema')!r}")
        if envelope.get("version") != ENVELOPE_VERSION:
            raise SchemaMismatch(
                f"envelope version {envelope.get('version')} != {ENVELOPE_VERSION}")
        return envelope

    # -- correlated exchange ---------------------------------------------
    def submit_result(self, app: str, correlation_id: str, result: Any) -> None:
        self._require(app, Capability.PUBLISH)
        with self._lock:
            self._results[correlation_id] = {"app": canonical_app(app), "result": result,
                                             "at": time.time()}

    def await_result(self, reader: str, correlation_id: str, timeout_s: float = .25,
                     poll_s: float = .005) -> Dict[str, Any]:
        """Wait for a correlated result; a missing answer times out, never hangs."""
        self._require(reader, Capability.READ_RESULTS)
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            with self._lock:
                found = self._results.get(correlation_id)
            if found is not None:
                producer = self._grants.get(found["app"])
                if producer is None or not producer.consents_to(reader):
                    raise AclDenied(f"{found['app']} has not consented to share with "
                                    f"{canonical_app(reader)}")
                return found
            time.sleep(poll_s)
        raise ExchangeTimeout(f"no result for {correlation_id!r} within {timeout_s}s")

    # -- recovery --------------------------------------------------------
    def recover(self) -> Dict[str, Any]:
        """Scan the ring after a crash; discard torn slots instead of parsing them.

        A slot whose header claims a length that does not fit, or whose body is
        not decodable, is evidence of a half-written envelope.  It is zeroed,
        not repaired -- a partially written record has no correct interpretation.
        """
        intact, torn = 0, []
        with self._lock:
            for slot in range(self.slots):
                start = slot * self.slot_size
                length, generation, _ = struct.unpack_from(HEADER, self._ring, start)
                if generation == 0 and length == 0:
                    continue  # never written
                if length <= 0 or length > self.slot_size - HEADER_SIZE:
                    torn.append({"slot": slot, "reason": "impossible_length"})
                    self._zero(slot)
                    continue
                raw = bytes(self._ring[start + HEADER_SIZE:start + HEADER_SIZE + length])
                try:
                    envelope = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    torn.append({"slot": slot, "reason": "undecodable"})
                    self._zero(slot)
                    continue
                if envelope.get("schema") != ENVELOPE_SCHEMA:
                    torn.append({"slot": slot, "reason": "foreign_schema"})
                    self._zero(slot)
                    continue
                intact += 1
        return {"intact": intact, "torn": torn, "slots": self.slots}

    def _zero(self, slot: int) -> None:
        start = slot * self.slot_size
        self._ring[start:start + self.slot_size] = b"\x00" * self.slot_size
        self._generation[slot] += 1   # invalidate every lease on this slot

    # -- introspection ---------------------------------------------------
    def quota_state(self) -> Dict[str, Any]:
        with self._lock:
            return {app: {"used": self._quota_used.get(app, 0), "limit": g.publish_quota}
                    for app, g in self._grants.items()}


def publish_remote(federation: GovernedFederation, app: str, payload: Any,
                   host: str, transport: Optional[Callable[[str, bytes], Any]] = None) -> Any:
    """Cross-host publish.  Refuses to pretend shared memory crosses a network.

    A ring buffer removes a copy between processes on one machine.  Across
    hosts there is a real network boundary, and it must be carried by the
    established secure transport -- not by a shared-memory API that quietly
    becomes a plaintext socket.
    """
    if transport is None:
        raise InsecureTransport(
            f"cross-host publish to {host!r} requires an explicit secure transport; "
            "a shared ring buffer does not span hosts")
    grant = federation._require(app, Capability.PUBLISH)  # noqa: SLF001 - same module contract
    body = redact(payload, grant.redact_fields)
    envelope = json.dumps({"schema": ENVELOPE_SCHEMA, "version": ENVELOPE_VERSION,
                           "app": grant.app, "body": body},
                          sort_keys=True, separators=(",", ":")).encode()
    return transport(host, envelope)
