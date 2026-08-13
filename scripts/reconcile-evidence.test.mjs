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
  buildPreservationPlan,
  classifyBridgeArtifact,
  classifyExternalWorktree,
  collectFlag,
  enumerateBridgeArtifacts,
  classifyCodexOutput,
  readBridgeReceipt,
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

describe('buildPreservationPlan', () => {
  const branch = (name, over = {}) => ({
    kind: 'branch',
    ref: `refs/heads/${name}`,
    sha: 'a'.repeat(40),
    classification: 'RECOVERABLE_VALUE',
    remotePreserved: false,
    uniqueCommits: 3,
    ...over,
  })

  it('plans a push for every recoverable tip with no remote copy', () => {
    const { script, atRisk } = buildPreservationPlan([branch('agent/one'), branch('agent/two')])
    assert.equal(atRisk, 2)
    assert.match(script, /push a{40} refs\/preserved\/agent\/one/)
    assert.match(script, /push a{40} refs\/preserved\/agent\/two/)
  })

  it('never plans a push into refs/heads — a preserved ref must not become a branch', () => {
    const { script } = buildPreservationPlan([branch('agent/one')])
    assert.ok(!/refs\/heads\//.test(script.split('\n').filter((l) => l.startsWith('push ')).join('\n')))
  })

  it('defaults to a dry run so the operator sees the plan first', () => {
    const { script } = buildPreservationPlan([branch('agent/one')])
    assert.match(script, /APPLY="\$\{APPLY:-0\}"/)
    assert.match(script, /would push/)
  })

  it('skips tips a remote already preserves', () => {
    const { atRisk } = buildPreservationPlan([branch('agent/safe', { remotePreserved: true })])
    assert.equal(atRisk, 0)
  })

  it('skips anything that is not a recoverable branch', () => {
    const { atRisk } = buildPreservationPlan([
      branch('agent/present', { classification: 'ALREADY_PRESENT' }),
      branch('agent/no-sha', { sha: null }),
      { ...branch('agent/rescue'), kind: 'rescue_ref' },
    ])
    assert.equal(atRisk, 0)
  })

  it('produces a runnable no-op script when nothing is at risk', () => {
    const { script } = buildPreservationPlan([])
    assert.match(script, /nothing at risk/)
    assert.match(script, /^#!\/usr\/bin\/env bash/)
  })

  it('honours an alternate namespace', () => {
    const { script } = buildPreservationPlan([branch('agent/one')], { namespace: 'refs/attic' })
    assert.match(script, /refs\/attic\/agent\/one/)
  })
})

describe('readBridgeReceipt', () => {
  const withReceipt = (name, body) => {
    const dir = path.join(root, 'receipts')
    fs.mkdirSync(dir, { recursive: true })
    const p = path.join(dir, name)
    fs.writeFileSync(p, 'payload')
    if (body !== null) fs.writeFileSync(`${p}.result.txt`, body)
    return p
  }

  it('reads the branch the bridge says it pushed', () => {
    const p = withReceipt(
      '20260812-020326--repo--thing.patch',
      '[chatgpt-bridge] default branch: master\n[chatgpt-bridge] pushed branch chatgpt/thing-08120203\nOK\n',
    )
    assert.equal(readBridgeReceipt(p), 'chatgpt/thing-08120203')
  })

  it('returns null when there is no receipt, rather than throwing', () => {
    assert.equal(readBridgeReceipt(withReceipt('a--b--c.patch', null)), null)
  })

  it('returns null when the receipt records no push', () => {
    const p = withReceipt('a--b--d.patch', '[chatgpt-bridge] failed to apply\n')
    assert.equal(readBridgeReceipt(p), null)
  })
})

describe('bridge artifacts beyond .zip', () => {
  const drop = () => {
    const dir = path.join(root, `drop-${Math.random().toString(36).slice(2)}`)
    fs.mkdirSync(path.join(dir, '_applied'), { recursive: true })
    return dir
  }

  it('enumerates .patch and .diff payloads, not just .zip', () => {
    const dir = drop()
    for (const f of ['a.zip', 'b.patch', 'c.diff', 'd.txt', 'b.patch.result.txt']) {
      fs.writeFileSync(path.join(dir, '_applied', f), 'x')
    }
    const found = enumerateBridgeArtifacts(dir).map((p) => path.basename(p)).sort()
    assert.deepEqual(found, ['a.zip', 'b.patch', 'c.diff'])
  })

  it('trusts the receipt over the filename when the bridge added a run suffix', () => {
    const dir = drop()
    const p = path.join(dir, '_applied', '20260812-020326--repo--thing-20260812.patch')
    fs.writeFileSync(p, 'x')
    fs.writeFileSync(`${p}.result.txt`, '[chatgpt-bridge] pushed branch chatgpt/thing-20260812-08120203\n')
    const r = classifyBridgeArtifact(p, {
      mainSha: 'HEAD',
      localDefaultSha: null,
      liveTaskSlugs: [],
      remoteBranches: new Set(['chatgpt/thing-20260812-08120203']),
    })
    assert.equal(r.classification, 'ALREADY_PRESENT')
    assert.deepEqual(r.preservedIn, ['origin/chatgpt/thing-20260812-08120203'])
  })

  it('still classifies a .patch with no remote as the last copy', () => {
    const dir = drop()
    const p = path.join(dir, '_applied', '20260812-020326--repo--orphan.patch')
    fs.writeFileSync(p, 'x')
    const r = classifyBridgeArtifact(p, {
      mainSha: 'HEAD', localDefaultSha: null, liveTaskSlugs: [], remoteBranches: new Set(),
    })
    assert.equal(r.classification, 'RECOVERABLE_VALUE')
    assert.match(r.reason, /orphan/)
  })
})

describe('classifyCodexOutput', () => {
  const mk = (dir, name, body) => {
    fs.mkdirSync(dir, { recursive: true })
    const p = path.join(dir, name)
    fs.writeFileSync(p, body)
    return p
  }

  it('shares the fate of a byte-identical dropbox twin, across the rename', () => {
    const base = path.join(root, `cx-${Math.random().toString(36).slice(2)}`)
    const out = mk(path.join(base, 'outputs'), 'repo--thing-20260812.patch', 'PATCH BODY')
    const twin = mk(path.join(base, '_applied'), '20260812-020326--repo--thing-20260812.patch', 'PATCH BODY')
    fs.writeFileSync(`${twin}.result.txt`, '[chatgpt-bridge] pushed branch chatgpt/thing-20260812-08120203\n')

    const r = classifyCodexOutput(
      out,
      { mainSha: 'HEAD', localDefaultSha: null, liveTaskSlugs: [], remoteBranches: new Set(['chatgpt/thing-20260812-08120203']) },
      [twin],
    )
    assert.equal(r.classification, 'ALREADY_PRESENT')
    assert.equal(r.identicalTo, twin)
    assert.equal(r.ref, out)
    assert.match(r.reason, /byte-identical/)
  })

  it('does not claim a twin when the bytes differ', () => {
    const base = path.join(root, `cx-${Math.random().toString(36).slice(2)}`)
    const out = mk(path.join(base, 'outputs'), 'repo--other.patch', 'ONE')
    const other = mk(path.join(base, '_applied'), '20260812-000000--repo--other.patch', 'TWO')
    const r = classifyCodexOutput(
      out,
      { mainSha: 'HEAD', localDefaultSha: null, liveTaskSlugs: [], remoteBranches: new Set() },
      [other],
    )
    assert.equal(r.identicalTo, undefined)
    assert.equal(r.classification, 'RECOVERABLE_VALUE')
  })

  it('falls back to the slug in the name when no twin exists', () => {
    const base = path.join(root, `cx-${Math.random().toString(36).slice(2)}`)
    const out = mk(path.join(base, 'outputs'), 'repo--named-thing.patch', 'BODY')
    const r = classifyCodexOutput(
      out,
      { mainSha: 'HEAD', localDefaultSha: null, liveTaskSlugs: [], remoteBranches: new Set(['chatgpt/named-thing-0812']) },
      [],
    )
    assert.equal(r.classification, 'ALREADY_PRESENT')
    assert.deepEqual(r.preservedIn, ['origin/chatgpt/named-thing-0812'])
  })

  it('calls an output that nothing carries the only copy', () => {
    const base = path.join(root, `cx-${Math.random().toString(36).slice(2)}`)
    const out = mk(path.join(base, 'outputs'), 'repo--orphaned.patch', 'BODY')
    const r = classifyCodexOutput(
      out,
      { mainSha: 'HEAD', localDefaultSha: null, liveTaskSlugs: [], remoteBranches: new Set() },
      [],
    )
    assert.equal(r.classification, 'RECOVERABLE_VALUE')
    assert.match(r.reason, /only copy/)
    assert.equal(typeof r.sha256, 'string')
  })

  it('flags an output the snapshot names but disk no longer has', () => {
    const r = classifyCodexOutput(path.join(root, 'nope', 'gone.patch'), { remoteBranches: new Set() }, [])
    assert.equal(r.classification, 'CONFLICTED_NEEDS_FOCUSED_TASK')
  })
})
