#!/usr/bin/env node
/**
 * Evidence-source enumerators for local ChatGPT/Codex build evidence.
 *
 * `reconcile-rescue-evidence.mjs` covers one source: `refs/orch-rescue`. Local
 * evidence is wider than that — a rescue sweep also parks work in local-only
 * branch tips, in the stash, and (most fragile of all) in the dirty worktree of
 * the main checkout. An audit that only walks the rescue refs reports "zero
 * UNKNOWN" while the uncommitted work sits one `git checkout` away from gone.
 *
 * READ-ONLY, without exception. Nothing here deletes, resets, cleans, pops or
 * moves anything. The stash is read via `git stash list`, never popped. The
 * dirty worktree is read via `git status --porcelain`, never cleaned.
 */

import { execFileSync } from 'node:child_process'

export const EVIDENCE_KINDS = [
  'orchestrator_rescue_refs',
  'local_only_branch_tips',
  'stashes',
  'dirty_worktree',
]

function git(args, { cwd = process.cwd(), allowFail = false } = {}) {
  try {
    return execFileSync('git', args, { cwd, encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 }).trim()
  } catch (error) {
    if (allowFail) return null
    throw error
  }
}

function lines(value) {
  return value ? value.split('\n').filter(Boolean) : []
}

/** `refs/orch-rescue/*` — the parked rescue sweeps. */
export function enumerateRescueRefs(cwd = process.cwd(), namespace = 'refs/orch-rescue') {
  return lines(
    git(['for-each-ref', namespace, '--format=%(refname)%09%(objectname)%09%(creatordate:unix)'], {
      cwd,
      allowFail: true,
    }),
  ).map(line => {
    const [ref, sha, createdAt] = line.split('\t')
    return { kind: 'orchestrator_rescue_refs', ref, sha, createdAt: Number(createdAt) || null }
  })
}

/**
 * Local heads with no counterpart on the remote. These are the branches a
 * `git gc` or a stale-branch cleanup would take with it, so they are evidence
 * even when their content turns out to be already merged.
 */
export function enumerateLocalOnlyBranchTips(cwd = process.cwd()) {
  const remote = new Set(
    lines(git(['for-each-ref', 'refs/remotes/origin', '--format=%(refname:strip=3)'], { cwd, allowFail: true })),
  )
  return lines(
    git(['for-each-ref', 'refs/heads', '--format=%(refname:short)%09%(objectname)%09%(creatordate:unix)'], {
      cwd,
      allowFail: true,
    }),
  )
    .map(line => {
      const [name, sha, createdAt] = line.split('\t')
      return { kind: 'local_only_branch_tips', ref: name, sha, createdAt: Number(createdAt) || null }
    })
    .filter(item => !remote.has(item.ref))
}

/**
 * `git stash list` — read, never popped. Each entry classifies as a commit.
 *
 * The separator is `%x09`, not `%09`. Git's pretty-format spells a literal tab
 * `%x09`; `%09` is a padding directive and passes through unexpanded, so the
 * whole line arrives as one field and every stash ends up with `sha:
 * undefined`. That does not throw — it classifies all 33 stashes as
 * ALREADY_PRESENT ("does not resolve to a commit") and the audit reports a
 * confident, wrong, zero-UNKNOWN result. Found by `verify-recovery-ledger.mjs`
 * re-checking a committed ledger, which is what that tool is for.
 */
export function enumerateStashes(cwd = process.cwd()) {
  return lines(git(['stash', 'list', '--format=%gd%x09%H%x09%ct%x09%gs'], { cwd, allowFail: true })).map(
    line => {
      const [ref, sha, createdAt, subject] = line.split('\t')
      return {
        kind: 'stashes',
        ref,
        sha,
        createdAt: Number(createdAt) || null,
        subject: subject ?? null,
      }
    },
  )
}

/**
 * Uncommitted changes in a checkout. Not a commit, so it has no sha — the
 * classifier handles it by content, not by reachability.
 *
 * `--porcelain=v1 -z` so paths with spaces or renames survive the parse; a
 * silently dropped path here is exactly the evidence loss this guards against.
 */
export function enumerateDirtyWorktree(cwd = process.cwd()) {
  const raw = execFileSync('git', ['status', '--porcelain=v1', '-z', '--untracked-files=normal'], {
    cwd,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
  })
  const fields = raw.split('\0').filter(Boolean)
  const items = []
  for (let i = 0; i < fields.length; i += 1) {
    const entry = fields[i]
    const status = entry.slice(0, 2)
    const path = entry.slice(3)
    // Rename/copy statuses carry the source path as the following NUL field.
    if (status[0] === 'R' || status[0] === 'C') i += 1
    items.push({ kind: 'dirty_worktree', ref: `worktree:${path}`, sha: null, status, path, createdAt: null })
  }
  return items
}

/** Every local evidence source, in one list. Order is stable for diffing. */
export function enumerateAllEvidence(cwd = process.cwd(), { namespace = 'refs/orch-rescue' } = {}) {
  return [
    ...enumerateRescueRefs(cwd, namespace),
    ...enumerateLocalOnlyBranchTips(cwd),
    ...enumerateStashes(cwd),
    ...enumerateDirtyWorktree(cwd),
  ]
}

/**
 * Classify a dirty-worktree path. It has no commit, so reachability cannot
 * answer the question; content can.
 *
 *   ALREADY_PRESENT    the working copy matches the default branch
 *   RECOVERABLE_VALUE  the working copy differs, or the file is untracked
 *
 * An untracked file is always RECOVERABLE_VALUE: nothing else in the repo holds
 * it, so "no action" would mean losing it.
 */
export function classifyDirtyPath(item, { base, cwd = process.cwd() }) {
  if (item.status === '??') {
    return {
      classification: 'RECOVERABLE_VALUE',
      detail: { reason: 'untracked file — held nowhere but the worktree', status: item.status },
    }
  }
  if (item.status[0] === 'D' || item.status[1] === 'D') {
    return {
      classification: 'SUPERSEDED_BY_NEWER',
      detail: { reason: 'local deletion of a tracked file — no content to recover', status: item.status },
    }
  }
  const differs = git(['diff', '--quiet', base, '--', item.path], { cwd, allowFail: true })
  if (differs !== null) {
    return {
      classification: 'ALREADY_PRESENT',
      detail: { reason: `working copy matches ${base}`, status: item.status },
    }
  }
  return {
    classification: 'RECOVERABLE_VALUE',
    detail: { reason: `uncommitted edit not present in ${base}`, status: item.status },
  }
}
