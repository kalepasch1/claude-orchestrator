import assert from 'node:assert/strict'
import { test } from 'node:test'

import { resolveRef, rollUp } from './map_snapshot_evidence.mjs'

const BASE = 'origin/master'
// No live rows and nothing readable unless a case says otherwise: the default is the
// case that used to go wrong, so every test states its own git reality explicitly.
const io = (over = {}) => ({
  shaExists: () => true,
  containingBranches: () => [],
  remoteExists: () => false,
  ...over,
})

test('a snapshot ref matched to a live row adopts that row verbatim', () => {
  const live = [{ ref: 'refs/heads/agent/x', sha: 'a'.repeat(40),
    classification: 'RECOVERABLE_VALUE', disposition: 'applies cleanly' }]
  const r = resolveRef({ ref: 'agent/x', sha: 'a'.repeat(40) }, live, BASE, io())
  assert.equal(r.classification, 'RECOVERABLE_VALUE')
  assert.equal(r.disposition, 'applies cleanly')
})

test('an unreadable sha is already-present, not recoverable', () => {
  const r = resolveRef({ ref: 'agent/gone', sha: 'b'.repeat(40) }, [], BASE,
    io({ shaExists: () => false }))
  assert.equal(r.classification, 'ALREADY_PRESENT')
})

test('a sha contained in the base has shipped', () => {
  const r = resolveRef({ ref: 'agent/shipped', sha: 'c'.repeat(40) }, [], BASE,
    io({ containingBranches: () => ['remotes/origin/master', 'master'] }))
  assert.equal(r.classification, 'ALREADY_PRESENT')
})

test('a sha published on some other remote branch is owned elsewhere', () => {
  const r = resolveRef({ ref: 'agent/pushed', sha: 'd'.repeat(40) }, [], BASE,
    io({ containingBranches: () => ['remotes/origin/agent/pushed'] }))
  assert.equal(r.classification, 'ACTIVE_IN_ANOTHER_TASK')
})

// The regression this rule exists for: the live local-only pass deliberately skips a
// ref that has a remote counterpart, so an unmatched snapshot ref whose NAME is on
// origin is a tip the published branch moved past — not a conflict. Filing it as
// CONFLICTED buried the refs that genuinely had nowhere to go.
test('same name on origin at a different commit is superseded, not conflicted', () => {
  const r = resolveRef({ ref: 'agent/diverged', sha: 'e'.repeat(40) }, [], BASE,
    io({ remoteExists: (ref) => ref === 'agent/diverged' }))
  assert.equal(r.classification, 'SUPERSEDED_BY_NEWER')
})

test('a ref with no base, no remote and no live row needs a focused task', () => {
  const r = resolveRef({ ref: 'agent/orphan', sha: 'f'.repeat(40) }, [], BASE, io())
  assert.equal(r.classification, 'CONFLICTED_NEEDS_FOCUSED_TASK')
})

test('resolveRef never returns an unclassified verdict', () => {
  const allowed = new Set(['ALREADY_PRESENT', 'SUPERSEDED_BY_NEWER',
    'ACTIVE_IN_ANOTHER_TASK', 'RECOVERABLE_VALUE', 'CONFLICTED_NEEDS_FOCUSED_TASK'])
  for (const over of [{}, { shaExists: () => false }, { remoteExists: () => true },
    { containingBranches: () => ['remotes/origin/master'] }]) {
    const r = resolveRef({ ref: 'agent/any', sha: '0'.repeat(40) }, [], BASE, io(over))
    assert.ok(allowed.has(r.classification), `unclassified: ${r.classification}`)
  }
})

test('roll-up keeps the item with work left rather than the reassuring one', () => {
  assert.equal(rollUp(['ALREADY_PRESENT', 'RECOVERABLE_VALUE']), 'RECOVERABLE_VALUE')
  assert.equal(rollUp(['RECOVERABLE_VALUE', 'CONFLICTED_NEEDS_FOCUSED_TASK']),
    'CONFLICTED_NEEDS_FOCUSED_TASK')
  assert.equal(rollUp(['ALREADY_PRESENT']), 'ALREADY_PRESENT')
  assert.equal(rollUp([]), 'ALREADY_PRESENT')
})
