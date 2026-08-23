#!/usr/bin/env node
/**
 * Route unrecovered evidence back to the task that produced it.
 *
 * Read-only; parses ref names, looks nothing up. Whether a named task is still
 * live is a question for whoever holds the task list — and it is the important
 * follow-up question, because if the task IS live the right move is usually to
 * let it finish rather than open a duplicate.
 *
 * Usage:
 *   node scripts/attribute-recovery-ledger.mjs <ledger.json> [--out <path>] [--json]
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { ATTRIBUTION_KINDS, attributeLedger } from './lib/evidence-attribution.mjs'

export function toMarkdown(report) {
  const lines = [
    '# Evidence attribution',
    '',
    `- Audit fingerprint: \`${report.auditFingerprint ?? '—'}\``,
    `- Attributed: ${report.attributedAt}`,
    `- Items with remaining value: **${report.totals.considered}**`,
    `- Distinct tasks: **${report.totals.distinctTasks}** · unattributable: **${report.totals.unattributable}**`,
    '',
    'A rescue sweep fires on a timer, so one task routinely leaves many refs.',
    'Grouping by task turns a long anonymous queue into a short list of work,',
    'each item of which already knows what it was for.',
    '',
    '## By attribution kind',
    '',
    '| Kind | Items |',
    '| --- | ---: |',
    ...ATTRIBUTION_KINDS.map(kind => `| ${kind} | ${report.totals.byKind[kind]} |`),
    '',
    '## Tasks that left work behind',
    '',
  ]
  if (report.tasks.length === 0) {
    lines.push('None attributable.', '')
  } else {
    lines.push('| Task slug | Refs | First | Last |', '| --- | ---: | --- | --- |')
    for (const task of report.tasks) {
      lines.push(
        `| \`${task.slug}\` | ${task.items.length} | ${task.firstSeenAt ?? '—'} | ${task.lastSeenAt ?? '—'} |`,
      )
    }
    lines.push(
      '',
      'Before opening a follow-up for any of these, check whether the task is still',
      'live. If it is, letting it finish beats opening a second one.',
      '',
    )
  }
  return lines.join('\n')
}

function parseArgs(argv) {
  const args = { ledger: null, out: null, json: false }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    if (flag === '--json') args.json = true
    else if (flag === '--out') args.out = argv[++i]
    else if (!args.ledger) args.ledger = flag
  }
  return args
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.ledger) {
    console.error('attribute-recovery-ledger: pass a ledger JSON path')
    process.exit(2)
  }

  const ledger = JSON.parse(readFileSync(args.ledger, 'utf8'))
  if (!Array.isArray(ledger.items)) {
    console.error(`${args.ledger}: not a recovery ledger — no items array`)
    process.exit(2)
  }

  const report = attributeLedger(ledger)

  if (args.json) {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
    return
  }

  const stem = args.out ?? args.ledger.replace(/\.json$/, '.attribution')
  writeFileSync(`${stem}.json`, `${JSON.stringify(report, null, 2)}\n`)
  writeFileSync(`${stem}.md`, toMarkdown(report))

  console.log(`considered      ${report.totals.considered}`)
  console.log(`distinct tasks  ${report.totals.distinctTasks}`)
  for (const kind of ATTRIBUTION_KINDS) console.log(`  ${kind.padEnd(16)} ${report.totals.byKind[kind]}`)
  for (const task of report.tasks.slice(0, 10)) {
    console.log(`  ${String(task.items.length).padStart(4)}  ${task.slug}`)
  }
  console.log(`wrote ${stem}.json and ${stem}.md`)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
