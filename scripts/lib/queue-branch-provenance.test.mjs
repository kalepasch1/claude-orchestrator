/**
 * A reconciliation ledger that is never committed may as well not exist.
 *
 * The acceptance for this module: one run produces either a commit on the agent branch
 * containing the ledger, or a clear "branch not created due to policy" artifact — and in
 * both cases the follow-up stubs come out as machine-readable JSON in a separate file.
 * The second half is the one that is easy to get wrong: losing the follow-up list because
 * a branch could not be created defeats the point of running at all.
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  BRANCH_PREFIX,
  FOCUSED_CLASSIFICATIONS,
  FOLLOW_UP_CLASSIFICATION,
  branchNameFor,
  followUpItems,
  followUpStub,
  planProvenance,
  readLedger,
  writeProvenance,
} from './queue-branch-provenance.mjs'

const LEDGER = {
  audit_fingerprint: '939f3db3fe9c',
  items: [
    { ref: 'refs/orch-rescue/aaa', classification: 'ALREADY_PRESENT' },
    { ref: 'refs/orch-rescue/bbb', classification: FOLLOW_UP_CLASSIFICATION,
      reason: 'evidence snapshot sections missing' },
    { ref: 'refs/orch-rescue/ccc', classification: 'CONFLICTED_NEEDS_FOCUSED_TASK' },
    { ref: 'refs/orch-rescue/ddd', classification: 'RECOVERABLE_VALUE' },
  ],
}

function newRepo() {
  const dir = mkdtempSync(join(tmpdir(), 'prov-'))
  const run = (args) => execFileSync('git', args, { cwd: dir, encoding: 'utf8', timeout: 30000 })
  run(['init', '-q', '-b', 'master', '.'])
  run(['config', 'user.name', 't'])
  run(['config', 'user.email', 't@t'])
  writeFileSync(join(dir, 'seed.txt'), 'seed\n')
  run(['add', '-A'])
  run(['commit', '-qm', 'seed'])
  return dir
}

// ─── naming ──────────────────────────────────────────────────────────────────

test('branch names follow the merge-train convention', () => {
  assert.equal(branchNameFor('my-slug'), `${BRANCH_PREFIX}my-slug`)
})

test('an already-prefixed slug is not double-prefixed', () => {
  assert.equal(branchNameFor('agent/my-slug'), 'agent/my-slug')
})

test('an unusable slug yields no branch name', () => {
  for (const bad of ['', '   ', null, undefined]) assert.equal(branchNameFor(bad), '')
})

// ─── follow-up selection ─────────────────────────────────────────────────────

test('only unresolved classifications become follow-ups', () => {
  const found = followUpItems(LEDGER).map((i) => i.ref)
  assert.deepEqual(found, ['refs/orch-rescue/bbb', 'refs/orch-rescue/ccc'])
})

test('both focused classifications are covered', () => {
  assert.ok(FOCUSED_CLASSIFICATIONS.includes(FOLLOW_UP_CLASSIFICATION))
  assert.ok(FOCUSED_CLASSIFICATIONS.includes('CONFLICTED_NEEDS_FOCUSED_TASK'))
})

test('a bare array of items is accepted too', () => {
  assert.equal(followUpItems(LEDGER.items).length, 2)
})

test('a malformed ledger yields no follow-ups rather than throwing', () => {
  for (const bad of [null, undefined, 7, 'text', {}, { items: 'nope' }]) {
    assert.deepEqual(followUpItems(bad), [])
  }
})

// ─── stub content ────────────────────────────────────────────────────────────

test('a stub names the ref and why it is unresolved', () => {
  const stub = followUpStub(LEDGER.items[1], { slug: 's', ledgerPath: '.orch/l.json' })
  assert.ok(stub.title.includes('refs/orch-rescue/bbb'))
  assert.ok(stub.prompt.includes('evidence snapshot sections missing'))
  assert.ok(stub.prompt.includes('.orch/l.json'))
})

test('a stub tells the next agent to stay read-only', () => {
  const stub = followUpStub(LEDGER.items[1], {})
  assert.ok(stub.prompt.includes('READ-ONLY'))
  assert.ok(stub.prompt.includes('Do NOT delete or move the ref'))
})

test('a stub survives an item with no reason', () => {
  const stub = followUpStub({ ref: 'x', classification: FOLLOW_UP_CLASSIFICATION }, {})
  assert.ok(stub.prompt.length > 0)
})

// ─── planning is pure ────────────────────────────────────────────────────────

test('the plan is computed before anything happens', () => {
  const plan = planProvenance({ slug: 's', ledgerPath: '.orch/l.json', ledger: LEDGER })
  assert.equal(plan.branch, 'agent/s')
  assert.equal(plan.action, 'create-branch-and-commit')
  assert.equal(plan.follow_up_count, 2)
})

test('a disallowed environment plans instead of failing', () => {
  const plan = planProvenance({ slug: 's', ledger: LEDGER, allowBranchCreation: false })
  assert.equal(plan.allowed, false)
  assert.equal(plan.action, 'branch-plan-only')
  assert.ok(plan.reason.includes('disallowed'))
})

test('no slug is reported as such rather than guessed at', () => {
  const plan = planProvenance({ slug: '', ledger: LEDGER })
  assert.equal(plan.allowed, false)
  assert.ok(plan.reason.includes('no usable slug'))
})

// ─── execution ───────────────────────────────────────────────────────────────

test('one run produces exactly one commit on the agent branch, carrying the ledger', () => {
  const repo = newRepo()
  mkdirSync(join(repo, '.orch'), { recursive: true })
  writeFileSync(join(repo, '.orch/ledger.json'), JSON.stringify(LEDGER))

  const before = execFileSync('git', ['rev-list', '--count', 'HEAD'],
    { cwd: repo, encoding: 'utf8' }).trim()
  const out = writeProvenance({
    repo, slug: 'recon-939f3db3', ledgerPath: '.orch/ledger.json', ledger: LEDGER,
  })
  const after = execFileSync('git', ['rev-list', '--count', 'HEAD'],
    { cwd: repo, encoding: 'utf8' }).trim()

  assert.equal(out.result, 'committed')
  assert.equal(Number(after) - Number(before), 1, 'exactly one new commit')
  const branch = execFileSync('git', ['rev-parse', '--abbrev-ref', 'HEAD'],
    { cwd: repo, encoding: 'utf8' }).trim()
  assert.equal(branch, 'agent/recon-939f3db3')
  const files = execFileSync('git', ['show', '--name-only', '--format=', 'HEAD'],
    { cwd: repo, encoding: 'utf8' })
  assert.ok(files.includes('.orch/ledger.json'), 'the ledger is in the commit')
})

test('the follow-up stubs land in a SEPARATE machine-readable file', () => {
  const repo = newRepo()
  mkdirSync(join(repo, '.orch'), { recursive: true })
  writeFileSync(join(repo, '.orch/ledger.json'), JSON.stringify(LEDGER))
  const out = writeProvenance({
    repo, slug: 'recon-x', ledgerPath: '.orch/ledger.json', ledger: LEDGER,
  })
  assert.ok(out.stub_file && out.stub_file !== '.orch/ledger.json')
  const parsed = JSON.parse(readFileSync(join(repo, out.stub_file), 'utf8'))
  assert.equal(parsed.follow_up_count, 2)
  assert.ok(Array.isArray(parsed.follow_ups))
  assert.ok(parsed.follow_ups[0].prompt.length > 0)
})

test('policy-blocked still emits the artifact and still writes the stubs', () => {
  const repo = newRepo()
  const out = writeProvenance({
    repo, slug: 'recon-y', ledger: LEDGER, allowBranchCreation: false,
  })
  assert.equal(out.result, 'branch-plan-only')
  assert.ok(existsSync(join(repo, out.stub_file)), 'stubs are not lost to policy')
  const branch = execFileSync('git', ['rev-parse', '--abbrev-ref', 'HEAD'],
    { cwd: repo, encoding: 'utf8' }).trim()
  assert.equal(branch, 'master', 'no branch was created')
})

test('an existing branch is never overwritten', () => {
  const repo = newRepo()
  execFileSync('git', ['branch', 'agent/taken'], { cwd: repo })
  const out = writeProvenance({ repo, slug: 'taken', ledger: LEDGER })
  assert.equal(out.result, 'branch-plan-only', 'falls back rather than clobbering')
  assert.ok(out.error)
})

test('no destructive git verb appears in the module', () => {
  const src = readFileSync(new URL('./queue-branch-provenance.mjs', import.meta.url), 'utf8')
  const code = src.split('\n').filter((l) => !l.trim().startsWith('*') && !l.trim().startsWith('//'))
    .join('\n')
  // Match git ARGUMENT LISTS, not any substring — `const clean = ...` is a variable, not
  // `git clean`, and a check that cannot tell them apart gets deleted the first time it
  // fires on a false positive.
  const gitCalls = [...code.matchAll(/git\(\[([^\]]*)\]/g)].map((m) => m[1])
  assert.ok(gitCalls.length > 0, 'expected to find the git call sites')
  const verbs = gitCalls.map((c) => (c.match(/'([a-z-]+)'/) || [])[1])
  for (const verb of verbs) {
    assert.ok(!['reset', 'clean', 'prune', 'push', 'rebase'].includes(verb),
      `module must not run git ${verb}`)
  }
  for (const flag of ["'--force'", "'-f'", "'-D'"]) {
    assert.ok(!gitCalls.some((c) => c.includes(flag)), `module must not pass ${flag} to git`)
  }
})

test('readLedger is fail-soft on an unreadable path', () => {
  assert.deepEqual(readLedger('/nonexistent/nope.json'), {})
})
