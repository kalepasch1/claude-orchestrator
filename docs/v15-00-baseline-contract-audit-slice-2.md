# V15 adaptive runtime — baseline contract audit (slice 2: fleet gap matrix)

Continues `docs/v15-00-baseline-contract-audit-slice-1.md`, which inventoried the landed
runtime. This slice answers the second half of the brief: **where does each fleet repo
stand against that contract, and what exactly is missing.**

Nothing here is rebuilt. The runtime is audited as landed at commits `b3d38813`
("feat: add fleet-wide V15 adaptive runtime") and `e2834ef5` ("rename Illuminati app to
Trojun"), the only two commits touching
`packages/darwin-kernel/src/hivemindV15/index.ts`.

## Source of truth

| Artifact | Path | Size |
| --- | --- | --- |
| TypeScript runtime | `packages/darwin-kernel/src/hivemindV15/index.ts` | 246 lines |
| Python runtime | `runner/hivemind_v15.py` | parallel implementation |
| Kernel re-export | `packages/darwin-kernel/src/index.ts:32` | `export * as hivemindV15` |
| Slice-1 contract | `docs/v15-00-baseline-contract-audit-slice-1.md` | prose + machine-checked |
| Slice-1 enforcement | `runner/tests/test_v15_baseline_contract.py` | pins the enumerations |

## Adoption states

The matrix uses four states, defined so a row cannot be read optimistically:

- **native** — imports the runtime directly. Only possible inside this repository.
- **seam** — a local adapter deliberately mirrors the contract across the repo boundary,
  because the runtime cannot be imported across repos.
- **none** — no adoption. Any textual match is a build artifact, an unrelated subsystem,
  or planning prose.
- **absent** — the repository is not present on this machine, so no claim is made.

## Gap matrix

| App id | Repo | Adoption | Evidence | Gap to the contract |
| --- | --- | --- | --- | --- |
| `orchestrator` | `beethoven/claude-orchestrator` | **native** | `runner/runner.py` intake hook + `hivemind-v15-300` tick; kernel re-export | none for adoption; carries every defect in slice 1 |
| `galop` | `galop/racefeed` | **seam** | `lib/v15Adapter.ts` — explicit adapter documenting flags-off parity | no shared state with the runtime; parity is by hand-written mirror, unenforced across repos |
| `hisanta` | `hisanta` (santas-secret-workshop) | **planned** | `DARWIN_KERNEL_ADOPTION.md` describes a `git subtree` vendor of the kernel | kernel adoption is documented, V15 specifically is not wired; plan not executed |
| `trojun` | `trojun` (and legacy `illuminati`) | **none** | `types/index.ts:165` `hivemind_consensus` is an unrelated field | no adapter, no import; app id exists in `HIVEMIND_APPS` with nothing behind it |
| `smarter` | `smarter` | **none** | `/api/hivemind/*` routes in `generated/capability-contracts.json` are a different subsystem | same-word collision only |
| `tomorrow` | `tomorrow/tomorrow` | **none** | matches are `.vercel/output` build artifacts | no adapter, no import |
| `pareto` | `pareto/2080` | **none** | matches are `.vercel/output` build artifacts | no adapter, no import |
| `apparently` | `apparently` | **none** | matches are strategy `.md` prose | no adapter, no import |
| `vigil` | `vigil` | **none** | matches are `.output/server` build artifacts | no adapter, no import |
| `predictions` | prediction-markets-institute | **absent** | repo not present on this machine | not assessed |

Nine of the ten ids in `HIVEMIND_APPS` therefore have **no** live consumer. This confirms
and extends slice 1's finding ("No fleet application outside beethoven imports either
implementation today") with the one exception it did not have: galop's seam adapter.

## The blocking gap: there is no fleet contract to conform to yet

Slice 1 recorded that the runtime holds **no persistent state** — `FractalHolographicMemory`,
`MetabolicSpikeBudget`, `FractalCausalGraph`, the cluster and path-win maps are all
in-process `Map`s, and `HivemindV15` has no serialize/restore path.

That is not a missing feature to schedule; it is the reason a cross-repo contract cannot be
implemented as the runtime currently stands. Ten processes each holding a private memory
are ten runtimes, not one fleet. Every "none" row above is therefore blocked on the same
prerequisite, and closing them individually would produce ten isolated caches that share a
vocabulary and nothing else.

`lib/v15Adapter.ts` in galop is the honest shape of adoption under this constraint: it
owns its flags, tenant scoping and telemetry locally, guarantees flags-off parity, and
delegates rather than pretending to share state.

## Open questions carried from slice 1

| Question | Status after this slice |
| --- | --- |
| Two divergent `source` vocabularies (TS `memory\|rest\|compiled\|speculative` vs Python) | still open; nothing outside beethoven consumes either, so no caller is broken *yet* — adopting a second repo is what makes it a real defect |
| Hand-synced app lists (TS literal + Python `FLEET_APPS`) | still open; `e2834ef5` had to edit both. `test_v15_baseline_contract.py` now fails if they diverge, which contains the defect without removing it |
| Flags existing only on the Python side (`ORCH_V15_MEMORY_CAPACITY`, `ORCH_V15_SPIKE_THRESHOLD`) | still open; the TS runtime takes constructor args instead, so the same knob is not fleet-pushable via `fleet_config` |
| Non-persistent state | **promoted to the blocking gap above** |

## Benchmark claims

The brief requires 50X–500X figures be treated as hypotheses unless reproduced with
baseline, dataset, samples, percentiles, resource envelope and correctness parity. No such
benchmark exists in the repository. The runtime's own header says the same:

> the 50x–500x figures in the proposal remain benchmark targets, not promises.

**This audit makes no performance claim in either direction.** No row of the matrix is
justified by a speed argument.

## Proof

`cd packages/darwin-kernel && npm test -- --runInBand` → `tests 276, pass 276, fail 0`
(slice 1 recorded 255; the kernel has grown since, all green).

`python3 -m pytest runner/tests/test_v15_gap_matrix.py` pins every adoption state in the
matrix above against the live repositories, so a row that stops being true fails loudly
instead of ageing into fiction.
