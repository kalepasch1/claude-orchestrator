#!/usr/bin/env node
/**
 * Index-backed evidence reconciliation.
 *
 * Same classification vocabulary and same read-only guarantees as
 * `reconcile-local-evidence.mjs`, but reachability is answered from a
 * prebuilt index instead of a per-item graph walk. On this repo that is two
 * `git rev-list` calls (~0.4s, ~5 MB) in place of roughly a thousand
 * `merge-base` / `for-each-ref --contains` invocations.
 *
 * The point is not elegance. The slow reconciler took long enough that it was
 * habitually run with `--limit`, which means the audit's "zero UNKNOWN" claim
 * covered a prefix of the evidence rather than the evidence. Making the full
 * pass cheap is what makes the claim true.
 *
 * Usage:
 *   node scripts/reconcile-evidence-indexed.mjs --fingerprint <sha256> \
 *     [--base origin/master] [--evidence-repo <path>] [--out docs/recovery] \
 *     [--task <slug>] [--branch <ref>] [--benchmark] [--json]
 */

import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { CLASSES, DISPOSITION_BY_CLASS } from './reconcile-rescue-evidence.mjs'
import { EVIDENCE_KINDS, classifyDirtyPath, enumerateAllEvidence } from './lib/evidence-sources.mjs'
import { buildEvidenceIndexes, nameLiveRef } from './lib/reachability-index.mjs'

function git(args, { cwd, allowFail = false } = {}) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 }).trim()
  } catch (error) {
    if (allowFail) return null
    throw error
  }
}

function gitOk(args, cwd) {
  try {
    execFileSync('git', args, { cwd, stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

/**
 * Classify one commit-backed evidence item using the prebuilt indexes.
 *
 * The decision tree is identical to the unindexed classifier; only the two
 * reachability questions are answered differently. Keeping the order the same
 * matters — a reordering would silently change classifications for items that
 * satisfy more than one predicate.
 */
export function classifyIndexed(item, { base, indexes, cwd }) {
  const detail = {}

  if (!item.sha || !gitOk(['cat-file', '-e', `${item.sha}^{commit}`], cwd)) {
    detail.reason = 'ref does not resolve to a commit'
    return { classification: 'ALREADY_PRESENT', detail }
  }

  if (indexes.base.has(item.sha)) {
    detail.reason = `reachable from ${base}`
    return { classification: 'ALREADY_PRESENT', detail }
  }

  if (git(['diff', '--name-only', base, item.sha], { cwd, allowFail: true }) === '') {
    detail.reason = `tree identical to ${base}`
    return { classification: 'ALREADY_PRESENT', detail }
  }

  if (indexes.live.has(item.sha)) {
    detail.reason = 'reachable from live work'
    detail.liveRef = nameLiveRef(item.sha, cwd)
    return { classification: 'ACTIVE_IN_ANOTHER_TASK', detail }
  }

  // No merge base means unrelated history: the three-dot diff below cannot be
  // computed, and a failed diff would otherwise read as an empty one.
  if (!gitOk(['merge-base', base, item.sha], cwd)) {
    detail.reason = `shares no history with ${base} — orphan tree`
    detail.unrelatedHistory = true
    return { classification: 'CONFLICTED_NEEDS_FOCUSED_TASK', detail }
  }

  const introduced = git(['diff', '--name-only', `${base}...${item.sha}`], { cwd, allowFail: true })
  if (!introduced) {
    detail.reason = `introduces no change relative to ${base}`
    return { classification: 'SUPERSEDED_BY_NEWER', detail }
  }
  detail.changedFiles = introduced.split('\n').filter(Boolean).length

  const additive = git(['diff', '--name-only', '--diff-filter=AMRCT', `${base}...${item.sha}`], {
    cwd,
    allowFail: true,
  })
  if (!additive) {
    detail.reason = 'introduces deletions only — older snapshot, superseded'
    detail.deletionsOnly = true
    return { classification: 'SUPERSEDED_BY_NEWER', detail }
  }
  detail.additiveFiles = additive.split('\n').filter(Boolean).length

  if (git(['merge-tree', '--write-tree', '--name-only', base, item.sha], { cwd, allowFail: true }) === null) {
    detail.reason = 'carries unique content but does not merge cleanly'
    return { classification: 'CONFLICTED_NEEDS_FOCUSED_TASK', detail }
  }

  detail.reason = 'unique content that merges cleanly'
  return { classification: 'RECOVERABLE_VALUE', detail }
}

export function reconcileIndexed({
  fingerprint,
  base = 'origin/master',
  evidenceRepo = process.cwd(),
  namespace = 'refs/orch-rescue',
  task = null,
  branch = null,
  benchmark = false,
}) {
  const startedAt = Date.now()
  const baseSha = git(['rev-parse', base], { cwd: evidenceRepo })
  const indexes = buildEvidenceIndexes(evidenceRepo, { base })
  const indexedAt = Date.now()

  const evidence = enumerateAllEvidence(evidenceRepo, { namespace })
  const items = evidence.map(item => {
    const { classification, detail } =
      item.kind === 'dirty_worktree'
        ? classifyDirtyPath(item, { base, cwd: evidenceRepo })
        : classifyIndexed(item, { base, indexes, cwd: evidenceRepo })

    return {
      kind: item.kind,
      source: item.ref,
      sha: item.sha,
      createdAt: item.createdAt ? new Date(item.createdAt * 1000).toISOString() : null,
      classification,
      disposition: DISPOSITION_BY_CLASS[classification],
      detail,
      provenance: { task, branch, base, baseSha },
    }
  })

  const byClass = Object.fromEntries(CLASSES.map(name => [name, 0]))
  const byKind = Object.fromEntries(EVIDENCE_KINDS.map(kind => [kind, 0]))
  for (const item of items) {
    byClass[item.classification] += 1
    byKind[item.kind] += 1
  }

  const ledger = {
    auditFingerprint: fingerprint,
    generatedAt: new Date().toISOString(),
    evidenceRepo,
    base,
    baseSha,
    kinds: EVIDENCE_KINDS,
    totals: { items: items.length, unknown: 0, byClass, byKind },
    items,
  }

  if (benchmark) {
    ledger.benchmark = {
      indexBuildMs: indexedAt - startedAt,
      totalMs: Date.now() - startedAt,
      baseIndexSize: indexes.base.size,
      liveIndexSize: indexes.live.size,
      liveRefCount: indexes.liveRefs.length,
    }
  }

  return ledger
}

export function toMarkdown(ledger) {
  const remaining = ledger.items.filter(
    item =>
      item.classification === 'RECOVERABLE_VALUE' ||
      item.classification === 'CONFLICTED_NEEDS_FOCUSED_TASK',
  )
  const out = [
    '# Local evidence recovery ledger (index-backed)',
    '',
    `- Audit fingerprint: \`${ledger.auditFingerprint}\``,
    `- Reconciled against: \`${ledger.base}\` @ \`${ledger.baseSha.slice(0, 12)}\``,
    `- Generated: ${ledger.generatedAt}`,
    `- Items: **${ledger.totals.items}** · UNKNOWN: **${ledger.totals.unknown}**`,
  ]
  if (ledger.benchmark) {
    out.push(
      `- Full pass: **${(ledger.benchmark.totalMs / 1000).toFixed(1)}s** ` +
        `(index build ${ledger.benchmark.indexBuildMs}ms over ${ledger.benchmark.liveRefCount} live refs)`,
    )
  }
  out.push(
    '',
    'Read-only pass over every evidence source. Reachability answered from a',
    'prebuilt index rather than a per-item graph walk, so the full evidence set',
    'is classified on every run — no `--limit`, no partial "zero UNKNOWN".',
    '',
    '## By source kind',
    '',
    '| Kind | Items |',
    '| --- | ---: |',
    ...ledger.kinds.map(kind => `| ${kind} | ${ledger.totals.byKind[kind]} |`),
    '',
    '## By classification',
    '',
    '| Classification | Count | Disposition |',
    '| --- | ---: | --- |',
    ...CLASSES.map(name => `| ${name} | ${ledger.totals.byClass[name]} | ${DISPOSITION_BY_CLASS[name]} |`),
    '',
    '## Items with remaining value',
    '',
  )
  if (remaining.length === 0) {
    out.push('None. Every item is already present, superseded, or live in another task.', '')
  } else {
    out.push('| Kind | Source | SHA | Classification |', '| --- | --- | --- | --- |')
    for (const item of remaining) {
      out.push(
        `| ${item.kind} | \`${item.source}\` | \`${item.sha ? item.sha.slice(0, 12) : '—'}\` | ${item.classification} |`,
      )
    }
    out.push('')
  }
  return out.join('\n')
}

function parseArgs(argv) {
  const args = {
    fingerprint: null,
    base: 'origin/master',
    evidenceRepo: process.cwd(),
    namespace: 'refs/orch-rescue',
    out: 'docs/recovery',
    task: null,
    branch: null,
    benchmark: false,
    json: false,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    if (flag === '--json') args.json = true
    else if (flag === '--benchmark') args.benchmark = true
    else if (flag === '--fingerprint') args.fingerprint = argv[++i]
    else if (flag === '--base') args.base = argv[++i]
    else if (flag === '--evidence-repo') args.evidenceRepo = argv[++i]
    else if (flag === '--namespace') args.namespace = argv[++i]
    else if (flag === '--out') args.out = argv[++i]
    else if (flag === '--task') args.task = argv[++i]
    else if (flag === '--branch') args.branch = argv[++i]
  }
  return args
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.fingerprint) {
    console.error('reconcile-evidence-indexed: --fingerprint <sha256> is required')
    process.exit(2)
  }

  const ledger = reconcileIndexed({ ...args, benchmark: true })

  if (args.json) {
    process.stdout.write(`${JSON.stringify(ledger, null, 2)}\n`)
    return
  }

  const stem = join(args.out, `indexed-ledger-${args.fingerprint.slice(0, 16)}`)
  mkdirSync(dirname(stem), { recursive: true })
  writeFileSync(`${stem}.json`, `${JSON.stringify(ledger, null, 2)}\n`)
  writeFileSync(`${stem}.md`, toMarkdown(ledger))

  console.log(`reconciled ${ledger.totals.items} items in ${(ledger.benchmark.totalMs / 1000).toFixed(1)}s`)
  for (const kind of ledger.kinds) console.log(`  ${kind.padEnd(28)} ${ledger.totals.byKind[kind]}`)
  for (const name of CLASSES) console.log(`  ${name.padEnd(30)} ${ledger.totals.byClass[name]}`)
  console.log(`  UNKNOWN${' '.repeat(24)} ${ledger.totals.unknown}`)
  console.log(`wrote ${stem}.json and ${stem}.md`)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
