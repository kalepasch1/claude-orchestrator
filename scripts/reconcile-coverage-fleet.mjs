#!/usr/bin/env node
/**
 * reconcile-coverage-fleet — how much of each project's evidence is actually classified.
 *
 * Six `chatgpt-local-reconcile-*` tasks were queued across five projects on the
 * same day, on top of 32 ledgers already committed. Nobody could say whether that
 * was necessary, because coverage was only ever visible from inside a single
 * ledger. Measured across the fleet:
 *
 *   project             refs  ledgers   rows  covered  bookkeeping  OUTSTANDING
 *   beethoven           1648       19   9481     1279           91          993
 *   apparently          1196        6   1221      401           41          959
 *   darwn                656        0      0        0           65          591
 *   sustainable-barks    421        0      0        0           43          378
 *   pareto-2080          367        4   1152      480           38          194
 *   racefeed             326        3    324      287           14          312
 *   ------------------------------------------------------------------------
 *   totals              4614       32  12459     2447          292         3427
 *
 * Two things that only show up at this scale:
 *
 *   * 12,459 ledger rows cover 2,447 DISTINCT sources — 5.1x re-classification
 *     across the fleet, and 7.4x in beethoven alone (9,481 rows -> 1,279). Passes
 *     keep re-deriving each other's work because each ledger is committed to its
 *     own agent branch, so a pass can only see predecessors it happens to share a
 *     ref with.
 *   * darwn and sustainable-barks have ZERO ledgers. They have never been
 *     reconciled at all, and that is invisible from any single-project view —
 *     which is why "reconcile project X" kept being queued for the projects that
 *     were already the most reconciled.
 *
 * Orchestration bookkeeping is excluded BEFORE anything counts as outstanding:
 * 292 refs across the fleet carry nothing but recovery ledgers and
 * `.recovery-intent-*` stubs — the reconciliation's own exhaust. See
 * scripts/lib/orchestration-artifacts.mjs.
 *
 * Read-only: for-each-ref, ls-tree, cat-file, diff-tree, stash list. Nothing is
 * applied, dropped, reset, popped or moved in any repository.
 *
 *   node scripts/reconcile-coverage-fleet.mjs \
 *     --repo /path/to/repo:origin/main:name  [--repo ...]
 *   node scripts/reconcile-coverage-fleet.mjs --repo ... --list 20
 */

import { execFileSync } from 'node:child_process'
import { partitionEvidence, summariseExclusions } from './lib/orchestration-artifacts.mjs'

const NAMESPACES = ['refs/orch-rescue', 'refs/rescue', 'refs/codex', 'refs/archive', 'refs/heads']

function git(repo, args) {
  try {
    // stderr is dropped deliberately: some rescue refs point at TREES rather than
    // commits, so diff-tree reports "object <sha> is a tree, not a commit" for
    // each. That is a shape of this evidence, not a fault — the ref yields no
    // paths and STAYS in the universe, because a read failure must never be
    // grounds for excluding something.
    return execFileSync('git', args, {
      cwd: repo, encoding: 'utf8', maxBuffer: 1 << 28, stdio: ['ignore', 'pipe', 'ignore'],
    })
  } catch {
    return ''
  }
}

/**
 * Sources already classified by the ledgers committed on `ref`.
 *
 * Dialects drifted across passes: rows live under `rows`, `records` or `items`,
 * and a source under `source`, `ref` or `name`. A reader that knows one dialect
 * reports the others as uncovered and manufactures a phantom backlog, so all
 * three spellings are accepted. A ledger whose rows carry no distinct source is
 * counted as malformed rather than as coverage — it cannot say WHAT it
 * classified, so treating its row count as progress hides real work.
 */
export function ledgerCoverage(repo, ref) {
  const covered = new Set()
  let rows = 0
  let malformed = 0
  const files = git(repo, ['ls-tree', '-r', '--name-only', ref, '.orch/'])
    .split('\n')
    .filter((p) => /^\.orch\/recovery-ledger-.*\.json$/.test(p))

  for (const path of files) {
    let parsed
    try {
      parsed = JSON.parse(git(repo, ['cat-file', '-p', `${ref}:${path}`]))
    } catch {
      malformed += 1
      continue
    }
    const list = parsed.rows || parsed.records || parsed.items || []
    rows += list.length
    const sources = new Set()
    for (const r of list) {
      if (!r || typeof r !== 'object') continue
      const s = r.source || r.ref || r.name
      if (s) sources.add(s)
    }
    if (list.length > 1 && sources.size <= 1) malformed += 1
    for (const s of sources) covered.add(s)
  }
  return { covered, rows, ledgers: files.length, malformed }
}

export function coverageFor(repo, ref, name) {
  const refs = git(repo, ['for-each-ref', '--format=%(refname)', ...NAMESPACES])
    .split('\n').filter(Boolean)
  const { covered, rows, ledgers, malformed } = ledgerCoverage(repo, ref)

  const universe = refs.map((r) => ({
    kind: 'ref',
    ref: r,
    paths: git(repo, ['diff-tree', '--no-commit-id', '--name-only', '-r', r])
      .split('\n').map((s) => s.trim()).filter(Boolean),
    createdAt: null,
  }))
  const { kept, excluded } = partitionEvidence(universe, {})
  const outstanding = kept.filter((e) => !covered.has(e.ref))

  return {
    name,
    repo,
    ref,
    refs: refs.length,
    ledgers,
    malformed,
    rows,
    covered: covered.size,
    bookkeeping: excluded.length,
    excludedByReason: summariseExclusions(excluded).byReason,
    outstanding: outstanding.map((e) => e.ref),
    stashes: git(repo, ['stash', 'list']).split('\n').filter(Boolean).length,
  }
}

function parseRepos(argv) {
  const out = []
  argv.forEach((a, i) => {
    if (a !== '--repo') return
    const [repo, ref, name] = String(argv[i + 1] || '').split(':')
    if (repo && ref) out.push({ repo, ref, name: name || repo.split('/').pop() })
  })
  return out
}

if (process.argv[1] && process.argv[1].endsWith('reconcile-coverage-fleet.mjs')) {
  const repos = parseRepos(process.argv)
  if (!repos.length) {
    console.error('usage: reconcile-coverage-fleet.mjs --repo <path>:<ref>:<name> [--repo ...]')
    process.exit(2)
  }
  const rows = repos.map((r) => coverageFor(r.repo, r.ref, r.name))

  const head = 'project'.padEnd(20) + ['refs', 'ledgers', 'rows', 'covered', 'bookkpg', 'OUTSTANDING', 'stashes']
    .map((h) => h.padStart(12)).join('')
  console.log('\n' + head)
  console.log('-'.repeat(head.length))
  const tot = { refs: 0, ledgers: 0, rows: 0, covered: 0, bookkeeping: 0, outstanding: 0, stashes: 0 }
  for (const r of rows) {
    console.log(
      r.name.padEnd(20) +
      [r.refs, r.ledgers + (r.malformed ? `(${r.malformed}!)` : ''), r.rows, r.covered,
       r.bookkeeping, r.outstanding.length, r.stashes]
        .map((v) => String(v).padStart(12)).join(''))
    tot.refs += r.refs; tot.ledgers += r.ledgers; tot.rows += r.rows
    tot.covered += r.covered; tot.bookkeeping += r.bookkeeping
    tot.outstanding += r.outstanding.length; tot.stashes += r.stashes
  }
  console.log('-'.repeat(head.length))
  console.log('totals'.padEnd(20) +
    [tot.refs, tot.ledgers, tot.rows, tot.covered, tot.bookkeeping, tot.outstanding, tot.stashes]
      .map((v) => String(v).padStart(12)).join(''))
  if (tot.covered) {
    console.log(`\n  ${(tot.rows / tot.covered).toFixed(1)}x re-classification: ${tot.rows} rows cover ${tot.covered} distinct sources.`)
  }
  const never = rows.filter((r) => r.ledgers === 0).map((r) => r.name)
  if (never.length) console.log(`  never reconciled at all: ${never.join(', ')}`)
  console.log()

  const li = process.argv.indexOf('--list')
  if (li > -1) {
    const n = Number(process.argv[li + 1] || 20)
    for (const r of rows) {
      if (!r.outstanding.length) continue
      console.log(`  ${r.name} — first ${Math.min(n, r.outstanding.length)} of ${r.outstanding.length} outstanding:`)
      for (const ref of r.outstanding.slice(0, n)) console.log(`      ${ref}`)
    }
  }
}
