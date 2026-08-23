# ChatGPT/Codex local build-evidence reconciliation — beethoven (rescue refs, recovery pass)

- Audit fingerprint: `b4da5a48b1eeb8276582676a4fb8c4b792004fbdbc9e911f67926f35fec527f3`
- Task: `chatgpt-local-reconcile-beethoven-b4da5a48b1ee`
- Evidence kind: `orchestrator_rescue_refs` — `refs/orch-rescue/*`, read-only
- Refs enumerated: **601**
- UNKNOWN items: **0**

## Classification summary

| Classification | Count |
|---|---|
| SUPERSEDED_BY_NEWER | 225 |
| ALREADY_PRESENT | 207 |
| CONFLICTED_NEEDS_FOCUSED_TASK | 112 |
| RECOVERABLE_VALUE (recovered on this branch) | 25 |
| ACTIVE_IN_ANOTHER_TASK | 32 |

Ledger: `.orch/recovery-ledger-b4da5a48b1ee.json`, one `coordination_tasks` record per
ref. Each recovered ref carries `recovered_on`, so the branch that took it is part of the
record rather than something to infer.

## This is the branch that actually takes the rescue refs

Four tasks in this session enumerate the same `refs/orch-rescue/*` population and all four
find the same ~52 refs that still hold value. This one's evidence is rescue refs **alone**,
so it owns them; the siblings record the ownership and take nothing. That division is
deliberate — the previous reconciliation pass produced five sibling branches chained on
each other, each carrying the others' commits, and the merge train could not integrate any
of them.

## How the refs were selected, and why the obvious way was wrong

The first attempt applied all 52 in one pass. The result had conflict markers in three
runner modules, deleted seven unrelated `HOLD-PROMPT-*.md` files, and created a file
literally named `Updated show_greeting.py`. That tree was discarded, not committed.

The pass that produced this branch has three stages:

1. **Probe in isolation.** Each ref applied alone against a pristine tree, then reset, so
   one ref's mess never contaminates the next one's verdict. 48 clean, 2 malformed
   (patch fragments whose "filenames" are lines of Python), 1 no-op, 1 deletes tracked
   paths.
2. **Apply sequentially, oldest first,** rolling back to the last good tree on any
   failure. 27 landed; 21 apply alone but not once their siblings are in — recorded as
   CONFLICTED with that exact reason rather than forced.
3. **Run the suite and compare against master**, because "the patch applies" and "the
   result works" are different claims.

Two of the 27 were then dropped on evidence:

- `20260807T173615-claude-orchestrator-12001806` → `runner/bandit.py`. Applies perfectly
  and produces a tree that will not import: `PerformanceTracker.__init__` reads
  `ACCEPTANCE_CONFIDENCE`, which is undefined — **in the ref's own tree as well**. It came
  from an auto-resolved merge that dropped the constant block, so the evidence is broken at
  the source, not by the recovery. 51 bandit tests fail with `NameError`. Reverted;
  reconstructing the missing definition is queued as a focused task.
- `20260805T145454-deployfix-…-vercel-production-build` → `.vercel/project.json` only.
  That file is Vercel CLI link state, not source. Recovering it rewrites deploy
  configuration for no product change.

**25 refs recovered**, spanning `runner/` (`config_store`, `fleet_control`,
`priority_scorer`, `slo_controller`, `release_train`, `pipeline_metrics`,
`ab_test_framework`, `contract_validator`, `resource_medic`, `write_guard`,
`reconcile_agent_branches`), `packages/darwin-kernel/` (passport + fleet-admin guidance),
`pareto/2080/household_legal/`, and `tools/map_snapshot_evidence.mjs` — several with the
tests that came with them.

## Test evidence

The full `runner/tests` suite was run on this branch and on a pristine `origin/master`
worktree, same machine, same session.

`origin/master` is not green: **799 failed, 15 errors, 12852 passed**. That is a
pre-existing fleet condition, and it is exactly why "the suite passes" was not usable as
the acceptance signal here. The comparison is set-difference against the baseline, not an
absolute pass rate.

The `bandit.py` regression above is the entire reason the two-stage check exists: without
the baseline comparison, 51 new failures would have been invisible inside 799 existing
ones.

Recovering these refs also **fixes 17 tests that fail or error on master** — all 15 errors
in `test_release_on_capacity.py` plus two `test_pipeline_metrics.py` fail-soft cases. The
work being recovered here is, in part, the work that was supposed to fix them.

## Deferred, with the reason recorded

112 CONFLICTED items, each with its own reason in the ledger: 21 refs that apply alone but
not alongside their siblings, 86 whose diffs no longer apply to master at all, the broken
`bandit.py` merge, and the malformed-patch fragments whose paths are not filenames.

## Provenance

- Every one of the 601 `refs/orch-rescue/*` refs is intact. Nothing was deleted, reset,
  cleaned, popped or moved; the recovery worktree is a fresh isolated checkout and the
  refs were only ever read.
- Recovered content lives on this branch alone.
