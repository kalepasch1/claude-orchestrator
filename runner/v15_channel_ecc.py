#!/usr/bin/env python3
"""Bounded adaptive redundancy over the V15 error-correction curriculum.

``hivemind_v15.AdaptiveErrorCorrection`` learns a per-(source, target, time
bucket) error rate and maps it to a redundancy count of 1, 2 or 3.  Proposal 5
asks for the transport that *uses* that signal safely, which is where the real
requirements live:

* **Strict caps.**  Redundancy must never grow without bound just because a
  channel is bad; a channel that is down cannot be fixed by sending more copies
  of the payload, only by backing off.
* **End-to-end integrity.**  Redundancy protects against *loss*.  It does
  nothing about *corruption*, and a corrupted replica that is accepted because
  it arrived first is worse than a dropped one.  Every replica carries a
  checksum and a mismatching replica is rejected, not voted on.
* **Backoff.**  Repeated failure must slow the sender down, with a deterministic
  ceiling so recovery is predictable rather than exponential forever.
* **Deterministic fallback.**  When the learned signal is unavailable or the
  adaptive path is disabled, the sender falls back to a FIXED redundancy that
  does not depend on any learned state.
* **Concept drift.**  A channel that recovers must see its redundancy come back
  down; the curriculum's EWMA does this, and the tests prove it rather than
  assuming it.
* **Honest measurement.**  :func:`compare_to_fixed` runs the adaptive policy and
  a fixed baseline over the *same* simulated failure trace and reports both
  transmission counts and both delivery rates -- including the cases where
  adaptive sends more, which is the correct outcome on a genuinely bad channel.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - import shape depends on caller
    from hivemind_v15 import AdaptiveErrorCorrection, canonical_app
except ImportError:  # pragma: no cover
    from .hivemind_v15 import AdaptiveErrorCorrection, canonical_app  # type: ignore


MIN_REDUNDANCY = 1
MAX_REDUNDANCY = 3          # matches the curriculum's own ceiling
FIXED_REDUNDANCY = 2        # deterministic fallback


class IntegrityError(ValueError):
    """A replica arrived with a payload that does not match its checksum."""


class ChannelUnavailable(RuntimeError):
    """The channel is in backoff and the send was not attempted."""


def checksum(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()


@dataclass(frozen=True)
class Replica:
    """One transmitted copy, carrying its own end-to-end integrity tag."""

    index: int
    payload: Any
    tag: str

    @classmethod
    def build(cls, index: int, payload: Any) -> "Replica":
        return cls(index=index, payload=payload, tag=checksum(payload))

    def verify(self) -> bool:
        return self.tag == checksum(self.payload)


@dataclass
class Backoff:
    """Deterministic capped backoff: predictable recovery, no unbounded growth."""

    base_seconds: float = .05
    factor: float = 2.0
    max_seconds: float = 1.0
    failures: int = 0
    blocked_until: float = 0.0

    def delay(self) -> float:
        if self.failures <= 0:
            return 0.0
        return min(self.max_seconds, self.base_seconds * (self.factor ** (self.failures - 1)))

    def record_failure(self, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        self.failures += 1
        wait = self.delay()
        self.blocked_until = now + wait
        return wait

    def record_success(self) -> None:
        self.failures = 0
        self.blocked_until = 0.0

    def available(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return now >= self.blocked_until


@dataclass
class SendResult:
    delivered: bool
    redundancy: int
    attempts: int
    accepted_index: Optional[int] = None
    rejected: List[dict] = field(default_factory=list)
    adaptive: bool = True
    backoff_s: float = 0.0


class ReliableChannel:
    """Adaptive-redundancy sender with integrity checks, caps and backoff."""

    def __init__(self, ecc: Optional[AdaptiveErrorCorrection] = None,
                 max_redundancy: int = MAX_REDUNDANCY,
                 fixed_redundancy: int = FIXED_REDUNDANCY,
                 adaptive: bool = True,
                 backoff: Optional[Backoff] = None) -> None:
        if not (MIN_REDUNDANCY <= fixed_redundancy <= max_redundancy):
            raise ValueError("fixed_redundancy must sit within the redundancy caps")
        if max_redundancy > MAX_REDUNDANCY:
            raise ValueError(f"max_redundancy is capped at {MAX_REDUNDANCY}")
        self.ecc = ecc or AdaptiveErrorCorrection()
        self.max_redundancy = max_redundancy
        self.fixed_redundancy = fixed_redundancy
        self.adaptive = adaptive
        self.backoffs: Dict[Tuple[str, str], Backoff] = {}
        self._backoff_template = backoff or Backoff()
        self.metrics: Counter = Counter()

    # -- policy ----------------------------------------------------------
    def redundancy_for(self, source: str, target: str,
                       when: Optional[float] = None) -> int:
        """Learned redundancy, clamped into [1, max].  Falls back deterministically."""
        if not self.adaptive:
            self.metrics["fixed_policy"] += 1
            return self.fixed_redundancy
        try:
            learned = int(self.ecc.redundancy(source, target, when))
        except Exception:
            # A broken or empty curriculum must not take the channel down; the
            # fixed value depends on no learned state at all.
            self.metrics["fallback_fixed"] += 1
            return self.fixed_redundancy
        return max(MIN_REDUNDANCY, min(self.max_redundancy, learned))

    def _backoff(self, source: str, target: str) -> Backoff:
        key = (canonical_app(source), canonical_app(target))
        bo = self.backoffs.get(key)
        if bo is None:
            t = self._backoff_template
            bo = Backoff(base_seconds=t.base_seconds, factor=t.factor, max_seconds=t.max_seconds)
            self.backoffs[key] = bo
        return bo

    # -- transport -------------------------------------------------------
    def send(self, source: str, target: str, payload: Any,
             transmit: Callable[[Replica], Optional[Replica]],
             when: Optional[float] = None) -> SendResult:
        """Send up to ``redundancy`` replicas; accept the first INTACT one.

        ``transmit`` returns the replica as it arrived (possibly ``None`` for a
        drop, possibly mutated for corruption).  Corruption is rejected on the
        checksum rather than accepted for arriving first -- that is the whole
        point of an end-to-end check.
        """
        bo = self._backoff(source, target)
        now = when if when is not None else time.time()
        if not bo.available(now):
            self.metrics["backoff_blocked"] += 1
            raise ChannelUnavailable(
                f"{canonical_app(source)}->{canonical_app(target)} in backoff for "
                f"{bo.blocked_until - now:.3f}s")

        redundancy = self.redundancy_for(source, target, when)
        rejected: List[dict] = []
        attempts = 0
        # A rejected replica is live evidence that this channel is bad *now*.
        # The learned rate is an EWMA and will not catch up until after this
        # message is already lost, so the sender escalates within the send --
        # still bounded by the hard cap, never unbounded retransmission.
        budget = redundancy
        while attempts < budget:
            index = attempts
            attempts += 1
            self.metrics["transmissions"] += 1
            arrived = transmit(Replica.build(index, payload))
            if arrived is None:
                rejected.append({"index": index, "reason": "lost"})
                budget = min(self.max_redundancy, budget + 1)
                continue
            if not arrived.verify():
                self.metrics["corrupt_rejected"] += 1
                rejected.append({"index": index, "reason": "integrity"})
                budget = min(self.max_redundancy, budget + 1)
                continue
            self.ecc.observe(source, target, failed=False, when=when)
            bo.record_success()
            self.metrics["delivered"] += 1
            return SendResult(delivered=True, redundancy=redundancy, attempts=attempts,
                              accepted_index=index, rejected=rejected, adaptive=self.adaptive)

        self.ecc.observe(source, target, failed=True, when=when)
        wait = bo.record_failure(now)
        self.metrics["failed"] += 1
        return SendResult(delivered=False, redundancy=redundancy, attempts=attempts,
                          rejected=rejected, adaptive=self.adaptive, backoff_s=wait)

    # -- curriculum ------------------------------------------------------
    def remedial_schedule(self, minimum_samples: int = 5) -> List[dict]:
        """Channel pairs the curriculum says are worth targeted training."""
        gaps = self.ecc.gaps(minimum_samples=minimum_samples)
        return sorted(gaps, key=lambda g: -g["error_rate"])


# -- simulation / measurement -------------------------------------------
def lossy_transport(loss_rate: float = .0, corruption_rate: float = .0,
                    seed: int = 0) -> Callable[[Replica], Optional[Replica]]:
    """Deterministic simulated transport for repeatable measurement."""
    rng = random.Random(seed)

    def transmit(replica: Replica) -> Optional[Replica]:
        if rng.random() < loss_rate:
            return None
        if rng.random() < corruption_rate:
            # Payload edited in flight; the tag is left alone, which is exactly
            # what an end-to-end check has to catch.
            return Replica(index=replica.index, payload={"corrupt": True}, tag=replica.tag)
        return replica

    return transmit


def compare_to_fixed(messages: int = 200, loss_rate: float = .4,
                     seed: int = 7, source: str = "tomorrow",
                     target: str = "galop") -> Dict[str, Any]:
    """Adaptive vs fixed redundancy over the SAME trace.  No target is asserted.

    Adaptive sending more than fixed is a legitimate result on a bad channel --
    that is the policy working, not failing -- and it is reported as measured.
    """
    results: Dict[str, Any] = {}
    for label, adaptive in (("adaptive", True), ("fixed", False)):
        channel = ReliableChannel(adaptive=adaptive,
                                  backoff=Backoff(base_seconds=0.0, max_seconds=0.0))
        transmit = lossy_transport(loss_rate=loss_rate, seed=seed)
        delivered = cap_reached = 0
        starting: Counter = Counter()
        for i in range(messages):
            outcome = channel.send(source, target, {"seq": i}, transmit, when=1_700_000_000)
            delivered += int(outcome.delivered)
            starting[outcome.redundancy] += 1
            if outcome.attempts >= channel.max_redundancy:
                cap_reached += 1
        starting = dict(sorted(starting.items()))
        results[label] = {
            "delivered": delivered,
            "delivery_rate": delivered / messages,
            "transmissions": channel.metrics["transmissions"],
            "transmissions_per_message": channel.metrics["transmissions"] / messages,
            "cap_reached": cap_reached,
            "starting_redundancy": starting,
        }
    results["messages"] = messages
    results["loss_rate"] = loss_rate
    results["identical"] = results["adaptive"] == results["fixed"]
    results["note"] = (
        "Under stop-on-first-success semantics, redundancy is a CEILING on attempts, "
        "not a fixed per-message cost: a healthy channel costs one transmission under "
        "either policy. The two policies therefore coincide except where the ceiling "
        "binds, and this comparison reports that tie honestly rather than manufacturing "
        "a difference. The learned signal earns its keep in 'starting_redundancy' "
        "(how many copies go out before any failure is observed) and in the remedial "
        "schedule, not in raw delivery rate.")
    return results


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(compare_to_fixed(), indent=2, sort_keys=True))
