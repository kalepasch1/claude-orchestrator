# `_Trojun_archived` triage (audit 165f6c7173b5, 2026-08-23)

`/Users/kpasch/Documents/_Trojun_archived` was reported by
`tools/reconcile_unregistered_repos.py` as RECOVERABLE_VALUE with **223
uncommitted paths** — "the single largest pocket of unreviewed local state
found in the sweep".

**Nothing in it is recoverable into `claude-orchestrator`.** The headline number
was an artifact of two bugs in the scanner, both fixed alongside this note.

The checkout is READ-ONLY and was left exactly as found: not deleted, reset,
cleaned, stashed, moved, or registered as a project.

## STEP 1 — the split

HEAD is `e3b5c172` (2026-07-26, "feat: add Multiplayer Hivemind Development
System (5-layer)"), which is **not** an ancestor of `origin/master`.

| | count |
|---|---:|
| tracked modifications | **1** |
| untracked entries (as `--porcelain` reported them) | 222 |
| untracked files (expanded, `-uall`) | 227 |

So 222 of the 223 "uncommitted paths" were untracked, and the one tracked
modification is `web/components/StatusPill.vue`.

### The 227 untracked files

| | count |
|---|---:|
| byte-identical to `origin/master` at a shifted path | **169** |
| present on master but different | 14 |
| absent from master | 44 |

The 169 are `web/supabase/migrations/*.sql` — master carries the same files at
`supabase/migrations/`, without the `web/` prefix. Same bytes, different path.
Nothing to recover.

The 44 absent files are a **different product**: `web/pages/advisory.vue`,
`filings.vue`, `regulatory.vue`, `policies.vue`, `assessments.vue`,
`web/components/IlluminatiLogo.vue`, and 16 migrations named
`create_gateway_requests`, `legal_escalations`, `monetization_scaffolding`,
`cascade_operations`, `fleet_agents`, `terminal_logs`. That is the
Trojun/Illuminati surface built inside a clone of this repo, not orchestrator
work. Landing it here would be wrong.

### The 14 that exist on master but differ

Every one is a near-total rewrite, and in most cases the Trojun copy is the
*smaller, earlier* one:

| file | Trojun | master |
|---|---:|---:|
| `web/composables/useFleetWebSocket.ts` | 57 | 139 |
| `web/composables/useOrchestratorSnapshot.ts` | 30 | 82 |
| `runner/suggestion_engine.py` | 100 | 198 |
| `runner/qa_agents.py` | 191 | 122 |
| `runner/verification_pipeline.py` | 196 | 117 |

`useOrchestratorSnapshot.ts` is a file master has actively developed since;
taking the 30-line version would be a large regression.

`web/components/StatusPill.vue`, the single tracked modification, is not an
edit to master's component at all — it is a different component with a
different prop API (`status: string` vs master's `label` + `tone`) that happens
to share a filename.

## The two scanner bugs this exposed

Both fixed in `tools/reconcile_unregistered_repos.py`, with regression tests in
`tools/test_reconcile_unregistered_repos.py`.

**1. Untracked files were counted as work at risk.** `dirty_paths` summed
tracked modifications and untracked files into one number, and any non-zero
value produced RECOVERABLE_VALUE. A tracked modification overwrites content the
base already has, so losing the checkout loses it for good; an untracked file
may be a stale copy, build output, or an entire other project. They are now
counted separately, and untracked-only state classifies as
`UNTRACKED_NEEDS_TRIAGE` — "diff these against the base before queueing
recovery" — instead of asserting value nobody has checked.

**2. Unpushed-branch detection never fired — the worse bug.** The scan ran

```
git rev-list --count --not --remotes <branch>
```

`--not` negates everything that follows it, so this excluded the branch as well
as the remotes and returned `0` for *every* branch in *every* repo. An
unregistered checkout holding genuinely unpushed commits on a clean tree was
therefore classified ALREADY_PRESENT — silent loss, which is the one thing this
scan exists to prevent. The branch must come before `--not`.

`--porcelain` also collapses an untracked directory into a single `?? dir/`
entry, so the counts understated reality; the scan now uses `-uall`.

## Recommendation

Close `recover-unregistered-repo-trojun-archived-223-dirty` as triaged. Do not
register `_Trojun_archived` as a project — the `_archived` prefix looks
deliberate, and its contents belong to a different product. Re-running the
fixed scanner will reclassify it `UNTRACKED_NEEDS_TRIAGE`, and may surface
checkouts with real unpushed commits that the `--not` bug has been hiding.
