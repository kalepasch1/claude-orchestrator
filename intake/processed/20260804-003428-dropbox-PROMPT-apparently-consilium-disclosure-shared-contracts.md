# Apparently — Consilium audit + conspicuous-disclosure engine: SHARED CONTRACTS

RECOVERY NOTE (2026-08-03). This is a reconstruction of the `…-contracts` shard of the
2026-07-29 operator directive "apparently: Consilium continuous-operation audit (then
guarantee it) + conspicuous-disclosure engine" (SUBMITTED-BY kale@smrter.us,
operator/counsel; workflow governed_heavy; resolves Round12 C.2 and H.1). That shard's
prompt was destroyed by the auto-remediate prompt-overwrite bug (since fixed) and
quarantined as `spec-lost`; the source drop-box file is gone from disk and from git. Both
sibling shards SURVIVED and are QUEUED, and both say "honor the shared contracts" — so the
contracts they depend on are the one piece missing. This spec is derived from what those
siblings explicitly require.

DO NOT re-implement the sibling sections. They are already queued and owned:
  * §1 Consilium continuous-operation AUDIT → then guarantee (Round12 C.2)
  * §2 Conspicuous-disclosure engine (Round12 H.1)

Build ONLY the shared contracts. Real code — types, Zod schemas, a counsel-editable table
where the spec calls for one, and the CI test harness the disclosure shard plugs into.

---

## Scope: the contracts both shards must honor

### 1. Audit evidence contract (§1a depends on this)
The audit must be honest, which means it must read the REAL stores and be unable to
report a number it did not observe.
- `EvidenceSource` enumerating the authoritative stores: `cade_run_ledger`, the committee
  tables, colosseum/tournament records, and `docs/decisions` ADRs. A source that cannot be
  read is reported as UNREACHABLE and NAMED — never silently counted as zero. This is the
  coverage doctrine: declare the universe, record what was processed, name what was not.
- `ContinuityVerdict`: `RUNNING` | `ON_DEMAND_ONLY` | `UNKNOWN`, each carrying the evidence
  that produced it. `UNKNOWN` is a legitimate, reportable outcome; a missing read must not
  collapse into `ON_DEMAND_ONLY` or into `RUNNING`.
- `ActivityWindow` — the trailing-30-day counts the audit reports: sessions convened,
  questions debated, dissents recorded, papers and predictions produced, corpus deltas,
  filings and first drafts generated.

### 2. Session persistence contract (§1b depends on this)
- `ConsiliumSession`: question, panel, positions, dissent, consensus, confidence, corpus
  delta. Dissent is a required field — a session that records no dissent must say so
  explicitly rather than omitting the field, since "no recorded dissent" and "dissent not
  captured" are different claims and only one of them is marketable.
- `SessionTrigger`: standing calendar (per vertical — gaming, financial services, AI/data)
  or event (corpus ingest, regulatory change, enforcement action, court opinion, NAL).

### 3. First-draft currency contract (§1c depends on this)
- `FirstDraft` carries the corpus hash it is current as of, plus the staleness rule that
  decides when it must be re-drafted. "Keeps current" is a testable property, not a claim.

### 4. Disclosure single source of truth (§2a depends on this)
- ONE canonical disclosure string + one component. Every surface imports it; no surface
  may inline its own copy. Legal services are provided by the licensed professional
  entity — brand and platform entities perform no legal services.
- `DisclosureSurface`: the enumerated registry of surfaces where a client could form an
  impression — site footer, header-adjacent on legal-services pages, every engagement
  letter, every invoice, every email signature and template, every generated deliverable's
  cover and footer, portal login, and the escalation panel.
- `SurfaceExemption`: the allow-list shape. An exemption requires an explicit written
  justification field — an unexplained exemption must not typecheck.

### 5. Jurisdiction gate (§2c depends on this)
- `JurisdictionRule` — per-state trade-name and advertising rules, counsel-editable, with
  provenance and a last-verified timestamp on every row.
- `resolveVariant(state) -> DisclosureVariant`. Unknown or unverified state resolves to the
  MOST CONSERVATIVE variant. Fail-closed: this is a legal-posture gate, and a missing row
  must never open the brand-forward variant.

### 6. CI enforcement contract (§2b depends on this)
- The harness the disclosure shard's test plugs into: enumerate every registered surface,
  render it, assert the disclosure component is present, and FAIL THE BUILD otherwise.
- The harness must itself be tested against a fixture page with the disclosure REMOVED, to
  prove it can fail. A green enforcement test that has never been observed failing proves
  nothing — that failure mode has cost this fleet real incidents.

### 7. Franchise parameterization (§2e depends on this)
- `BoutiqueDisclosureConfig` — the same engine parameterizes for every Apparently OS
  boutique under the franchise architecture, so a new boutique inherits conspicuous-
  disclosure compliance automatically rather than re-implementing it.

---

## Legal posture (governed_heavy — do not soften)
- Human sign-off remains mandatory on anything outbound to a regulator or court. Bots
  draft and track; licensed humans send. Nothing in these contracts may create an
  auto-send path.
- The independence statement ("no control over legal judgment") is surfaced alongside the
  disclosure, per §2d.
- Anything that would force licensing, registration, custody, transmission, or advice is
  owner-only and escalates rather than proceeding.

## Repo conventions (non-negotiable)
- Types from `~/types/database.types`; typed Supabase helpers only — no raw `.from('table')`.
- Zod schemas in `shared/schemas/`; RLS default-deny on every new table.
- No hardcoded model strings; no `console.log` (use `server/utils/logger.ts`).
- Migrations idempotent, name-checked, `npm run lint:migrations` clean.

## Acceptance
- Every contract is imported by a sibling call site or pinned by a test.
- `resolveVariant()` has tests for known-compliant, known-restrictive, and UNKNOWN state —
  UNKNOWN must return the conservative variant.
- The CI harness demonstrably FAILS on a fixture page with the disclosure removed.
- An unexplained `SurfaceExemption` fails to typecheck or fails a test.
- The audit reports `UNKNOWN` (not a fabricated zero) when an evidence source is
  unreachable, and names the unreachable source.
