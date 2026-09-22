# Consilium outcome audit — 2026-09-12

## Finding

The pathway has generated internal research, but current production absorption
and business value are **not demonstrated**. A successful process exit, self-rated
confidence, citation count, or a debate win is not a verified customer outcome.
No measured 100x/1000x improvement is claimed.

Live control plane `eatfwdzfurujcuwlhdgj`:

- 315 cards total; three identify `consilium_v2`, all internal.
- 24 publication reviews (12 cards, 12 committee opinions), all rejected.
  The three newer cards were also reviewed and rejected; it was not exclusively
  a legacy review backlog.
- 8,247 positions, zero resolved; zero experts have `brier_n > 0`.
- 100,699 expert-memory rows, zero with source URLs.
- No `paper:`, `ambig:`, or `regopp:` approval packets.
- One newer card records a cross-vendor challenge and revision. This is evidence
  of an internal critique, not independent proof of legal correctness or product use.

Apparently's live database `olaxnyrzoptjcntrrjgn` has zero verdict cards,
zero Consilium sessions and zero Consilium first drafts. Build-time data is a
different path: Smarter's host snapshot has 120 cards from August 20; the canonical
Apparently-layer snapshot is empty and dated August 9. The layer's risk-gradient
consumer reads the empty snapshot. Law's `steer.tribunal` Counsel Link path calls
that Apparently consumer; no separate direct Law card ingestion was found.

The old `foulkon_sync.py` defaults to the retired Illuminati checkout and is not
scheduled by this Consilium daemon. Its fresh-only filter is not sufficient
publication or steering admission. **Do not reconnect it wholesale or copy the
120 unreviewed host cards into the canonical layer.**

## Live data repair (completed)

All three v2 citation fields were malformed JSON strings sliced at exactly 8,000
characters. The original archived `final_memo.citations` arrays were available in
`.runtime/consilium/tournaments.jsonl`. For each repair we matched docket ID,
question and verdict, and required the archived Python-serialized citations to
match every one of the existing 8,000 characters exactly. One guarded transaction
restored native JSON arrays; no position, verdict, confidence, publication state,
or prior review decision was changed.

| Card | Restored citations | Canonical citation SHA-256 |
|---|---:|---|
| `6437c44f-b631-4b52-a5bf-6a46b11d8cc6` | 21 | `6ce1ff6d3b0c8ae1744f1dfb36f4e107603b97a0f159cb7270ca7cfa2f659d90` |
| `d0af873e-21a9-47f4-bff4-9d7dccde5c7f` | 18 | `9f597d9ff96cad4f00068a229e3b71352000e714ac148f55b006bb53bff546f5` |
| `57204e66-c929-4d4f-ac71-ce951c77e268` | 23 | `506de5b4e3ea0a26ffccbcab92f90242bd6e90c3a3281d86fdc27ea94ffbc047` |

Digest serialization: Python `json.dumps(citations, sort_keys=True,
separators=(',', ':'))`, UTF-8, default ASCII escaping. Each existing rejection
retains its scores/reasons and now carries a repair receipt and
`requires_rereview=true`. Read-only candidate selection verified all three full
arrays and matching digests. They are queued for review, **not approved**.

## Active worker fixes (source used by existing LaunchAgent)

- Outcome receipts separate clean execution, reported production, no work,
  unavailable/failed work, and unverified absorption/value. Unavailable work
  remains due with bounded backoff; idle checks cannot overwrite the last
  reported-productive timestamp.
- Strict bounded corpus reads distinguish transport/query errors from emptiness.
  Source document text is used when clause text is absent. Previously missed
  documents and failed judgments retry with bounded backoff and pagination.
  Read-only live verification recovered 53,818 and 30,409 characters for two
  documents previously recorded as `no_text`.
- Review prompts preserve complete JSON/evidence within a bounded envelope;
  oversized input defers rather than being sliced. Invalid scores and unavailable
  reviewers defer, without a weaker local substitute or a false merits rejection.
- Commission state transitions now match the deployed CHECK constraint:
  publish/steer-only -> attorney_review, revise -> commission_review,
  reject -> withdrawn. No model decision self-publishes.
- Unconfirmed review persistence cannot advance a card. A transport-repaired
  record is re-reviewed only for the exact repaired citation digest, with its
  prior rejection/repair provenance retained in bounded review history.

Verification: 71 hermetic tests across resource admission, outcomes, corpus reads
and review integrity; 22 existing frontier tests. No model inference or manual
business job was launched. No scheduler restart or budget/guard reduction.

## Product-side correction

Smarter release commit `6705e03cf` fixes a separate deterministic bug: `unlawful`
matched `lawful`, lowering three of the old host snapshot's prohibitive cards.
Both host and canonical-layer consumers now share a conservative classifier;
negative wording wins and only exact unqualified positive labels lower risk.
53 focused tests passed. Consult the release PR for deployment state; this audit
does not claim the fix is already in production.

## Resource state and outstanding work

Ollama `/api/ps` is empty. The original Consilium LaunchAgent is registered on
its 600-second interval, not paused (17 runs at inspection). Native limits are
one loaded model, one parallel request, queue 2, context 4096, idle residency 30s.
Host pressure remains warning level 2, so inference is correctly deferred.
Read-only scheduler status also confirms `paused=false`, frontier enabled,
no cooldown, 600,000 hourly tokens available but zero remaining in the configured
3,000,000-token daily budget. Subscription budget exhaustion is independent of
local RAM; freeing memory alone does not authorize another frontier call.

Four Smarter Nuxt processes (ports 3008, 3019, 3002, 3021) account for roughly
45 GB of process footprint including compressed allocations. This is not RSS and
is not all physical RAM simultaneously. Law previews add more. No other task's
server was stopped; the user was asked about retiring duplicates while keeping
3008 and Law3027. Preserve source edits and confirm exact PID/owner before acting.

The configured 27B fallback remains permanently above the 8GiB model budget.
Do not raise the ceiling, silently downgrade legal reasoning, or buy cloud
capacity to force a green test. Explicit route-blocked classification, bounded
non-inference maintenance admission, and transport total deadlines remain work.

Next acceptance gates:

1. Recover host capacity; observe a normal guarded re-review and persisted result.
2. Preserve rejects/dissent; admit only properly reviewed, current evidence.
3. Implement one canonical exporter/consumer contract with exact artifact hashes,
   review provenance, freshness and destination receipts. Law should use the
   same admitted corpus through its existing signed gateway, not a second copy.
4. Observe actual authenticated retrieval/use and attach outcome feedback to the
   originating artifact. Do not count export/deployment as customer value.
5. Resolve forecasts against independently checked authority before claiming
   calibration or expertise improvements. Define and benchmark useful accepted
   outcomes per token/minute; do not optimize artifact volume.

Shared resource PR65 is still open at `d5a6ca635`, with two hosted jobs queued
at inspection. Local worker improvements must not be confused with that separate
shared release. Preserve unrelated Consilium WIP and do not merge its whole
feature history into canonical staging as a hotfix.
