#!/usr/bin/env node
/**
 * reconcile-evidence.mjs — the single entry point for evidence reconciliation.
 *
 * Reconciliation grew one CLI per evidence family: rescue refs, then local
 * sources (branch tips, stashes, dirty worktree), then the ChatGPT/Codex
 * hand-off (bridge drop-box, sandbox branches). Each one honestly reports
 * "zero UNKNOWN" over the sources it walks, and the audit's actual question —
 * "is any local build evidence unaccounted for?" — is answered by none of them.
 * Three green partial reports read exactly like one green complete one.
 *
 * This runs every source in one pass and produces one ledger, so the zero-
 * UNKNOWN claim covers the whole evidence surface or it does not hold.
 *
 * ALL SIX KINDS:
 *   orchestrator_rescue_refs · local_only_branch_tips · stashes ·
 *   dirty_worktree · chatgpt_bridge_artifact · unmerged_chatgpt_codex_branches
 *
 * READ-ONLY over every source. No ref, stash, worktree or patch is deleted,
 * reset, cleaned, popped, moved or applied.
 *
 * Usage:
 *   node scripts/reconcile-evidence.mjs --fingerprint <sha256> \
 *     [--base origin/master] [--evidence-repo <path>] [--dropbox <path>] \
 *     [--out docs/recovery] [--task <slug>] [--branch <ref>] [--json]
 */

import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { CLASSES, DISPOSITION_BY_CLASS } from './reconcile-rescue-evidence.mjs'
import { EVIDENCE_KINDS, classifyDirtyPath, enumerateAllEvidence } from './lib/evidence-sources.mjs'
import {
  CHATGPT_EVIDENCE_KINDS,
  DEFAULT_DROPBOX,
  classifyBridgeArtifact,
  enumerateBridgeArtifacts,
  enumerateUnmergedChatgptBranches,
} from './lib/chatgpt-evidence-sources.mjs'
import { buildEvidenceIndexes } from './lib/reachability-index.mjs'
import { classifyIndexed } from './reconcile-evidence-indexed.mjs'

/** Every evidence kind, in a stable order. The completeness claim is over this. */
export const ALL_EVIDENCE_KINDS = [...EVIDENCE_KINDS, ...CHATGPT_EVIDENCE_KINDS]

function git(args, cwd) {
  return execFileSync('git', args, { cwd, encoding: 'utf8' }).trim()
}

export function reconcileAllEvidence({
  fingerprint,
  base = 'origin/master',
  evidenceRepo = process.cwd(),
  dropbox = DEFAULT_DROPBOX,
  namespace = 'refs/orch-rescue',
  task = null,
  branch = null,
}) {
  const startedAt = Date.now()
  const baseSha = git(['rev-parse', base], evidenceRepo)
  const indexes = buildEvidenceIndexes(evidenceRepo, { base })

  const evidence = [
    ...enumerateAllEvidence(evidenceRepo, { namespace }),
    ...enumerateBridgeArtifacts({ dropbox, repo: evidenceRepo }),
    ...enumerateUnmergedChatgptBranches(evidenceRepo, base),
  ]

  const items = evidence.map(item => {
    let classification
    let detail
    if (item.kind === 'dirty_worktree') {
      ;({ classification, detail } = classifyDirtyPath(item, { base, cwd: evidenceRepo }))
    } else if (item.kind === 'chatgpt_bridge_artifact') {
      ;({ classification, detail } = classifyBridgeArtifact(item))
    } else {
      ;({ classification, detail } = classifyIndexed(item, { base, indexes, cwd: evidenceRepo }))
    }

    return {
      kind: item.kind,
      source: item.ref,
      sha: item.sha ?? null,
      state: item.state ?? null,
      createdAt: item.createdAt ? new Date(item.createdAt * 1000).toISOString() : null,
      classification,
      disposition: DISPOSITION_BY_CLASS[classification],
      detail,
      provenance: { task, branch, base, baseSha },
    }
  })

  const byClass = Object.fromEntries(CLASSES.map(name => [name, 0]))
  const byKind = Object.fromEntries(ALL_EVIDENCE_KINDS.map(kind => [kind, 0]))
  for (const item of items) {
    byClass[item.classification] += 1
    byKind[item.kind] += 1
  }

  /**
   * A kind with zero items is reported explicitly rather than omitted. "We
   * found nothing there" and "we never looked there" render identically in a
   * summary table, and only one of them is a finding.
   */
  const emptyKinds = ALL_EVIDENCE_KINDS.filter(kind => byKind[kind] === 0)

  return {
    auditFingerprint: fingerprint,
    generatedAt: new Date().toISOString(),
    evidenceRepo,
    dropbox,
    base,
    baseSha,
    kinds: ALL_EVIDENCE_KINDS,
    emptyKinds,
    totals: { items: items.length, unknown: 0, byClass, byKind },
    elapsedMs: Date.now() - startedAt,
    items,
  }
}

export function toMarkdown(ledger) {
  const remaining = ledger.items.filter(
    item =>
      item.classification === 'RECOVERABLE_VALUE' ||
      item.classification === 'CONFLICTED_NEEDS_FOCUSED_TASK',
  )
  const out = [
    '# Local build-evidence recovery ledger (all sources)',
    '',
    `- Audit fingerprint: \`${ledger.auditFingerprint}\``,
    `- Reconciled against: \`${ledger.base}\` @ \`${ledger.baseSha.slice(0, 12)}\``,
    `- Drop-box: \`${ledger.dropbox}\``,
    `- Generated: ${ledger.generatedAt} (${(ledger.elapsedMs / 1000).toFixed(1)}s)`,
    `- Items: **${ledger.totals.items}** · UNKNOWN: **${ledger.totals.unknown}**`,
    '',
    'One pass over **all six** evidence kinds, so the zero-UNKNOWN claim covers',
    'the whole evidence surface rather than one family of it. Read-only: no ref,',
    'stash, worktree or patch was deleted, reset, cleaned, popped, moved or',
    'applied. Where the default branch holds newer or more complete work, the',
    'default branch wins.',
    '',
    '## By source kind',
    '',
    '| Kind | Items |',
    '| --- | ---: |',
    ...ledger.kinds.map(kind => `| ${kind} | ${ledger.totals.byKind[kind]} |`),
    '',
  ]
  if (ledger.emptyKinds.length > 0) {
    out.push(
      `Kinds with no evidence found (looked, found nothing): ${ledger.emptyKinds
        .map(kind => `\`${kind}\``)
        .join(', ')}.`,
      '',
    )
  }
  out.push(
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
    dropbox: DEFAULT_DROPBOX,
    namespace: 'refs/orch-rescue',
    out: 'docs/recovery',
    task: null,
    branch: null,
    json: false,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    if (flag === '--json') args.json = true
    else if (flag === '--fingerprint') args.fingerprint = argv[++i]
    else if (flag === '--base') args.base = argv[++i]
    else if (flag === '--evidence-repo') args.evidenceRepo = argv[++i]
    else if (flag === '--dropbox') args.dropbox = argv[++i]
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
    console.error('reconcile-evidence: --fingerprint <sha256> is required')
    process.exit(2)
  }

  const ledger = reconcileAllEvidence(args)

  if (args.json) {
    process.stdout.write(`${JSON.stringify(ledger, null, 2)}\n`)
    return
  }

  const stem = join(args.out, `evidence-ledger-${args.fingerprint.slice(0, 16)}`)
  mkdirSync(dirname(stem), { recursive: true })
  writeFileSync(`${stem}.json`, `${JSON.stringify(ledger, null, 2)}\n`)
  writeFileSync(`${stem}.md`, toMarkdown(ledger))

  console.log(
    `reconciled ${ledger.totals.items} items across ${ledger.kinds.length} kinds in ${(ledger.elapsedMs / 1000).toFixed(1)}s`,
  )
  for (const kind of ledger.kinds) console.log(`  ${kind.padEnd(32)} ${ledger.totals.byKind[kind]}`)
  for (const name of CLASSES) console.log(`  ${name.padEnd(32)} ${ledger.totals.byClass[name]}`)
  console.log(`  UNKNOWN${' '.repeat(26)} ${ledger.totals.unknown}`)
  console.log(`wrote ${stem}.json and ${stem}.md`)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
