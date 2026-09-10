# Recovery ledger — `a8452a1f6114`

Audit fingerprint: `a8452a1f61147e1437778a5a83ceeecb05e738e011f1067ba173345f4cdfabf9`
Task slug: `chatgpt-local-reconcile-beethoven-a8452a1f6114`
Base: `origin/master` · reconciled 2026-09-10

Per-item records: `.orch/recovery-ledger-a8452a1f6114-worktrees.json`
Produced with the repo's existing read-only reconciler,
`tools/reconcile_worktree_evidence.py` — the live evidence set was enumerated
rather than the 14-item snapshot in the task prompt. Nothing was stashed,
popped, reset, cleaned or moved.

## Result

**86 evidence items classified, 0 UNKNOWN.**

| Classification | Count |
|---|---:|
| ALREADY_PRESENT | 57 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 16 |
| RECOVERABLE_VALUE | 9 |
| ACTIVE_IN_ANOTHER_TASK | 4 |

## The pass fixed the classifier before trusting it

The first run over this evidence returned **30 RECOVERABLE_VALUE**, and 23 of
those were a single filename repeated once per worktree: `.orch-worktree.json`,
the per-worktree identity marker `runner/worktree_identity.py` writes into every
agent worktree. It is not in `.gitignore`, so `git status` reports it untracked,
and `origin/master` does not carry the path — exactly the shape the reconciler
reads as "authored work the base is missing".

`GENERATED_HINTS` already carried `/.orch/`, but that matches the *directory*.
The marker sits at the worktree root, so it slipped through. Acting on that
classification would have committed 23 copies of the orchestrator's own
bookkeeping as recovered source — the same defect `is_own_task_scratch` was
added to stop one layer down, where a reconcile pass recovers the exhaust of the
previous pass.

Two changes, both on this branch:

- `tools/reconcile_worktree_evidence.py` gained `ORCH_SCRATCH_BASENAMES` /
  `ORCH_SCRATCH_PREFIXES`, matched on **basename**. The first attempt added the
  filename to the substring-matched `GENERATED_HINTS` and a test immediately
  caught it excluding an authored `docs/.orch-worktree.json.md` — a rule that
  quietly drops real files is the expensive direction of this trade, so the rule
  is anchored instead.
- `tools/reconcile-local-evidence.mjs` gained the same entry in its already
  `$`-anchored `ORCH_SCRATCH_RE`, so the two lists agree deliberately rather
  than by coincidence.

Regression test: `tools/tests/test_worktree_evidence_orch_scratch.py`, 17 tests
— scratch excluded, previously-covered artefacts still excluded, and authored
paths (including `runner/db.py`, migrations, `CLAUDE.md`) still recognised.

After the fix the same 86 items reclassify to 9 RECOVERABLE_VALUE.

## The 9 items that keep value

| Source | Files | Disposition |
|---|---|---|
| `…-wt/improve-enhance-branch-management-…-slice-2` | `runner/tests/test_adaptive_pipeline.py` | **Integrated** on `agent/chatgpt-local-reconcile-beethoven-4a838e298f31` (18 passed) |
| `…-wt/improve-enhanced-testing-pipeline-inspect-local-br-slice-2` | `runner/tests/test_adaptive_budget.py` | **Integrated** on the same branch (18 passed) |
| `…-wt/improve-enhance-test-automation-…-slice-5` | `runner/tests/test_action_drafter.py` | Hangs; preserved as artifact, follow-up `fix-recovered-test-action-drafter-4a838e298f31` |
| `…-wt/improve-enhanced-testing-pipeline-fix-source-confi-slice-4` | `runner/tests/test_cross_project_templates.py` | 2 failed; follow-up `fix-recovered-test-cross-project-templates-4a838e298f31` |
| `…-wt/improve-implement-real-time-queue-state-update-slice-5` | `runner/tests/test_adaptive_probe.py` | 3 failed, 52s; follow-up `fix-recovered-test-adaptive-probe-4a838e298f31` |
| `…-wt/chatgpt-local-reconcile-beethoven-62b37b518e5e` | `docs/recovery-ledger-62b37b518e5e.json` | This session's sibling task; delivered on its own branch |
| `…-wt/chatgpt-local-reconcile-beethoven-a8452a1f6114` | the three files above | This branch — the change you are reading |
| `_applied/20260817-192242--apparently--absorb-otc-payoff-slice1` | `server/utils/otc/*`, `docs/absorption/STATUS-20260817.md` | **Wrong repo** — see below |
| `_applied/20260817-201758--apparently--absorb-otc-payoff-slice1-v2` | same | **Wrong repo** — see below |

Five of the nine were already adjudicated in this session under fingerprint
`4a838e298f31`, so they are recorded here and not recovered twice.

### The two `apparently` patches are not beethoven's to land

Both carry `server/utils/otc/...` and are named `--apparently--`: they are
`apparently`-repo work that happens to be parked in the shared ChatGPT dropbox
this sweep reads. They are classified as holding value because they do — just
not here. They were **not** applied, for two independent reasons: the paths do
not exist in this repo, and `apparently` is currently **paused** in `controls`
("HOLD 2026-09-01 … pending single-dev-branch consolidation"), so queuing work
against it from a beethoven task would route around a deliberate operator halt.
They stay in `_applied/` untouched, recorded here, for whoever lifts that hold.

## The 16 conflicted items

Recorded with full per-item provenance in the JSON. None were force-applied;
per the coordination rule a conflict earns a focused follow-up, not an
overwrite.
