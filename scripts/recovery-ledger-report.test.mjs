#!/usr/bin/env node
/**
 * Tests for scripts/recovery-ledger-report.mjs.
 * Run: node --test scripts/recovery-ledger-report.test.mjs
 *
 * This repo has two recovery-ledger producers that disagree on field names:
 * scripts/reconcile-rescue-refs.mjs emits {audit_fingerprint, total_items,
 * unknown_items, summary, records[]}, tools/reconcile-local-evidence.mjs emits
 * {fingerprint, total, unknown, counts, items[]}. The reporter read only the
 * first, so every local-evidence ledger died on `ledger.records.filter is not a
 * function`. These pin both shapes so the reporter cannot silently regress to
 * single-producer again.
 */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it } from 'node:test'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SCRIPT = path.join(HERE, 'recovery-ledger-report.mjs')

// One item with remaining value, one without — enough to exercise both the
// summary table and the "items with remaining value" section.
const CLASSIFIED = [
  { classification: 'CONFLICTED_NEEDS_FOCUSED_TASK', files: ['a.py', 'b.py'] },
  { classification: 'ALREADY_PRESENT', files: [] },
]

const COMMON = {
  base: 'origin/orchestrator/dev',
  base_sha: 'bcacf428ecb1aaaa',
  generated_at: '2026-09-09T00:00:00.000Z',
}

/** The shape tools/reconcile-local-evidence.mjs writes. */
const localEvidenceLedger = () => ({
  ...COMMON,
  fingerprint: 'f'.repeat(64),
  kind: 'rescue-refs',
  total: CLASSIFIED.length,
  unknown: 0,
  counts: { CONFLICTED_NEEDS_FOCUSED_TASK: 1, ALREADY_PRESENT: 1 },
  items: CLASSIFIED.map((c, i) => ({
    source: `refs/orch-rescue/2026-example-${i}`,
    sha: String(i).repeat(40),
    subject: `example subject ${i}`,
    ...c,
  })),
})

/** The shape scripts/reconcile-rescue-refs.mjs writes. */
const rescueRefsLedger = () => ({
  ...COMMON,
  audit_fingerprint: 'e'.repeat(64),
  total_items: CLASSIFIED.length,
  unknown_items: 0,
  summary: { CONFLICTED_NEEDS_FOCUSED_TASK: 1, ALREADY_PRESENT: 1 },
  records: CLASSIFIED.map((c, i) => ({
    source: `refs/orch-rescue/2026-example-${i}`,
    source_sha: String(i).repeat(40),
    source_subject: `example subject ${i}`,
    touched_file_count: c.files.length,
    classification: c.classification,
  })),
})

function run(ledger) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ledger-report-'))
  const json = path.join(dir, 'ledger.json')
  const md = path.join(dir, 'ledger.md')
  fs.writeFileSync(json, JSON.stringify(ledger))
  const res = spawnSync(
    process.execPath,
    [SCRIPT, '--ledger', json, '--md', md, '--project', 'beethoven'],
    { encoding: 'utf8' },
  )
  return { res, md: fs.existsSync(md) ? fs.readFileSync(md, 'utf8') : '' }
}

describe('recovery-ledger-report ledger-schema normalisation', () => {
  it('reads a tools/reconcile-local-evidence ledger', () => {
    const { res, md } = run(localEvidenceLedger())
    assert.equal(res.status, 0, res.stderr)
    assert.match(res.stdout, /items: 2 · unknown: 0 · remaining-value: 1/)
    assert.match(md, /2 evidence items classified, 0 UNKNOWN/)
    // File counts must fall back to items[].files when touched_file_count is absent.
    assert.match(md, /\|\s*2\s*\|\s*example subject 0\s*\|/)
  })

  it('names the reconciler that actually produced the ledger', () => {
    assert.match(
      run(localEvidenceLedger()).md,
      /tools\/reconcile-local-evidence\.mjs --kind rescue-refs/,
    )
    assert.match(
      run(rescueRefsLedger()).md,
      /scripts\/reconcile-rescue-refs\.mjs --base origin\/orchestrator\/dev/,
    )
  })

  it('still reads a scripts/reconcile-rescue-refs ledger unchanged', () => {
    const { res, md } = run(rescueRefsLedger())
    assert.equal(res.status, 0, res.stderr)
    assert.match(res.stdout, /items: 2 · unknown: 0 · remaining-value: 1/)
    assert.match(md, /--out/)
  })

  it('reports a zero unknown count instead of treating 0 as missing', () => {
    // 0 UNKNOWN is the completion bar for a reconcile run, so it is exactly the
    // value that must not be coalesced away by `||`.
    assert.match(run(localEvidenceLedger()).md, /0 UNKNOWN/)
  })

  it('exits 2 when --ledger is omitted', () => {
    assert.equal(spawnSync(process.execPath, [SCRIPT], { encoding: 'utf8' }).status, 2)
  })
})
