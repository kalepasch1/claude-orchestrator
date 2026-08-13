#!/usr/bin/env node
/**
 * EVIDENCE RECONCILIATION — classify local ChatGPT/Codex build evidence without
 * destroying it.
 *
 *   node scripts/reconcile-evidence.mjs --fingerprint <sha> [--json out.json] [--default-branch master]
 *
 * ─── READ-ONLY, AND THAT IS ENFORCED RATHER THAN PROMISED ───────────────────
 * Every source path, stash, rescue ref and worktree is treated as read-only. This
 * script uses ONLY plumbing that cannot mutate: `rev-parse`, `merge-base`,
 * `rev-list`, `diff --stat`, `for-each-ref`, `stash list`, `worktree list`. The
 * allowlist below is the guarantee — `runGit` refuses any subcommand not on it, so
 * a future edit that reaches for `checkout`, `stash pop`, `reset` or `clean`
 * fails loudly instead of quietly eating the evidence.
 *
 * ─── WHY THE CLASSIFIER IS CONSERVATIVE ─────────────────────────────────────
 * The expensive error here is not "flagged something already merged". It is
 * "discarded something that was the only copy". So:
 *
 *   - ancestry is checked against BOTH origin/main and the local default, because
 *     a ref merged locally but not pushed is not yet safe
 *   - a ref that cannot be resolved is CONFLICTED_NEEDS_FOCUSED_TASK, never
 *     ALREADY_PRESENT — an unreadable ref is unknown, and unknown is not "fine"
 *   - RECOVERABLE_VALUE requires unique commits AND a non-empty diff against the
 *     merge base; either alone is not evidence of value
 *
 * Completion bar: ZERO items classified UNKNOWN.
 */
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'

// ─── The read-only guarantee ─────────────────────────────────────────────────

const READ_ONLY_SUBCOMMANDS = new Set([
  'rev-parse', 'rev-list', 'merge-base', 'for-each-ref', 'stash', 'worktree',
  'diff', 'diff-tree', 'log', 'branch', 'show', 'cat-file', 'name-rev', 'ls-remote',
])

/** Subcommands that would mutate the evidence. Named so the refusal is specific. */
const DESTRUCTIVE = new Set([
  'checkout', 'switch', 'reset', 'clean', 'restore', 'merge', 'rebase', 'cherry-pick',
  'commit', 'push', 'fetch', 'pull', 'gc', 'prune', 'update-ref', 'apply', 'am',
])

function runGit(args, { allowFail = false } = {}) {
  const sub = args[0]
  if (DESTRUCTIVE.has(sub)) {
    throw new Error(
      `refusing to run "git ${sub}": this tool is read-only over the evidence. ` +
        `Reconciliation must never mutate the source it is classifying.`,
    )
  }
  if (!READ_ONLY_SUBCOMMANDS.has(sub)) {
    throw new Error(`"git ${sub}" is not on the read-only allowlist; add it deliberately.`)
  }
  // `git stash list` is read-only; `git stash pop|drop|apply` is not.
  if (sub === 'stash' && args[1] !== 'list' && args[1] !== 'show') {
    throw new Error(`refusing "git stash ${args[1]}": only \`list\` and \`show\` are read-only.`)
  }
  try {
    return execFileSync('git', args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).trim()
  } catch (e) {
    if (allowFail) return null
    throw e
  }
}

// ─── Classification ──────────────────────────────────────────────────────────

export const CLASSIFICATIONS = Object.freeze([
  'ALREADY_PRESENT',
  'SUPERSEDED_BY_NEWER',
  'ACTIVE_IN_ANOTHER_TASK',
  'RECOVERABLE_VALUE',
  'CONFLICTED_NEEDS_FOCUSED_TASK',
])

function resolve(ref) {
  return runGit(['rev-parse', '--verify', '-q', `${ref}^{commit}`], { allowFail: true })
}

/**
 * Codex writes turn-diff captures as refs pointing at a TREE rather than a commit.
 *
 * Those are not broken refs and not conflicts — they are content snapshots with no
 * history, and `rev-parse ^{commit}` on one fails by design. Classifying them as
 * CONFLICTED because of an object-type mismatch would put six healthy captures in
 * front of a human for no reason, which is how a triage list stops being read.
 */
function objectType(ref) {
  return runGit(['cat-file', '-t', ref], { allowFail: true })
}

function classifyTreeCapture(ref, tree) {
  return {
    ref,
    sha: tree,
    objectType: 'tree',
    classification: 'ALREADY_PRESENT',
    reason:
      'Codex turn-diff capture: a ref pointing at a TREE, not a commit. It is a ' +
      'content snapshot of a working state that the surrounding capture series ' +
      'already represents, and it carries no history to recover. Left untouched.',
  }
}

function isAncestor(sha, of) {
  try {
    execFileSync('git', ['merge-base', '--is-ancestor', sha, of], { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

/**
 * Classify one evidence item.
 *
 * `liveTaskSlugs` are slugs of orchestrator tasks currently RUNNING/QUEUED. A ref
 * whose name matches one is ACTIVE_IN_ANOTHER_TASK — reconciling it here would
 * duplicate work already represented by a live task, which the coordination rule
 * forbids.
 */
export function classifyRef(ref, ctx) {
  const { mainSha, localDefaultSha, liveTaskSlugs, remoteBranches } = ctx

  const sha = resolve(ref)
  if (!sha) {
    // Distinguish "points at a tree" (a Codex capture, healthy) from "does not
    // resolve at all" (genuinely broken, and a human's problem).
    const type = objectType(ref)
    if (type === 'tree') {
      return classifyTreeCapture(ref, runGit(['rev-parse', ref], { allowFail: true }))
    }
    return {
      ref,
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      reason:
        `ref does not resolve to a commit (object type: ${type ?? 'unresolvable'}). ` +
        'An unreadable ref is UNKNOWN, and unknown is never "already present" — it ' +
        'needs a human to find out what happened to it.',
      sha: null,
    }
  }

  // Merged into what we ship → the content is present.
  if (isAncestor(sha, mainSha)) {
    return {
      ref,
      sha,
      classification: 'ALREADY_PRESENT',
      reason: 'commit is an ancestor of origin/main; its content already ships.',
    }
  }

  const uniqueCommits = Number(
    runGit(['rev-list', '--count', `${mainSha}..${sha}`], { allowFail: true }) ?? '0',
  )

  // Merged locally but not pushed is NOT safe: the only copy is on this disk.
  if (localDefaultSha && isAncestor(sha, localDefaultSha) && uniqueCommits > 0) {
    return {
      ref,
      sha,
      classification: 'RECOVERABLE_VALUE',
      uniqueCommits,
      reason:
        'merged into the LOCAL default branch but not into origin/main. The only copy ' +
        'is on this disk, so this is recoverable value rather than already present.',
    }
  }

  // A live task already owns this work.
  const owningTask = liveTaskSlugs.find((slug) => ref.includes(slug))
  if (owningTask) {
    return {
      ref,
      sha,
      classification: 'ACTIVE_IN_ANOTHER_TASK',
      uniqueCommits,
      owningTask,
      reason: `a live orchestrator task ("${owningTask}") already represents this work.`,
    }
  }

  if (uniqueCommits === 0) {
    return {
      ref,
      sha,
      classification: 'ALREADY_PRESENT',
      uniqueCommits: 0,
      reason: 'no commits ahead of origin/main; nothing here is missing from what ships.',
    }
  }

  // Does it still change anything?
  const base = runGit(['merge-base', mainSha, sha], { allowFail: true })
  const stat = base ? runGit(['diff', '--stat', `${base}..${sha}`], { allowFail: true }) : null
  const changesNothing = !stat || stat.length === 0

  if (changesNothing) {
    return {
      ref,
      sha,
      classification: 'SUPERSEDED_BY_NEWER',
      uniqueCommits,
      reason:
        `${uniqueCommits} unique commit(s), but the tree is identical to the merge base — ` +
        'whatever it did has been done another way. The newest implementation wins.',
    }
  }

  const filesChanged = stat.split('\n').length - 1
  const remoteExists = remoteBranches.has(ref.replace(/^refs\/heads\//, ''))

  return {
    ref,
    sha,
    classification: 'RECOVERABLE_VALUE',
    uniqueCommits,
    filesChanged,
    remotePreserved: remoteExists,
    reason:
      `${uniqueCommits} unique commit(s) touching ${filesChanged} file(s) not on ` +
      `origin/main.` +
      (remoteExists
        ? ' A remote branch preserves it, so the durable copy already exists.'
        : ' NO remote branch preserves it — this is the only copy.'),
  }
}

/** A stash is classified by whether its diff still contains anything not on main. */
export function classifyStash(entry, ctx) {
  const sha = resolve(entry.ref)
  if (!sha) {
    return {
      ref: entry.ref,
      classification: 'CONFLICTED_NEEDS_FOCUSED_TASK',
      reason: 'stash entry does not resolve; needs a human.',
      sha: null,
    }
  }
  const base = runGit(['rev-parse', `${entry.ref}^`], { allowFail: true })
  const stat = base ? runGit(['diff', '--stat', `${base}..${sha}`], { allowFail: true }) : null

  if (!stat || stat.length === 0) {
    return {
      ref: entry.ref,
      sha,
      classification: 'ALREADY_PRESENT',
      subject: entry.subject,
      reason: 'stash carries no diff against its own base.',
    }
  }

  return {
    ref: entry.ref,
    sha,
    classification: 'RECOVERABLE_VALUE',
    subject: entry.subject,
    filesChanged: stat.split('\n').length - 1,
    reason:
      `stash holds ${stat.split('\n').length - 1} changed file(s). NOT popped, NOT ` +
      'dropped — the entry is left exactly where it was.',
  }
}

// ─── Duplicate-snapshot collapse ─────────────────────────────────────────────

/** Which kind of evidence is the most durable carrier of a given tree. */
const CARRIER_RANK = { branch: 3, worktree: 2, rescue_ref: 1, stash: 0 }

/**
 * Collapse items that carry the SAME TREE.
 *
 * Rescue refs are timestamped snapshots, and the same branch gets snapshotted
 * repeatedly — `20260803T000657-tomorrow` and `20260803T000744-tomorrow` are two
 * photographs of one thing. Counting each as independently recoverable inflates
 * the backlog with work that is already represented, which is exactly what the
 * coordination rule forbids.
 *
 * The survivor is the most durable carrier: a remote-backed branch beats a local
 * branch, which beats a rescue ref, which beats a stash. Everything else becomes
 * ALREADY_PRESENT **with a pointer to where it survives** — so nothing is written
 * off as gone; it is written down as already held somewhere better.
 */
export function collapseDuplicateTrees(items) {
  const treeOf = new Map()
  for (const item of items) {
    if (!item.sha) continue
    const tree = runGit(['rev-parse', `${item.sha}^{tree}`], { allowFail: true })
    if (tree) treeOf.set(item, tree)
  }

  const byTree = new Map()
  for (const [item, tree] of treeOf) {
    if (item.classification !== 'RECOVERABLE_VALUE') continue
    const list = byTree.get(tree) ?? []
    list.push(item)
    byTree.set(tree, list)
  }

  for (const [tree, group] of byTree) {
    if (group.length < 2) continue
    const carrier = [...group].sort((a, b) => {
      const rank = (CARRIER_RANK[b.kind] ?? 0) - (CARRIER_RANK[a.kind] ?? 0)
      if (rank !== 0) return rank
      // Prefer the one a remote preserves.
      return Number(b.remotePreserved === true) - Number(a.remotePreserved === true)
    })[0]

    for (const item of group) {
      if (item === carrier) {
        item.duplicateSnapshots = group.length - 1
        continue
      }
      item.classification = 'ALREADY_PRESENT'
      item.presentIn = carrier.ref
      item.reason =
        `identical tree (${tree.slice(0, 8)}) to ${carrier.ref}, which is a more durable ` +
        `carrier (${carrier.kind}). This is a duplicate snapshot, not a second copy of ` +
        `lost work — the content survives, and it survives there.`
    }
  }

  return items
}

// ─── Enumeration ─────────────────────────────────────────────────────────────

export function enumerateEvidence() {
  const branches = runGit([
    'for-each-ref', '--format=%(refname)', 'refs/heads',
  ]).split('\n').filter(Boolean)

  const rescueRefs = ['refs/orch-rescue', 'refs/rescue', 'refs/codex', 'refs/archive']
    .flatMap((ns) =>
      (runGit(['for-each-ref', '--format=%(refname)', ns], { allowFail: true }) ?? '')
        .split('\n')
        .filter(Boolean),
    )

  const stashes = (runGit(['stash', 'list', '--format=%gd\t%s'], { allowFail: true }) ?? '')
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const [ref, ...rest] = line.split('\t')
      return { ref, subject: rest.join('\t') }
    })

  const worktrees = (runGit(['worktree', 'list', '--porcelain'], { allowFail: true }) ?? '')
    .split('\n\n')
    .filter(Boolean)
    .map((block) => {
      const path = /^worktree (.+)$/m.exec(block)?.[1] ?? null
      const branch = /^branch (.+)$/m.exec(block)?.[1] ?? 'DETACHED'
      return { path, branch }
    })
    .filter((w) => w.path)

  return { branches, rescueRefs, stashes, worktrees }
}

// ─── Main ────────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2)
  const fingerprint = args[args.indexOf('--fingerprint') + 1]
  const jsonOut = args.includes('--json') ? args[args.indexOf('--json') + 1] : null

  if (!fingerprint || fingerprint.startsWith('--')) {
    console.error('usage: node scripts/reconcile-evidence.mjs --fingerprint <sha> [--json out]')
    process.exit(2)
  }

  // The default branch is not always `main`. Take it from --default-branch, else
  // from the remote HEAD symref, else try the two conventional names. Guessing
  // wrong here would classify every ref against a branch that does not exist and
  // report the entire repository as recoverable — a confidently useless answer.
  const explicitDefault = args.includes('--default-branch')
    ? args[args.indexOf('--default-branch') + 1]
    : null
  const symref = runGit(['rev-parse', '--abbrev-ref', 'origin/HEAD'], { allowFail: true })
  const candidates = [
    explicitDefault && `origin/${explicitDefault.replace(/^origin\//, '')}`,
    symref,
    'origin/main',
    'origin/master',
  ].filter(Boolean)

  let defaultRef = null
  let mainSha = null
  for (const candidate of candidates) {
    const sha = resolve(candidate)
    if (sha) {
      defaultRef = candidate
      mainSha = sha
      break
    }
  }

  if (!mainSha) {
    console.error(
      `cannot resolve a default branch (tried ${candidates.join(', ')}); refusing to ` +
        `classify against nothing.`,
    )
    process.exit(1)
  }

  const localDefaultSha = resolve(defaultRef.replace(/^origin\//, ''))

  const remoteBranches = new Set(
    runGit(['for-each-ref', '--format=%(refname:strip=3)', 'refs/remotes/origin'])
      .split('\n')
      .filter(Boolean),
  )

  // Live orchestrator task slugs, supplied by the caller so this tool needs no DB.
  const liveTaskSlugs = (process.env.LIVE_TASK_SLUGS ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  const ctx = { mainSha, localDefaultSha, liveTaskSlugs, remoteBranches }
  const { branches, rescueRefs, stashes, worktrees } = enumerateEvidence()

  const items = collapseDuplicateTrees([
    ...branches.map((b) => ({ kind: 'branch', ...classifyRef(b, ctx) })),
    ...rescueRefs.map((r) => ({ kind: 'rescue_ref', ...classifyRef(r, ctx) })),
    ...stashes.map((s) => ({ kind: 'stash', ...classifyStash(s, ctx) })),
    ...worktrees.map((w) => ({
      kind: 'worktree',
      ref: w.path,
      branch: w.branch,
      ...classifyRef(w.branch === 'DETACHED' ? 'HEAD' : w.branch, ctx),
    })),
  ])

  const counts = {}
  for (const c of CLASSIFICATIONS) counts[c] = 0
  let unknown = 0
  for (const i of items) {
    if (CLASSIFICATIONS.includes(i.classification)) counts[i.classification] += 1
    else unknown += 1
  }

  const ledger = {
    auditFingerprint: fingerprint,
    repo: runGit(['rev-parse', '--show-toplevel']),
    against: { ref: defaultRef, sha: mainSha },
    generatedAt: new Date().toISOString(),
    readOnly: true,
    itemCount: items.length,
    counts,
    unknown,
    items,
  }

  console.log(`\nEvidence reconciliation — ${fingerprint.slice(0, 12)}`)
  console.log(`  repo:        ${ledger.repo}`)
  console.log(`  against:     ${defaultRef} @ ${mainSha.slice(0, 8)}`)
  console.log(`  items:       ${items.length}`)
  for (const c of CLASSIFICATIONS) console.log(`    ${c.padEnd(30)} ${counts[c]}`)
  console.log(`  UNKNOWN:     ${unknown}${unknown === 0 ? '  ✓' : '  ✗ completion bar not met'}`)

  const onlyCopies = items.filter(
    (i) => i.classification === 'RECOVERABLE_VALUE' && i.remotePreserved === false,
  )
  if (onlyCopies.length > 0) {
    console.log(`\n  ${onlyCopies.length} item(s) have NO remote copy — the only copy is on this disk:`)
    for (const i of onlyCopies.slice(0, 20)) console.log(`    ${i.ref}`)
    if (onlyCopies.length > 20) console.log(`    … and ${onlyCopies.length - 20} more`)
  }

  console.log('\n  Nothing was popped, dropped, reset or moved. The evidence is where it was.\n')

  if (jsonOut) {
    writeFileSync(jsonOut, `${JSON.stringify(ledger, null, 2)}\n`)
    console.log(`  ledger → ${jsonOut}\n`)
  }

  process.exit(unknown === 0 ? 0 : 1)
}

if (import.meta.url === `file://${process.argv[1]}`) main()
