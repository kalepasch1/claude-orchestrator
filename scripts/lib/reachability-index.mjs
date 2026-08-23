#!/usr/bin/env node
/**
 * Batched reachability index for evidence reconciliation.
 *
 * The reconciler answers two questions per evidence item: "is this commit
 * already on the default branch?" and "is it reachable from live work?". The
 * obvious implementations — `git merge-base --is-ancestor` and
 * `git for-each-ref --contains` — each walk the commit graph from scratch, once
 * per item. With ~480 evidence items and ~430 live branches in this repo a full
 * pass takes minutes, which is why the audit was being run rarely and with a
 * `--limit`. A reconciliation you avoid running is a reconciliation that does
 * not catch anything.
 *
 * Walk the graph ONCE per ref set instead and answer from a hash set. Two
 * `git rev-list` calls replace ~1000 graph walks, and lookup becomes O(1).
 *
 * READ-ONLY, like every other part of the reconciler.
 */

import { execFileSync } from 'node:child_process'

/** Above this many commits, warn rather than silently eating memory. */
export const LARGE_INDEX_WARNING = 2_000_000

function revList(refs, cwd) {
  if (refs.length === 0) return []
  // Refs arrive on stdin so a repo with hundreds of branches cannot blow the
  // argv limit — the failure mode there is an E2BIG that looks like a git bug.
  const out = execFileSync('git', ['rev-list', '--stdin'], {
    cwd,
    input: `${refs.join('\n')}\n`,
    encoding: 'utf8',
    maxBuffer: 1024 * 1024 * 1024,
  })
  return out.split('\n').filter(Boolean)
}

/**
 * A set of every commit reachable from `refs`.
 *
 * `has(sha)` is exactly `git merge-base --is-ancestor sha <any ref>` for the
 * same ref set, but without the walk. Shas are compared full-length; callers
 * must pass a full 40-char sha, which every enumerator already does.
 */
export class ReachabilityIndex {
  constructor(shas, { refs = [], label = 'index' } = {}) {
    this.shas = shas instanceof Set ? shas : new Set(shas)
    this.refs = refs
    this.label = label
  }

  get size() {
    return this.shas.size
  }

  has(sha) {
    return typeof sha === 'string' && this.shas.has(sha)
  }
}

export function buildReachabilityIndex(refs, cwd = process.cwd(), label = 'index') {
  const shas = revList(refs, cwd)
  if (shas.length > LARGE_INDEX_WARNING) {
    // Loud rather than fatal: a repo can legitimately be this large, and an
    // audit that refuses to run is worse than one that uses more memory.
    console.warn(
      `reachability-index: ${label} holds ${shas.length} commits — expect high memory use`,
    )
  }
  return new ReachabilityIndex(shas, { refs, label })
}

/** Refs that represent live, in-flight work rather than parked evidence. */
export const LIVE_WORK_NAMESPACES = [
  'refs/heads/agent',
  'refs/remotes/origin/agent',
  'refs/orchestrator',
]

export function resolveLiveWorkRefs(cwd = process.cwd(), namespaces = LIVE_WORK_NAMESPACES) {
  try {
    const out = execFileSync('git', ['for-each-ref', '--format=%(refname)', ...namespaces], {
      cwd,
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
    })
    return out.split('\n').filter(Boolean)
  } catch {
    return []
  }
}

/**
 * Build both indexes the reconciler needs.
 *
 * `liveRefBySha` is deliberately NOT built: naming which live ref contains a
 * commit costs a per-item walk again, and the classification only needs to know
 * that one exists. Callers that want the name can resolve it lazily for the
 * handful of items that land in ACTIVE_IN_ANOTHER_TASK.
 */
export function buildEvidenceIndexes(cwd = process.cwd(), { base = 'origin/master' } = {}) {
  const liveRefs = resolveLiveWorkRefs(cwd)
  return {
    base: buildReachabilityIndex([base], cwd, `base:${base}`),
    live: buildReachabilityIndex(liveRefs, cwd, 'live-work'),
    liveRefs,
  }
}

/**
 * Name a live ref containing `sha`. Only called for items already known to be
 * reachable from live work, so the expensive walk happens a handful of times
 * instead of once per evidence item.
 */
export function nameLiveRef(sha, cwd = process.cwd(), namespaces = LIVE_WORK_NAMESPACES) {
  try {
    const out = execFileSync(
      'git',
      ['for-each-ref', '--contains', sha, '--count=1', '--format=%(refname)', ...namespaces],
      { cwd, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 },
    ).trim()
    return out || null
  } catch {
    return null
  }
}
