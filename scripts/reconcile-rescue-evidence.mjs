#!/usr/bin/env node
/**
 * Reconcile local rescue evidence (rescue refs, stashes, archived branches)
 * against the current default branch and live work — without destroying it.
 *
 * READ-ONLY over the evidence. This script never deletes, resets, cleans, pops
 * or moves a ref or stash. It only reads and classifies. That is the whole
 * point: the previous failure mode was a "recovery" pass that preferred legacy
 * code over current code and lost the newer implementation.
 *
 * Every item lands in exactly one class — the decision tree has no UNKNOWN
 * branch, because "we didn't look" is the outcome this task exists to prevent:
 *
 *   ALREADY_PRESENT             commit is an ancestor of the default branch, or
 *                               its tree is identical to it — nothing to recover
 *   ACTIVE_IN_ANOTHER_TASK      reachable from a live agent/ or orchestrator ref
 *   SUPERSEDED_BY_NEWER         introduces no change vs the default branch, or
 *                               every change it introduces is already applied
 *   CONFLICTED_NEEDS_FOCUSED_TASK  has unique content but does not merge cleanly
 *   RECOVERABLE_VALUE           has unique content and merges cleanly
 *
 * Usage:
 *   node scripts/reconcile-rescue-evidence.mjs --fingerprint <sha256> \
 *     [--namespace refs/orch-rescue] [--base origin/master] \
 *     [--out docs/recovery] [--limit N] [--json]
 */

import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

export const CLASSES = [
  'ALREADY_PRESENT',
  'ACTIVE_IN_ANOTHER_TASK',
  'SUPERSEDED_BY_NEWER',
  'CONFLICTED_NEEDS_FOCUSED_TASK',
  'RECOVERABLE_VALUE',
]

/** Dispositions are advisory: what a human or follow-up task should do next. */
export const DISPOSITION_BY_CLASS = {
  ALREADY_PRESENT: 'no_action_evidence_retained',
  ACTIVE_IN_ANOTHER_TASK: 'defer_to_live_task',
  SUPERSEDED_BY_NEWER: 'no_action_evidence_retained',
  CONFLICTED_NEEDS_FOCUSED_TASK: 'queue_focused_followup',
  RECOVERABLE_VALUE: 'queue_recovery_task',
}

function git(args, { cwd = process.cwd(), allowFail = false } = {}) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 }).trim()
  } catch (error) {
    if (allowFail) return null
    throw error
  }
}

function gitOk(args, cwd = process.cwd()) {
  try {
    execFileSync('git', args, { cwd, stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

/** Enumerate the live evidence source. Never trust a stale snapshot digest. */
export function enumerateEvidence(namespace, cwd = process.cwd()) {
  const out = git(['for-each-ref', namespace, '--format=%(refname)%09%(objectname)%09%(creatordate:unix)'], {
    cwd,
    allowFail: true,
  })
  if (!out) return []
  return out
    .split('\n')
    .filter(Boolean)
    .map(line => {
      const [ref, sha, createdAt] = line.split('\t')
      return { ref, sha, createdAt: Number(createdAt) || null }
    })
}

/** Namespaces that represent live, in-flight work rather than parked evidence. */
export const LIVE_WORK_NAMESPACES = [
  'refs/heads/agent',
  'refs/remotes/origin/agent',
  'refs/orchestrator',
]

export function liveWorkRefs(cwd = process.cwd()) {
  const out = git(['for-each-ref', '--format=%(refname)', ...LIVE_WORK_NAMESPACES], {
    cwd,
    allowFail: true,
  })
  return out ? out.split('\n').filter(Boolean) : []
}

/**
 * First live ref that contains `sha`, or null.
 *
 * One `for-each-ref --contains` rather than one `merge-base` per live branch:
 * with ~400 agent branches and ~400 evidence items the naive form is 160k git
 * invocations and does not finish.
 */
export function containingLiveRef(sha, cwd = process.cwd()) {
  const out = git(
    ['for-each-ref', '--contains', sha, '--count=1', '--format=%(refname)', ...LIVE_WORK_NAMESPACES],
    { cwd, allowFail: true },
  )
  return out || null
}

/**
 * Classify one evidence item. Pure decision tree over git plumbing results —
 * every path returns a class, so a caller can assert zero UNKNOWN.
 */
export function classify(item, { base, liveRefs, cwd = process.cwd() }) {
  const detail = {}

  if (!gitOk(['cat-file', '-e', `${item.sha}^{commit}`], cwd)) {
    // A ref that no longer resolves to a commit cannot hold recoverable code.
    detail.reason = 'ref does not resolve to a commit'
    return { classification: 'ALREADY_PRESENT', detail }
  }

  if (gitOk(['merge-base', '--is-ancestor', item.sha, base], cwd)) {
    detail.reason = `ancestor of ${base}`
    return { classification: 'ALREADY_PRESENT', detail }
  }

  const treeDiff = git(['diff', '--name-only', base, item.sha], { cwd, allowFail: true })
  if (treeDiff === '') {
    detail.reason = `tree identical to ${base}`
    return { classification: 'ALREADY_PRESENT', detail }
  }

  const liveRef = containingLiveRef(item.sha, cwd)
  if (liveRef) {
    detail.reason = `reachable from live ref ${liveRef}`
    detail.liveRef = liveRef
    return { classification: 'ACTIVE_IN_ANOTHER_TASK', detail }
  }

  const introduced = git(['diff', '--name-only', `${base}...${item.sha}`], { cwd, allowFail: true })
  if (!introduced) {
    detail.reason = `introduces no change relative to ${base}`
    return { classification: 'SUPERSEDED_BY_NEWER', detail }
  }
  detail.changedFiles = introduced.split('\n').filter(Boolean).length

  /**
   * Deletion-only refs are stale snapshots, not recoverable work. A rescue ref
   * taken before a file existed "introduces" that file's deletion relative to
   * today's default branch, and merge-tree reports a modify/delete conflict.
   * Treating that as CONFLICTED would queue follow-up tasks whose only content
   * is "delete code master has since improved" — the exact inversion this task
   * exists to prevent. Newest/most complete wins, so it is superseded.
   */
  const additive = git(['diff', '--name-only', '--diff-filter=AMRCT', `${base}...${item.sha}`], {
    cwd,
    allowFail: true,
  })
  if (!additive) {
    detail.reason = 'introduces deletions only — older snapshot, superseded by the default branch'
    detail.deletionsOnly = true
    return { classification: 'SUPERSEDED_BY_NEWER', detail }
  }
  detail.additiveFiles = additive.split('\n').filter(Boolean).length

  const merged = git(['merge-tree', '--write-tree', '--name-only', base, item.sha], {
    cwd,
    allowFail: true,
  })
  if (merged === null) {
    // merge-tree exits non-zero on conflict; that IS the signal, not an error.
    detail.reason = 'carries unique content but does not merge cleanly onto the default branch'
    return { classification: 'CONFLICTED_NEEDS_FOCUSED_TASK', detail }
  }

  detail.reason = 'unique content that merges cleanly'
  return { classification: 'RECOVERABLE_VALUE', detail }
}

export function reconcile({ fingerprint, namespace, base, limit, task, branch, cwd = process.cwd() }) {
  const baseSha = git(['rev-parse', base], { cwd })
  const liveRefs = liveWorkRefs(cwd)
  let evidence = enumerateEvidence(namespace, cwd)
  if (limit) evidence = evidence.slice(0, limit)

  const items = evidence.map(item => {
    const { classification, detail } = classify(item, { base, liveRefs, cwd })
    return {
      source: item.ref,
      sha: item.sha,
      createdAt: item.createdAt ? new Date(item.createdAt * 1000).toISOString() : null,
      classification,
      disposition: DISPOSITION_BY_CLASS[classification],
      detail,
      // Durable provenance: which task and branch made this determination, so
      // the classification is re-verifiable later against the exact tree.
      provenance: { task: task ?? null, branch: branch ?? null, base, baseSha },
    }
  })

  const byClass = Object.fromEntries(CLASSES.map(name => [name, 0]))
  for (const item of items) byClass[item.classification] += 1

  return {
    auditFingerprint: fingerprint,
    generatedAt: new Date().toISOString(),
    namespace,
    base,
    baseSha,
    liveRefCount: liveRefs.length,
    totals: { items: items.length, unknown: 0, byClass },
    items,
  }
}

export function toMarkdown(ledger) {
  const lines = [
    `# Recovery ledger — \`${ledger.namespace}\``,
    '',
    `- Audit fingerprint: \`${ledger.auditFingerprint}\``,
    `- Reconciled against: \`${ledger.base}\` @ \`${ledger.baseSha.slice(0, 12)}\``,
    `- Generated: ${ledger.generatedAt}`,
    `- Items: **${ledger.totals.items}** · UNKNOWN: **${ledger.totals.unknown}**`,
    '',
    'The evidence source was treated as read-only. Nothing was deleted, reset,',
    'cleaned, popped or moved. Newest/most complete implementation wins.',
    '',
    '## Classification summary',
    '',
    '| Classification | Count | Disposition |',
    '| --- | ---: | --- |',
    ...CLASSES.map(
      name => `| ${name} | ${ledger.totals.byClass[name]} | ${DISPOSITION_BY_CLASS[name]} |`,
    ),
    '',
  ]

  const needsWork = ledger.items.filter(
    item =>
      item.classification === 'RECOVERABLE_VALUE' ||
      item.classification === 'CONFLICTED_NEEDS_FOCUSED_TASK',
  )
  lines.push('## Items with remaining value', '')
  if (needsWork.length === 0) {
    lines.push('None. Every item is already present, superseded, or live in another task.', '')
  } else {
    lines.push('| Source | SHA | Classification | Files | Disposition |', '| --- | --- | --- | ---: | --- |')
    for (const item of needsWork) {
      lines.push(
        `| \`${item.source}\` | \`${item.sha.slice(0, 12)}\` | ${item.classification} | ${
          item.detail.changedFiles ?? '—'
        } | ${item.disposition} |`,
      )
    }
    lines.push('')
  }
  return lines.join('\n')
}

function parseArgs(argv) {
  const args = {
    namespace: 'refs/orch-rescue',
    base: 'origin/master',
    out: 'docs/recovery',
    fingerprint: null,
    limit: 0,
    json: false,
    task: null,
    branch: null,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    if (flag === '--json') args.json = true
    else if (flag === '--task') args.task = argv[++i]
    else if (flag === '--branch') args.branch = argv[++i]
    else if (flag === '--fingerprint') args.fingerprint = argv[++i]
    else if (flag === '--namespace') args.namespace = argv[++i]
    else if (flag === '--base') args.base = argv[++i]
    else if (flag === '--out') args.out = argv[++i]
    else if (flag === '--limit') args.limit = Number(argv[++i]) || 0
  }
  return args
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.fingerprint) {
    console.error('reconcile-rescue-evidence: --fingerprint <sha256> is required')
    process.exit(2)
  }

  const ledger = reconcile(args)

  if (args.json) {
    process.stdout.write(`${JSON.stringify(ledger, null, 2)}\n`)
    return
  }

  const stem = join(args.out, `ledger-${args.fingerprint.slice(0, 16)}`)
  mkdirSync(dirname(stem), { recursive: true })
  writeFileSync(`${stem}.json`, `${JSON.stringify(ledger, null, 2)}\n`)
  writeFileSync(`${stem}.md`, toMarkdown(ledger))

  console.log(`reconciled ${ledger.totals.items} items from ${ledger.namespace}`)
  for (const name of CLASSES) console.log(`  ${name.padEnd(30)} ${ledger.totals.byClass[name]}`)
  console.log(`  UNKNOWN${' '.repeat(24)} ${ledger.totals.unknown}`)
  console.log(`wrote ${stem}.json and ${stem}.md`)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
