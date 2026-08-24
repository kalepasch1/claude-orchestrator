/**
 * orchestration-artifacts — keep the reconciliation loop from eating its own tail.
 *
 * The local-evidence reconciliation was feeding on its own output. Observed
 * across ~30 `chatgpt-local-reconcile-*` runs:
 *
 *   • smarter: a RECOVERABLE_VALUE item was `refs/orch-rescue/…-reconcile-250fb499`,
 *     whose ONLY source file is `scripts/reconcile-evidence.mjs` — a sibling
 *     reconcile task's own artifact, swept by the periodic sweeper, arriving as
 *     the next pass's evidence.
 *   • beethoven: a main-worktree sweep's 85 paths were entirely sibling ledgers.
 *   • pareto-2080, darwn: the sweeper created new `refs/orch-rescue/*` DURING a
 *     reconcile run, and that same run then had to classify them.
 *
 * Every pass manufactured a little more evidence for the next one, so the queue
 * could not converge, and the tasks looked like progress while producing none.
 *
 * THE RULE, and its one important restriction:
 *
 *   An item is orchestration bookkeeping only when EVERY path it carries is
 *   bookkeeping. One real source file and it stays in the evidence universe and
 *   is classified normally.
 *
 * That asymmetry is deliberate. Excluding a mixed item to keep the loop tidy
 * would discard real unshipped work, which is the exact loss this reconciliation
 * exists to prevent — far worse than an extra pass. Excluding is also never
 * silent: everything removed is returned with a reason so the caller can list it
 * in the ledger under its own key. An unexplained disappearance is the same bug
 * class the coverage doctrine forbids.
 *
 * Pure. No git, no filesystem, no clock — the caller supplies paths and times.
 */

/**
 * Paths that exist only because the fleet ran, not because anyone built anything.
 * Anchored, so a real source file cannot match merely by containing the word.
 */
export const ORCHESTRATION_PATH_PATTERNS = Object.freeze([
  /^\.orch\/recovery-ledger-.*\.json$/,
  /^\.orch\/[^/]*\.(json|md|txt)$/,
  /^docs\/tasks\/chatgpt-local-reconcile-.*\.md$/,
  /^docs\/recovery-ledger\//,
  /^docs\/recovery-ledger-[0-9a-z]+\.(json|md)$/,
  /^docs\/recovery\//,
  /^scripts\/reconcile-[^/]*$/,
  /^scripts\/recovery\/[^/]*$/,
  /^tools\/reconcile_[^/]*$/,
  /(^|\/)\.recovery-intent-[^/]*$/,
])

/** Directories the fleet creates to work in, which are nobody's evidence. */
export const SCAFFOLDING_PATH_PATTERNS = Object.freeze([
  /(^|\/)[^/]+-wt\//, // agent worktrees: {repo}-wt/{slug}
  /^\/private\/tmp\/.*-baseline/, // baseline checkouts made to compare against
  /^\/tmp\/.*-baseline/,
])

export const EXCLUSION_REASONS = Object.freeze({
  BOOKKEEPING: 'ORCHESTRATION_ARTIFACT',
  SCAFFOLDING: 'RUN_SCAFFOLDING',
})

/** Is this one path pure orchestration bookkeeping? */
export function isOrchestrationPath(path) {
  const p = String(path || '').trim().replace(/^\.\//, '')
  if (!p) return false
  return ORCHESTRATION_PATH_PATTERNS.some((re) => re.test(p))
}

/** Is this path inside something the fleet created to work in? */
export function isScaffoldingPath(path) {
  const p = String(path || '').trim()
  if (!p) return false
  return SCAFFOLDING_PATH_PATTERNS.some((re) => re.test(p))
}

/**
 * Does this set of paths consist ENTIRELY of orchestration bookkeeping?
 *
 * An empty set is not bookkeeping. "We could not read what it carries" and "it
 * carries only ledgers" are different claims, and treating the first as the
 * second would drop evidence nobody ever looked at.
 */
export function allPathsAreOrchestration(paths) {
  const list = (paths || []).map((p) => String(p || '').trim()).filter(Boolean)
  if (!list.length) return false
  return list.every((p) => isOrchestrationPath(p) || isScaffoldingPath(p))
}

/**
 * Was this ref created by the very run that is now classifying it?
 *
 * Strictly after the run started, so a ref written a moment before the run began
 * is still evidence. Missing or unparseable times mean "not created by this run":
 * the safe answer is always to keep classifying.
 */
export function createdDuringRun(createdAt, runStartedAt) {
  if (!createdAt || !runStartedAt) return false
  const made = Date.parse(createdAt)
  const started = Date.parse(runStartedAt)
  if (Number.isNaN(made) || Number.isNaN(started)) return false
  return made > started
}

/**
 * Why should this item be kept out of the evidence universe? `null` to keep it.
 *
 * `item.paths` is the set of paths the item carries, `item.ref` its name, and
 * `item.createdAt` when it came into being, if known.
 */
export function exclusionReason(item, { runStartedAt = null } = {}) {
  if (!item || typeof item !== 'object') return null

  const ref = String(item.ref || '')
  if (isScaffoldingPath(ref)) {
    return { reason: EXCLUSION_REASONS.SCAFFOLDING, detail: `path is fleet scaffolding: ${ref}` }
  }

  if (allPathsAreOrchestration(item.paths)) {
    return {
      reason: EXCLUSION_REASONS.BOOKKEEPING,
      detail: `all ${item.paths.length} path(s) are orchestration bookkeeping ` +
        `(e.g. ${item.paths[0]})`,
    }
  }

  if (createdDuringRun(item.createdAt, runStartedAt)) {
    return {
      reason: EXCLUSION_REASONS.SCAFFOLDING,
      detail: `created at ${item.createdAt}, after this run began at ${runStartedAt}`,
    }
  }

  return null
}

/**
 * Split an evidence set into what should be classified and what should not.
 *
 * Returns `{ kept, excluded }`. Nothing is discarded: every excluded entry keeps
 * its identity and gains `exclusionReason` / `exclusionDetail`, so the ledger can
 * account for it by name.
 */
export function partitionEvidence(items, opts = {}) {
  const kept = []
  const excluded = []
  for (const item of items || []) {
    const verdict = exclusionReason(item, opts)
    if (verdict) {
      excluded.push({ ...item, exclusionReason: verdict.reason, exclusionDetail: verdict.detail })
    } else {
      kept.push(item)
    }
  }
  return { kept, excluded }
}

/** Counts by reason, for the ledger key. */
export function summariseExclusions(excluded) {
  const byReason = {}
  for (const e of excluded || []) {
    const r = e && e.exclusionReason ? e.exclusionReason : 'UNKNOWN'
    byReason[r] = (byReason[r] || 0) + 1
  }
  return { total: (excluded || []).length, byReason }
}

export default {
  ORCHESTRATION_PATH_PATTERNS,
  SCAFFOLDING_PATH_PATTERNS,
  EXCLUSION_REASONS,
  isOrchestrationPath,
  isScaffoldingPath,
  allPathsAreOrchestration,
  createdDuringRun,
  exclusionReason,
  partitionEvidence,
  summariseExclusions,
}
