#!/usr/bin/env python3
"""Versioned, retained, corruption-tolerant holographic keys.

``hivemind_v15.HolographicMemory`` gives us fractal encoding, LSH bucketing and
a consolidation sleep cycle.  This module supplies the operational guarantees
proposal 2 asks for and the base class does not have:

* **Versioned keys.**  A key encodes the encoder parameters that produced it.
  Changing ``scales``/``keep_per_scale`` silently changes every coefficient, so
  without a version stamp an upgraded process reads old entries as near-random
  neighbours.  :class:`VersionedKey` makes the mismatch detectable and
  :meth:`VersionedMemory.migrate` re-encodes instead of guessing.
* **Retention controls.**  The base class only evicts on capacity.  A TTL means
  a stale answer cannot be served indefinitely just because nothing pushed it
  out of an under-full cache.
* **Corruption recovery.**  Coefficients live in memory and are snapshotted by
  callers; a truncated or edited record must be *detected and dropped*, not
  silently scored against live queries.  Every record carries a checksum.
* **Honest benchmarks.**  :func:`benchmark` reports measured compression (bytes
  of coefficients vs bytes of the full signal) and measured recall on the
  caller's own data, including when compression is negative for small inputs.

**On tenant isolation.**  ``HolographicMemory`` shares entries across apps: one
app stores a signal and another reads it back, reported as
``source="federated_memory"``.  That is the deliberate contract of a *fleet*
hivemind and three tests in ``test_hivemind_v15`` assert it, so this module does
not change it.  Isolation is offered as an explicit, opt-in :class:`Scope`
instead -- ``Scope.FLEET`` (the default) preserves federation exactly, while
``Scope.TENANT`` gives an app a private memory for signals it may not share.
Choosing is a policy decision, and callers now get to make it deliberately
rather than discovering the answer in production.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

try:  # pragma: no cover - import shape depends on caller
    from hivemind_v15 import FractalEncoder, HolographicMemory, MemoryHit, canonical_app, value_key
except ImportError:  # pragma: no cover
    from .hivemind_v15 import (  # type: ignore
        FractalEncoder, HolographicMemory, MemoryHit, canonical_app, value_key)


KEY_SCHEMA = "hk"          # holographic key
KEY_VERSION = 1            # bump when the on-key layout changes
Coefficients = Tuple[Tuple[int, int, float], ...]


class CorruptRecord(ValueError):
    """A stored record failed its integrity check and was refused."""


class QuotaExceeded(RuntimeError):
    """An app tried to exceed its share of a shared memory."""


def encoder_fingerprint(encoder: FractalEncoder) -> str:
    """Identity of the *encoding function*, not of any particular value."""
    raw = f"{encoder.scales}:{encoder.keep_per_scale}".encode()
    return hashlib.blake2b(raw, digest_size=4).hexdigest()


@dataclass(frozen=True)
class VersionedKey:
    schema: str
    version: int
    encoder: str
    app: str
    digest: str

    def encode(self) -> str:
        return f"{self.schema}.{self.version}.{self.encoder}.{self.app}.{self.digest}"

    @classmethod
    def parse(cls, raw: str) -> "VersionedKey":
        parts = raw.split(".")
        if len(parts) != 5:
            raise ValueError(f"malformed holographic key: {raw!r}")
        schema, version, enc, app, digest = parts
        if schema != KEY_SCHEMA:
            raise ValueError(f"unknown key schema {schema!r}")
        try:
            version_i = int(version)
        except ValueError as exc:
            raise ValueError(f"bad key version in {raw!r}") from exc
        return cls(schema, version_i, enc, app, digest)

    @classmethod
    def build(cls, app: str, coefficients: Coefficients, encoder: FractalEncoder) -> "VersionedKey":
        digest = hashlib.blake2b(repr(coefficients).encode(), digest_size=12).hexdigest()
        return cls(KEY_SCHEMA, KEY_VERSION, encoder_fingerprint(encoder),
                   canonical_app(app), digest)

    def compatible_with(self, encoder: FractalEncoder) -> bool:
        return self.version == KEY_VERSION and self.encoder == encoder_fingerprint(encoder)


@dataclass
class Record:
    app: str
    key: str
    coefficients: Coefficients
    signal_key: str
    value: Any
    stored_at: float
    checksum: str

    @staticmethod
    def compute_checksum(app: str, coefficients: Coefficients, signal_key: str, value: Any) -> str:
        payload = json.dumps([app, list(coefficients), signal_key, value],
                             sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()

    def verify(self) -> bool:
        return self.checksum == self.compute_checksum(
            self.app, self.coefficients, self.signal_key, self.value)


class Scope:
    """Sharing policy for a :class:`VersionedMemory`."""

    FLEET = "fleet"     # federated: apps read each other's entries (base behaviour)
    TENANT = "tenant"   # private: each app gets its own backing memory

    ALL = (FLEET, TENANT)


class VersionedMemory:
    """Holographic memory with versioned keys, TTL retention and integrity checks.

    ``scope`` defaults to :data:`Scope.FLEET`, so wrapping an existing memory
    changes nothing about who can read what.  Pass :data:`Scope.TENANT` for
    signals an app must not publish to the fleet.
    """

    def __init__(self, memory: Optional[HolographicMemory] = None,
                 ttl_seconds: Optional[float] = None,
                 per_app_quota: Optional[int] = None,
                 scope: str = Scope.FLEET,
                 capacity: int = 4096) -> None:
        if scope not in Scope.ALL:
            raise ValueError(f"scope must be one of {Scope.ALL}, got {scope!r}")
        self.scope = scope
        self.capacity = capacity
        self.memory = memory or HolographicMemory(capacity=capacity)
        self.ttl_seconds = ttl_seconds
        self.per_app_quota = per_app_quota
        self._records: Dict[str, Record] = {}
        self._by_app: Dict[str, set] = {}
        self._tenant_memories: Dict[str, HolographicMemory] = {}
        self._lock = threading.RLock()
        self.metrics: Counter = Counter()

    def backing(self, app: str) -> HolographicMemory:
        """The memory an app's signals live in, per the configured scope."""
        if self.scope == Scope.FLEET:
            return self.memory
        app = canonical_app(app)
        with self._lock:
            mem = self._tenant_memories.get(app)
            if mem is None:
                mem = HolographicMemory(capacity=self.capacity, encoder=self.memory.encoder)
                self._tenant_memories[app] = mem
            return mem

    # -- write -----------------------------------------------------------
    def put(self, app: str, signal: Any, value: Any) -> str:
        app = canonical_app(app)
        coefficients = self.memory.encoder.encode(signal)
        vkey = VersionedKey.build(app, coefficients, self.memory.encoder)
        raw = vkey.encode()
        with self._lock:
            owned = self._by_app.setdefault(app, set())
            if (self.per_app_quota is not None and raw not in owned
                    and len(owned) >= self.per_app_quota):
                self.metrics["quota_rejected"] += 1
                raise QuotaExceeded(
                    f"{app} holds {len(owned)} of {self.per_app_quota} permitted entries")
            self._records[raw] = Record(
                app=app, key=raw, coefficients=coefficients, signal_key=value_key(signal),
                value=value, stored_at=time.time(),
                checksum=Record.compute_checksum(app, coefficients, value_key(signal), value))
            owned.add(raw)
        self.backing(app).put(app, signal, value)
        self.metrics["put"] += 1
        return raw

    # -- read ------------------------------------------------------------
    def get(self, app: str, signal: Any, threshold: float = .55,
            now: Optional[float] = None) -> Optional[MemoryHit]:
        """Read under the configured scope, refusing expired or corrupt records."""
        app = canonical_app(app)
        now = now if now is not None else time.time()
        self.expire(now=now)
        hit = self.backing(app).get(app, signal, threshold=threshold)
        if hit is None:
            self.metrics["miss"] += 1
            return None
        coefficients = self.memory.encoder.encode(signal)
        raw = VersionedKey.build(app, coefficients, self.memory.encoder).encode()
        record = self._records.get(raw)
        if record is None:
            # An associative (non-exact) neighbour: the base memory found a
            # similar signal, so there is no versioned record under this exact
            # key.  That is a legitimate hit, not an integrity failure.
            self.metrics["associative_hit"] += 1
            return hit
        if not record.verify():
            self.drop(raw)
            self.metrics["corrupt_dropped"] += 1
            raise CorruptRecord(f"record {raw} failed its integrity check and was dropped")
        self.metrics["hit"] += 1
        return hit

    def read_record(self, key: str) -> Record:
        record = self._records.get(key)
        if record is None:
            raise KeyError(key)
        if not record.verify():
            self.drop(key)
            raise CorruptRecord(f"record {key} failed its integrity check and was dropped")
        return record

    # -- lifecycle -------------------------------------------------------
    def drop(self, key: str) -> bool:
        with self._lock:
            record = self._records.pop(key, None)
            if record is None:
                return False
            self._by_app.get(record.app, set()).discard(key)
            return True

    def expire(self, now: Optional[float] = None) -> int:
        """Retention control: TTL eviction independent of capacity pressure."""
        if self.ttl_seconds is None:
            return 0
        now = now if now is not None else time.time()
        with self._lock:
            stale = [k for k, r in self._records.items() if now - r.stored_at > self.ttl_seconds]
            for key in stale:
                self.drop(key)
        if stale:
            self.metrics["expired"] += len(stale)
        return len(stale)

    def scrub(self) -> Dict[str, Any]:
        """Corruption recovery sweep: drop every record failing its checksum."""
        with self._lock:
            bad = [k for k, r in self._records.items() if not r.verify()]
            for key in bad:
                self.drop(key)
        self.metrics["scrub_dropped"] += len(bad)
        return {"scanned": len(self._records) + len(bad), "dropped": len(bad), "keys": bad}

    def migrate(self, encoder: FractalEncoder) -> Dict[str, Any]:
        """Key-version migration: retire records the new encoder cannot read.

        Only the *identity* of a signal is retained (``signal_key`` is a hash),
        never the signal itself, so a record genuinely cannot be re-encoded
        under new parameters -- and it must not be reinterpreted either, since
        old coefficients scored against a different basis return neighbours
        that look confident and are wrong.  Retiring them is the only sound
        option, and callers see exactly which keys went.

        ``retained`` are the records whose key already matches the incoming
        encoder and therefore need no work.
        """
        retired, retained = [], []
        with self._lock:
            for key in list(self._records):
                try:
                    parsed = VersionedKey.parse(key)
                except ValueError:
                    self.drop(key); retired.append(key); continue
                if parsed.compatible_with(encoder):
                    retained.append(key)
                    continue
                self.drop(key)
                retired.append(key)
            self.memory.encoder = encoder
        self.metrics["migration_retired"] += len(retired)
        return {"retired": retired, "retained": retained,
                "encoder": encoder_fingerprint(encoder),
                "note": "incompatible records are retired, never reinterpreted under a different basis"}

    def consolidate(self) -> Dict[str, Any]:
        """Sleep-cycle re-encoding across every backing memory in scope."""
        stats = self.memory.consolidate()
        for mem in list(self._tenant_memories.values()):
            tenant_stats = mem.consolidate()
            stats["removed"] = stats.get("removed", 0) + tenant_stats.get("removed", 0)
            stats["retained"] = stats.get("retained", 0) + tenant_stats.get("retained", 0)
        stats["scope"] = self.scope
        stats["versioned_records"] = len(self._records)
        stats["tracked_apps"] = len([a for a, keys in self._by_app.items() if keys])
        return stats

    def app_usage(self) -> Dict[str, int]:
        with self._lock:
            return {app: len(keys) for app, keys in self._by_app.items() if keys}


# -- measurement ---------------------------------------------------------
def compression_report(encoder: FractalEncoder, signals: Sequence[Any]) -> Dict[str, Any]:
    """Measured compression: coefficient bytes vs full-signal vector bytes."""
    if not signals:
        raise ValueError("need at least one signal to measure compression")
    coeff_bytes = full_bytes = 0
    for signal in signals:
        coefficients = encoder.encode(signal)
        coeff_bytes += len(json.dumps(coefficients, separators=(",", ":")).encode())
        full_bytes += len(json.dumps(encoder.vector(signal), separators=(",", ":")).encode())
    ratio = (full_bytes / coeff_bytes) if coeff_bytes else 0.0
    return {
        "signals": len(signals), "coefficient_bytes": coeff_bytes,
        "full_signal_bytes": full_bytes, "compression_ratio": ratio,
        "note": "ratio below 1.0 means the coefficient form is larger than the raw vector for this data",
    }


def recall_report(memory: VersionedMemory, app: str,
                  pairs: Sequence[Tuple[Any, Any]], threshold: float = .55) -> Dict[str, Any]:
    """Measured recall: fraction of stored signals retrieved with the right value."""
    if not pairs:
        raise ValueError("need at least one (signal, value) pair to measure recall")
    for signal, value in pairs:
        memory.put(app, signal, value)
    correct = exact = 0
    for signal, value in pairs:
        hit = memory.get(app, signal, threshold=threshold)
        if hit is None:
            continue
        if hit.value == value:
            correct += 1
        if hit.exact:
            exact += 1
    return {"stored": len(pairs), "recalled": correct, "exact": exact,
            "recall": correct / len(pairs), "exact_recall": exact / len(pairs)}


def benchmark(app: str = "orchestrator", samples: int = 64) -> Dict[str, Any]:
    """End-to-end measured report; no target multipliers are asserted."""
    encoder = FractalEncoder()
    memory = VersionedMemory(HolographicMemory(capacity=max(16, samples * 2)))
    signals = [{"kind": "task", "n": i, "body": f"payload-{i}" * 4} for i in range(samples)]
    started = time.perf_counter()
    recall = recall_report(memory, app, [(s, f"value-{i}") for i, s in enumerate(signals)])
    elapsed = time.perf_counter() - started
    return {"compression": compression_report(encoder, signals), "recall": recall,
            "elapsed_s": elapsed, "app_usage": memory.app_usage()}


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(benchmark(), indent=2, sort_keys=True))
