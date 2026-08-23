#!/usr/bin/env node
/**
 * recovery-doctor — is the evidence audit still telling the truth?
 *
 * Runs the self-checks against the most recent committed ledger. Every stage of
 * the recovery pipeline fails quietly — an enumerator that goes blind reports
 * zero items and zero unknowns, which is indistinguishable from a clean audit —
 * so this asks whether each stage is still doing its job, not whether it ran.
 *
 * Read-only.
 *
 * Usage:  node scripts/recovery-doctor.mjs [--repo <path>] [--ledger-dir <path>] [--json]
 * Exit 0 ok · 1 warn · 2 fail
 */

import { runSelfCheck } from './lib/recovery-selfcheck.mjs'

const ICON = { ok: '✓', warn: '!', fail: '✗' }

function parseArgs(argv) {
  const args = { repoPath: process.cwd(), ledgerDir: 'docs/recovery', json: false }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    if (flag === '--json') args.json = true
    else if (flag === '--repo') args.repoPath = argv[++i]
    else if (flag === '--ledger-dir') args.ledgerDir = argv[++i]
  }
  return args
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  const result = runSelfCheck(args)

  if (args.json) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
  } else {
    console.log(`ledger  ${result.ledgerPath ?? '(none)'}`)
    for (const item of result.checks) {
      console.log(`  ${ICON[item.severity]} ${item.name.padEnd(26)} ${item.detail}`)
    }
    console.log(`\noverall: ${result.severity}`)
    if (result.severity === 'fail') {
      console.log('\nA failing check means the audit is reporting something it did not verify.')
      console.log('Re-run `npm run reconcile:evidence` and investigate before trusting the ledger.')
    }
  }

  process.exit(result.severity === 'fail' ? 2 : result.severity === 'warn' ? 1 : 0)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
