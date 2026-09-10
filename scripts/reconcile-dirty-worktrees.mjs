#!/usr/bin/env node
/**
 * DIRTY-WORKTREE RECONCILIATION — classify UNCOMMITTED work, read-only.
 *
 *   node scripts/reconcile-dirty-worktrees.mjs --fingerprint <sha> [--json out.json]
 *                                              [--base origin/master]
 *
 * ─── WHY THIS EXISTS SEPARATELY FROM reconcile-evidence.mjs ─────────────────
 * That script is deliberate about worktrees: "a worktree is a checkout, not a
 * copy. Its committed content is only a real loss if that ref is also gone."
 * That is right, and it is why every worktree in its ledger classifies
 * ALREADY_PRESENT — it compares committed trees.
 *
 * It also means it cannot see uncommitted work at all. `status` is not on its
 * read-only allowlist, so the question is not merely unanswered, it is
 * unaskable. And uncommitted work is the case with no ref behind it: nothing
 * pushed it, nothing else carries it, and `git worktree remove --force` or a
 * sweep takes it silently.
 *
 * A dirty worktree is therefore the one shape of evidence where "the only copy
 * is on this disk" can be literally true, which is exactly what the recovery
 * tasks are for.
 *
 * ─── READ-ONLY, ENFORCED NOT PROMISED ──────────────────────────────────────
 * Same discipline as the sibling script: an allowlist of subcommands that
 * cannot mutate, and a named refusal for the ones that can. `status`,
 * `hash-object` (without -w) and `ls-tree` are pure reads. `stash`, `checkout`,
 * `clean` and friends are refused by name, because the failure mode this whole
 * exercise exists to prevent is a reconciliation that eats its own evidence.
 */
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'

const READ_ONLY = new Set([
  'worktree', 'status', 'hash-object', 'ls-tree', 'rev-parse', 'cat-file', 'diff', 'log',
  // Added deliberately for the ownership check: both only read refs.
  // `for-each-ref` lists local agent branches; `ls-remote` lists the remote's.
  'for-each-ref', 'ls-remote',
])

const DESTRUCTIVE = new Set([
  'checkout', 'switch', 'reset', 'clean', 'restore', 'merge', 'rebase', 'cherry-pick',
  'commit', 'push', 'pull', 'gc', 'prune', 'update-ref', 'apply', 'am', 'stash', 'add', 'rm',
])

export function runGit(args, { cwd = process.cwd(), allowFail = false, raw = false } = {}) {
  const sub = args[0]
  if (DESTRUCTIVE.has(sub)) {
    throw new Error(
      `refusing to run "git ${sub}": this tool is read-only over the evidence. ` +
        'Reconciliation must never mutate the source it is classifying.',
    )
  }
  if (!READ_ONLY.has(sub)) {
    throw new Error(`"git ${sub}" is not on the read-only allowlist; add it deliberately.`)
  }
  // `git hash-object -w` writes into the object store. Without -w it is pure.
  if (sub === 'hash-object' && args.includes('-w')) {
    throw new Error('refusing "git hash-object -w": writing objects is not read-only.')
  }
  try {
    const out = execFileSync('git', args, {
      cwd,
      encoding: 'utf8',
      maxBuffer: 256 * 1024 * 1024,
    })
    // NEVER trim `status --porcelain -z`. A not-staged modification is reported
    // as " M path" — leading space — so trimming eats it and every path in the
    // record shifts one character left. That produced "unner/release_train.py"
    // and hashed nothing, i.e. it silently reclassified real uncommitted work
    // as absent. Whitespace is data in this format.
    return raw ? out : out.trim()
  } catch (e) {
    if (allowFail) return null
    throw e
  }
}

/**
 * Paths whose dirtiness is never lost work: build output, dependency trees,
 * runtime scratch and the orchestrator's own per-worktree bookkeeping. A vitest
 * cache is noise, and a follow-up task spawned for one can never produce a
 * meaningful diff — the sibling script makes the same argument for refs.
 */
const NOISE = [
  /(^|\/)node_modules(\/|$)/,
  /(^|\/)\.(nuxt|output|vite|next|turbo|cache|venv|pytest_cache|mypy_cache|ruff_cache)(\/|$)/,
  /(^|\/)(dist|build|coverage|__pycache__)(\/|$)/,
  /(^|\/)\.runtime(\/|$)/,
  /(^|\/)\.orch-tmp(\/|$)/,
  /(^|\/)\.orch-worktree\.json$/,
  /\.(log|pyc|pyo|tsbuildinfo)$/,
  /(^|\/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|uv\.lock)$/,
]

export const isNoise = (p) => NOISE.some((re) => re.test(p))

/** Parse `git status --porcelain=v1 -z` into {code, path} entries. */
export function parseStatusZ(out) {
  if (!out) return []
  const parts = out.split('\0')
  const entries = []
  for (let i = 0; i < parts.length; i += 1) {
    const rec = parts[i]
    if (!rec) continue
    const code = rec.slice(0, 2)
    let path = rec.slice(3)
    // Renames/copies carry the origin path in the following NUL-separated field.
    if (code[0] === 'R' || code[0] === 'C') i += 1
    if (path) entries.push({ code, path })
  }
  return entries
}

/**
 * Classify one uncommitted path against the base tree.
 *
 * The question is only ever "if this worktree vanished, would anything be
 * gone?" — so a working-tree blob whose content already matches the base is
 * ALREADY_PRESENT no matter how git labels it, and a deletion is never lost
 * work because the content it removes is still on the base.
 */
export function classifyPath({ code, path }, { blobAt, hashWorking }) {
  if (isNoise(path)) {
    return { classification: 'ALREADY_PRESENT', reason: 'generated/dependency path; dirtiness here is build noise, not work' }
  }
  if (code.includes('D')) {
    return { classification: 'ALREADY_PRESENT', reason: 'deletion — the content it removes still exists on the base; nothing to lose' }
  }
  const working = hashWorking(path)
  if (working === null) {
    return { classification: 'ALREADY_PRESENT', reason: 'unreadable in the working tree (vanished or not a regular file)' }
  }
  const base = blobAt(path)
  if (base && base === working) {
    return { classification: 'ALREADY_PRESENT', reason: 'byte-identical to the base blob at this path' }
  }
  return {
    classification: 'RECOVERABLE_VALUE',
    reason: base
      ? 'uncommitted modification that differs from the base; no ref carries it'
      : 'untracked file with no counterpart on the base; no ref carries it',
  }
}

export function listWorktrees(repo) {
  return (runGit(['worktree', 'list', '--porcelain'], { cwd: repo, allowFail: true }) ?? '')
    .split('\n\n')
    .filter(Boolean)
    .map((block) => ({
      path: /^worktree (.+)$/m.exec(block)?.[1] ?? null,
      branch: /^branch (.+)$/m.exec(block)?.[1] ?? 'DETACHED',
    }))
    .filter((w) => w.path)
}

/** Classify every uncommitted path in one worktree. */
export function reconcileWorktree(wt, base, { cap = 4000 } = {}) {
  // -uall, not the default -unormal: the default collapses an untracked
  // directory to a single "lib/models/" entry, which git cannot hash and this
  // pass would then write off as unreadable. A collapsed directory can hold the
  // only copy of any number of files, so the one summary line is precisely the
  // wrong unit to reason about loss in.
  const status = runGit(['status', '--porcelain=v1', '-z', '--no-renames', '-uall'], {
    cwd: wt.path,
    allowFail: true,
    raw: true,
  })
  if (status === null) {
    return { ...wt, unreadable: true, paths: [], counts: {}, dirty: 0 }
  }
  const entries = parseStatusZ(status)
  const blobCache = new Map()
  const blobAt = (p) => {
    if (!blobCache.has(p)) {
      const line = runGit(['ls-tree', base, '--', p], { cwd: wt.path, allowFail: true })
      blobCache.set(p, line ? (line.split(/\s+/)[2] ?? null) : null)
    }
    return blobCache.get(p)
  }
  const hashWorking = (p) =>
    runGit(['hash-object', '--', p], { cwd: wt.path, allowFail: true }) || null

  // Two worktrees here carry >4000 dirty paths. Hashing every one costs more
  // than the answer is worth, so cap and say so rather than quietly sampling.
  const considered = entries.slice(0, cap)
  const paths = considered.map((e) => ({ ...e, ...classifyPath(e, { blobAt, hashWorking }) }))
  const counts = {}
  for (const p of paths) counts[p.classification] = (counts[p.classification] ?? 0) + 1
  return {
    ...wt,
    dirty: entries.length,
    truncated: Math.max(0, entries.length - considered.length),
    counts,
    paths,
  }
}

/**
 * Is this worktree still owned by a live agent task?
 *
 * This repo's convention (CLAUDE.md): "All agent work happens in isolated git
 * worktrees under {repo}-wt/{slug} ... the agent/{slug} branch persists for
 * merge-train pickup." So a dirty worktree sitting on an `agent/*` branch that
 * still resolves is not orphaned work — it is somebody's open task, mid-edit.
 *
 * The distinction is load-bearing, not cosmetic. Uncommitted-and-unique is the
 * same observation in both cases; only ownership separates "the only copy of
 * something nobody will come back for" from "another executor is typing into
 * this right now". Calling the second one RECOVERABLE_VALUE invites exactly the
 * behaviour the coordination rule forbids — a second task hauling a first
 * task's in-flight edits onto its own branch.
 *
 * This pass caught its own sibling doing it: run before
 * chatgpt-local-reconcile-beethoven-0ce4c6e8284c committed, it reported that
 * task's half-written scripts/reconcile-dirty-worktrees.mjs as recoverable.
 *
 * A DETACHED worktree, or one whose branch has been deleted, has no owner left
 * and stays RECOVERABLE_VALUE — that is the case worth alarming about.
 */
export function ownedByLiveTask(wt, { liveBranches }) {
  if (!wt.branch || wt.branch === 'DETACHED') return null
  const ref = wt.branch.replace(/^refs\/heads\//, '')
  if (!ref.startsWith('agent/')) return null
  return liveBranches.has(ref) ? ref : null
}

/** A worktree is only as safe as its least-safe uncommitted path. */
export function worktreeClassification(wt) {
  if (wt.unreadable) return 'CONFLICTED_NEEDS_FOCUSED_TASK'
  if ((wt.counts.RECOVERABLE_VALUE ?? 0) === 0) return 'ALREADY_PRESENT'
  return wt.ownerBranch ? 'ACTIVE_IN_ANOTHER_TASK' : 'RECOVERABLE_VALUE'
}

/**
 * Every `agent/*` branch that still resolves, local or on the remote. Local
 * counts on its own: a task that has not pushed yet is the one most likely to
 * be mid-edit, and therefore the one it would be worst to treat as abandoned.
 */
export function liveAgentBranches(repo, { offline = false } = {}) {
  const set = new Set()
  const local = runGit(['for-each-ref', '--format=%(refname:short)', 'refs/heads/agent/'], {
    cwd: repo,
    allowFail: true,
  })
  for (const b of (local ?? '').split('\n').filter(Boolean)) set.add(b)
  if (!offline) {
    // ls-remote is a read; it is on the allowlist. Failure is non-fatal —
    // offline we still have the local refs, which are the riskier half anyway.
    const remote = runGit(['ls-remote', '--heads', 'origin', 'refs/heads/agent/*'], {
      cwd: repo,
      allowFail: true,
    })
    for (const line of (remote ?? '').split('\n').filter(Boolean)) {
      const ref = line.split('\t')[1]
      if (ref) set.add(ref.replace(/^refs\/heads\//, ''))
    }
  }
  return set
}

export function reconcile(repo, base, fingerprint, opts = {}) {
  const liveBranches = opts.liveBranches ?? liveAgentBranches(repo, opts)
  const worktrees = listWorktrees(repo)
    .map((w) => reconcileWorktree(w, base, opts))
    .map((w) => ({ ...w, ownerBranch: ownedByLiveTask(w, { liveBranches }) }))
  const items = worktrees.map((w) => ({
    kind: 'dirty_worktree',
    ref: w.path,
    branch: w.branch,
    ownerBranch: w.ownerBranch,
    classification: worktreeClassification(w),
    dirtyPaths: w.dirty,
    truncated: w.truncated ?? 0,
    counts: w.counts,
    reason: w.unreadable
      ? 'worktree could not be read; unknown is not "fine", so it needs a focused look'
      : w.ownerBranch
        ? `${w.counts.RECOVERABLE_VALUE ?? 0} uncommitted path(s), but ${w.ownerBranch} still owns this worktree — leave it to that task; do not carry its edits onto another branch`
        : `${w.counts.RECOVERABLE_VALUE ?? 0} of ${w.dirty} uncommitted path(s) exist only here, and no live task owns them`,
    recoverable: (w.paths ?? [])
      .filter((p) => p.classification === 'RECOVERABLE_VALUE')
      .map((p) => p.path),
  }))
  const counts = {}
  for (const i of items) counts[i.classification] = (counts[i.classification] ?? 0) + 1
  return {
    auditFingerprint: fingerprint,
    kind: 'dirty-worktrees',
    against: { ref: base, sha: runGit(['rev-parse', base], { cwd: repo, allowFail: true }) ?? '' },
    generatedAt: new Date().toISOString(),
    readOnly: true,
    itemCount: items.length,
    unknown: 0,
    counts,
    // Only ownerless paths are "at risk". Work an open task is still editing is
    // not at risk from neglect; it is at risk from a second task touching it.
    uncommittedAtRisk: items
      .filter((i) => i.classification === 'RECOVERABLE_VALUE')
      .reduce((n, i) => n + (i.counts.RECOVERABLE_VALUE ?? 0), 0),
    uncommittedOwnedElsewhere: items
      .filter((i) => i.classification === 'ACTIVE_IN_ANOTHER_TASK')
      .reduce((n, i) => n + (i.counts.RECOVERABLE_VALUE ?? 0), 0),
    items,
  }
}

/**
 * The generic recovery-ledger-report.mjs is written around refs and file
 * counts. Dirty worktrees are a different unit — a path count per checkout —
 * so this emits its own table rather than bending that one out of shape.
 */
export function markdown(report, { project = 'beethoven', ledgerPath = '' } = {}) {
  const l = []
  const at = (i) => i.counts?.RECOVERABLE_VALUE ?? 0
  l.push(`# Dirty-worktree reconciliation — ${project}`, '')
  l.push(`Audit fingerprint: \`${report.auditFingerprint}\``, '')
  l.push(`Base: \`${report.against.ref}\` @ \`${report.against.sha.slice(0, 12)}\` · generated ${report.generatedAt}`, '')
  l.push('Regenerate with:', '', '```bash')
  l.push('node scripts/reconcile-dirty-worktrees.mjs \\')
  l.push(`  --base ${report.against.ref} \\`)
  l.push(`  --fingerprint ${report.auditFingerprint}${ledgerPath ? ' \\' : ''}`)
  if (ledgerPath) l.push(`  --json ${ledgerPath}`)
  l.push('```', '')
  l.push('## Result', '')
  l.push(
    `**${report.itemCount} worktrees classified, ${report.unknown} UNKNOWN.** ` +
      `**${report.uncommittedAtRisk} uncommitted path(s) exist only on this disk** — no branch, ` +
      'no rescue ref and no remote carries them. Nothing was popped, dropped, reset or moved.',
    '',
  )
  l.push('| Classification | Worktrees |', '|---|---:|')
  for (const [k, v] of Object.entries(report.counts)) l.push(`| ${k} | ${v} |`)
  l.push('')
  l.push('## Worktrees holding the only copy, with no live task to claim it', '')
  l.push('| Worktree | Branch | Unique | Dirty |', '|---|---|---:|---:|')
  for (const i of report.items.filter((x) => x.classification === 'RECOVERABLE_VALUE').sort((a, b) => at(b) - at(a)))
    l.push(`| \`${i.ref}\` | ${i.branch} | ${at(i)} | ${i.dirtyPaths} |`)
  l.push('')
  const owned = report.items.filter((x) => x.classification === 'ACTIVE_IN_ANOTHER_TASK').sort((a, b) => at(b) - at(a))
  if (owned.length) {
    l.push('## Dirty, but another live task owns it — do not touch', '')
    l.push(
      `${owned.length} worktree(s), ${report.uncommittedOwnedElsewhere} uncommitted path(s). ` +
        'These are open tasks mid-edit, not lost work. Carrying their edits onto a ' +
        'second branch is the duplication the coordination rule exists to prevent.',
      '',
    )
    l.push('| Worktree | Owned by | Unique |', '|---|---|---:|')
    for (const i of owned) l.push(`| \`${i.ref}\` | \`${i.ownerBranch}\` | ${at(i)} |`)
    l.push('')
  }
  const unreadable = report.items.filter((x) => x.classification === 'CONFLICTED_NEEDS_FOCUSED_TASK')
  if (unreadable.length) {
    l.push('## Unreadable — unknown is not "fine"', '')
    for (const i of unreadable) l.push(`- \`${i.ref}\``)
    l.push('')
  }
  l.push('## Why a separate pass', '')
  l.push('`reconcile-evidence.mjs` compares *committed* trees, on the correct principle that')
  l.push('a worktree is a checkout rather than a copy. That is why every worktree in its ledger')
  l.push('is ALREADY_PRESENT. Uncommitted work is the case with no ref behind it, and `status`')
  l.push('is not on that script\'s allowlist, so there the question cannot even be asked.', '')
  return l.join('\n')
}

function main(argv) {
  const arg = (n, d = null) => (argv.includes(n) ? argv[argv.indexOf(n) + 1] : d)
  const fingerprint = arg('--fingerprint')
  if (!fingerprint) {
    console.error(
      'usage: node scripts/reconcile-dirty-worktrees.mjs --fingerprint <sha>\n' +
        '                 [--base origin/master] [--json out.json] [--repo <path>]',
    )
    return 2
  }
  const repo = arg('--repo', process.cwd())
  const base = arg('--base', 'origin/master')
  const report = reconcile(repo, base, fingerprint)

  console.log(`\nDirty-worktree reconciliation — ${fingerprint.slice(0, 12)}`)
  console.log(`  repo:      ${repo}`)
  console.log(`  against:   ${report.against.ref} @ ${report.against.sha.slice(0, 8)}`)
  console.log(`  worktrees: ${report.itemCount}`)
  for (const [k, v] of Object.entries(report.counts)) console.log(`    ${k.padEnd(30)} ${v}`)
  console.log(`  UNCOMMITTED PATHS THAT EXIST ONLY HERE, UNOWNED: ${report.uncommittedAtRisk}`)
  console.log(`  uncommitted paths owned by a live task (leave alone): ${report.uncommittedOwnedElsewhere}`)
  for (const i of report.items.filter((x) => x.classification === 'RECOVERABLE_VALUE')) {
    console.log(`\n  ${i.ref}  [${i.branch}]`)
    console.log(`    ${i.counts.RECOVERABLE_VALUE} of ${i.dirtyPaths} dirty path(s) unique`)
    for (const p of i.recoverable.slice(0, 12)) console.log(`      ${p}`)
    if (i.recoverable.length > 12) console.log(`      … and ${i.recoverable.length - 12} more`)
  }
  console.log('\n  Nothing was popped, dropped, reset or moved. The evidence is where it was.')

  const jsonOut = arg('--json')
  if (jsonOut) {
    writeFileSync(jsonOut, `${JSON.stringify(report, null, 2)}\n`)
    console.log(`  ledger → ${jsonOut}`)
  }
  const mdOut = arg('--md')
  if (mdOut) {
    writeFileSync(mdOut, `${markdown(report, { project: arg('--project', 'beethoven'), ledgerPath: jsonOut ?? '' })}\n`)
    console.log(`  report → ${mdOut}`)
  }
  return report.unknown === 0 ? 0 : 1
}

if (import.meta.url === `file://${process.argv[1]}`) {
  process.exit(main(process.argv.slice(2)))
}
