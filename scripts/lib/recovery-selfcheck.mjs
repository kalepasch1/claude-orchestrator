#!/usr/bin/env node
/**
 * Does the evidence audit still work?
 *
 * The recovery tooling is now a pipeline — enumerate, classify, verify, dedupe,
 * queue, triage, plan — and its most dangerous property is that every stage
 * fails QUIETLY. A source enumerator that stops returning anything reports zero
 * items and zero unknowns, which reads exactly like a clean audit. A ledger
 * frozen at last month's base looks identical to a fresh one. Nothing throws.
 *
 * This is the check that would have caught the two defects already found the
 * hard way: the stash enumerator that parsed every sha as `undefined`, and a
 * ledger reporting a confident zero-UNKNOWN over evidence it had not looked at.
 *
 * Every check answers "is this stage still doing its job?", not "did it run".
 */

import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

export const CHECK_SEVERITIES = ['ok', 'warn', 'fail']

function git(args, cwd) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).trim()
  } catch {
    return null
  }
}

function check(name, severity, detail) {
  return { name, severity, detail }
}

/** Every enumerator that returns nothing while its source is non-empty. */
export function checkEnumeratorsSeeSomething(repoPath, counts) {
  const results = []

  const rescueOnDisk = (git(['for-each-ref', 'refs/orch-rescue', '--format=%(refname)'], repoPath) ?? '')
    .split('\n')
    .filter(Boolean).length
  const stashOnDisk = (git(['stash', 'list'], repoPath) ?? '').split('\n').filter(Boolean).length

  results.push(
    rescueOnDisk > 0 && (counts.orchestrator_rescue_refs ?? 0) === 0
      ? check(
          'rescue-refs-enumerated',
          'fail',
          `${rescueOnDisk} rescue refs on disk but the ledger holds none — the enumerator has gone blind`,
        )
      : check('rescue-refs-enumerated', 'ok', `${counts.orchestrator_rescue_refs ?? 0} enumerated`),
  )

  results.push(
    stashOnDisk > 0 && (counts.stashes ?? 0) === 0
      ? check('stashes-enumerated', 'fail', `${stashOnDisk} stashes on disk but the ledger holds none`)
      : check('stashes-enumerated', 'ok', `${counts.stashes ?? 0} enumerated`),
  )

  return results
}

/**
 * Commit-backed items must carry a resolvable sha.
 *
 * This is the exact shape of the stash bug: nothing threw, the count was right,
 * and every item classified as "does not resolve to a commit" — a confident,
 * wrong, silent pass.
 */
export function checkShasResolve(ledger, repoPath, sampleSize = 25) {
  const commitBacked = ledger.items.filter(
    item => item.kind !== 'dirty_worktree' && item.kind !== 'chatgpt_bridge_artifact',
  )
  if (commitBacked.length === 0) return [check('shas-resolve', 'ok', 'no commit-backed items')]

  const missing = commitBacked.filter(item => !item.sha)
  if (missing.length > 0) {
    return [
      check(
        'shas-resolve',
        'fail',
        `${missing.length}/${commitBacked.length} commit-backed items carry no sha (e.g. ${missing[0].source})`,
      ),
    ]
  }

  const sample = commitBacked.slice(0, sampleSize)
  const unresolvable = sample.filter(
    item => git(['cat-file', '-e', `${item.sha}^{commit}`], repoPath) === null,
  )
  if (unresolvable.length > sample.length / 2) {
    return [
      check(
        'shas-resolve',
        'fail',
        `${unresolvable.length}/${sample.length} sampled shas do not resolve — the ledger may be from another repo`,
      ),
    ]
  }
  return [check('shas-resolve', 'ok', `${sample.length} sampled shas resolve`)]
}

/** A ledger written against a base that has since moved is stale. */
export function checkLedgerFreshness(ledger, repoPath, maxAgeDays = 14) {
  const results = []

  const currentBase = git(['rev-parse', ledger.base ?? 'origin/master'], repoPath)
  if (currentBase && ledger.baseSha && currentBase !== ledger.baseSha) {
    results.push(
      check(
        'ledger-base-current',
        'warn',
        `ledger was written against ${ledger.baseSha.slice(0, 12)} but the base is now ${currentBase.slice(0, 12)} — re-run`,
      ),
    )
  } else {
    results.push(check('ledger-base-current', 'ok', 'base unchanged since the ledger was written'))
  }

  const generated = Date.parse(ledger.generatedAt ?? '')
  if (Number.isFinite(generated)) {
    const ageDays = Math.floor((Date.now() - generated) / 86_400_000)
    results.push(
      ageDays > maxAgeDays
        ? check('ledger-age', 'warn', `ledger is ${ageDays} days old`)
        : check('ledger-age', 'ok', `${ageDays} day(s) old`),
    )
  } else {
    results.push(check('ledger-age', 'warn', 'ledger has no generatedAt'))
  }

  return results
}

/** The claim the whole exercise rests on. */
export function checkNoUnknowns(ledger) {
  const declared = ledger.totals?.unknown
  const undeclared = ledger.items.filter(item => !item.classification).length

  if (undeclared > 0) {
    return [check('no-unknowns', 'fail', `${undeclared} item(s) carry no classification`)]
  }
  if (declared !== 0) {
    return [check('no-unknowns', 'fail', `totals.unknown is ${declared}`)]
  }
  if (ledger.totals?.items !== ledger.items.length) {
    return [
      check(
        'no-unknowns',
        'fail',
        `totals.items ${ledger.totals?.items} disagrees with ${ledger.items.length} rows`,
      ),
    ]
  }
  return [check('no-unknowns', 'ok', `${ledger.items.length} items, none unclassified`)]
}

/**
 * An audit that classifies everything as accounted for is either a triumph or
 * a broken classifier, and those look identical in a summary. Say so.
 */
export function checkClassifierDiscriminates(ledger) {
  const byClass = ledger.totals?.byClass ?? {}
  const distinct = Object.values(byClass).filter(count => count > 0).length
  if (ledger.items.length >= 20 && distinct <= 1) {
    return [
      check(
        'classifier-discriminates',
        'warn',
        'every item landed in a single class — plausible, but far more often a broken classifier',
      ),
    ]
  }
  return [check('classifier-discriminates', 'ok', `${distinct} classes represented`)]
}

/**
 * Sidecar reports written NEXT TO a ledger, named after it.
 *
 * `evidence-ledger-<fp>.dedupe.json` and friends all match a naive
 * `*ledger*.json` glob, are written after the ledger, and therefore win a
 * newest-first sort. The doctor then reads a dedupe report, correctly observes
 * it has no `items` array, and reports the AUDIT as failing — a false alarm
 * about the one thing this tool exists to make trustworthy. Observed in the
 * first live run of the doctor; excluded by suffix rather than by ordering,
 * because a future sidecar would reintroduce the same bug.
 */
export const SIDECAR_SUFFIXES = [
  '.dedupe.json',
  '.attribution.json',
  '.triage.json',
  '.risk.json',
  '.plans.json',
]

export function isSidecar(name) {
  return SIDECAR_SUFFIXES.some(suffix => name.endsWith(suffix))
}

export function findLatestLedger(dir) {
  if (!existsSync(dir)) return null
  const candidates = readdirSync(dir)
    .filter(name => name.endsWith('.json') && name.includes('ledger') && !isSidecar(name))
    .map(name => join(dir, name))
  if (candidates.length === 0) return null
  return candidates.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs)[0]
}

export function runSelfCheck({ repoPath = process.cwd(), ledgerDir = 'docs/recovery' } = {}) {
  const ledgerPath = findLatestLedger(ledgerDir)
  if (!ledgerPath) {
    return {
      ledgerPath: null,
      checks: [check('ledger-present', 'fail', `no ledger found in ${ledgerDir} — this repo has never been audited`)],
      severity: 'fail',
    }
  }

  let ledger
  try {
    ledger = JSON.parse(readFileSync(ledgerPath, 'utf8'))
  } catch (error) {
    return {
      ledgerPath,
      checks: [check('ledger-parses', 'fail', `${ledgerPath} is not valid JSON: ${error.message}`)],
      severity: 'fail',
    }
  }
  if (!Array.isArray(ledger.items)) {
    return {
      ledgerPath,
      checks: [check('ledger-parses', 'fail', `${ledgerPath} has no items array`)],
      severity: 'fail',
    }
  }

  const checks = [
    ...checkEnumeratorsSeeSomething(repoPath, ledger.totals?.byKind ?? {}),
    ...checkShasResolve(ledger, repoPath),
    ...checkNoUnknowns(ledger),
    ...checkClassifierDiscriminates(ledger),
    ...checkLedgerFreshness(ledger, repoPath),
  ]

  const severity = checks.some(item => item.severity === 'fail')
    ? 'fail'
    : checks.some(item => item.severity === 'warn')
      ? 'warn'
      : 'ok'

  return { ledgerPath, checks, severity }
}
