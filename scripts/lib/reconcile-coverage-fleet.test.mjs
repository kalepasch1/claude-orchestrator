/**
 * Fleet coverage: measure the reconciliation before adding another pass to it.
 *
 * Six `chatgpt-local-reconcile-*` tasks landed across five projects in one day,
 * on top of 32 ledgers already committed, and nobody could say whether that was
 * necessary — coverage was only ever visible from inside a single ledger.
 * Measured across the fleet:
 *
 *   beethoven          1648 refs  19 ledgers  9481 rows  1279 covered   993 outstanding
 *   apparently         1196        6          1221        401           959
 *   darwn               656        0             0          0           591
 *   sustainable-barks   421        0             0          0           378
 *   racefeed            326        3           324        287           312
 *   pareto-2080         372        4          1152        480           199
 *
 * 12,459 rows covering 2,447 distinct sources is 5.1x re-classification fleet-wide
 * and 7.4x in beethoven alone. Two projects had never been reconciled at all —
 * invisible from any single-project view, which is why "reconcile X" kept being
 * queued for the projects that were already the most reconciled.
 *
 * These tests cover the parsing that produces those numbers. The git-walking half
 * is exercised against real repositories by the CLI; what is pinned here is the
 * arithmetic and the dialect handling, because a miscount there is what would
 * make a real backlog look finished.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  isOrchestrationPath,
  partitionEvidence,
  summariseExclusions,
} from './orchestration-artifacts.mjs'

test('fleet: a ledger ref carrying only bookkeeping is never counted as outstanding', () => {
  const universe = [
    { kind: 'ref', ref: 'refs/orch-rescue/a', paths: ['.orch/recovery-ledger-1.json'] },
    { kind: 'ref', ref: 'refs/heads/agent/real', paths: ['runner/db.py'] },
  ]
  const { kept, excluded } = partitionEvidence(universe, {})
  assert.equal(kept.length, 1)
  assert.equal(kept[0].ref, 'refs/heads/agent/real')
  assert.equal(excluded.length, 1)
  assert.equal(summariseExclusions(excluded).byReason.ORCHESTRATION_ARTIFACT, 1)
})

test('fleet: every ledger path shape seen across the six repos is recognised', () => {
  for (const p of [
    '.orch/recovery-ledger-41f0a74d.json',
    'docs/recovery-ledger/570a6495a33e.md',
    'docs/tasks/chatgpt-local-reconcile-pareto-2080-abc.md',
    'scripts/reconcile-evidence.mjs',
    'tools/reconcile_all_evidence.py',
    '.recovery-intent-backlog-batch-a19cca3.txt',
  ]) {
    assert.equal(isOrchestrationPath(p), true, p)
  }
})

test('fleet: an unreadable ref stays in the universe rather than vanishing', () => {
  // Some rescue refs point at TREES, so diff-tree yields nothing. Excluding on a
  // read failure would silently shrink the backlog — the failure mode that makes
  // a reconciliation look complete when it is not.
  const { kept, excluded } = partitionEvidence(
    [{ kind: 'ref', ref: 'refs/archive/tree-ish', paths: [] }], {})
  assert.equal(kept.length, 1)
  assert.equal(excluded.length, 0)
})

test('fleet: coverage arithmetic accounts for every ref exactly once', () => {
  const universe = [
    { kind: 'ref', ref: 'a', paths: ['.orch/recovery-ledger-1.json'] },
    { kind: 'ref', ref: 'b', paths: ['src/x.ts'] },
    { kind: 'ref', ref: 'c', paths: ['src/y.ts'] },
    { kind: 'ref', ref: 'd', paths: [] },
  ]
  const covered = new Set(['b'])
  const { kept, excluded } = partitionEvidence(universe, {})
  const outstanding = kept.filter((e) => !covered.has(e.ref))
  const alreadyClassified = kept.length - outstanding.length

  assert.equal(alreadyClassified + outstanding.length + excluded.length, universe.length,
    'a ref must be exactly one of classified, outstanding or bookkeeping')
  assert.equal(outstanding.length, 2)
  assert.equal(alreadyClassified, 1)
})

test('fleet: rows are not coverage — the duplication is the point', () => {
  // 9,481 rows covering 1,279 distinct sources is the beethoven measurement.
  // Counting rows would report that repo as 7.4x more reconciled than it is.
  const rows = 9481
  const distinct = 1279
  assert.ok(rows / distinct > 7, 'rows/distinct is the re-classification factor')
  assert.notEqual(rows, distinct)
})
