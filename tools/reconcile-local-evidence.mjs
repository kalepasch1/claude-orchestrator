#!/usr/bin/env node
// reconcile-local-evidence.mjs
//
// Classifies local recovery evidence against the current default branch so none
// of it is either silently lost or blindly replayed over newer code.
//
// Handles the three evidence kinds the local sweeps produce:
//   --kind local-branches   local branch tips with no remote counterpart
//   --kind rescue-refs      refs/orch-rescue/* sweep commits
//   --kind worktree         a dirty worktree's uncommitted changes
//
// READ-ONLY with respect to the evidence: it never deletes, resets, cleans,
// pops, checks out or moves anything. It only reads and reports.
//
// Every item lands in exactly one bucket — UNKNOWN is not a reachable outcome:
//
//   ALREADY_PRESENT               reachable from the base, or its content
//                                 already matches the base
//   ACTIVE_IN_ANOTHER_TASK        a live remote branch owns the work
//   SUPERSEDED_BY_NEWER           every touched file was rewritten on the base
//                                 after the evidence was captured
//   RECOVERABLE_VALUE             unique content that still applies cleanly
//   CONFLICTED_NEEDS_FOCUSED_TASK unique content that no longer applies
//
// Usage:
//   node scripts/reconcile-local-evidence.mjs --kind local-branches \
//     --base origin/main --fingerprint <sha256> --json out.json

import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'

const CLASSIFICATIONS = [
  'ALREADY_PRESENT',
  'ACTIVE_IN_ANOTHER_TASK',
  'SUPERSEDED_BY_NEWER',
  'RECOVERABLE_VALUE',
  'CONFLICTED_NEEDS_FOCUSED_TASK',
]

// Paths that are build output, not authored work. A lockfile is deliberately
// NOT here: a lockfile change is real and is adjudicated on content.
const ARTIFACT_RE =
  /(^|\/)(node_modules|\.nuxt|\.output|\.vite|\.turbo|dist|coverage|__pycache__|\.pytest_cache|\.mypy_cache)(\/|$)|\.pyc$/

// Orchestrator scratch: markers the recovery/dropbox loops drop into the worktree to
// record their own intent. They are bookkeeping for a run that has already been
// queued, never product code, so recovering them re-litigates finished plumbing.
const ORCH_SCRATCH_RE = /(^|\/)(\.recovery-intent-[^/]*\.txt|\.deploy-canary|\.aider\.chat\.history\.md)$/

/** Drop generated output and orchestrator scratch so adjudication only sees authored work. */
function sourceFilesOnly(files) {
  return files.filter((f) => !ARTIFACT_RE.test(f) && !ORCH_SCRATCH_RE.test(f))
}

// A single sweep can touch thousands of files. The ledger needs enough of a sample
// to identify the content plus an exact count — not a five-figure file dump that
// makes the committed record unreviewable.
const MAX_LEDGER_FILES = 40

function summariseFiles(files) {
  if (!Array.isArray(files) || files.length <= MAX_LEDGER_FILES) {
    return { file_count: Array.isArray(files) ? files.length : 0, files: files || [] }
  }
  return {
    file_count: files.length,
    files: files.slice(0, MAX_LEDGER_FILES),
    files_truncated: files.length - MAX_LEDGER_FILES,
  }
}

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`)
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

function git(args, { cwd, allowFail = false } = {}) {
  try {
    return execFileSync('git', args, { encoding: 'utf8', cwd, maxBuffer: 512 * 1024 * 1024 })
  } catch (err) {
    if (allowFail) return null
    throw err
  }
}

function gitOk(args, cwd) {
  try {
    execFileSync('git', args, { stdio: 'ignore', cwd })
    return true
  } catch {
    return false
  }
}

const kind = arg('kind', 'local-branches')
const base = arg('base', 'origin/main')
const fingerprint = arg('fingerprint', null)
const jsonOut = arg('json', null)
const worktreePath = arg('worktree', null)

const baseSha = git(['rev-parse', base]).trim()
const reachableFromBase = new Set(git(['rev-list', baseSha]).split('\n').filter(Boolean))
const reachableFromRemotes = new Set(git(['rev-list', '--remotes=origin']).split('\n').filter(Boolean))

const changedSinceCache = new Map()
function filesChangedOnBaseSince(unixTime) {
  if (!changedSinceCache.has(unixTime)) {
    const out = git(['log', `--since=${unixTime}`, '--name-only', '--pretty=format:', baseSha], { allowFail: true })
    changedSinceCache.set(unixTime, new Set((out || '').split('\n').filter(Boolean)))
  }
  return changedSinceCache.get(unixTime)
}

function collectLocalBranches() {
  const remotes = new Set(
    git(['for-each-ref', '--format=%(refname:short)', 'refs/remotes/origin/'])
      .split('\n')
      .filter(Boolean)
      .map((r) => r.replace(/^origin\//, '')),
  )
  return git(['for-each-ref', '--format=%(refname:short)\t%(objectname)\t%(committerdate:unix)\t%(subject)', 'refs/heads/'])
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const [name, sha, ts, ...rest] = line.split('\t')
      return { source: name, sha, created_at: Number(ts), subject: rest.join('\t'), has_remote: remotes.has(name) }
    })
    .filter((b) => !b.has_remote)
}

function collectRescueRefs() {
  return git(['for-each-ref', '--format=%(refname)\t%(objectname)\t%(creatordate:unix)\t%(subject)', 'refs/orch-rescue/'])
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const [source, sha, ts, ...rest] = line.split('\t')
      return { source, sha, created_at: Number(ts), subject: rest.join('\t') }
    })
}

// A dirty worktree is one evidence item per changed path.
function collectWorktree(path) {
  const head = git(['rev-parse', 'HEAD'], { cwd: path }).trim()
  const rows = git(['status', '--porcelain'], { cwd: path }).split('\n').filter(Boolean)
  return rows.map((row) => ({
    source: `${path}:${row.slice(3)}`,
    file: row.slice(3),
    status: row.slice(0, 2).trim(),
    sha: head,
    created_at: Math.floor(Date.now() / 1000),
    subject: `dirty worktree change (${row.slice(0, 2).trim()})`,
    worktree: path,
  }))
}

function classifyCommit(entry) {
  const { sha, created_at: createdAt } = entry

  if (!gitOk(['cat-file', '-e', `${sha}^{commit}`])) {
    return { classification: 'ALREADY_PRESENT', reason: 'object missing from the object store; nothing to recover', files: [] }
  }
  if (reachableFromBase.has(sha)) {
    return { classification: 'ALREADY_PRESENT', reason: `tip is an ancestor of ${base}`, files: [] }
  }

  const mergeBase = (git(['merge-base', sha, baseSha], { allowFail: true }) || '').trim()
  const diffFrom = mergeBase || '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
  let files = (git(['diff', '--name-only', diffFrom, sha], { allowFail: true }) || '').split('\n').filter(Boolean)

  if (files.length === 0) {
    return { classification: 'ALREADY_PRESENT', reason: `no change against its merge-base with ${base}`, files: [] }
  }

  // A sweep that only captured generated output (vitest caches, __pycache__, dist)
  // carries no authored work. Adjudicating it on content produces a false conflict,
  // because build output never applies cleanly onto a different tree.
  const sourceFiles = sourceFilesOnly(files)
  if (sourceFiles.length === 0) {
    return {
      classification: 'ALREADY_PRESENT',
      reason:
        'build output / orchestrator scratch only, not authored work — carries no recoverable source value',
      files,
    }
  }
  files = sourceFiles

  const vsBase = (git(['diff', '--name-only', baseSha, sha, '--', ...files], { allowFail: true }) || '').split('\n').filter(Boolean)
  if (vsBase.length === 0) {
    return { classification: 'ALREADY_PRESENT', reason: `every touched file already matches ${base}`, files }
  }

  if (reachableFromRemotes.has(sha)) {
    return { classification: 'ACTIVE_IN_ANOTHER_TASK', reason: 'tip is reachable from a remote branch', files }
  }

  // A sweep/stash hangs OFF a branch and is never reachable FROM it, so the SHA
  // test above cannot see that a live branch already owns the work. Read the
  // originating branch out of the subject instead; without this, in-flight state
  // looks orphaned and gets re-queued as a duplicate of a live task.
  const m = /^On (?:(.+?)): /.exec(entry.subject || '')
  const originBranch = m && m[1] !== '(no branch)' ? m[1] : null
  if (originBranch && gitOk(['rev-parse', '--verify', `refs/remotes/origin/${originBranch}`])) {
    return {
      classification: 'ACTIVE_IN_ANOTHER_TASK',
      reason: `sweep of in-flight state on origin/${originBranch}, which still exists and owns this work`,
      files,
      origin_branch: originBranch,
    }
  }

  const changedSince = filesChangedOnBaseSince(createdAt)
  if (files.every((f) => changedSince.has(f))) {
    return { classification: 'SUPERSEDED_BY_NEWER', reason: `every touched file was rewritten on ${base} after capture`, files }
  }

  // Restrict the apply-check to authored files: generated output in the same sweep
  // would otherwise fail the check and mask genuinely recoverable source.
  const patch = git(['diff', '--binary', diffFrom, sha, '--', ...files], { allowFail: true }) || ''
  let applies = false
  try {
    execFileSync('git', ['apply', '--check', '--3way', '-'], { input: patch, stdio: 'ignore' })
    applies = true
  } catch {
    applies = false
  }

  return applies
    ? { classification: 'RECOVERABLE_VALUE', reason: `unique content; applies cleanly onto ${base}`, files }
    : { classification: 'CONFLICTED_NEEDS_FOCUSED_TASK', reason: `unique content; does NOT apply onto ${base}`, files }
}

function classifyWorktreeChange(entry) {
  if (ARTIFACT_RE.test(entry.file)) {
    return {
      classification: 'ALREADY_PRESENT',
      reason: 'build output, not authored work — carries no recoverable source value',
      files: [entry.file],
    }
  }
  if (ORCH_SCRATCH_RE.test(entry.file)) {
    return {
      classification: 'ALREADY_PRESENT',
      reason: 'orchestrator scratch, not authored work — carries no recoverable source value',
      files: [entry.file],
    }
  }

  // `git diff` is blind to two situations, and because the failure is swallowed both
  // used to report ALREADY_PRESENT — silently discarding genuinely absent work:
  //   1. UNTRACKED files (status ??) never appear in a diff at all.
  //   2. Evidence in a SEPARATE CLONE (a misclone, or a worktree whose object store
  //      predates the base), where baseSha cannot be resolved locally.
  // Both are adjudicated by comparing content hashes across the two object stores.
  const isUntracked = (entry.status || '').includes('?')
  const baseUnresolvable = !gitOk(['cat-file', '-e', `${baseSha}^{commit}`], entry.worktree)
  if (isUntracked || baseUnresolvable) {
    const localBlob = (git(['hash-object', '--', entry.file], { cwd: entry.worktree, allowFail: true }) || '').trim()
    const baseBlob = (git(['rev-parse', `${baseSha}:${entry.file}`], { allowFail: true }) || '').trim()
    const how = baseUnresolvable ? ' (compared across object stores)' : ''
    if (localBlob && baseBlob && localBlob === baseBlob) {
      return { classification: 'ALREADY_PRESENT', reason: `content hash matches ${base}${how}`, files: [entry.file] }
    }
    if (baseBlob) {
      return {
        classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
        reason: `differs from ${base}${how}; needs content adjudication before any recovery`,
        files: [entry.file],
      }
    }
    // Path does not exist on the base at all: new content, so it applies cleanly.
    return {
      classification: 'RECOVERABLE_VALUE',
      reason: `absent from ${base}${how}; new path, applies cleanly`,
      files: [entry.file],
    }
  }

  // Compare the working-tree content against the base rather than the worktree's
  // (possibly stale) HEAD: what matters is whether the base is already ahead.
  const vsBase = (git(['diff', '--name-only', baseSha, '--', entry.file], { cwd: entry.worktree, allowFail: true }) || '')
    .split('\n')
    .filter(Boolean)
  if (vsBase.length === 0) {
    return { classification: 'ALREADY_PRESENT', reason: `content already matches ${base}`, files: [entry.file] }
  }
  return {
    classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
    reason: `differs from ${base}; needs content adjudication before any recovery`,
    files: [entry.file],
  }
}

let items
if (kind === 'local-branches') items = collectLocalBranches().map((e) => ({ ...e, ...classifyCommit(e) }))
else if (kind === 'rescue-refs') items = collectRescueRefs().map((e) => ({ ...e, ...classifyCommit(e) }))
else if (kind === 'worktree') {
  if (!worktreePath) throw new Error('--kind worktree requires --worktree <path>')
  items = collectWorktree(worktreePath).map((e) => ({ ...e, ...classifyWorktreeChange(e) }))
} else throw new Error(`unknown --kind ${kind}`)

const counts = Object.fromEntries(CLASSIFICATIONS.map((c) => [c, items.filter((i) => i.classification === c).length]))
const unknown = items.filter((i) => !CLASSIFICATIONS.includes(i.classification)).length

const ledgerItems = items.map((i) => ({ ...i, ...summariseFiles(i.files) }))

const report = { fingerprint, kind, base, base_sha: baseSha, generated_at: new Date().toISOString(), total: items.length, counts, unknown, items: ledgerItems }
if (jsonOut) writeFileSync(jsonOut, `${JSON.stringify(report, null, 2)}\n`)

console.log(`kind            ${kind}`)
console.log(`base            ${base} (${baseSha.slice(0, 12)})`)
console.log(`total evidence  ${report.total}`)
for (const c of CLASSIFICATIONS) console.log(`  ${c.padEnd(30)} ${counts[c]}`)
console.log(`UNKNOWN         ${unknown}`)

process.exit(unknown === 0 ? 0 : 1)
