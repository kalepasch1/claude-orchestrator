#!/usr/bin/env python3
"""Fleet-wide adaptive execution and memory runtime.

This module implements the ten V15 proposals as composable, standard-library
primitives.  It intentionally treats the advertised multipliers as benchmark
targets: callers get telemetry from real executions instead of fabricated
speedup claims.  All state is process-local and bounded; persistence adapters
may snapshot ``maintenance()`` output to the fleet database.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import struct
import threading
import time
from collections import Counter, OrderedDict, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


FLEET_APPS: Tuple[str, ...] = (
    "galop", "tomorrow", "smarter", "pareto", "apparently",
    "orchestrator", "vigil", "hisanta", "predictions", "trojun",
)


def canonical_app(value: str) -> str:
    value = (value or "orchestrator").strip().lower()
    aliases = {"beethoven": "orchestrator", "claude-orchestrator": "orchestrator",
               "racefeed": "galop", "pareto-2080": "pareto", "2080": "pareto",
               "santas-secret-workshop": "hisanta", "illuminati": "trojun"}
    value = aliases.get(value, value)
    return value if value in FLEET_APPS else "orchestrator"


def pattern_key(query: Any) -> str:
    """Stable, privacy-preserving pattern key; raw query text is never retained."""
    if isinstance(query, Mapping):
        shape = sorted((str(k), type(v).__name__) for k, v in query.items())
    else:
        words = str(query).lower().split()
        shape = ["#" if w.replace(".", "", 1).isdigit() else w for w in words[:24]]
    return hashlib.blake2b(json.dumps(shape, sort_keys=True).encode(), digest_size=12).hexdigest()


def value_key(value: Any) -> str:
    """Stable content key for exact replay (unlike the structural pattern key)."""
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()


class FractalEncoder:
    """Haar-like multi-scale decomposition retaining dominant coefficients."""

    def __init__(self, scales: int = 6, keep_per_scale: int = 4):
        self.scales = max(1, scales)
        self.keep_per_scale = max(1, keep_per_scale)

    @staticmethod
    def vector(value: Any, dimensions: int = 64) -> List[float]:
        if isinstance(value, (list, tuple)) and all(isinstance(x, (int, float)) for x in value):
            vals = [float(x) for x in value]
            return (vals + [0.0] * dimensions)[:dimensions]
        raw = json.dumps(value, sort_keys=True, default=str).encode()
        out = [0.0] * dimensions
        for i in range(0, len(raw), 2):
            token = raw[i:i + 2]
            h = int.from_bytes(hashlib.blake2b(token, digest_size=4).digest(), "big")
            out[h % dimensions] += -1.0 if h & 1 else 1.0
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]

    def encode(self, value: Any) -> Tuple[Tuple[int, int, float], ...]:
        current = self.vector(value)
        result: List[Tuple[int, int, float]] = []
        for scale in range(self.scales):
            if len(current) < 2:
                break
            approx, detail = [], []
            for i in range(0, len(current) - 1, 2):
                approx.append((current[i] + current[i + 1]) / 2.0)
                detail.append((current[i] - current[i + 1]) / 2.0)
            dominant = sorted(enumerate(detail), key=lambda x: abs(x[1]), reverse=True)[:self.keep_per_scale]
            result.extend((scale, idx, round(coef, 5)) for idx, coef in dominant if coef)
            current = approx
        return tuple(result)

    @staticmethod
    def similarity(a: Sequence[Tuple[int, int, float]], b: Sequence[Tuple[int, int, float]]) -> float:
        da = {(s, i): v for s, i, v in a}; db = {(s, i): v for s, i, v in b}
        keys = da.keys() | db.keys()
        dot = sum(da.get(k, 0.0) * db.get(k, 0.0) for k in keys)
        na = math.sqrt(sum(v * v for v in da.values())) or 1.0
        nb = math.sqrt(sum(v * v for v in db.values())) or 1.0
        return dot / (na * nb)

    @staticmethod
    def lsh_key(coefficients: Sequence[Tuple[int, int, float]]) -> str:
        signs = [(s, i, 1 if v >= 0 else -1) for s, i, v in coefficients[:16]]
        return hashlib.blake2b(repr(signs).encode(), digest_size=8).hexdigest()


@dataclass
class MemoryHit:
    app: str
    value: Any
    similarity: float
    key: str
    exact: bool = False


class HolographicMemory:
    """Bounded fractal-key memory with average O(1) LSH bucket lookup."""

    def __init__(self, capacity: int = 4096, encoder: Optional[FractalEncoder] = None):
        self.capacity = capacity
        self.encoder = encoder or FractalEncoder()
        self._items: "OrderedDict[str, Tuple[str, tuple, str, Any, float]]" = OrderedDict()
        self._buckets: Dict[str, set] = defaultdict(set)
        self._lock = threading.RLock()

    def put(self, app: str, signal: Any, value: Any) -> str:
        coefficients = self.encoder.encode(signal)
        bucket = self.encoder.lsh_key(coefficients)
        key = hashlib.blake2b((canonical_app(app) + repr(coefficients)).encode(), digest_size=12).hexdigest()
        with self._lock:
            if key in self._items:
                self._buckets[self._items[key][0]].discard(key)
            self._items[key] = (bucket, coefficients, value_key(signal), value, time.time())
            self._items.move_to_end(key)
            self._buckets[bucket].add(key)
            while len(self._items) > self.capacity:
                old_key, (old_bucket, _, _, _, _) = self._items.popitem(last=False)
                self._buckets[old_bucket].discard(old_key)
        return key

    def get(self, app: str, signal: Any, threshold: float = 0.55) -> Optional[MemoryHit]:
        coefficients = self.encoder.encode(signal)
        bucket = self.encoder.lsh_key(coefficients)
        with self._lock:
            candidates = list(self._buckets.get(bucket, ()))
            # Exact-key miss fallback stays bounded, avoiding an O(n) full scan.
            if not candidates:
                candidates = list(self._items.keys())[-min(32, len(self._items)):]
            scored = [(self.encoder.similarity(coefficients, self._items[k][1]), k) for k in candidates]
            if not scored:
                return None
            score, key = max(scored)
            if score < threshold:
                return None
            _, _, stored_signal, value, _ = self._items[key]
            self._items.move_to_end(key)
            return MemoryHit(canonical_app(app), value, score, key, stored_signal == value_key(signal))

    def consolidate(self) -> Dict[str, int]:
        """Sleep-cycle re-encoding: remove near-duplicate entries in each bucket."""
        removed = 0
        with self._lock:
            for bucket, keys in list(self._buckets.items()):
                ordered = sorted(keys, key=lambda k: self._items[k][4], reverse=True)
                keep: List[str] = []
                for key in ordered:
                    coeff = self._items[key][1]
                    if any(self.encoder.similarity(coeff, self._items[k][1]) > .985 for k in keep):
                        self._items.pop(key, None); keys.discard(key); removed += 1
                    else:
                        keep.append(key)
        return {"retained": len(self._items), "removed": removed}


class ZeroCopyFederation:
    """In-process ring of packed fractal vectors exposed as memoryviews.

    A deployment adapter can back this buffer with POSIX shared memory.  The API
    deliberately returns views, so readers do not deserialize or copy payloads.
    """

    SLOT = 512

    def __init__(self, memory: HolographicMemory, slots: int = 128):
        self.memory = memory; self.slots = slots
        self._ring = bytearray(self.SLOT * slots); self._cursor = 0
        self._lock = threading.Lock()

    def publish_key(self, coefficients: Sequence[Tuple[int, int, float]]) -> memoryview:
        payload = json.dumps(coefficients, separators=(",", ":")).encode()[:self.SLOT - 4]
        with self._lock:
            slot = self._cursor % self.slots; self._cursor += 1
            start = slot * self.SLOT
            struct.pack_into("!I", self._ring, start, len(payload))
            self._ring[start + 4:start + 4 + len(payload)] = payload
            return memoryview(self._ring)[start:start + 4 + len(payload)].toreadonly()

    def query(self, requesting_app: str, signal: Any) -> Tuple[Optional[MemoryHit], memoryview]:
        coeff = self.memory.encoder.encode(signal)
        return self.memory.get(requesting_app, signal), self.publish_key(coeff)


@dataclass
class MetabolicState:
    load: float = 0.0
    capacity: float = 0.0
    awake: bool = False
    last_spike: float = 0.0


class SpikeBudget:
    """Significance-triggered attention with metabolic wake/sleep control."""

    def __init__(self, threshold: float = .6, decay: float = .85, max_budget: float = 1.0):
        self.threshold = threshold; self.decay = decay; self.max_budget = max_budget
        self.states: Dict[str, MetabolicState] = defaultdict(MetabolicState)
        self.spikes = 0; self.suppressed = 0

    def signal(self, module: str, significance: float, demand: float = 1.0) -> float:
        state = self.states[module]
        state.load = self.decay * state.load + (1 - self.decay) * max(0.0, demand)
        if significance < self.threshold or state.load < .05:
            state.awake = False; state.capacity = 0.0; self.suppressed += 1
            return 0.0
        state.awake = True
        state.capacity = min(1.0, max(.1, state.load))
        state.last_spike = time.time(); self.spikes += 1
        return min(self.max_budget, significance * state.capacity)

    def rest_idle(self, idle_seconds: float = 60.0) -> int:
        now = time.time(); rested = 0
        for state in self.states.values():
            if state.awake and now - state.last_spike > idle_seconds:
                state.awake = False; state.capacity = 0.0; rested += 1
        return rested


class AdaptiveErrorCorrection:
    """Time-bucketed curriculum for predictive channel redundancy."""

    def __init__(self, alpha: float = .2):
        self.alpha = alpha
        self.error_rate: Dict[Tuple[str, str, int], float] = defaultdict(float)
        self.samples: Counter = Counter()

    @staticmethod
    def _key(source: str, target: str, when: Optional[float] = None) -> Tuple[str, str, int]:
        return canonical_app(source), canonical_app(target), time.localtime(when or time.time()).tm_hour // 4

    def observe(self, source: str, target: str, failed: bool, when: Optional[float] = None) -> None:
        key = self._key(source, target, when); old = self.error_rate[key]
        self.error_rate[key] = self.alpha * float(failed) + (1 - self.alpha) * old
        self.samples[key] += 1

    def redundancy(self, source: str, target: str, when: Optional[float] = None) -> int:
        key = self._key(source, target, when); rate = self.error_rate[key]
        return 3 if rate >= .2 else 2 if rate >= .05 else 1

    def gaps(self, minimum_samples: int = 5) -> List[dict]:
        return [{"source": k[0], "target": k[1], "time_bucket": k[2], "error_rate": self.error_rate[k]}
                for k, n in self.samples.items() if n >= minimum_samples and self.error_rate[k] >= .05]


class FractalCausalGraph:
    """Multi-scale lagged correlation graph for bounded temporal prediction."""

    def __init__(self, scales: Sequence[int] = (1, 4, 16, 64), history: int = 512):
        self.scales = tuple(scales); self.history = history
        self.series: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=history))

    def observe(self, values: Mapping[str, float]) -> None:
        for name, value in values.items(): self.series[name].append(float(value))

    def predict(self, target: str, drivers: Iterable[str]) -> Dict[str, Any]:
        target_values = list(self.series[target]); contributions = []
        for driver in drivers:
            values = list(self.series[driver])
            for scale in self.scales:
                n = min(len(target_values), len(values))
                if n <= scale + 2: continue
                xs = values[-n:-scale]; ys = target_values[-n + scale:]
                mx = sum(xs) / len(xs); my = sum(ys) / len(ys)
                denom = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys)) or 1.0
                corr = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / denom
                contributions.append({"driver": driver, "scale": scale, "correlation": corr})
        contributions.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        delta = 0.0
        for item in contributions[:3]:
            d = list(self.series[item["driver"]])
            if len(d) > item["scale"]:
                delta += item["correlation"] * (d[-1] - d[-1-item["scale"]]) / 3
        return {"target": target, "prediction": (target_values[-1] if target_values else 0) + delta,
                "causes": contributions[:10]}


class AdversarialAnomalyCurriculum:
    """Promotes increasingly subtle synthetic anomalies after mastery."""

    def __init__(self, seed: int = 0):
        self.level = 1; self.rng = random.Random(seed); self.outcomes: Deque[bool] = deque(maxlen=32)

    def generate(self, sample: Sequence[float], count: int = 8) -> List[List[float]]:
        severity = max(.02, .8 / self.level); batch = []
        for _ in range(count):
            row = list(map(float, sample))
            if not row: batch.append(row); continue
            idx = self.rng.randrange(len(row))
            mode = self.level % 3
            if mode == 1: row[idx] += self.rng.choice((-1, 1)) * severity * (abs(row[idx]) + 1)
            elif mode == 2: row[idx] *= 1 + self.rng.choice((-severity, severity))
            else: row[max(0, idx-1):idx+1] = reversed(row[max(0, idx-1):idx+1])
            batch.append(row)
        return batch

    def record(self, detected: bool) -> int:
        self.outcomes.append(bool(detected))
        if len(self.outcomes) >= 16 and sum(self.outcomes) / len(self.outcomes) >= .85:
            self.level += 1; self.outcomes.clear()
        return self.level


class DistilledNode:
    """Safe topology distillation: exact replay cache with teacher fallback."""

    def __init__(self, teacher: Callable[[Any], Any], capacity: int = 256):
        self.teacher = teacher; self.capacity = capacity; self.examples: OrderedDict[str, Any] = OrderedDict()

    def __call__(self, value: Any) -> Any:
        key = value_key(value)
        if key in self.examples: self.examples.move_to_end(key); return self.examples[key]
        result = self.teacher(value); self.examples[key] = result
        if len(self.examples) > self.capacity: self.examples.popitem(last=False)
        return result

    @property
    def compression(self) -> Dict[str, Any]:
        return {"kind": "exact-replay-with-teacher-fallback", "cached_patterns": len(self.examples)}


@dataclass
class QueryCluster:
    app: str
    pattern: str
    node: DistilledNode
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    hits: int = 0


class QueryTopology:
    """Forms and dissolves ephemeral compiled query clusters."""

    def __init__(self, formation_threshold: int = 3, ttl_seconds: float = 900):
        self.threshold = formation_threshold; self.ttl = ttl_seconds
        self.counts: Counter = Counter(); self.clusters: Dict[Tuple[str, str], QueryCluster] = {}

    def observe(self, app: str, query: Any, teacher: Callable[[Any], Any]) -> Optional[QueryCluster]:
        key = (canonical_app(app), pattern_key(query)); self.counts[key] += 1
        cluster = self.clusters.get(key)
        if cluster:
            cluster.last_seen = time.time(); cluster.hits += 1; return cluster
        if self.counts[key] >= self.threshold:
            cluster = QueryCluster(key[0], key[1], DistilledNode(teacher)); self.clusters[key] = cluster
            return cluster
        return None

    def dissolve(self, now: Optional[float] = None) -> int:
        now = now or time.time(); stale = [k for k, c in self.clusters.items() if now-c.last_seen > self.ttl]
        for key in stale: self.clusters.pop(key, None)
        return len(stale)


class SpeculativeChains:
    """Two-tier speculative execution: predicted topology paths, then path-local work."""

    def __init__(self, max_paths: int = 3):
        self.max_paths = max_paths; self.transitions: Dict[str, Counter] = defaultdict(Counter)
        self.latencies: Deque[float] = deque(maxlen=512)

    def observe_transition(self, query: Any, path_name: str) -> None:
        self.transitions[pattern_key(query)][path_name] += 1

    def likely(self, query: Any, available: Mapping[str, Callable[[Any], Any]]) -> List[Tuple[str, Callable]]:
        ranked = [name for name, _ in self.transitions[pattern_key(query)].most_common() if name in available]
        ranked.extend(name for name in available if name not in ranked)
        return [(name, available[name]) for name in ranked[:self.max_paths]]

    def execute(self, query: Any, available: Mapping[str, Callable[[Any], Any]],
                accept: Optional[Callable[[Any], bool]] = None) -> Dict[str, Any]:
        started = time.perf_counter(); chosen = self.likely(query, available)
        if not chosen: return {"winner": None, "result": None, "attempts": []}
        attempts = []; winner = result = None
        pool = ThreadPoolExecutor(max_workers=len(chosen), thread_name_prefix="topology-spec")
        try:
            futures = {pool.submit(self._execute_path, fn, query): name for name, fn in chosen}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    value = future.result(); attempts.append({"path": name, "ok": True})
                    if winner is None and (accept is None or accept(value)):
                        winner, result = name, value
                        for other in futures: other.cancel()
                        break
                except Exception as exc:
                    attempts.append({"path": name, "ok": False, "error": type(exc).__name__})
        finally:
            # Do not wait for losing paths; cancellation is best-effort for work
            # that has already started.
            pool.shutdown(wait=False, cancel_futures=True)
        elapsed = time.perf_counter() - started; self.latencies.append(elapsed)
        if winner: self.observe_transition(query, winner)
        return {"winner": winner, "result": result, "attempts": attempts, "elapsed_s": elapsed}

    @staticmethod
    def _execute_path(fn: Callable[[Any], Any], query: Any) -> Any:
        """Run a coarse path and hand candidate lists to the V12 fine executor."""
        value = fn(query)
        try:
            import speculative_executor as fine
            if isinstance(value, list) and value and all(isinstance(v, fine.TaskCandidate) for v in value):
                results = fine.execute_speculative(value, max_results=1)
                winner = next((r for r in results if r.ok), None)
                if winner is None:
                    raise RuntimeError("fine speculation produced no successful result")
                return winner.value
        except ImportError:
            pass
        return value


@dataclass(frozen=True)
class FleetAdapter:
    """Small app-facing facade; all ten apps share the same runtime contract."""
    app: str
    hivemind: "HivemindV15"

    def query(self, query: Any, paths: Mapping[str, Callable[[Any], Any]],
              significance: float = 1.0, accept: Optional[Callable[[Any], bool]] = None) -> Dict[str, Any]:
        return self.hivemind.execute_query(self.app, query, paths, significance, accept)

    def channel_outcome(self, target: str, failed: bool) -> int:
        return self.hivemind.observe_channel(self.app, target, failed)

    def temporal_observation(self, values: Mapping[str, float]) -> None:
        self.hivemind.causal.observe({f"{self.app}:{k}": v for k, v in values.items()})

    def adversarial_anomalies(self, sample: Sequence[float], count: int = 8) -> List[List[float]]:
        return self.hivemind.curriculum.generate(sample, count)


class HivemindV15:
    """End-to-end facade shared by every fleet application."""

    def __init__(self):
        self.memory = HolographicMemory(capacity=int(os.getenv("ORCH_V15_MEMORY_CAPACITY", "4096")))
        self.federation = ZeroCopyFederation(self.memory)
        self.budget = SpikeBudget(threshold=float(os.getenv("ORCH_V15_SPIKE_THRESHOLD", ".6")))
        self.ecc = AdaptiveErrorCorrection(); self.causal = FractalCausalGraph()
        self.curriculum = AdversarialAnomalyCurriculum(); self.topology = QueryTopology()
        self.speculation = SpeculativeChains(max_paths=3)
        self.metrics: Counter = Counter()
        self.adapters: Dict[str, FleetAdapter] = {app: FleetAdapter(app, self) for app in FLEET_APPS}

    def execute_query(self, app: str, query: Any, paths: Mapping[str, Callable[[Any], Any]],
                      significance: float = 1.0, accept: Optional[Callable[[Any], bool]] = None) -> Dict[str, Any]:
        app = canonical_app(app)
        hit, ring_view = self.federation.query(app, query)
        if hit and hit.exact:
            self.metrics["memory_hits"] += 1
            return {"app": app, "source": "federated_memory", "result": hit.value,
                    "similarity": hit.similarity, "zero_copy_bytes": len(ring_view)}
        if hit:
            self.metrics["associative_context_hits"] += 1
        attention = self.budget.signal(app, significance)
        if attention <= 0:
            self.metrics["spike_suppressed"] += 1
            return {"app": app, "source": "metabolic_rest", "result": None, "attention": 0.0}
        primary = next(iter(paths.values()), lambda q: None)
        cluster = self.topology.observe(app, query, primary)
        if cluster and cluster.hits:
            result = cluster.node(query); source = "compiled_topology"
        else:
            execution = self.speculation.execute(query, paths, accept)
            result = execution["result"]; source = "speculative_chain"
        self.memory.put(app, query, result); self.metrics[source] += 1
        return {"app": app, "source": source, "result": result, "attention": attention}

    def observe_channel(self, source: str, target: str, failed: bool) -> int:
        self.ecc.observe(source, target, failed)
        return self.ecc.redundancy(source, target)

    def adapter(self, app: str) -> FleetAdapter:
        return self.adapters[canonical_app(app)]

    def federated_anomaly_batch(self, failures: Mapping[str, Sequence[float]], count: int = 4) -> List[dict]:
        """Share synthetic failure modes as vectors, never raw app records."""
        batch = []
        for app, sample in failures.items():
            for vector in self.curriculum.generate(sample, count):
                batch.append({"source": canonical_app(app), "level": self.curriculum.level, "vector": vector})
        return batch

    def maintenance(self) -> Dict[str, Any]:
        return {"apps": list(FLEET_APPS), "memory": self.memory.consolidate(),
                "rested_modules": self.budget.rest_idle(), "dissolved_clusters": self.topology.dissolve(),
                "error_correction_gaps": self.ecc.gaps(), "metrics": dict(self.metrics),
                "anomaly_curriculum_level": self.curriculum.level,
                "active_clusters": len(self.topology.clusters)}


_runtime: Optional[HivemindV15] = None
_runtime_lock = threading.Lock()


def runtime() -> HivemindV15:
    global _runtime
    with _runtime_lock:
        if _runtime is None: _runtime = HivemindV15()
        return _runtime


def observe_task(task: Mapping[str, Any]) -> Dict[str, Any]:
    """Cheap runner intake hook: learn/prewarm patterns without model calls."""
    rt = runtime(); app = canonical_app(str(task.get("project") or task.get("project_name") or "orchestrator"))
    query = {"kind": task.get("kind"), "prompt": str(task.get("prompt", ""))[:512],
             "files": task.get("file_scope")}
    rt.topology.counts[(app, pattern_key(query))] += 1
    rt.causal.observe({f"queue:{app}": 1.0, "timestamp": time.time() % 86400})
    rt.metrics["tasks_observed"] += 1
    if rt.metrics["tasks_observed"] % 100 == 0:
        rt.maintenance()
    return {"app": app, "pattern": pattern_key(query), "seen": rt.topology.counts[(app, pattern_key(query))]}


if __name__ == "__main__":
    print(json.dumps(runtime().maintenance(), indent=2, sort_keys=True))
