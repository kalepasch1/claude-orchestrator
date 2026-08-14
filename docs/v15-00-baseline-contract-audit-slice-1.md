# V15 adaptive runtime — baseline contract audit (slice 1: inventory)

Slice 1 of `v15-00-baseline-contract-audit`. Scope is the first bullet of the parent
brief: **locate the already-landed implementation and enumerate its public interfaces,
feature flags, persistence formats, telemetry, privacy boundaries and current consumers.**
The fleet gap matrix is slice 2's job and is deliberately not attempted here.

The slice-1 prompt itself arrived as an unrecoverable hex patch-template
(`[patch-template:388aab34b91e]`, intent line is hash-word soup). The real intent was
recovered from sibling `v15-00-baseline-contract-audit-slice-2`, which carries the
readable original request — the same recovery route used for
`v15-03-spike-attention-budget-slice-1`.

## Source of truth

| Commit | Date | What it landed |
| --- | --- | --- |
| `b3d38813ade9ccc8d989c03663c2f59ddddfcac8` | 2026-07-22 | `feat: add fleet-wide V15 adaptive runtime` — `runner/hivemind_v15.py` (537 lines), `runner/hivemind_v15_tick.py`, `packages/darwin-kernel/src/hivemindV15/index.ts` (245), `packages/darwin-kernel/test/hivemindV15.test.ts`, hooks in `runner/runner.py` and `runner/common_brain.py` |
| `e2834ef5990e255d8b2baae7fab8132e8ce96a7d` | 2026-07-23 | `rename Illuminati app to Trojun` — app-id rename across both implementations |

Both are ancestors of `origin/master`. There are two parallel implementations of the same
concept, one per language; they are **not** generated from a shared schema.

## Public interface

### TypeScript — `packages/darwin-kernel/src/hivemindV15/index.ts`

Exported: `HIVEMIND_APPS`, `HivemindApp`, `Path<T,R>`, `canonicalApp`, `structuralPattern`,
`FractalCoefficient`, `fractalKey`, `MemoryHit<T>`, `FractalHolographicMemory`,
`ZeroCopyHolographicRing`, `FractalCausalGraph`, `MetabolicSpikeBudget`,
`ErrorCorrectionCurriculum`, `AdversarialAnomalyCurriculum`, `DistilledTopologyNode<T,R>`,
`QueryResult<R>`, `HivemindV15`, `HivemindAdapter`.

### Python — `runner/hivemind_v15.py`

Module functions: `canonical_app`, `pattern_key`, `value_key`, `runtime`, `observe_task`.
Classes: `FractalEncoder`, `MemoryHit`, `HolographicMemory`, `ZeroCopyFederation`,
`MetabolicState`, `SpikeBudget`, `AdaptiveErrorCorrection`, `FractalCausalGraph`,
`AdversarialAnomalyCurriculum`, `DistilledNode`, `QueryCluster`, `QueryTopology`,
`SpeculativeChains`, `FleetAdapter`, `HivemindV15`.

Facade entry point is `HivemindV15.execute_query(app, query, paths, significance, accept)`,
returning `{app, source, result, ...}` where `source` is one of `federated_memory`,
`metabolic_rest`, plus the live-path values. The TS `QueryResult.source` union is
`'memory' | 'rest' | 'compiled' | 'speculative'`. **The two source vocabularies do not
match**, so a consumer cannot branch on `source` portably across the two runtimes.

## App identifiers

Both sides list ten apps in the same order:
`galop, tomorrow, smarter, pareto, apparently, orchestrator, vigil, hisanta, predictions, trojun`
(Python `FLEET_APPS`, TS `HIVEMIND_APPS`). Both fall back to `orchestrator` for an unknown
value. The lists are duplicated literals in two files, kept in sync only by hand — the
`e2834ef5` rename had to touch both. `test_v15_baseline_contract.py` now pins the parity.

## Feature flags

Exactly two, both read once in `HivemindV15.__init__` (`runner/hivemind_v15.py:456,458`):

| Variable | Default | Effect |
| --- | --- | --- |
| `ORCH_V15_MEMORY_CAPACITY` | `4096` | `HolographicMemory` capacity |
| `ORCH_V15_SPIKE_THRESHOLD` | `.6` | `SpikeBudget` significance threshold |

Read at construction, so a change requires a process restart. The TS implementation has
**no** equivalent flags: its thresholds are constructor arguments only, so the two runtimes
cannot be tuned by the same operator action.

## Persistence format — there is none

This is the audit's headline finding, and it is empirical rather than inferred.

`grep -nE "open\(|sqlite|pickle|shelve|redis|Path\(" runner/hivemind_v15.py` returns no
persistence call; the only `json.dumps` uses are hashing and in-memory encoding
(lines 48, 53, 69, 191) plus the CLI pretty-print at 537. There is no table, no state
file, no cache directory. **All learned state — memory, topology counts, causal series,
curriculum level, metrics — is process-local and dies with the process.**

That interacts badly with how the runtime is scheduled. `runner/runner.py:3032` registers
`("hivemind-v15-300", "hivemind_v15_tick.py", "interval", 300)`, and the tick is a
standalone script whose entire body is `print(json.dumps(runtime().maintenance()))`.
Because `_runtime` is a module-level singleton (`runner/hivemind_v15.py:512-520`), a
separate process gets a **freshly constructed, empty** `HivemindV15`. Observed by running
it directly:

```
$ python3 runner/hivemind_v15_tick.py
{ "active_clusters": 0, "anomaly_curriculum_level": 1,
  "dissolved_clusters": 0, "error_correction_gaps": [],
  "memory": { "removed": 0, "retained": 0 }, ... }
```

So the 300-second consolidation/metabolism/topology lifecycle **never touches the state
the runner actually accumulated**. The real consolidation path is the incidental
`if rt.metrics["tasks_observed"] % 100 == 0: rt.maintenance()` inside `observe_task`.
The scheduled tick is, today, a no-op that costs a process launch every five minutes.

This is recorded as a finding, not fixed here: slice 1 is an audit, and the fix (persist
state, or run maintenance in-process, or drop the tick) is a behaviour change that belongs
in its own task with its own acceptance test.

## Telemetry

`HivemindV15.metrics` is a `collections.Counter` incremented in-process. Observed keys:
`memory_hits`, `associative_context_hits`, `spike_suppressed`, `tasks_observed`.
`maintenance()` returns `{apps, memory{removed,retained}, rested_modules,
dissolved_clusters, error_correction_gaps, metrics, anomaly_curriculum_level,
active_clusters}`. There is no metrics exporter, no Prometheus surface and no DB sink —
consistent with the no-persistence finding, the counters are readable only by the process
that owns them.

## Privacy boundaries

- `observe_task` truncates the prompt to 512 characters and hashes it via `pattern_key`,
  so what is retained is a structural fingerprint (blake2b, 12-byte digest) rather than
  prompt text. Task `kind` and `file_scope` are retained in the query shape.
- `canonical_app` / `canonicalApp` collapse unknown app ids to `orchestrator`, so a
  mislabelled caller's observations land in the orchestrator bucket rather than being
  rejected. Cross-tenant *isolation is therefore not enforced at this boundary* — it is a
  namespacing convention inside one shared `HolographicMemory`.
- `ZeroCopyFederation` shares one ring across all apps by design; a memory hit is looked up
  per app, but the backing store is common.

The related, already-shipped finding from `v15-02-fractal-holographic-retrieval` (that
`HolographicMemory` provides little real tenant/app isolation) is consistent with what this
audit sees and is not re-litigated here.

## Current consumers

| Consumer | Site | Nature |
| --- | --- | --- |
| `runner/runner.py:843-846` | `import hivemind_v15; hivemind_v15.observe_task(t)` | intake hook, wrapped in try/except and logged at debug — fail-soft, never blocks a task |
| `runner/runner.py:3032` | scheduled `hivemind-v15-300` tick | fires every 300s; see the no-op finding above |
| `packages/darwin-kernel/src/index.ts` | re-export | makes the TS runtime part of the kernel's public surface |

`runner/runner.py:1334-1337` (`task_memory.hivemind_query` / `inject_hivemind`) is a
**different** subsystem despite the shared word — it is not a consumer of this runtime.
No fleet application outside beethoven imports either implementation today.

## Benchmark claims

The parent brief instructs that 50X–500X figures be treated as hypotheses unless reproduced
with baseline, dataset, samples, percentiles, resource envelope and correctness parity.
**No such benchmark exists in the repository**, so this audit makes no performance claim in
either direction.

## Proof

`cd packages/darwin-kernel && npm test -- --runInBand` → `tests 255, pass 255, fail 0`.
`python3 -m pytest runner/tests/test_v15_baseline_contract.py` pins every enumeration above
so the contract fails loudly if the runtime drifts from this document.

## Handover to slice 2

Slice 2 should build its gap matrix on these facts, and treat as open questions:
the two divergent `source` vocabularies, the hand-synced app lists, the flags that exist
only on the Python side, and the non-persistent state that makes any cross-process fleet
contract unimplementable as the runtime currently stands.
