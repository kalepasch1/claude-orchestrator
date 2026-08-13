/**
 * Recovery logic for agent branches in the "missing" state:
 * underlying git work exists (was pushed) but the ledger entry's commit_sha
 * is absent because the DB update failed after a successful push.
 *
 * Without recovery the next runner cycle tries to re-push the same patch,
 * which git rejects with a non-fast-forward error (HTTP 409 on the GitHub
 * API). This module detects the missing-metadata state and produces the
 * reconciliation update so the runner skips the re-push.
 */

import { createLogger } from '~/server/utils/logger'

const log = createLogger('agent-runtime/branch-recovery')

// ─── Types ───────────────────────────────────────────────────────────────────

export interface BranchProposal {
  id: string
  rollback_data: Record<string, unknown> | null
  proposed_change?: {
    target_branch?: string
    changed_files?: string[]
  } | null
}

export interface ExistingBranchInfo {
  branch: string
  commitSha: string
}

/** The classification of a proposal relative to the git branch it targets. */
export type BranchState =
  | 'pending'                    // No commit yet, branch absent — normal queued state
  | 'committed_missing_metadata' // Branch exists in git but commit_sha absent in ledger — needs recovery
  | 'committed_tracked'          // commit_sha already recorded — no action needed

// ─── Core functions ───────────────────────────────────────────────────────────

/**
 * Classifies the branch state of a proposal by cross-referencing its ledger
 * metadata with the set of branches known to exist on the remote.
 *
 * Called before each apply attempt so the runner can skip re-push when the
 * work is already committed (preventing the HTTP 409 conflict).
 */
export function classifyBranchState(
  proposal: BranchProposal,
  existingBranches: ExistingBranchInfo[],
): BranchState {
  const commitSha = proposal.rollback_data?.commit_sha
  if (commitSha) return 'committed_tracked'

  const targetBranch = proposal.proposed_change?.target_branch
  if (!targetBranch) return 'pending'

  const found = existingBranches.find(b => b.branch === targetBranch)
  if (found) {
    log.info(
      { proposalId: proposal.id, branch: targetBranch, sha: found.commitSha },
      'existing committed branch: metadata absent, recovery required',
    )
    return 'committed_missing_metadata'
  }

  return 'pending'
}

/**
 * Builds the ledger update payload that recovers a missing-metadata proposal.
 * Stamping commit_sha and pushed_to prevents the runner from re-attempting
 * the push and triggering a 409 conflict on the next cycle.
 */
export function buildRecoveryUpdate(
  proposal: BranchProposal,
  existing: ExistingBranchInfo,
): Record<string, unknown> {
  return {
    rollback_data: {
      ...(proposal.rollback_data ?? {}),
      action: 'git_commit_approved',
      commit_sha: existing.commitSha,
      pushed_to: existing.branch,
      recovered_missing_branch: true,
    },
  }
}

/**
 * Filters a list of proposals to those that need branch recovery.
 * Returns each proposal paired with the branch info needed for the update.
 */
export function findMissingBranchProposals(
  proposals: BranchProposal[],
  existingBranches: ExistingBranchInfo[],
): Array<{ proposal: BranchProposal; existing: ExistingBranchInfo }> {
  const results: Array<{ proposal: BranchProposal; existing: ExistingBranchInfo }> = []
  for (const proposal of proposals) {
    const state = classifyBranchState(proposal, existingBranches)
    if (state === 'committed_missing_metadata') {
      const targetBranch = proposal.proposed_change?.target_branch as string
      const existing = existingBranches.find(b => b.branch === targetBranch)!
      results.push({ proposal, existing })
    }
  }
  return results
}
