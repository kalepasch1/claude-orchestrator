# Focused triage — CONFLICTED_NEEDS_FOCUSED_TASK rescue refs

- audit fingerprint: `5dc36bf5e0bed6f108545572d49189cbfbc558ee98ae1290254e2e125f7e5918`
- base: `origin/master`
- refs triaged: **13**
- hunks examined: **14300**
- genuinely missing hunks: **1**
- deletion-only hunks (reported, never proposed): **13991**

Every rescue ref was treated as read-only. No ref, stash or worktree
was deleted, reset, cleaned, popped or moved by this triage.

## Per-ref outcome

| ref | files | hunks | missing | deletion-only | superseded | already present | path gone | outcome |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `refs/orch-rescue/20260805T191227-cc-mutual-default-fund-1d7e8d9a` | 1993 | 1980 | 0 | 1955 | 0 | 1 | 24 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260805T191228-cc-solvency-passport-6138fffd` | 355 | 353 | 0 | 341 | 0 | 1 | 11 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260806T131026-improve-value-aware-test-routing-early-exit-r-slice-3-adapt-merged-patterns-d09561bf` | 1289 | 1277 | 1 | 1258 | 0 | 0 | 18 | PARTIAL_REIMPLEMENT |
| `refs/orch-rescue/20260806T131034-5bee398fbf584c3252b3-57b674c5` | 2583 | 2565 | 0 | 2520 | 0 | 0 | 45 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260806T161111-relfix-release-hold-deadlock-cowork-20260806-e9050616` | 3 | 9 | 0 | 0 | 0 | 8 | 1 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260806T224945-relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch-7d9bd79d` | 2189 | 2174 | 0 | 2138 | 0 | 0 | 36 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260807T015247-dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p4-releasetrain-vercel-9c79f8f6` | 1439 | 1427 | 0 | 1408 | 0 | 0 | 19 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260807T220546-improve-automate-branch-management-slice-3-310c54b3` | 1644 | 1632 | 0 | 1611 | 0 | 0 | 21 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260808T040916-improve-immediate-auto-merge-on-test-pass-low-r-slice-3-implement-test-completio-7bf524c4` | 256 | 255 | 0 | 219 | 0 | 0 | 36 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260808T184515-cade-mirror-negotiation-5d33743e` | 1786 | 1774 | 0 | 1739 | 0 | 0 | 35 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260808T184519-canary-claude-27-slice-3-update-tests-checks-analyze-patch-behavior-analyze-patc-a4a7ec82` | 851 | 840 | 0 | 802 | 0 | 0 | 38 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260813T063106-chatgpt-local-reconcile-beethoven-6c8911116873-36ff050f` | 3 | 6 | 0 | 0 | 4 | 2 | 0 | FULLY_ACCOUNTED_FOR |
| `refs/orch-rescue/20260813T081746-chatgpt-local-reconcile-beethoven-e0945946bd0d-45fefc8b` | 2 | 8 | 0 | 0 | 0 | 8 | 0 | FULLY_ACCOUNTED_FOR |

## Why the deletion-only column is large, and why it is not work

A rescue ref is a sweep snapshot whose first parent is frequently an
unrelated older tip, so most of its diff is removals that carry no intent.
Treating those as unapplied deletions would propose deleting most of the
repository in order to recover it. They are counted here and never
proposed: recovery restores lost work, it does not remove present work.

## Outcome vocabulary

- `FULLY_ACCOUNTED_FOR` — every hunk is already present, superseded by a
  newer implementation, or targets a path base no longer has. Nothing to
  reimplement; the ref stays as durable provenance.
- `PARTIAL_REIMPLEMENT` — some hunks still apply and their content is
  absent from base. Only those get reimplemented, minimally, on top of
  current code. Never a forced overwrite of the whole ref.
- `NEEDS_HUMAN_READ` — hunks that neither apply nor are explained by a
  newer base. Read before acting.
