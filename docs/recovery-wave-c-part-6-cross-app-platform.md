# Recovery analysis — Wave C Part 6 (cross-app platform)

- **Date**: 2026-08-14
- **Status**: recovered — content verified present, re-carried on this branch
- **Recovery branch**: `agent/recover-missing-branch-dropbox-wave-c-compounding-codegen-platform-spine-pipeline-structure-part-6-cross-app-platform`
- **Proof**: `python3 -m pytest runner/tests/test_matter_spine.py` → 25 passed
- **Recovered commit**: `6915dfba` ("agent: dropbox-wave-c-part-6-cross-app-platform"),
  cherry-picked onto this branch as an exact copy

## What was thought lost

The intent stub flagged the branch
`agent/dropbox-wave-c-compounding-codegen-platform-spine-pipeline-structure-part-6-cross-app-platform`
as missing. That branch name exists locally but points at unrelated master history
(a `v15-30-fleet-release-verification` merge) with **no Part 6 content** — a stale
pointer, which is what tripped the missing-branch detector.

## What actually happened

The Part 6 work was not lost. It landed under a *shorter* branch name,
`agent/dropbox-wave-c-part-6-cross-app-platform` (commit `6915dfba`, authored
2026-08-14 02:22), and was merged to master at `95224073` (2026-08-14 04:56) —
roughly two hours **after** this recovery branch was cut from master at
`28a7d6d1` (02:54). The recovery intent and the real merge raced; both are
legitimate, and the content is identical.

## What the recovered work contains

`runner/matter_spine.py` + `runner/tests/test_matter_spine.py` (412 lines),
covering all three Part 6 spec pieces from
`intake/processed/20260802-181540-dropbox-PROMPT-waveC-codegen-platform-pipeline.md`:

1. **Matter spine** — `MatterSpine` keys filings, exposures and artifacts
   (video, newsletter, licence) to one matter record; inbox / portal / exposure
   are projections of that record, with a shared digest making
   "three views, one truth" checkable (`views_agree`).
2. **Exposure-to-hedge flywheel** — `hedgeable_share` (share of quantified
   `expected_loss_usd` hedgeable on Tomorrow; `None`, not 0, when nothing is
   measured), `flywheel_trend` (the metric is the trend), and `foundry_feed`
   (unhedgeable exposure routed to the instrument foundry, biggest gap first).
3. **Renewal annuity engine** — `renewal_calendar`, `due_within` (the ambient
   monitor's surfacing query) and `overdue`; every cadenced filing schedules its
   own renewal, one-offs schedule nothing.

## Merge-train note

Because this branch carries `6915dfba` verbatim and master already contains it,
the merge of this branch is content-identical and resolves clean. The stale
local pointer `agent/dropbox-wave-c-compounding-codegen-platform-spine-pipeline-structure-part-6-cross-app-platform`
can be deleted by fleet housekeeping; it holds nothing unique.
