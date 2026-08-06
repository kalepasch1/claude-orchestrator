# Wave C — shared contracts (Parts 4, 6, 7)

Authoritative spec: `IMPROVEMENTS_MASTER_UNQUEUED_2026-07-31.md`, Parts 4, 6 and 7.

This is the **contracts slice** of Wave C. It ships the shared interfaces and the DB
substrate the sibling shards implement against — and nothing else. No engines, no
behaviour, no wiring. Sibling shards must import from here rather than redeclaring
their own shapes; that is what makes the wave compose instead of fork.

- Python contracts: `runner/wave_c_contracts.py`
- DB substrate: `supabase/migrations/20260805000000_wave_c_platform_spine.sql`
  (**not yet applied to prod** — apply after a shadow dry-run, per the migration
  name-check rule in `CLAUDE.md`)

## Conventions carried from the repo

- Stdlib-only, dependency-free, so any shard can import without a new requirement.
- Fail-soft `Result` wrapper (`ok()` / `err()`), matching `runner/barks_contracts.py`.
  Contract helpers return `err(...)`; they never raise on bad input.
- `ORCH_`-prefixed env-var config so keys are fleet-pushable via `fleet_control.py`
  and carry no secrets.
- Tables use `snake_case` names, `gen_random_uuid()` PKs, and the same RLS posture as
  `steering_events`: `authenticated` reads, service role writes.

## Part 4 — self-service code generator

| Contract | Purpose |
| --- | --- |
| `TransplantCandidate` | A proven merged diff offered as an organ. `eligible` is true only at or above `ORCH_WAVEC_TRANSPLANT_MIN_SIMILARITY` (0.55). |
| `Disposition` / `DispositionLedgerEntry` | The "never grow tumors" audit trail — what was generated and how it ended. |
| `ContractFirstSpec` | Failing test + type signatures emitted *before* any body. The verify gate is the spec. |
| `GoldenPathTemplate` | Per-vertical scaffold distilled from top-decile merged shards. |
| `StrategyContext` | Approved tribunal strategy carried into every shard, so code is born compliant-by-design (a sweepstakes structure natively emits AMOE flows + state gates). |
| `CodeGenerator`, `DispositionLedger` | The two protocols an implementation satisfies. |

Backing tables: `codegen_disposition_ledger`, `codegen_golden_path_templates`.

## Part 6 — cross-app / platform

| Contract | Purpose |
| --- | --- |
| `MatterRecord` / `MatterStage` / `MatterView` | The matter spine. Intake, triage, licensing, filings, video and newsletters all key to one record; inbox, portal and the Foulkon exposure model are three **views**, not three truths. |
| `ExposureRecord`, `HedgeFlywheelMetric` | Exposure-to-hedge flywheel — the % of quantified `expected_loss_usd` hedgeable on Tomorrow, trending. Doubles as product-gap tracker, demand signal and investor stat. |
| `RenewalScheduleEntry` | Renewal annuity engine: every filing schedules its own renewal/reporting calendar, wired to the ambient monitor. |
| `MatterSpine`, `ExposureFlywheel`, `RenewalEngine` | The three protocols. |

Unhedgeable exposure carries a `foundry_request_id` — that is the auto-feed into the
instrument foundry, so a gap becomes demand rather than a dead end.

Backing tables: `matter_records`, `matter_exposures`, `matter_renewals`.

## Part 7 — pipeline structure

| Contract | Purpose |
| --- | --- |
| `Initiative` / `InitiativeState` | Merge unit = initiative, not branch. |
| `InitiativeMergeCard` | One judgeable card per coherent changeset, collapsing thousands of merge decisions to dozens. |
| `DispositionMemoryEntry` | Branch closures train dedupe + planner so duplicate work stops being *generated*, not just filtered. |
| `InitiativeIntegrator`, `DispositionMemory` | The two protocols. |

`ORCH_WAVEC_MERGE_UNIT` (default `initiative`) lets the merge train fall back to
per-branch behaviour without a code change if initiative grouping needs to be stood down.

Backing tables: `initiatives`, `disposition_memory`.

## What siblings must NOT do

- Do not redefine these dataclasses locally — import them.
- Do not add engine behaviour to `runner/wave_c_contracts.py`; it stays body-free.
- Do not apply the migration from a shard. Migration application is an operator step
  after a name-check against the live DB (see `CLAUDE.md` → *Migration Authoring*).
