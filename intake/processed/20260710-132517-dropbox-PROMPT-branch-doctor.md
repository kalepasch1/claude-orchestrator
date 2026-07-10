# Branch Doctor — autonomous rebase/conflict/gate repair for agent branches

## Problem (from 2026-07-10 fleet brief)
The offline deploy sweep flagged 5 CONFLICT + 3 GATE-RED agent branches in
santas-secret-workshop that sat for days until an operator manually rebased and fixed
them. The failure classes were mechanical and recur across repos:
- CONFLICT: stale `package.json` build-script hunks vs base (resolution: prefer base side
  for build tooling files), plus lockfile drift.
- GATE-RED: test-pattern bugs — `assert.notMatch` (doesn't exist; use `assert.doesNotMatch`),
  extensionless relative imports under `node --test` type-stripping (need explicit `.ts`),
  calling a zustand hook outside React instead of using the store object
  (`useXStore()` → `useXStore` + `.getState()/.setState()`), and value-imports of types
  that Node can't strip (need `import type`).

## Objective
Build `runner/branch_doctor.py`, a recurring DB-independent job (wire into the sentinel
cadence like `git_deploy_sweep`, and runnable standalone) that:
1. Scans each repo in the deploy-sweep REPOS map for `agent/*` branches on origin that are
   behind base or previously logged CONFLICT/GATE-RED in `.runtime/git_deploy_sweep.jsonl`.
2. For each candidate, in an ISOLATED worktree (never the operator checkout):
   rebase onto `origin/<base>`; auto-resolve conflicts confined to lockfiles and
   package.json script hunks by preferring the base side; abort cleanly on any other
   conflict shape and record it.
3. Run the repo's gate. On failure, apply the known mechanical fix patterns above
   (conservative AST/regex transforms limited to test files, except `import type`
   tightening which may touch source) and re-run the gate once.
4. On green: force-push with `--force-with-lease` pinned to the pre-rebase SHA, agent
   branches only — never base/master.
5. On anything unresolved: append one line to a `branch-doctor` ledger
   (`.runtime/branch_doctor.jsonl`) and raise a single clustered approval card per repo
   per day (not per branch) so the operator sees a digest, not spam.

## Constraints
- Follow repo conventions: fail-soft everywhere, env-var tunables
  (`ORCH_BRANCH_DOCTOR_ENABLED`, per-run branch cap default 10), thread-safe, no secrets.
- Gate `--force-with-lease` on the exact observed SHA; skip if lease fails.
- 20+ unit tests: conflict-resolution policy, each fix pattern transform, lease pinning,
  ledger writes, cap enforcement, disabled-by-env.

## Acceptance
- Running against a fixture repo with a seeded package.json conflict and a seeded
  `assert.notMatch` failure lands both branches green without human input.
- A conflict outside the allowed shapes is left untouched and appears in the ledger +
  one clustered approval card.
