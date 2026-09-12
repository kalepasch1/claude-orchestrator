/**
 * The reconciliation loop must not feed on its own output.
 *
 * Observed across ~30 reconcile runs: a rescue ref whose only source file was a
 * sibling reconcile script arrived as the next pass's evidence; a sweep whose 85
 * paths were entirely sibling ledgers; refs created by the sweeper DURING a run
 * and classified by that same run. Each pass manufactured evidence for the next,
 * so the queue could not converge while the tasks looked like progress.
 *
 * The restriction matters as much as the rule: an item is excluded only when
 * EVERY path it carries is bookkeeping. Excluding a mixed item would discard real
 * unshipped work — the exact loss this reconciliation exists to prevent.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  EXCLUSION_REASONS,
  allPathsAreOrchestration,
  createdDuringRun,
  exclusionReason,
  isOrchestrationPath,
  isScaffoldingPath,
  partitionEvidence,
  summariseExclusions,
} from './orchestration-artifacts.mjs'

// ── which paths are bookkeeping ──────────────────────────────────────────────

test('recognises every bookkeeping path the loop kept re-ingesting', () => {
  for (const p of [
    '.orch/recovery-ledger-41f0a74d.json',
    'docs/tasks/chatgpt-local-reconcile-pareto-2080-abc123.md',
    'docs/recovery-ledger/570a6495a33e.md',
    'docs/recovery-ledger-11a417e1202b.md',
    'docs/recovery/chatgpt-local-reconcile-pareto-2080-03bd7d62007c.md',
    'scripts/reconcile-evidence.mjs',
    'scripts/reconcile-local-evidence.mjs',
    'scripts/recovery/evidence-provenance-41f0a74d.mjs',
    'tools/reconcile_all_evidence.py',
    '.recovery-intent-backlog-batch-a19cca3.txt',
  ]) {
    assert.equal(isOrchestrationPath(p), true, `${p} should be bookkeeping`)
  }
})

test('does not mistake real source for bookkeeping', () => {
  for (const p of [
    'runner/periodic.py',
    'scripts/reconcile.md', // not scripts/reconcile-*
    'server/utils/referralStore.ts',
    'docs/architecture.md',
    'src/tools/reconcile_ui.tsx', // tools/ must be top-level
    'app/reconcile-evidence.mjs', // scripts/ must be top-level
  ]) {
    assert.equal(isOrchestrationPath(p), false, `${p} is real work`)
  }
})

test('recognises fleet scaffolding directories', () => {
  assert.equal(isScaffoldingPath('/Users/x/Documents/darwn/darwn-wt/some-slug/file.ts'), true)
  assert.equal(isScaffoldingPath('/private/tmp/pareto-baseline/x'), true)
  assert.equal(isScaffoldingPath('/tmp/beethoven-baseline'), true)
  assert.equal(isScaffoldingPath('/Users/x/Documents/darwn/darwn/file.ts'), false)
})

// ── the restriction: mixed content is still evidence ─────────────────────────

test('a set of only bookkeeping paths is bookkeeping', () => {
  assert.equal(allPathsAreOrchestration([
    '.orch/recovery-ledger-a.json', 'docs/recovery-ledger/b.md',
  ]), true)
})

test('ONE real file makes the whole item evidence again', () => {
  assert.equal(allPathsAreOrchestration([
    '.orch/recovery-ledger-a.json', 'runner/periodic.py',
  ]), false, 'excluding this would discard real unshipped work')
})

test('an unreadable item is not bookkeeping', () => {
  // "we could not read what it carries" is not "it carries only ledgers".
  assert.equal(allPathsAreOrchestration([]), false)
  assert.equal(allPathsAreOrchestration(null), false)
})

// ── run scaffolding ──────────────────────────────────────────────────────────

test('a ref created after the run began belongs to the run', () => {
  assert.equal(createdDuringRun('2026-08-23T10:00:01Z', '2026-08-23T10:00:00Z'), true)
})

test('a ref created before the run began is still evidence', () => {
  assert.equal(createdDuringRun('2026-08-23T09:59:59Z', '2026-08-23T10:00:00Z'), false)
})

test('unknown or unparseable times keep the item in the universe', () => {
  assert.equal(createdDuringRun(null, '2026-08-23T10:00:00Z'), false)
  assert.equal(createdDuringRun('not a date', '2026-08-23T10:00:00Z'), false)
  assert.equal(createdDuringRun('2026-08-23T10:00:01Z', null), false)
})

// ── the acceptance cases named in the task ───────────────────────────────────

test('ACCEPTANCE: a rescue ref containing only a recovery ledger is excluded, not classified', () => {
  const ref = {
    kind: 'rescue_ref',
    ref: 'refs/orch-rescue/20260817T004119-reconcile-250fb499',
    paths: ['scripts/reconcile-evidence.mjs'],
  }
  const verdict = exclusionReason(ref)
  assert.ok(verdict, 'a sibling reconcile artifact must never reach a verdict')
  assert.equal(verdict.reason, EXCLUSION_REASONS.BOOKKEEPING)

  const { kept, excluded } = partitionEvidence([ref])
  assert.equal(kept.length, 0)
  assert.equal(excluded.length, 1)
  assert.equal(excluded[0].classification, undefined, 'excluded items carry no classification')
})

test('ACCEPTANCE: a sweep of only sibling ledgers is excluded', () => {
  const sweep = {
    kind: 'rescue_ref',
    ref: 'refs/orch-rescue/20260818T000000-main-worktree',
    paths: Array.from({ length: 85 }, (_, i) => `.orch/recovery-ledger-${i}.json`),
  }
  const verdict = exclusionReason(sweep)
  assert.equal(verdict.reason, EXCLUSION_REASONS.BOOKKEEPING)
  assert.match(verdict.detail, /all 85 path\(s\)/)
})

test("ACCEPTANCE: a run's own scaffolding is excluded", () => {
  const runStartedAt = '2026-08-23T10:00:00Z'
  const madeByThisRun = {
    kind: 'rescue_ref',
    ref: 'refs/orch-rescue/20260823T100500-sweep',
    paths: ['runner/periodic.py'], // real content, but it did not exist before the run
    createdAt: '2026-08-23T10:05:00Z',
  }
  const worktree = {
    kind: 'worktree',
    ref: '/Users/x/Documents/darwn/darwn-wt/some-slug',
    paths: [],
  }
  const { kept, excluded } = partitionEvidence([madeByThisRun, worktree], { runStartedAt })
  assert.equal(kept.length, 0)
  assert.equal(excluded.length, 2)
  for (const e of excluded) assert.equal(e.exclusionReason, EXCLUSION_REASONS.SCAFFOLDING)
})

test('ACCEPTANCE: exclusions are named and counted, never silently dropped', () => {
  const { excluded } = partitionEvidence([
    { kind: 'rescue_ref', ref: 'a', paths: ['.orch/recovery-ledger-1.json'] },
    { kind: 'rescue_ref', ref: 'b', paths: ['tools/reconcile_x.py'] },
    { kind: 'worktree', ref: '/x/repo-wt/slug', paths: [] },
  ])
  for (const e of excluded) {
    assert.ok(e.ref, 'an excluded item keeps its identity')
    assert.ok(e.exclusionReason, 'and states why it was excluded')
    assert.ok(e.exclusionDetail, 'and says so in words a reader can check')
  }
  assert.deepEqual(summariseExclusions(excluded), {
    total: 3,
    byReason: { ORCHESTRATION_ARTIFACT: 2, RUN_SCAFFOLDING: 1 },
  })
})

// ── real work is never excluded ──────────────────────────────────────────────

test('an ordinary agent branch is kept', () => {
  const { kept, excluded } = partitionEvidence([
    { kind: 'branch', ref: 'refs/heads/agent/real-work', paths: ['runner/bandit.py'] },
  ])
  assert.equal(kept.length, 1)
  assert.equal(excluded.length, 0)
})

test('a rescue ref mixing a ledger with real work is kept', () => {
  const { kept, excluded } = partitionEvidence([
    {
      kind: 'rescue_ref',
      ref: 'refs/orch-rescue/mixed',
      paths: ['.orch/recovery-ledger-x.json', 'server/engines/hive/vertical-spawner.ts'],
    },
  ])
  assert.equal(kept.length, 1, 'one real file keeps the whole item in the universe')
  assert.equal(excluded.length, 0)
})

test('partition never loses an item', () => {
  const items = [
    { ref: 'a', paths: ['.orch/recovery-ledger-1.json'] },
    { ref: 'b', paths: ['runner/x.py'] },
    { ref: 'c', paths: [] },
  ]
  const { kept, excluded } = partitionEvidence(items)
  assert.equal(kept.length + excluded.length, items.length)
})

test('malformed entries do not throw', () => {
  assert.equal(exclusionReason(null), null)
  assert.equal(exclusionReason(undefined), null)
  assert.equal(exclusionReason('nonsense'), null)
  const { kept, excluded } = partitionEvidence([null, undefined])
  assert.equal(kept.length + excluded.length, 2)
})
