#!/usr/bin/env node
/**
 * verify-no-self-feeding — the acceptance check, re-runnable on real data.
 *
 * Enumerates this repository's actual evidence universe, applies the exclusion,
 * and asserts the property that matters: after exclusion, NOTHING reaching
 * classification is pure orchestration bookkeeping. Exits non-zero if anything
 * leaks, so it can be used as a gate rather than read as a report.
 *
 * Deliberately independent of reconcile-evidence.mjs's own classification pass,
 * which walks ancestry for ~1,700 refs and takes minutes: this answers only the
 * exclusion question, in seconds, so the property can actually be re-checked.
 *
 * Read-only: for-each-ref, diff-tree, log.
 *
 *   node scripts/lib/verify-no-self-feeding.mjs
 */

import { execFileSync } from 'node:child_process'
import {
  partitionEvidence,
  summariseExclusions,
  isOrchestrationPath,
} from './orchestration-artifacts.mjs'

const git = (args) => {
  try {
    return execFileSync('git', args, { encoding: 'utf8', maxBuffer: 1 << 28 })
  } catch {
    return ''
  }
}

const runStartedAt = new Date().toISOString()

const rescue = ['refs/orch-rescue', 'refs/rescue', 'refs/codex', 'refs/archive']
  .flatMap((ns) => git(['for-each-ref', '--format=%(refname)', ns]).split('\n').filter(Boolean))
const branches = git(['for-each-ref', '--format=%(refname)', 'refs/heads'])
  .split('\n')
  .filter(Boolean)

const universe = [
  ...branches.map((ref) => ({ kind: 'branch', ref, paths: [], createdAt: null })),
  ...rescue.map((ref) => ({
    kind: 'rescue_ref',
    ref,
    paths: git(['diff-tree', '--no-commit-id', '--name-only', '-r', ref])
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean),
    createdAt: git(['log', '-1', '--format=%cI', ref]).trim() || null,
  })),
]

const { kept, excluded } = partitionEvidence(universe, { runStartedAt })

console.log(`universe: ${universe.length}  (branches ${branches.length}, sweeps/rescue ${rescue.length})`)
console.log(`kept:     ${kept.length}`)
console.log(`excluded: ${excluded.length}`, JSON.stringify(summariseExclusions(excluded).byReason))

console.log('\nexcluded (first 8):')
for (const e of excluded.slice(0, 8)) {
  console.log(`  ${e.exclusionReason}  ${e.ref}\n      ${e.exclusionDetail}`)
}

// The acceptance: nothing left in the kept set is pure orchestration bookkeeping.
const leaked = kept.filter((k) => k.paths.length && k.paths.every(isOrchestrationPath))
console.log(`\nACCEPTANCE — orchestration artifacts still reaching classification: ${leaked.length}`)
for (const l of leaked.slice(0, 5)) console.log('   LEAK', l.ref, l.paths.slice(0, 3))
if (leaked.length) process.exitCode = 1
