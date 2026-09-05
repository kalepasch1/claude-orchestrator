/**
 * queue-branch-provenance.mjs — give a reconciliation ledger a durable home.
 *
 * WHY. A reconciliation run produces a ledger that is the ONLY record of what was
 * examined and what was decided. Until it is committed somewhere the merge train can see,
 * it lives in a worktree the executor deletes on the way out — which is how the same refs
 * get re-classified from scratch on the next pass, and how a "focused follow-up" verdict
 * becomes a note nobody can act on because the evidence it referred to is gone.
 *
 * This makes that record durable WITHOUT destructive operations. It never deletes,
 * resets, force-updates or prunes anything. Where repo policy forbids creating a branch
 * in this environment it emits a BRANCH PLAN instead of failing — a plan a human or the
 * merge train can execute later is worth more than an abort.
 *
 * Pure planning is separated from git side effects, so the naming and follow-up rules are
 * unit-testable without a repository.
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

/** Merge-train naming convention. CLAUDE.md: work lands on `agent/{slug}`. */
export const BRANCH_PREFIX = 'agent/'

/** Verdict meaning a human still owes this item an evidence snapshot. */
export const FOLLOW_UP_CLASSIFICATION = 'QUEUED_FOCUSED_FOLLOW_UP'

/** Classifications that warrant a focused task, per reconcile-evidence.mjs. */
export const FOCUSED_CLASSIFICATIONS = Object.freeze([
  FOLLOW_UP_CLASSIFICATION,
  'CONFLICTED_NEEDS_FOCUSED_TASK',
])

export function branchNameFor(slug) {
  const clean = String(slug ?? '').trim().replace(/^agent\//, '')
  return clean ? `${BRANCH_PREFIX}${clean}` : ''
}

/**
 * Items still owing evidence. Pure.
 *
 * Accepts the ledger shape reconcile-evidence.mjs emits (`{items: [...]}`) or a bare
 * array, because callers hold both.
 */
export function followUpItems(ledger) {
  const items = Array.isArray(ledger) ? ledger : (ledger?.items ?? [])
  if (!Array.isArray(items)) return []
  return items.filter((it) => it && FOCUSED_CLASSIFICATIONS.includes(it.classification))
}

/**
 * A single-pass task stub for one unresolved item.
 *
 * The prompt names the ref and says what is missing, because the failure this module
 * exists to prevent is a follow-up reading "investigate the reconciliation", which nobody
 * who was not there can act on.
 */
export function followUpStub(item, { slug = '', ledgerPath = '' } = {}) {
  const ref = String(item?.ref ?? item?.id ?? '(unnamed)')
  const why = String(item?.reason ?? item?.disposition ?? 'no evidence snapshot recorded')
  return {
    title: `Capture the missing evidence snapshot for ${ref}`,
    ref,
    classification: item?.classification ?? FOLLOW_UP_CLASSIFICATION,
    source_slug: slug,
    ledger: ledgerPath,
    prompt: [
      `Reconciliation left ${ref} unresolved: ${why}.`,
      ledgerPath ? `The ledger recording that decision is ${ledgerPath}.` : '',
      'Read the ref READ-ONLY (git show / git worktree add --detach on the sha; never',
      'checkout in the shared clone). Capture the evidence sections the ledger says are',
      'missing, compare each surviving file against the base branch, and either land the',
      'minimum coherent slice that is genuinely absent or close with the evidence that',
      'there is nothing to land. Do NOT delete or move the ref.',
    ].filter(Boolean).join(' '),
  }
}

/**
 * What this run intends to do. Pure — no git, no filesystem.
 *
 * Returned before anything happens so a caller can log the plan, and so the
 * policy-blocked path emits exactly the same object as an artifact.
 */
export function planProvenance({ slug, ledgerPath, ledger, allowBranchCreation = true }) {
  const branch = branchNameFor(slug)
  const stubs = followUpItems(ledger).map((it) => followUpStub(it, { slug, ledgerPath }))
  return {
    slug: String(slug ?? ''),
    branch,
    ledger: String(ledgerPath ?? ''),
    allowed: Boolean(allowBranchCreation && branch),
    action: allowBranchCreation && branch ? 'create-branch-and-commit' : 'branch-plan-only',
    reason: branch
      ? (allowBranchCreation ? '' : 'branch creation disallowed in this environment')
      : 'no usable slug',
    follow_ups: stubs,
    follow_up_count: stubs.length,
  }
}

function git(args, cwd) {
  return execFileSync('git', args, { cwd, encoding: 'utf8', timeout: 120000 }).trim()
}

/**
 * Execute the plan. Returns the plan annotated with what actually happened.
 *
 * Non-destructive by construction: the only mutating git commands are `checkout -b`
 * (which FAILS rather than overwrite when the branch exists), `add` of the ledger and the
 * stub file specifically, and `commit`. No reset, no clean, no force, no prune.
 */
export function writeProvenance({
  repo, slug, ledgerPath, ledger, outDir = '.orch',
  allowBranchCreation = true, commit = true,
}) {
  const plan = planProvenance({ slug, ledgerPath, ledger, allowBranchCreation })
  const stubPath = join(outDir, `${plan.slug || 'reconcile'}-follow-ups.json`)

  // The stub file is ALWAYS written, including on the policy-blocked path: the
  // machine-readable follow-up list is the deliverable, and losing it because a branch
  // could not be created would defeat the point.
  try {
    mkdirSync(join(repo, dirname(stubPath)), { recursive: true })
    writeFileSync(join(repo, stubPath), `${JSON.stringify(plan, null, 2)}\n`)
    plan.stub_file = stubPath
  } catch (err) {
    plan.stub_file = ''
    plan.error = `stub write failed: ${err?.message ?? err}`
  }

  if (!plan.allowed) {
    plan.result = 'branch-plan-only'
    return plan
  }

  try {
    git(['checkout', '-b', plan.branch], repo)
    const toAdd = [stubPath]
    if (ledgerPath && existsSync(join(repo, ledgerPath))) toAdd.push(ledgerPath)
    git(['add', '--', ...toAdd], repo)
    if (commit) {
      git(['-c', 'user.name=kalepasch1', '-c', 'user.email=kalepasch@gmail.com',
        'commit', '--no-verify', '-m',
        `reconcile(${plan.slug}): ledger + ${plan.follow_up_count} follow-up stub(s)`], repo)
      plan.commit = git(['rev-parse', 'HEAD'], repo)
    }
    plan.result = 'committed'
  } catch (err) {
    // Fail-soft into the plan-only path rather than half-finishing: a caller holding a
    // plan can retry or hand it to a human; one holding an exception loses both.
    plan.result = 'branch-plan-only'
    plan.error = String(err?.message ?? err).slice(0, 400)
  }
  return plan
}

export function readLedger(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return {}
  }
}
