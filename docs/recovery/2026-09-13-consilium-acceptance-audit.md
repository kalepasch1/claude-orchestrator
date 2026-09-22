# Consilium acceptance audit — 2026-09-13

Read-only observations around 19:00 UTC. This is an acceptance checkpoint, not
authorization to publish, weaken review, or run extra inference.

## Result

Yesterday's integrity fixes are active, but useful product absorption remains
**unproven**. No new merits review or accepted output is present. A scheduler
heartbeat is not evidence of value.

### Control plane (`eatfwdzfurujcuwlhdgj`)

- 315 verdict cards, including exactly three Consilium v2 cards.
- 24 publication reviews; all decisions remain `reject`.
- Zero `paper:`, `ambig:`, or `regopp:` approval packets.
- Zero experts with `brier_n > 0`; zero expert-memory rows with source URLs.
- The three repaired cards remain `internal` and `fresh`; their prior rejections
  still require re-review. No review or publication state was changed.

Read-only `_candidates(3)` selected precisely these three cards. Native citation
arrays still match yesterday's canonical SHA-256 digests:

| Card | Citations | SHA-256 |
|---|---:|---|
| `6437c44f-b631-4b52-a5bf-6a46b11d8cc6` | 21 | `6ce1ff6d3b0c8ae1744f1dfb36f4e107603b97a0f159cb7270ca7cfa2f659d90` |
| `d0af873e-21a9-47f4-bff4-9d7dccde5c7f` | 18 | `9f597d9ff96cad4f00068a229e3b71352000e714ac148f55b006bb53bff546f5` |
| `57204e66-c929-4d4f-ac71-ce951c77e268` | 23 | `506de5b4e3ea0a26ffccbcab92f90242bd6e90c3a3281d86fdc27ea94ffbc047` |

The candidate reader warned that its newest-first query hit its nine-row cap.
It did select all three repaired cards; this does not establish completeness
for a future larger backlog. Filtering/pagination remains a separate concern.

### Consumer evidence

Apparently live database `olaxnyrzoptjcntrrjgn`: zero rows in each of
`verdict_cards`, `consilium_sessions`, and `consilium_first_drafts`.

Current Smarter release source still has two different build-time snapshots:

- Host snapshot: 120 cards, synced `2026-08-20T00:51:29Z`.
- Canonical Apparently-layer snapshot: zero cards, synced `2026-08-09T08:01:27Z`.

The canonical risk-gradient imports the Apparently-layer verdict-card lookup.
Law's existing Counsel Link integration remains the shared gateway path; this
audit did not invoke it or demonstrate an authenticated retrieval. Do not copy
the old host snapshot wholesale into the layer to manufacture absorption.

### Runtime evidence

The existing LaunchAgent still targets this checkout's `consilium_tick.py`.
All recorded latest attempts are `memory_pressure` deferrals; none has a
`last_productive_at` receipt. The new truthful outcome fields are therefore
active, but no post-fix productive run is demonstrated. One older corpus-index
deferral predates the `latest_attempt` field.

At `2026-09-13T19:00:25Z`, a read-only calculation over the existing rolling budget
ledger showed:

- Frontier hourly use: 0 of the configured 600,000 tokens.
- Frontier rolling 24-hour use: 461,455 of 3,000,000; remaining 2,538,545.
- 21 frontier calls in that rolling window; latest call `2026-09-12T20:04:16Z`.
- Codex rolling usage: 128,624; both cooldown timestamps zero.

Thus yesterday's exhausted daily budget is no longer the current blocker.
Budget availability does not waive host admission, review, or spending controls.
These values age as the rolling window advances.

## Smallest safe value demonstration

1. Recover host capacity without increasing model ceilings. Use the existing
   guarded commission path on the repaired evidence when resource admission
   permits it; do not regenerate the cards merely to create activity.
2. Retain all rejection/dissent history and record the new review against the
   exact citation/content version. A passing model review still requires the
   existing authorized human review before customer admission.
3. Build and test one canonical, fail-closed exporter/consumer contract while
   waiting: artifact/version hash, review provenance, destination, freshness,
   and revocation. Fixtures can prove rejects/internal cards stay excluded
   without model calls or live writes. With today's data, admitted count must
   remain zero.
4. Once an actually admitted card exists, demonstrate a single authenticated
   product retrieval, retain the exact originating artifact ID/hash and consumer
   receipt, and record whether it changed a real reviewed decision. Only that
   last acceptance—not export, deployment, or retrieval alone—supports value.

No model or business job was launched, no database writes were requested, no
scheduler was restarted, and no budget or review gate was relaxed during this
audit. No 100x/1000x outcome claim is supportable yet.
