#!/usr/bin/env node
/**
 * Tests for scripts/reconcile-rescue-refs.mjs.
 * Run: node --test scripts/reconcile-rescue-refs.test.mjs
 *
 * The case worth pinning hardest is the unreadable object. A rescue commit git
 * can no longer read was classified ALREADY_PRESENT, which the ledger renders
 * as "no action — value already on the default branch". That is a claim the run
 * has no basis for: unknown content and shipped content are opposite
 * conclusions from the same fact, and the wrong one leaves nobody looking for
 * the work.
 *
 * Real repos, real refs — the classifier's whole job is reading git correctly.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { after, before, describe, it } from 'node:test'

import { classify, DISPOSITION, isGenerated } from './reconcile-rescue-refs.mjs'

let repo
let cwd
let baseSha

const git = (args) =>
  execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()

before(() => {
  cwd = process.cwd()
  repo = fs.mkdtempSync(path.join(os.tmpdir(), 'rescue-refs-'))
  git(['init', '-q', '-b', 'main'])
  fs.writeFileSync(path.join(repo, 'app.py'), 'X = 1\n')
  git(['add', '-A'])
  git(['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base'])
  baseSha = git(['rev-parse', 'HEAD'])
  // The module runs git in the process CWD.
  process.chdir(repo)
})

after(() => {
  process.chdir(cwd)
  fs.rmSync(repo, { recursive: true, force: true })
})


const MISSING_SHA = '0'.repeat(40)

describe('unreadable objects', () => {
  it('is not classified as already present', () => {
    const out = classify({ sha: MISSING_SHA, created: 0 }, baseSha)
    assert.notEqual(
      out.classification,
      'ALREADY_PRESENT',
      'an object git cannot read is not evidence that the work shipped',
    )
  })

  it('is routed to a focused follow-up', () => {
    const out = classify({ sha: MISSING_SHA, created: 0 }, baseSha)
    assert.equal(out.classification, 'CONFLICTED_NEEDS_FOCUSED_TASK')
  })

  it('says why, naming the object', () => {
    const out = classify({ sha: MISSING_SHA, created: 0 }, baseSha)
    assert.match(out.reason, /not in the object db/)
    assert.match(out.reason, /^object 000000000000/)
  })

  it('does not claim the value is on the default branch', () => {
    const out = classify({ sha: MISSING_SHA, created: 0 }, baseSha)
    assert.doesNotMatch(DISPOSITION[out.classification], /already on the default branch/)
    assert.match(DISPOSITION[out.classification], /queue a focused/)
  })

  it('reports no files or carriers it could not have read', () => {
    const out = classify({ sha: MISSING_SHA, created: 0 }, baseSha)
    assert.deepEqual(out.files, [])
    assert.deepEqual(out.carriers, [])
  })
})

describe('classifications that were already right', () => {
  it('an ancestor of the base is already present', () => {
    const out = classify({ sha: baseSha, created: 0 }, baseSha)
    assert.equal(out.classification, 'ALREADY_PRESENT')
    assert.match(out.reason, /ancestor of/)
  })

  it('unique content that applies is recoverable', () => {
    git(['checkout', '-q', '-b', 'side'])
    fs.writeFileSync(path.join(repo, 'new_module.py'), 'Y = 2\n')
    git(['add', '-A'])
    git(['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'side work'])
    const sha = git(['rev-parse', 'HEAD'])
    git(['checkout', '-q', 'main'])
    git(['branch', '-q', '-D', 'side'])

    const out = classify({ sha, created: Math.floor(Date.now() / 1000) + 60 }, baseSha)
    assert.equal(out.classification, 'RECOVERABLE_VALUE')
    assert.ok(out.files.includes('new_module.py'))
  })

  it('never returns an empty classification', () => {
    for (const sha of [MISSING_SHA, baseSha]) {
      const out = classify({ sha, created: 0 }, baseSha)
      assert.ok(out.classification, 'UNKNOWN is the one outcome the bar forbids')
      assert.ok(DISPOSITION[out.classification], 'every classification needs a disposition')
    }
  })
})

describe('generated-path filter', () => {
  it('recognises build output', () => {
    for (const f of ['node_modules/x.js', 'dist/a.js', 'coverage/lcov.info',
      'src/__snapshots__/a.snap', '.nuxt/app.js']) {
      assert.equal(isGenerated(f), true, f)
    }
  })

  it('leaves real source alone', () => {
    for (const f of ['src/app.ts', 'runner/thing.py', 'distributed/real.py',
      'docs/build-notes.md']) {
      assert.equal(isGenerated(f), false, f)
    }
  })
})


describe('the patch fed to git apply keeps its trailing newline', () => {
  /**
   * The classifier built the patch with the trimming git() helper. A diff must
   * end with a newline; without it `git apply` answers "corrupt patch at line
   * N" and exits 128, which reads as "does not apply". So every ref that
   * reached the apply step was classified CONFLICTED whatever its content, and
   * RECOVERABLE_VALUE was unreachable through that branch.
   *
   * This test asserts the git behaviour directly, so it fails if anyone
   * reintroduces a trim between `git diff` and `git apply`.
   */
  it('git rejects the same patch once it is trimmed', () => {
    git(['checkout', '-q', '-b', 'newline-probe'])
    fs.writeFileSync(path.join(repo, 'probe.py'), 'P = 1\n')
    git(['add', '-A'])
    git(['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'probe'])
    const sha = git(['rev-parse', 'HEAD'])
    git(['checkout', '-q', 'main'])
    git(['branch', '-q', '-D', 'newline-probe'])

    const patch = execFileSync(
      'git', ['diff', `${baseSha}..${sha}`, '--', 'probe.py'],
      { cwd: repo, encoding: 'utf8' },
    )

    const check = (input) => {
      try {
        execFileSync('git', ['apply', '--check', '-'],
          { cwd: repo, input, stdio: ['pipe', 'ignore', 'ignore'] })
        return true
      } catch {
        return false
      }
    }

    assert.equal(check(patch), true, 'the untouched patch applies')
    assert.equal(check(patch.trim()), false,
      'trimming it makes git call it corrupt — this is the bug being pinned')
  })

  it('the classifier reaches RECOVERABLE_VALUE for such a patch', () => {
    git(['checkout', '-q', '-b', 'reachable'])
    fs.writeFileSync(path.join(repo, 'reachable.py'), 'R = 1\n')
    git(['add', '-A'])
    git(['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'reachable'])
    const sha = git(['rev-parse', 'HEAD'])
    git(['checkout', '-q', 'main'])
    git(['branch', '-q', '-D', 'reachable'])

    const out = classify({ sha, created: Math.floor(Date.now() / 1000) + 60 }, baseSha)
    assert.equal(out.classification, 'RECOVERABLE_VALUE')
  })
})
