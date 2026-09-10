// Tests for scripts/reconcile-dirty-worktrees.mjs (node --test).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  classifyPath,
  isNoise,
  ownedByLiveTask,
  parseStatusZ,
  runGit,
  worktreeClassification,
} from './reconcile-dirty-worktrees.mjs'

test('read-only is enforced, not promised', () => {
  for (const sub of ['checkout', 'clean', 'reset', 'stash', 'restore', 'apply', 'add', 'rm']) {
    assert.throws(() => runGit([sub]), /read-only|refusing/, sub)
  }
  // hash-object is a pure read only without -w.
  assert.throws(() => runGit(['hash-object', '-w', 'f']), /not read-only/)
  // An unlisted subcommand must fail loudly rather than run.
  assert.throws(() => runGit(['fsck']), /allowlist/)
})

test('status -z records keep their leading status characters', () => {
  // " M path" — not staged — begins with a space. Trimming the stream ate it and
  // shifted every path one character left, so the file was never found and real
  // uncommitted work classified as absent.
  const stream = ' M runner/release_train.py\0?? SPEC.md\0MM lib/a.ts\0'
  assert.deepEqual(parseStatusZ(stream), [
    { code: ' M', path: 'runner/release_train.py' },
    { code: '??', path: 'SPEC.md' },
    { code: 'MM', path: 'lib/a.ts' },
  ])
})

test('parseStatusZ tolerates an empty stream and trailing NUL', () => {
  assert.deepEqual(parseStatusZ(''), [])
  assert.deepEqual(parseStatusZ(null), [])
  assert.deepEqual(parseStatusZ('?? a\0'), [{ code: '??', path: 'a' }])
})

test('build output and orchestrator bookkeeping are noise, source is not', () => {
  for (const p of [
    'node_modules/x/index.js', '.nuxt/dist/a.js', 'coverage/lcov.info',
    'web/.vite/deps/x.js', '.runtime/integration-worktrees/a/b', '.orch-worktree.json',
    'runner/__pycache__/db.cpython-39.pyc', 'nohup.log', 'package-lock.json',
  ]) assert.equal(isNoise(p), true, p)

  for (const p of ['runner/db.py', 'scripts/x.mjs', 'SPEC.md', 'lib/models/user.ts'])
    assert.equal(isNoise(p), false, p)
})

const env = (baseBlob, workingBlob) => ({
  blobAt: () => baseBlob,
  hashWorking: () => workingBlob,
})

test('a working file identical to the base is not lost work', () => {
  const r = classifyPath({ code: ' M', path: 'runner/db.py' }, env('abc', 'abc'))
  assert.equal(r.classification, 'ALREADY_PRESENT')
  assert.match(r.reason, /byte-identical/)
})

test('an uncommitted modification that differs is recoverable value', () => {
  const r = classifyPath({ code: ' M', path: 'runner/db.py' }, env('abc', 'def'))
  assert.equal(r.classification, 'RECOVERABLE_VALUE')
  assert.match(r.reason, /no ref carries it/)
})

test('an untracked file with no base counterpart is recoverable value', () => {
  const r = classifyPath({ code: '??', path: 'SPEC.md' }, env(null, 'def'))
  assert.equal(r.classification, 'RECOVERABLE_VALUE')
  assert.match(r.reason, /untracked/)
})

test('a deletion is never lost work', () => {
  const r = classifyPath({ code: ' D', path: 'runner/db.py' }, env('abc', null))
  assert.equal(r.classification, 'ALREADY_PRESENT')
  assert.match(r.reason, /still exists on the base/)
})

test('noise short-circuits before hashing', () => {
  let hashed = false
  const r = classifyPath(
    { code: '??', path: 'node_modules/x' },
    { blobAt: () => null, hashWorking: () => { hashed = true; return 'x' } },
  )
  assert.equal(r.classification, 'ALREADY_PRESENT')
  assert.equal(hashed, false, 'must not hash dependency trees')
})

test('a worktree is only as safe as its least-safe path', () => {
  assert.equal(worktreeClassification({ counts: { ALREADY_PRESENT: 9 } }), 'ALREADY_PRESENT')
  assert.equal(
    worktreeClassification({ counts: { ALREADY_PRESENT: 9, RECOVERABLE_VALUE: 1 } }),
    'RECOVERABLE_VALUE',
  )
  // Unknown is not "fine".
  assert.equal(worktreeClassification({ unreadable: true, counts: {} }), 'CONFLICTED_NEEDS_FOCUSED_TASK')
})

// ─── ownership ───────────────────────────────────────────────────────────────
// Uncommitted-and-unique is the same observation whether or not a task owns the
// worktree. Only ownership separates "nobody is coming back for this" from
// "another executor is editing it right now", and only the first is recoverable.

const live = new Set([
  'agent/chatgpt-local-reconcile-beethoven-2829958769f3',
  'agent/canary-deepseek-1',
])

test('a dirty worktree on a live agent branch belongs to that task', () => {
  const wt = { branch: 'refs/heads/agent/chatgpt-local-reconcile-beethoven-2829958769f3' }
  assert.equal(ownedByLiveTask(wt, { liveBranches: live }), 'agent/chatgpt-local-reconcile-beethoven-2829958769f3')
  assert.equal(
    worktreeClassification({ counts: { RECOVERABLE_VALUE: 1 }, ownerBranch: 'agent/x' }),
    'ACTIVE_IN_ANOTHER_TASK',
  )
})

test('detached and deleted-branch worktrees have no owner left', () => {
  assert.equal(ownedByLiveTask({ branch: 'DETACHED' }, { liveBranches: live }), null)
  // The branch was deleted after the worktree was cut — nobody will come back.
  assert.equal(ownedByLiveTask({ branch: 'refs/heads/agent/long-gone' }, { liveBranches: live }), null)
  assert.equal(
    worktreeClassification({ counts: { RECOVERABLE_VALUE: 705 }, ownerBranch: null }),
    'RECOVERABLE_VALUE',
  )
})

test('only agent/* branches confer task ownership', () => {
  // A dirty main checkout is not "somebody's open task"; it is a dirty checkout.
  assert.equal(ownedByLiveTask({ branch: 'refs/heads/master' }, { liveBranches: live }), null)
  assert.equal(ownedByLiveTask({ branch: 'refs/heads/orchestrator/dev' }, { liveBranches: live }), null)
})

test('ownership never rescues a clean or unreadable worktree', () => {
  // Clean stays ALREADY_PRESENT; ownership only ever downgrades RECOVERABLE_VALUE.
  assert.equal(
    worktreeClassification({ counts: { ALREADY_PRESENT: 3 }, ownerBranch: 'agent/x' }),
    'ALREADY_PRESENT',
  )
  assert.equal(
    worktreeClassification({ unreadable: true, counts: {}, ownerBranch: 'agent/x' }),
    'CONFLICTED_NEEDS_FOCUSED_TASK',
  )
})
