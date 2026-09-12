# ChatGPT/Codex local build-evidence reconciliation — beethoven (rescue refs + broken worktrees + bridge artifacts)

- Audit fingerprint: `6642a2ea908cbdbc8fa1267b3c62224e240830a567e966a5281c2e832786ca30`
- Task: `chatgpt-local-reconcile-beethoven-6642a2ea908c`
- Evidence kinds: `orchestrator_rescue_refs`, `dirty_worktree`,
  `broken_codex_git_worktree`, `chatgpt_bridge_artifact`, `codex_output_artifact`
- Evidence sources (all read-only): `refs/orch-rescue/*`, every registered worktree,
  `~/Documents/chatgpt-dropbox`, and the Codex session directory
  `~/Documents/Codex/2026-08-07/cons/work/orchestrator-session-fabric`
- Items enumerated: **638**
- UNKNOWN items: **0**

## Classification summary

| Classification | Count |
|---|---|
| ALREADY_PRESENT | 231 |
| SUPERSEDED_BY_NEWER | 224 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 94 |
| RECOVERABLE_VALUE | 54 |
| ACTIVE_IN_ANOTHER_TASK | 35 |

Ledger: `.orch/recovery-ledger-6642a2ea908c.json`, one `coordination_tasks` record per
item under this fingerprint.

## The finding: "recoverable" and "unowned" are not the same question

The worktree reconciler classified three dirty worktrees as **RECOVERABLE_VALUE**:

| worktree | uncommitted | owning task | state |
|---|---|---|---|
| `canary-deepseek-1` | `runner/tests/conftest.py` | `canary-deepseek-1` | **RUNNING** |
| `orch-cross-project-depends` | `runner/runner.py` | `orch-cross-project-depends` | **RUNNING** |
| `madeus-group-3` | 6 new `web/server/**/embed*` files | `dropbox-beethoven-madeus-web-…-group-3` | **RUNNING** |

Every one of them was being edited by another executor account at the moment this pass
ran. Git said what git can see — the diff applies to base, nobody has pushed it — and by
that evidence all three looked like dropped work. Recovering any of them would have raced
a live agent for the same files and re-delivered work already in flight.

Git cannot answer this. The question is not "does this apply" but "is somebody holding
it", and that lives in task state.

### `tools/live_task_owner.py`

A standalone lookup: given a worktree path, return the live task that owns it, or
`None`.

- `slug_from_path()` strips what worktree directory names carry and task slugs do not —
  a trailing short sha, a space-separated suffix from a malformed registration.
- Ownership resolves by exact slug, then by longest matching prefix, because the runner
  truncates long slugs when it names a worktree.
- `LIVE_STATES` (QUEUED / RUNNING / DECOMPOSED / BLOCKED) means somebody will still ship
  it. QUEUED counts: an unstarted owner is still an owner.
- The query filters on state **server-side**. An unfiltered `tasks` scan pages against a
  1000-row cap, and a live owner past that cap reads as "nobody owns this" — precisely
  the wrong answer, and silently so.
- Fail-soft: unreachable task state yields "no known owner" rather than raising, so a
  reconciler with no database still produces a ledger. `strict=True` inverts that for
  callers who would rather defer than race.

It is deliberately **standalone** rather than wired into
`tools/reconcile_worktree_evidence.py`. That file is already modified on sibling branch
`agent/chatgpt-local-reconcile-beethoven-a7f5bb34989f`; editing it here too would put two
versions of one file on two branches and reproduce the unmergeable chain the previous
reconciliation pass had to unpick. Wiring is queued as a focused follow-up that depends
on both branches landing.

`tools/test_live_task_owner.py`: 14 cases, task state injected, no database touched.

## An honest gap this pass could not close

`madeus-group-3` is owned by
`dropbox-beethoven-madeus-web-multi-tenant-claude-preneur-platform-bi-group-3`, but its
directory name is not a prefix of that slug, so the lookup cannot prove it. It is
recorded as **CONFLICTED_NEEDS_FOCUSED_TASK** with that reason stated, not quietly
recovered and not quietly dropped. The general fix belongs in the runner — name a
worktree after the slug it serves — and is noted in the follow-up.

## Corrected from the first run

This task's worktree evidence was re-classified with the fixed untracked-vs-base check
from sibling `a7f5bb34989f`. Without it, `spine-types-x2` counted as recoverable on the
strength of a `packages/spine/package-lock.json` that `origin/master` already carries
byte-identically.

## What still holds value, and where it goes

- 2 `chatgpt_bridge_artifact` items in `_applied/` whose patches still apply — both
  target the **`apparently`** repo, not this one, and are queued there as
  `apparently-recover-otc-payoff-slice1-bridge-marked-applied`.
- 52 `refs/orch-rescue/*` recoverables — the shared population, owned by sibling
  `agent/chatgpt-local-reconcile-beethoven-b4da5a48b1ee`. Not duplicated here.

## Provenance

- Nothing deleted, reset, cleaned, popped or moved. Dirty worktrees were inspected in
  place and left exactly as found — which matters more than usual here, given three of
  them had an agent working in them.
- This task's own worktree is excluded from its own evidence.
