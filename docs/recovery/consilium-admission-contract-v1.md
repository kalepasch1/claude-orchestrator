# Proposed Consilium admission contract v1

`runner/consilium_admission.py` is a pure, inactive contract. It does not fetch or
write data, call models, export files, approve research, or claim product uptake.
Only synthetic unit fixtures currently exercise its successful admission path.

## Inputs and authority boundary

The card and commission review use the actual control-plane field names. All
reviewed content, assumptions, dissent, conditions, authority chain, and the full
native citation array are retained without slicing. Private `process` internals
are excluded. Mutable `status` and `publication_state` are checked separately:
only `fresh` + `published` can pass, so the legitimate human state transition
does not invalidate an unchanged reasoning hash.

Admission additionally requires new, **not yet implemented by a live adapter**
receipts:

1. Commission `detail.artifact_sha256`, `detail.evidence_sha256`, explicit
   `requires_rereview=false`, no veto, complete finite scores, correct weighted
   composite, accepted decision and current review timestamp. A citation-repair
   hash alone is not an accepted content-bound review.
2. `consilium-counsel-authorization/v1`: UUID identity and reviewer, `approved`
   decision, exact artifact/evidence hashes, review ID and full review hash,
   destination `apparently-canonical`, explicit `internal_steering` or
   `publication` purpose, approval and expiration timestamps.
3. `consilium-revocations/v1`: authenticated complete destination-scoped snapshot,
   checked/expiration timestamps, and artifact/review/authorization revocation
   ID lists. Missing or stale revocation state denies admission.

An explicit external `verify_receipt(kind, object)` dependency must authenticate
each complete commission, authorization and revocation receipt; validate issuer
authority, current counsel role and destination/purpose scope; and reject
invalid signatures/provenance. There is no default verifier. Passing `lambda:
True` is solely a synthetic-test device, never a production integration.
Hashes bind content; hashes alone do not authenticate a signer or legal quality.

## Time and scope

An aware server clock is mandatory. Conservative fixed maximum ages are 30 days
for artifacts, seven days for commission review, one day for counsel approval,
and five minutes for revocation snapshots. Future timestamps and exact expiry
boundaries deny. Issuer expiration can only shorten those windows. The returned
candidate expires at the earliest input limit. Consumers must recheck expiry
and revocations at use: a permanent build-time snapshot is not sufficient.

The sole canonical destination is Apparently; Law should consume through the
existing authenticated Counsel Link gateway, not an independent copied corpus.
An internal-steering authorization cannot authorize publication. Steering-only
commission results cannot authorize publication even with another purpose label.

## Serialization and receipt

Canonical v1 serialization is Python JSON with sorted keys, compact separators,
ASCII escaping, no NaN/Infinity, and UTF-8 bytes. Cross-language implementations
must match this exact version, including number representation. Inputs are
bounded to 128 KiB per object, 10,000 nodes and depth 16; oversized evidence is
rejected rather than truncated. Adapter tests must pin cross-language vectors
before integration.

The return has a uniform `admitted` boolean, reason code, exact hashes and expiry;
only admitted results carry a defensive-copy `card`. Both outcomes explicitly
retain `exported=false`, `absorbed=false`, and `value=unverified`. Denials carry no
card content. An admission receipt is neither a destination receipt nor customer
outcome evidence.

## Remaining integration gates

- Implement an authoritative persisted counsel sign-off and revocation source,
  with existing staff authorization/RLS and audited immutable version binding.
- Make commission review persist the exact full content/evidence hashes and
  explicit completed re-review status, without rewriting historical decisions.
- Supply the trusted verification adapter; authenticate fetched current source
  state and prevent time-of-check/time-of-use races before release.
- Sign/transport the complete export envelope; atomically ingest one canonical
  version and retain a destination receipt. Do not enable `foulkon_sync.py` as-is.
- Update the real consumer to enforce expiration and revocation, preserve dissent
  and all evidence, and bind actual authenticated retrieval/outcome feedback to
  originating artifact/version. The current consumer does none of these checks.
- Independently verify actual legal evidence; the contract validates provenance
  and consistency, not legal correctness, commercial value, or calibration.

Today's three real repaired cards are internal/rejected and must not pass. No
existing acceptance, trusted verifier, activated export, or product use is implied.
