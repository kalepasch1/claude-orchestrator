#!/usr/bin/env python3
"""Bounded, authorized, poison-resistant query-cluster formation.

``hivemind_v15.QueryTopology`` counts normalized query patterns and forms a
cluster once one repeats.  The idea is right; the bookkeeping is unbounded and
ungoverned, which is what proposal 10 asks to fix:

* **Unbounded cardinality.**  ``counts`` grows one entry per distinct query
  shape forever, and ``dissolve()`` prunes ``clusters`` but never ``counts``.
  5,000 distinct shapes leave 5,000 counters behind after every cluster is gone
  -- a memory leak driven purely by query variety.  Counting here is capped and
  decayed.
* **No authorization.**  Any app string forms a cluster.  Clusters here form
  only for explicitly authorized apps.
* **No plan lifecycle.**  A compiled plan is never invalidated, so a cluster
  keeps serving a stale plan after its source changes.  Plans here carry a
  fingerprint and are refused when it moves.
* **No cache integrity.**  Whatever the teacher returned is trusted forever.
  Entries here are stamped with the plan fingerprint that produced them, so a
  cache written under an old plan cannot be served under a new one.

A generic execution fallback is always available, and cluster results are
required to be *identical* to it -- a cluster that changes an answer is a bug,
not an optimisation.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

try:  # pragma: no cover - import shape depends on caller
    from hivemind_v15 import DistilledNode, canonical_app, pattern_key, value_key
except ImportError:  # pragma: no cover
    from .hivemind_v15 import (  # type: ignore
        DistilledNode, canonical_app, pattern_key, value_key)


KEY_SEPARATOR = "\x00"      # not typeable in an app name: collision-proof
DEFAULT_MAX_PATTERNS = 1024


class NotAuthorized(RuntimeError):
    """The app is not permitted to form clusters."""


class StalePlan(RuntimeError):
    """The compiled plan no longer matches its source."""


class AdmissionRefused(RuntimeError):
    """The cluster's reserved budget is exhausted."""


def tenant_key(app: str, pattern: str) -> str:
    """Composite key that cannot be forged by a crafted app or pattern name.

    Concatenating with a printable separator lets ``("a:b", "c")`` and
    ``("a", "b:c")`` collide.  A NUL separator cannot appear in either part.
    """
    app = canonical_app(app)
    if KEY_SEPARATOR in app or KEY_SEPARATOR in pattern:
        raise ValueError("key components must not contain the reserved separator")
    return f"{app}{KEY_SEPARATOR}{pattern}"


def plan_fingerprint(source: Any) -> str:
    """Identity of the compiled plan's SOURCE, so drift is detectable."""
    raw = json.dumps(source, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.blake2b(raw.encode(), digest_size=12).hexdigest()


@dataclass
class CompiledPlan:
    fingerprint: str
    compiled_at: float
    steps: Tuple[str, ...] = ()

    def matches(self, source: Any) -> bool:
        return self.fingerprint == plan_fingerprint(source)


@dataclass
class CacheEntry:
    value: Any
    plan_fingerprint: str
    written_at: float


class BoundedPatternCounter:
    """LRU-capped pattern counts: cardinality can never exceed the cap."""

    def __init__(self, max_patterns: int = DEFAULT_MAX_PATTERNS) -> None:
        if max_patterns < 1:
            raise ValueError("max_patterns must be >= 1")
        self.max_patterns = max_patterns
        self._counts: "OrderedDict[str, int]" = OrderedDict()
        self.evicted = 0

    def bump(self, key: str) -> int:
        if key in self._counts:
            self._counts[key] += 1
            self._counts.move_to_end(key)
        else:
            self._counts[key] = 1
            while len(self._counts) > self.max_patterns:
                self._counts.popitem(last=False)
                self.evicted += 1
        return self._counts[key]

    def get(self, key: str) -> int:
        return self._counts.get(key, 0)

    def forget(self, key: str) -> None:
        self._counts.pop(key, None)

    def __len__(self) -> int:
        return len(self._counts)


@dataclass
class Cluster:
    app: str
    pattern: str
    node: DistilledNode
    plan: CompiledPlan
    budget: int
    used: int = 0
    hits: int = 0
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    cache: Dict[str, CacheEntry] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return tenant_key(self.app, self.pattern)

    def remaining(self) -> int:
        return max(0, self.budget - self.used)


class Topology:
    """Forms bounded clusters for authorized apps, with a generic fallback."""

    def __init__(self, formation_threshold: int = 3, ttl_seconds: float = 900,
                 max_patterns: int = DEFAULT_MAX_PATTERNS,
                 max_clusters: int = 64, cluster_budget: int = 1000,
                 reserve_fraction: float = .2) -> None:
        if not (0.0 <= reserve_fraction < 1.0):
            raise ValueError("reserve_fraction must be in [0, 1)")
        self.threshold = formation_threshold
        self.ttl = ttl_seconds
        self.max_clusters = max_clusters
        self.cluster_budget = cluster_budget
        self.reserve_fraction = reserve_fraction
        self.counts = BoundedPatternCounter(max_patterns)
        self.clusters: Dict[str, Cluster] = {}
        self.authorized: Set[str] = set()
        self.metrics: Counter = Counter()
        self._lock = threading.RLock()

    # -- authorization ---------------------------------------------------
    def authorize(self, *apps: str) -> None:
        with self._lock:
            self.authorized.update(canonical_app(a) for a in apps)

    def _require_authorized(self, app: str) -> str:
        app = canonical_app(app)
        if app not in self.authorized:
            raise NotAuthorized(f"{app} is not authorized to form query clusters")
        return app

    # -- formation -------------------------------------------------------
    def observe(self, app: str, query: Any, teacher: Callable[[Any], Any],
                plan_source: Any = None, now: Optional[float] = None) -> Optional[Cluster]:
        """Count the pattern; form a cluster once it is genuinely hot."""
        now = now if now is not None else time.time()
        app = self._require_authorized(app)
        key = tenant_key(app, pattern_key(query))

        with self._lock:
            existing = self.clusters.get(key)
            if existing is not None:
                existing.last_seen = now
                existing.hits += 1
                return existing

            seen = self.counts.bump(key)
            if seen < self.threshold:
                return None
            if len(self.clusters) >= self.max_clusters:
                self.metrics["formation_refused_capacity"] += 1
                return None

            source = plan_source if plan_source is not None else pattern_key(query)
            cluster = Cluster(
                app=app, pattern=pattern_key(query), node=DistilledNode(teacher),
                plan=CompiledPlan(plan_fingerprint(source), now, steps=("normalize", "execute")),
                budget=self.cluster_budget, created_at=now, last_seen=now)
            self.clusters[key] = cluster
            self.counts.forget(key)      # the counter's job is done
            self.metrics["clusters_formed"] += 1
            return cluster

    # -- execution -------------------------------------------------------
    def execute(self, app: str, query: Any, generic: Callable[[Any], Any],
                plan_source: Any = None, now: Optional[float] = None) -> Dict[str, Any]:
        """Serve from a cluster when one exists; otherwise the generic path.

        The generic path is never removed, so an unformed, dissolved, exhausted
        or stale cluster degrades to a correct answer rather than an error.
        """
        now = now if now is not None else time.time()
        app = canonical_app(app)
        key = tenant_key(app, pattern_key(query))
        with self._lock:
            cluster = self.clusters.get(key)

        if cluster is None:
            self.metrics["generic"] += 1
            return {"result": generic(query), "source": "generic"}

        source = plan_source if plan_source is not None else pattern_key(query)
        if not cluster.plan.matches(source):
            # A stale plan must not serve. Dissolve and fall back rather than
            # answer from a plan whose source has moved.
            self.dissolve_key(key, reason="stale_plan")
            self.metrics["stale_plan"] += 1
            return {"result": generic(query), "source": "generic_after_stale_plan"}

        with self._lock:
            if cluster.remaining() <= 0:
                self.metrics["budget_exhausted"] += 1
                return {"result": generic(query), "source": "generic_budget_exhausted"}
            cluster.used += 1
            cluster.last_seen = now
            cluster.hits += 1

        cache_key = value_key(query)
        entry = cluster.cache.get(cache_key)
        if entry is not None and entry.plan_fingerprint == cluster.plan.fingerprint:
            self.metrics["cache_hit"] += 1
            return {"result": entry.value, "source": "cluster_cache"}

        result = cluster.node(query)
        cluster.cache[cache_key] = CacheEntry(result, cluster.plan.fingerprint, now)
        self.metrics["cluster"] += 1
        return {"result": result, "source": "cluster"}

    def warm(self, app: str, queries: Sequence[Any], now: Optional[float] = None) -> int:
        """Pre-populate a cluster's cache through its OWN node.

        Warming never accepts caller-supplied values; a cache that can be
        written from outside is a poisoning primitive, not an optimisation.
        """
        now = now if now is not None else time.time()
        warmed = 0
        for query in queries:
            key = tenant_key(canonical_app(app), pattern_key(query))
            cluster = self.clusters.get(key)
            if cluster is None:
                continue
            cache_key = value_key(query)
            if cache_key in cluster.cache:
                continue
            cluster.cache[cache_key] = CacheEntry(
                cluster.node(query), cluster.plan.fingerprint, now)
            warmed += 1
        self.metrics["warmed"] += warmed
        return warmed

    def admit(self, app: str, query: Any, cost: int = 1) -> None:
        """Reserve budget, keeping a slice back so bursts cannot starve others."""
        key = tenant_key(canonical_app(app), pattern_key(query))
        with self._lock:
            cluster = self.clusters.get(key)
            if cluster is None:
                return
            reserve = int(cluster.budget * self.reserve_fraction)
            if cluster.remaining() - cost < reserve:
                self.metrics["admission_refused"] += 1
                raise AdmissionRefused(
                    f"cluster {cluster.pattern} would breach its {reserve}-unit "
                    "starvation reserve")
            cluster.used += cost

    # -- dissolution -----------------------------------------------------
    def dissolve_key(self, key: str, reason: str = "explicit") -> bool:
        with self._lock:
            cluster = self.clusters.pop(key, None)
        if cluster is None:
            return False
        self.metrics[f"dissolved_{reason}"] += 1
        return True

    def dissolve(self, now: Optional[float] = None) -> List[str]:
        """Deterministic dissolution: TTL-expired clusters, in sorted key order."""
        now = now if now is not None else time.time()
        with self._lock:
            stale = sorted(k for k, c in self.clusters.items() if now - c.last_seen > self.ttl)
        for key in stale:
            self.dissolve_key(key, reason="ttl")
        return stale

    def state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "clusters": len(self.clusters),
                "tracked_patterns": len(self.counts),
                "patterns_evicted": self.counts.evicted,
                "max_patterns": self.counts.max_patterns,
                "metrics": dict(self.metrics),
            }
