#!/usr/bin/env node
/**
 * Tests for scripts/reconcile-evidence.mjs.
 * Run: node --test scripts/reconcile-evidence.test.mjs
 *
 * These cover the classifiers for evidence git cannot enumerate for itself —
 * broken external worktrees and ChatGPT-bridge dropbox artifacts. Those are the
 * two kinds that previously fell off the end of a run into the UNKNOWN bucket,
 * and UNKNOWN is the one outcome the completion bar forbids, so they are the
 * two worth pinning down.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { after, before, describe, it } from 'node:test'

import {
  CLASSIFICATIONS,
  classifyBridgeArtifact,
  classifyExternalWorktree,
  collectFlag,
  enumerateBridgeArtifacts,
} from './reconcile-evidence.mjs'

let root
before(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), 'rec-ev-')) })
after(() => { try { fs.rmSync(root, { recursive: true, force: true }) } catch {} })

const ctx = (over = {}) => ({
  mainSha: 'HEAD',
  localDefaultSha: null,
  liveTaskSlugs: [],
  remoteBranches: new Set(),
  ...over,
})

/** A directory that looks like a worktree whose gitdir points wherever we say. */
function makeWorktree(name, gitdirTarget) {
  const dir = path.join(root, name)
  fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(path.join(dir, '.git'), `gitdir: ${gitdirTarget}\n`)
  return dir
}

describe('collectFlag', () => {
  it('collects every occurrence, so the flag is repeatable', () => {
    assert.deepEqual(collectFlag(['--w', 'a', '--w', 'b', '--other', 'c'], '--w'), ['a', 'b'])
  })

  it('ignores a flag whose value is another flag', () => {
    assert.deepEqual(collectFlag(['--w', '--json'], '--w'), [])
  })

  it('returns empty rather than throwing when the flag is absent', () => {
    assert.deepEqual(collectFlag([], '--w'), [])
  })
})

describe('classifyExternalWorktree', () => {
  it('never returns a classification outside the vocabulary', () => {
    const wt = makeWorktree('vocab', path.join(root, 'gone'))
    assert.ok(CLASSIFICATIONS.includes(classifyExternalWorktree(wt, ctx()).classification))
  })

  it('flags a vanished path for a human instead of passing it silently', () => {
    const r = classifyExternalWorktree(path.join(root, 'never-existed'), ctx())
    assert.equal(r.classification, 'CONFLICTED_NEEDS_FOCUSED_TASK')
  })

  it('defers to the registered-worktree pass when the gitdir still resolves', () => {
    const live = path.join(root, 'live-gitdir')
    fs.mkdirSync(live, { recursive: true })
    const wt = makeWorktree('healthy', live)
    const r = classifyExternalWorktree(wt, ctx())
    assert.equal(r.classification, 'ALREADY_PRESENT')
  })

  it('is CONFLICTED when the gitdir is gone and no ref is named for it', () => {
    const wt = makeWorktree('orphan-xyzzy-no-such-ref', path.join(root, 'pruned'))
    const r = classifyExternalWorktree(wt, ctx())
    assert.equal(r.classification, 'CONFLICTED_NEEDS_FOCUSED_TASK')
    assert.match(r.reason, /cannot be diffed/)
  })

  it('does not recover work a live task already owns', () => {
    const wt = makeWorktree('session-fabric', path.join(root, 'pruned'))
    const r = classifyExternalWorktree(wt, ctx({ liveTaskSlugs: ['recover-session-fabric'] }))
    assert.equal(r.classification, 'ACTIVE_IN_ANOTHER_TASK')
    assert.equal(r.owningTask, 'recover-session-fabric')
  })

  it('records that uncommitted drift is unreadable rather than assuming it is nothing', () => {
    // `refs/heads/master` ends in `/master`, so a worktree named `master` finds a home.
    const wt = makeWorktree('master', path.join(root, 'pruned'))
    const r = classifyExternalWorktree(wt, ctx())
    assert.equal(r.classification, 'RECOVERABLE_VALUE')
    assert.equal(r.uncommittedDriftUnreadable, true)
    assert.ok(r.preservedIn.length > 0)
  })
})

describe('classifyBridgeArtifact', () => {
  const zip = (bucket, name) => {
    const dir = path.join(root, 'dropbox', bucket)
    fs.mkdirSync(dir, { recursive: true })
    const p = path.join(dir, name)
    fs.writeFileSync(p, 'PK')
    return p
  }

  it('is ALREADY_PRESENT once a remote branch carries the payload', () => {
    const p = zip('_applied', '20260811-160222--claude-orchestrator--queue-bridge-20260811.zip')
    const r = classifyBridgeArtifact(p, ctx({
      remoteBranches: new Set(['chatgpt/queue-bridge-20260811-08111602']),
    }))
    assert.equal(r.classification, 'ALREADY_PRESENT')
    assert.deepEqual(r.preservedIn, ['origin/chatgpt/queue-bridge-20260811-08111602'])
  })

  it('does not take "_applied" as proof: no remote branch means the zip is the only copy', () => {
    const p = zip('_applied', '20260811-160222--claude-orchestrator--never-pushed.zip')
    const r = classifyBridgeArtifact(p, ctx())
    assert.equal(r.classification, 'RECOVERABLE_VALUE')
    assert.match(r.reason, /the remote says otherwise/)
  })

  it('sends an unrecoverable failed payload to a human', () => {
    const p = zip('_failed', '20260811-160222--claude-orchestrator--broke.zip')
    const r = classifyBridgeArtifact(p, ctx())
    assert.equal(r.classification, 'CONFLICTED_NEEDS_FOCUSED_TASK')
  })

  it('flags an artifact the snapshot names but disk no longer has', () => {
    const r = classifyBridgeArtifact(path.join(root, 'dropbox', '_applied', 'gone.zip'), ctx())
    assert.equal(r.classification, 'CONFLICTED_NEEDS_FOCUSED_TASK')
  })
})

describe('enumerateBridgeArtifacts', () => {
  it('reads both buckets and ignores non-zips', () => {
    const dir = path.join(root, 'dropbox2')
    for (const b of ['_applied', '_failed']) fs.mkdirSync(path.join(dir, b), { recursive: true })
    fs.writeFileSync(path.join(dir, '_applied', 'a.zip'), 'PK')
    fs.writeFileSync(path.join(dir, '_applied', 'notes.txt'), 'x')
    fs.writeFileSync(path.join(dir, '_failed', 'b.zip'), 'PK')
    const found = enumerateBridgeArtifacts(dir).map((p) => path.basename(p)).sort()
    assert.deepEqual(found, ['a.zip', 'b.zip'])
  })

  it('returns empty for a dropbox that is not configured or not there', () => {
    assert.deepEqual(enumerateBridgeArtifacts(null), [])
    assert.deepEqual(enumerateBridgeArtifacts(path.join(root, 'no-dropbox')), [])
  })
})
