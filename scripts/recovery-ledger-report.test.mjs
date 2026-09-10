// Schema tests for scripts/recovery-ledger-report.mjs (node --test).
//
// The reporter read `ledger.records`. reconcile-evidence.mjs writes
// `ledger.items` with camelCase envelope keys, so every ledger it has ever
// produced crashed this script on `.filter` of undefined — including via the
// two-command "Regenerate with" block the script prints into its own output.
// These tests pin both producers' shapes.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const script = join(dirname(fileURLToPath(import.meta.url)), 'recovery-ledger-report.mjs')

function render(ledger, project = 'beethoven') {
  const dir = mkdtempSync(join(tmpdir(), 'ledger-report-'))
  const jsonPath = join(dir, 'ledger.json')
  const mdPath = join(dir, 'ledger.md')
  writeFileSync(jsonPath, JSON.stringify(ledger))
  const r = spawnSync(
    process.execPath,
    [script, '--ledger', jsonPath, '--md', mdPath, '--project', project],
    { encoding: 'utf8' },
  )
  return { status: r.status, stdout: r.stdout, stderr: r.stderr, md: r.status === 0 ? readFileSync(mdPath, 'utf8') : '' }
}

// scripts/reconcile-evidence.mjs
const evidenceShape = {
  auditFingerprint: 'a'.repeat(64),
  against: { ref: 'origin/master', sha: 'bcacf428ecb1dae850d2eab98400741cd5467ec0' },
  generatedAt: '2026-09-10T04:47:14.762Z',
  itemCount: 2,
  unknown: 0,
  readOnly: true,
  counts: { RECOVERABLE_VALUE: 1, ALREADY_PRESENT: 1 },
  items: [
    { kind: 'local_branch', ref: 'refs/heads/agent/x', sha: '0'.repeat(40), classification: 'RECOVERABLE_VALUE', reason: 'unique commits; diff applies' },
    { kind: 'rescue_ref', ref: 'refs/orch-rescue/y', sha: '1'.repeat(40), classification: 'ALREADY_PRESENT', reason: 'ancestor of origin/master' },
  ],
}

// scripts/reconcile-rescue-refs.mjs
const rescueShape = {
  audit_fingerprint: 'b'.repeat(64),
  base: 'origin/master',
  base_sha: 'bcacf428ecb1dae850d2eab98400741cd5467ec0',
  generated_at: '2026-09-10T00:00:00.000Z',
  total_items: 1,
  unknown_items: 0,
  summary: { CONFLICTED_NEEDS_FOCUSED_TASK: 1 },
  records: [
    { source: 'refs/orch-rescue/20260803T000716-z', source_sha: '2'.repeat(40), source_subject: 'periodic sweep', classification: 'CONFLICTED_NEEDS_FOCUSED_TASK', touched_file_count: 6 },
  ],
}

test('reads reconcile-evidence.mjs ledgers', () => {
  const { status, stdout, md, stderr } = render(evidenceShape)
  assert.equal(status, 0, stderr)
  assert.match(stdout, /items: 2 · unknown: 0 · remaining-value: 1/)
  assert.match(md, /\*\*2 evidence items classified, 0 UNKNOWN\.\*\*/)
  // against:{ref,sha} must become base/base_sha, not "[object Object]".
  assert.match(md, /Base: `origin\/master` @ `bcacf428ecb1`/)
  // `ref` becomes the source column and `reason` stands in for the missing subject.
  assert.match(md, /\| `refs\/heads\/agent\/x` \| RECOVERABLE_VALUE \| 0 \| unique commits; diff applies \|/)
  assert.doesNotMatch(md, /undefined|\[object Object\]/)
})

test('still reads reconcile-rescue-refs.mjs ledgers', () => {
  const { status, stdout, md, stderr } = render(rescueShape)
  assert.equal(status, 0, stderr)
  assert.match(stdout, /items: 1 · unknown: 0 · remaining-value: 1/)
  assert.match(md, /\| `20260803T000716-z` \| CONFLICTED_NEEDS_FOCUSED_TASK \| 6 \| periodic sweep \|/)
  assert.doesNotMatch(md, /undefined|\[object Object\]/)
})

test('the regenerate block names the producer that wrote the ledger', () => {
  const ev = render(evidenceShape).md
  assert.match(ev, /node scripts\/reconcile-evidence\.mjs/)
  assert.match(ev, /--default-branch master/)
  assert.doesNotMatch(ev, /reconcile-rescue-refs\.mjs/)

  const rescue = render(rescueShape).md
  assert.match(rescue, /node scripts\/reconcile-rescue-refs\.mjs/)
  assert.doesNotMatch(rescue, /node scripts\/reconcile-evidence\.mjs/)
})

test('a truncated files array does not understate the item', () => {
  // Producers cap `files` and keep the real total in file_count.
  const capped = {
    ...rescueShape,
    records: [{ ...rescueShape.records[0], touched_file_count: undefined, file_count: 337, files: ['a', 'b'] }],
  }
  assert.match(render(capped).md, /\| CONFLICTED_NEEDS_FOCUSED_TASK \| 337 \|/)
})

test('an all-clear ledger reports rather than crashes', () => {
  const clean = { ...evidenceShape, itemCount: 1, counts: { ALREADY_PRESENT: 1 }, items: [evidenceShape.items[1]] }
  const { status, md } = render(clean)
  assert.equal(status, 0)
  assert.match(md, /None\. Every item is already present/)
})
