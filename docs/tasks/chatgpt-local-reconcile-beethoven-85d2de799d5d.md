# chatgpt-local-reconcile-beethoven-85d2de799d5d

Audit fingerprint `85d2de799d5d7001150165432605b7b60bd32907bde50b5710b19b9d9ecb9b16`.
Base `origin/master` @ `d3a6b47a`. Ledger: `.orch/recovery-ledger-85d2de79.json`.

## What was reconciled

The task prompt carried a two-entry evidence *snapshot*. A snapshot is a digest, not the
source, so the live source was enumerated as well and every live item was classified. The
snapshot entries are additionally carried as their own ledger rows, so a named item that has
since vanished from the live enumeration cannot be quietly filed as covered.

Enumeration is read-only throughout: `for-each-ref`, `stash list`, `worktree list`,
`branch --contains`, `merge-base --is-ancestor`, `log`, `cat-file`, `diff --stat`. Nothing was
stashed, popped, dropped, applied, reset, cleaned, checked out or pruned in any evidence
source, and no ref was moved — the only ref writes were additive
(`refs/orch-preserved/<slug>-attempt-prior`).

## Result — 632 evidence items, zero UNKNOWN

| Classification | Count |
| --- | --- |
| SUPERSEDED_BY_NEWER | 291 |
| ALREADY_PRESENT | 221 |
| RECOVERABLE_VALUE | 65 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 52 |
| ACTIVE_IN_ANOTHER_TASK | 3 |
| **UNKNOWN** | **0** |

By evidence class:

| Kind | Items |
| --- | --- |
| orchestrator_rescue_refs (`refs/orch-rescue/*`) | 580 |
| dirty_worktree | 26 |
| local_only_branch_tips | 21 |
| chatgpt_bridge_artifact | 2 |
| codex_output_artifact | 1 |
| snapshot rows (from the prompt) | 2 |

`git stash list` is empty on this repo, so the stash class contributes no items.

## The two snapshot entries

- `.../Codex/2026-08-07/cons/work/orchestrator-session-fabric` — the recorded path no longer
  resolves its git metadata, but the live enumeration finds its successor worktree
  `orchestrator-session-fabric-current` (`59de85f2`, 18 uncommitted paths) whose tracked diff
  still applies to `origin/master`. Rolled up as **RECOVERABLE_VALUE**; the worst case governs
  the snapshot row rather than the reassuring one. The source worktree was not touched.
- `.../chatgpt-dropbox/_applied/20260811-160222--claude-orchestrator--chatgpt-local-queue-bridge-20260811.zip`
  — bridge artifact, status `applied`, shipped as PR #20. Its sha is no longer readable in this
  object store, so there is nothing left on disk to lose: **ALREADY_PRESENT**.

## Items with remaining value

65 RECOVERABLE_VALUE items (58 rescue refs, 4 dirty worktrees, 1 local-only tip
`fix/session-20260816-repairs`, 1 bridge patch, 1 snapshot roll-up) and 52
CONFLICTED_NEEDS_FOCUSED_TASK items are recorded in the ledger with source, sha, disposition
and evidence, and published to `coordination_tasks` (`task_type='recovery_ledger'`, one row per
item, idempotent on `(audit_fingerprint, source)`). Nothing was force-applied over current code:
conflicted items are queued for a focused follow-up, not overwritten.

One bridge artifact is worth calling out: `_applied/20260812-020326--claude-orchestrator--
operator-output-truth-session-fabric-20260812.patch` is marked *applied* by the bridge, yet its
patch still applies cleanly to `origin/master` — the change never actually reached the default
branch. It is filed RECOVERABLE_VALUE rather than trusting the bridge's own status field.

The 3 ACTIVE_IN_ANOTHER_TASK items are each contained in a remote agent branch belonging to a
live QUEUED task (`recover-missing-branch-dropbox-wave-c-...-part-6-cross-app-platform`,
`factory-unblock-dropbox-wave-c-compounding-codegen-platform-spine-sl`,
`copyfix-beethoven-07180848-slice-3-public-landing-domain-intent-labels-copy`) and are left to
those tasks rather than duplicated here.

## Tooling

Reused master's reconcilers unchanged — `tools/reconcile_rescue_refs.py`,
`tools/reconcile_local_branches.py`, `tools/reconcile_worktree_evidence.py` (normally driven by
`tools/reconcile_all_evidence.py`; run as three parallel processes here because the host was
under load average 100+, then merged with the driver's own merge semantics). Snapshot mapping
uses `tools/map_snapshot_evidence.mjs`, whose `node --test` suite passes 8/8. Publishing uses
`tools/recovery_ledger_publish.py`.
