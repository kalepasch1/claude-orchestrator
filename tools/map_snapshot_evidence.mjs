#!/usr/bin/env node
/**
 * Map a task's evidence SNAPSHOT onto the LIVE reconciliation ledger.
 *
 * The chatgpt-local-reconcile-* tasks carry a snapshot of local evidence taken
 * when the task was queued. tools/reconcile_all_evidence.py enumerates the LIVE
 * source, which is authoritative — but the two sets are not identical: a ref in
 * the snapshot may since have been pushed (so it is no longer a local-only tip
 * and the live pass never sees it), and the live pass finds items the snapshot
 * never recorded.
 *
 * The ledger contract is one record per evidence item, and "evidence item"
 * includes the ones the task actually named. A snapshot ref that silently
 * vanishes from the live enumeration is exactly the case that used to be filed
 * as covered when nobody had checked it. So every snapshot entry gets its own
 * ledger row here, resolved in this order:
 *
 *   1. matched to a live row  -> adopt that row's classification verbatim
 *   2. sha contained in base  -> ALREADY_PRESENT (it shipped; that is why the
 *                               live local-only pass no longer lists it)
 *   3. sha on any remote      -> ACTIVE_IN_ANOTHER_TASK (published elsewhere)
 *   4. sha unreadable         -> ALREADY_PRESENT, nothing left on disk to lose
 *   5. otherwise              -> CONFLICTED_NEEDS_FOCUSED_TASK; never UNKNOWN,
 *                               and never silently dropped
 *
 * READ-ONLY: git is invoked only through merge-base/cat-file/branch --contains.
 *
 * Usage:
 *   node tools/map_snapshot_evidence.mjs --ledger .orch/recovery-ledger-<fp8>.json \
 *     --snapshot /tmp/evidence-<fp8>.json --base origin/master [--out <path>]
 */

import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'

const CLASSES = [
  'ALREADY_PRESENT', 'SUPERSEDED_BY_NEWER', 'ACTIVE_IN_ANOTHER_TASK',
  'RECOVERABLE_VALUE', 'CONFLICTED_NEEDS_FOCUSED_TASK',
]

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`)
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

function git(args) {
  try {
    return execFileSync('git', args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).trim()
  } catch {
    return ''
  }
}

function shaExists(sha) {
  return sha ? git(['cat-file', '-t', `${sha}^{commit}`]) === 'commit' : false
}

function containingBranches(sha) {
  return git(['branch', '--all', '--contains', sha])
    .split('\n').map((l) => l.replace(/^[*+ ]+/, '').trim()).filter(Boolean)
}

/** Worst (most work remaining) classification wins when a snapshot item covers many live rows. */
export function rollUp(classifications) {
  for (const c of ['CONFLICTED_NEEDS_FOCUSED_TASK', 'RECOVERABLE_VALUE',
    'ACTIVE_IN_ANOTHER_TASK', 'SUPERSEDED_BY_NEWER', 'ALREADY_PRESENT']) {
    if (classifications.includes(c)) return c
  }
  return 'ALREADY_PRESENT'
}

export function resolveRef(entry, live, base, io = {}) {
  const shaOk = io.shaExists || shaExists
  const contained = io.containingBranches || containingBranches
  const remoteHas = io.remoteExists ||
    ((r) => Boolean(git(['rev-parse', '--verify', '--quiet', `refs/remotes/origin/${r}`])))
  const ref = entry.ref || entry.branch || ''
  const sha = entry.sha || entry.head || ''
  const hit = live.find((i) => i.ref === ref || i.ref === `refs/heads/${ref}` ||
    (sha && i.sha && i.sha.startsWith(sha.slice(0, 12))))
  if (hit) {
    return { classification: hit.classification, disposition: hit.disposition,
      evidence: `matched live ledger row ${hit.ref}` }
  }
  if (!shaOk(sha)) {
    return { classification: 'ALREADY_PRESENT',
      disposition: 'snapshot sha is no longer readable in this repo; nothing left to recover',
      evidence: 'object absent from the object store' }
  }
  const contains = contained(sha)
  if (contains.some((b) => b === base || b === base.replace(/^origin\//, '') ||
      b === `remotes/${base}`)) {
    return { classification: 'ALREADY_PRESENT',
      disposition: `snapshot sha is contained in ${base}; it shipped after the snapshot was taken`,
      evidence: `contained in ${base}` }
  }
  if (contains.some((b) => b.startsWith('remotes/'))) {
    return { classification: 'ACTIVE_IN_ANOTHER_TASK',
      disposition: 'snapshot sha is published on a remote branch; delivery is owned elsewhere',
      evidence: contains.filter((b) => b.startsWith('remotes/'))[0] }
  }
  // Same name on origin, different commit. The live local-only pass skips this ref
  // precisely because a remote counterpart exists, so an unmatched snapshot ref with
  // a published name is not a conflict — it is a tip the published branch moved past.
  // Filing it as CONFLICTED would bury the refs that genuinely have nowhere to go.
  if (ref && remoteHas(ref)) {
    return { classification: 'SUPERSEDED_BY_NEWER',
      disposition: `origin/${ref} exists but does not contain the snapshot sha; the published ` +
        'branch moved on. The local ref is left exactly where it is either way',
      evidence: `origin/${ref} diverged from the snapshot tip` }
  }
  return { classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
    disposition: 'snapshot ref is neither in the live enumeration nor reachable from base or ' +
      'any remote; queue a focused task rather than assuming it is safe to drop',
    evidence: 'unmatched snapshot ref' }
}

function main() {
  const ledgerPath = arg('ledger')
  const snapshotPath = arg('snapshot')
  const base = arg('base', 'origin/master')
  const out = arg('out', ledgerPath)
  if (!ledgerPath || !snapshotPath) {
    console.error('usage: map_snapshot_evidence.mjs --ledger <f> --snapshot <f> [--base ref] [--out f]')
    return 2
  }
  const ledger = JSON.parse(readFileSync(ledgerPath, 'utf8'))
  const snapshot = JSON.parse(readFileSync(snapshotPath, 'utf8'))
  // Idempotent: re-running over a ledger that already carries snapshot rows replaces
  // them rather than doubling every count.
  const live = (ledger.items || []).filter((i) => !String(i.kind || '').startsWith('snapshot:'))
  const rows = []

  for (const [n, item] of snapshot.entries()) {
    const kind = item.kind || 'unknown'
    const members = item.branches || item.items || item.items_sample || item.branches_sample || []
    if (members.length) {
      for (const m of members) {
        const r = resolveRef(m, live, base)
        rows.push({ kind: `snapshot:${kind}`, ref: `snapshot[${n}] ${m.ref || m.branch}`,
          sha: m.sha || m.head || '', ...r, files: [], subject: m.subject || '' })
      }
      continue
    }
    // A non-collection snapshot entry (a dirty worktree, a bridge/output artifact):
    // roll up whatever the live pass classified under that same path.
    const path = item.path || item.repo || ''
    const covered = live.filter((i) => String(i.ref || '').includes(path))
    const r = covered.length
      ? { classification: rollUp(covered.map((i) => i.classification)),
          disposition: `${covered.length} live row(s) under ${path}; ` +
            'worst-case classification governs the snapshot item',
          evidence: `rolled up from ${covered.length} live ledger row(s)` }
      : resolveRef(item, live, base)
    rows.push({ kind: `snapshot:${kind}`, ref: `snapshot[${n}] ${path || kind}`,
      sha: item.head || item.sha || '', ...r, files: [], subject: '' })
  }

  ledger.items = [...live, ...rows]
  ledger.total = ledger.items.length
  ledger.snapshot_items = rows.length
  const counts = Object.fromEntries(CLASSES.map((c) => [c, 0]))
  let unknown = 0
  for (const i of ledger.items) {
    if (CLASSES.includes(i.classification)) counts[i.classification] += 1
    else unknown += 1
  }
  ledger.counts = counts
  ledger.unknown = unknown
  ledger.counts_by_kind = ledger.counts_by_kind || {}
  for (const k of Object.keys(ledger.counts_by_kind)) {
    if (k.startsWith('snapshot:')) delete ledger.counts_by_kind[k]
  }
  for (const i of rows) {
    ledger.counts_by_kind[i.kind] = ledger.counts_by_kind[i.kind] || {}
    ledger.counts_by_kind[i.kind][i.classification] =
      (ledger.counts_by_kind[i.kind][i.classification] || 0) + 1
  }
  writeFileSync(out, `${JSON.stringify(ledger, null, 1)}\n`)
  console.log(JSON.stringify({ snapshot_rows: rows.length, total: ledger.total,
    unknown, counts }, null, 2))
  return unknown === 0 ? 0 : 1
}

// Only run as a CLI. The test imports the pure helpers above and must not exit.
if (process.argv[1] && process.argv[1].endsWith('map_snapshot_evidence.mjs')) {
  process.exit(main())
}
