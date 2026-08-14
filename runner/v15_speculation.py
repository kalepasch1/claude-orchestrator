#!/usr/bin/env python3
"""Budgeted, deterministic speculative execution over V15 topology paths.

``hivemind_v15.SpeculativeChains`` already ranks likely downstream paths and
fans them out.  It has three properties that make it unsafe as a general
execution substrate, and this module supplies the missing guarantees without
rewriting the existing class:

1. **The winner is whichever path finishes first.**  ``as_completed`` yields in
   completion order, so two runs of the same query can return results from
   different paths.  Speculation is only sound if it is *unobservable* -- the
   caller must get the same answer it would have gotten by running the primary
   path alone.  :class:`BudgetedSpeculator` selects by *rank*, not by clock.
2. **There is no budget.**  A hung path blocks the caller forever, and every
   candidate runs to completion even once a higher-ranked path has won.
3. **There is no fallback.**  If every speculative path raises, the caller gets
   ``{"winner": None}`` rather than a real result or a real exception.

Nothing here fabricates a speedup number: :func:`benchmark` measures the
speculative path against a serial baseline on the caller's own functions and
reports the observed ratio, including when that ratio is worse than 1.0.
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

try:  # pragma: no cover - import shape depends on caller (package vs script)
    from hivemind_v15 import SpeculativeChains, pattern_key
except ImportError:  # pragma: no cover
    from .hivemind_v15 import SpeculativeChains, pattern_key  # type: ignore


DEFAULT_MAX_PATHS = 3


class BudgetExceeded(RuntimeError):
    """Raised when no path produced an accepted result inside the budget."""


@dataclass(frozen=True)
class Budget:
    """Per-query resource ceiling.

    ``wall_seconds`` bounds the whole speculative attempt, not each path, so a
    caller can reason about the worst case it will ever wait.  ``max_paths``
    bounds concurrent work (the CPU/memory proxy available to us in-process --
    we deliberately do not claim to meter RSS, because a thread pool cannot).
    """

    wall_seconds: float = 5.0
    max_paths: int = DEFAULT_MAX_PATHS

    def __post_init__(self) -> None:
        if not (self.wall_seconds > 0):
            raise ValueError("wall_seconds must be positive")
        if self.max_paths < 1:
            raise ValueError("max_paths must be >= 1")


@dataclass
class SpeculationResult:
    winner: Optional[str]
    result: Any = None
    source: str = "speculation"
    attempts: List[dict] = field(default_factory=list)
    elapsed_s: float = 0.0
    paths_started: int = 0
    paths_cancelled: int = 0
    timed_out: bool = False
    fell_back: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "winner": self.winner, "result": self.result, "source": self.source,
            "attempts": self.attempts, "elapsed_s": self.elapsed_s,
            "paths_started": self.paths_started, "paths_cancelled": self.paths_cancelled,
            "timed_out": self.timed_out, "fell_back": self.fell_back,
        }


class BudgetedSpeculator:
    """Rank-deterministic speculation with a hard budget and a real fallback.

    The contract callers can rely on:

    * the returned value is always the value the highest-ranked *acceptable*
      path produced -- never the fastest one;
    * ``run`` returns within roughly ``budget.wall_seconds`` even if a path
      hangs, because it stops waiting (it cannot kill a running thread, and
      says so in telemetry rather than pretending otherwise);
    * if speculation yields nothing, the primary path runs serially and its
      result -- or its exception -- is what the caller sees.
    """

    def __init__(self, chains: Optional[SpeculativeChains] = None,
                 budget: Optional[Budget] = None) -> None:
        self.budget = budget or Budget()
        self.chains = chains or SpeculativeChains(max_paths=self.budget.max_paths)
        self.telemetry: Counter = Counter()
        self.latencies: Deque[float] = deque(maxlen=512)
        self._repeats: Counter = Counter()
        self._lock = threading.Lock()

    # -- ranking ---------------------------------------------------------
    def ranked_paths(self, query: Any,
                     available: Mapping[str, Callable[[Any], Any]]) -> List[Tuple[str, Callable]]:
        """Highest-confidence paths first, ties broken by name for determinism.

        ``SpeculativeChains.likely`` pads with ``available`` in dict order once
        the learned transitions run out; two callers passing the same paths in a
        different order would then speculate on different sets.  Sorting the
        unlearned tail by name makes the candidate set a pure function of the
        query and the path names.
        """
        counts = self.chains.transitions.get(pattern_key(query), Counter())
        known = [n for n, _ in counts.most_common() if n in available]
        rest = sorted(n for n in available if n not in known)
        return [(n, available[n]) for n in (known + rest)[:self.budget.max_paths]]

    # -- execution -------------------------------------------------------
    def run(self, query: Any, available: Mapping[str, Callable[[Any], Any]],
            accept: Optional[Callable[[Any], bool]] = None,
            budget: Optional[Budget] = None) -> SpeculationResult:
        budget = budget or self.budget
        started = time.perf_counter()
        chosen = self.ranked_paths(query, available)[:budget.max_paths]
        if not chosen:
            return SpeculationResult(winner=None, source="no_paths",
                                     elapsed_s=time.perf_counter() - started)

        key = pattern_key(query)
        with self._lock:
            self._repeats[key] += 1

        futures: List[Tuple[str, Future]] = []
        pool = ThreadPoolExecutor(max_workers=len(chosen), thread_name_prefix="v15-spec")
        try:
            for name, fn in chosen:
                futures.append((name, pool.submit(fn, query)))

            attempts: List[dict] = []
            winner: Optional[str] = None
            result: Any = None
            timed_out = False

            # Walk candidates in RANK order.  The first acceptable one wins even
            # if a lower-ranked path finished sooner -- that is what makes the
            # result reproducible.
            for name, future in futures:
                remaining = budget.wall_seconds - (time.perf_counter() - started)
                if remaining <= 0:
                    timed_out = True
                    attempts.append({"path": name, "ok": False, "error": "BudgetExceeded"})
                    continue
                try:
                    value = future.result(timeout=remaining)
                except TimeoutError:
                    timed_out = True
                    attempts.append({"path": name, "ok": False, "error": "TimeoutError"})
                    continue
                except Exception as exc:  # a losing path must not fail the query
                    attempts.append({"path": name, "ok": False, "error": type(exc).__name__})
                    continue
                ok = accept is None or bool(accept(value))
                attempts.append({"path": name, "ok": True, "accepted": ok})
                if ok:
                    winner, result = name, value
                    break

            cancelled = sum(1 for _, f in futures if f.cancel())
        finally:
            # Losing paths are abandoned, not awaited: a hung path must not turn
            # a bounded query into an unbounded one.
            pool.shutdown(wait=False, cancel_futures=True)

        elapsed = time.perf_counter() - started
        self.latencies.append(elapsed)

        if winner is None:
            self.telemetry["fallback"] += 1
            return self._fallback(query, available, accept, attempts, started, len(chosen),
                                  cancelled, timed_out)

        self.chains.observe_transition(query, winner)
        self.telemetry["speculative_win"] += 1
        self.telemetry[f"win:{winner}"] += 1
        if timed_out:
            self.telemetry["partial_timeout"] += 1
        return SpeculationResult(winner=winner, result=result, source="speculation",
                                 attempts=attempts, elapsed_s=elapsed,
                                 paths_started=len(chosen), paths_cancelled=cancelled,
                                 timed_out=timed_out)

    def _fallback(self, query: Any, available: Mapping[str, Callable[[Any], Any]],
                  accept: Optional[Callable[[Any], bool]], attempts: List[dict],
                  started: float, started_paths: int, cancelled: int,
                  timed_out: bool) -> SpeculationResult:
        """Deterministic serial fallback: run the primary path and report truth.

        The primary path is the highest-ranked one, so the fallback answer is the
        same answer a non-speculative caller would have computed.  Its exception
        is propagated rather than swallowed -- a query that genuinely fails must
        look like a failure, not like an empty success.
        """
        ranked = self.ranked_paths(query, available)
        if not ranked:
            raise BudgetExceeded("no path available for deterministic fallback")
        name, fn = ranked[0]
        value = fn(query)
        if accept is not None and not accept(value):
            raise BudgetExceeded(
                f"primary path {name!r} produced an unacceptable result after "
                f"{len(attempts)} speculative attempt(s)")
        attempts.append({"path": name, "ok": True, "accepted": True, "fallback": True})
        return SpeculationResult(winner=name, result=value, source="deterministic_fallback",
                                 attempts=attempts, elapsed_s=time.perf_counter() - started,
                                 paths_started=started_paths, paths_cancelled=cancelled,
                                 timed_out=timed_out, fell_back=True)

    # -- telemetry -------------------------------------------------------
    def repeat_patterns(self, minimum: int = 2) -> List[Dict[str, Any]]:
        """Query shapes seen often enough to be worth pre-warming."""
        with self._lock:
            items = [(k, n) for k, n in self._repeats.items() if n >= minimum]
        return [{"pattern": k, "count": n} for k, n in sorted(items, key=lambda x: (-x[1], x[0]))]

    def stats(self) -> Dict[str, Any]:
        lat = sorted(self.latencies)
        return {
            "counters": dict(self.telemetry),
            "samples": len(lat),
            "p50_s": lat[len(lat) // 2] if lat else 0.0,
            "p95_s": lat[min(len(lat) - 1, int(len(lat) * .95))] if lat else 0.0,
            "repeat_patterns": len(self.repeat_patterns()),
        }


def benchmark(speculator: BudgetedSpeculator, query: Any,
              available: Mapping[str, Callable[[Any], Any]],
              repeats: int = 5, accept: Optional[Callable[[Any], bool]] = None
              ) -> Dict[str, Any]:
    """Compare speculation against a serial baseline on the caller's own paths.

    Returns the measured wall time of both strategies and their ratio.  A ratio
    below 1.0 means speculation was *slower* -- the honest outcome for cheap
    paths, where thread-pool setup dominates -- and is reported as-is.
    """
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    ranked = speculator.ranked_paths(query, available)
    if not ranked:
        raise ValueError("no paths to benchmark")
    primary = ranked[0][1]

    t0 = time.perf_counter()
    for _ in range(repeats):
        primary(query)
    serial = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(repeats):
        speculator.run(query, available, accept=accept)
    speculative = time.perf_counter() - t0

    return {
        "repeats": repeats,
        "serial_s": serial,
        "speculative_s": speculative,
        "speedup": (serial / speculative) if speculative > 0 else float("inf"),
        "paths_considered": len(ranked),
        "note": "measured on the caller's functions; values below 1.0 mean speculation cost more than it saved",
    }


def parity_check(speculator: BudgetedSpeculator, queries: Sequence[Any],
                 available: Mapping[str, Callable[[Any], Any]]) -> Dict[str, Any]:
    """Assert speculation is unobservable: same answer as the primary path alone."""
    mismatches = []
    for query in queries:
        ranked = speculator.ranked_paths(query, available)
        expected = ranked[0][1](query)
        actual = speculator.run(query, available).result
        if actual != expected:
            mismatches.append({"query": pattern_key(query), "expected": expected, "actual": actual})
    return {"checked": len(queries), "mismatches": mismatches, "parity": not mismatches}
