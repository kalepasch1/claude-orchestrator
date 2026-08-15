/**
 * Acceptance tests for agent-runtime/branch-recovery.
 *
 * Validates the "missing branch" recovery scenario:
 *   A proposal's git work was already pushed (the branch exists on the remote)
 *   but the DB update failed, leaving commit_sha absent in rollback_data.
 *   Without recovery, the next runner cycle re-attempts the push and receives
 *   a non-fast-forward rejection (HTTP 409 conflict on the GitHub API).
 *   The recovery logic detects this state and produces a ledger update that
 *   stamps commit_sha so the push is never retried.
 *
 * These tests are isolated from the runner and the Supabase client — pure
 * function tests following the project's unit-test convention.
 */

import { describe, it, expect } from 'vitest'
import {
  classifyBranchState,
  buildRecoveryUpdate,
  findMissingBranchProposals,
  type BranchProposal,
  type ExistingBranchInfo,
} from '~/server/engines/agent-runtime/branch-recovery'

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const BRANCH = 'auto/self-improvement'
const SHA = 'abc1234def5678'

function makeProposal(overrides: Partial<BranchProposal> = {}): BranchProposal {
  return {
    id: 'prop-1',
    rollback_data: { action: 'git_commit_approved' },
    proposed_change: { target_branch: BRANCH },
    ...overrides,
  }
}

function makeExisting(branch = BRANCH, commitSha = SHA): ExistingBranchInfo {
  return { branch, commitSha }
}

// ─── classifyBranchState ──────────────────────────────────────────────────────

describe('classifyBranchState', () => {
  it('returns committed_missing_metadata when branch exists but commit_sha is absent', () => {
    // This is the core missing-branch scenario: work is committed on the remote
    // but the ledger has no commit_sha, so the runner would retry the push → 409.
    const proposal = makeProposal({ rollback_data: { action: 'git_commit_approved' } })
    const state = classifyBranchState(proposal, [makeExisting()])
    expect(state).toBe('committed_missing_metadata')
  })

  it('returns pending when branch is absent and no commit_sha recorded', () => {
    // Normal queued proposal — branch not yet pushed.
    const proposal = makeProposal({ rollback_data: null })
    const state = classifyBranchState(proposal, [])
    expect(state).toBe('pending')
  })

  it('returns pending when branch is absent even though rollback_data exists', () => {
    const proposal = makeProposal({ rollback_data: { action: 'git_commit_approved' } })
    const state = classifyBranchState(proposal, []) // no branches present
    expect(state).toBe('pending')
  })

  it('returns committed_tracked when commit_sha is already recorded', () => {
    // Already-recovered or normally-completed proposal — no further action needed.
    const proposal = makeProposal({
      rollback_data: { action: 'git_commit_approved', commit_sha: SHA },
    })
    const state = classifyBranchState(proposal, [makeExisting()])
    expect(state).toBe('committed_tracked')
  })

  it('returns committed_tracked even when no existing branches are provided', () => {
    // commit_sha is the source of truth; branch list is secondary.
    const proposal = makeProposal({
      rollback_data: { action: 'git_commit_approved', commit_sha: SHA },
    })
    expect(classifyBranchState(proposal, [])).toBe('committed_tracked')
  })

  it('returns pending when proposed_change has no target_branch', () => {
    const proposal = makeProposal({ proposed_change: {} })
    expect(classifyBranchState(proposal, [makeExisting()])).toBe('pending')
  })

  it('only matches the exact target branch, not other branches', () => {
    const proposal = makeProposal({ proposed_change: { target_branch: 'auto/feature-a' } })
    const existingBranches = [makeExisting('auto/feature-b', SHA)]
    expect(classifyBranchState(proposal, existingBranches)).toBe('pending')
  })
})

// ─── buildRecoveryUpdate ─────────────────────────────────────────────────────

describe('buildRecoveryUpdate', () => {
  it('stamps commit_sha and pushed_to in rollback_data', () => {
    const proposal = makeProposal({ rollback_data: { action: 'git_commit_approved' } })
    const update = buildRecoveryUpdate(proposal, makeExisting())
    expect(update.rollback_data).toMatchObject({
      commit_sha: SHA,
      pushed_to: BRANCH,
    })
  })

  it('sets recovered_missing_branch: true as an audit trail marker', () => {
    const proposal = makeProposal()
    const update = buildRecoveryUpdate(proposal, makeExisting())
    expect((update.rollback_data as any).recovered_missing_branch).toBe(true)
  })

  it('preserves existing rollback_data fields while adding recovery fields', () => {
    const proposal = makeProposal({
      rollback_data: { action: 'git_commit_approved', apply_attempts: 1, custom_field: 'value' },
    })
    const update = buildRecoveryUpdate(proposal, makeExisting())
    const rd = update.rollback_data as any
    expect(rd.apply_attempts).toBe(1)
    expect(rd.custom_field).toBe('value')
    expect(rd.commit_sha).toBe(SHA)
  })

  it('works when rollback_data is null', () => {
    const proposal = makeProposal({ rollback_data: null })
    const update = buildRecoveryUpdate(proposal, makeExisting())
    const rd = update.rollback_data as any
    expect(rd.commit_sha).toBe(SHA)
    expect(rd.pushed_to).toBe(BRANCH)
  })

  it('after recovery update, classifyBranchState returns committed_tracked', () => {
    // End-to-end invariant: applying the recovery update must prevent any
    // future re-classification as missing (and therefore prevent a 409 retry).
    const proposal = makeProposal({ rollback_data: { action: 'git_commit_approved' } })
    const update = buildRecoveryUpdate(proposal, makeExisting())
    const recovered: BranchProposal = {
      ...proposal,
      rollback_data: update.rollback_data as Record<string, unknown>,
    }
    expect(classifyBranchState(recovered, [makeExisting()])).toBe('committed_tracked')
  })
})

// ─── findMissingBranchProposals ───────────────────────────────────────────────

describe('findMissingBranchProposals', () => {
  it('returns only proposals in the committed_missing_metadata state', () => {
    const missing = makeProposal({ id: 'missing', rollback_data: { action: 'git_commit_approved' } })
    const tracked = makeProposal({ id: 'tracked', rollback_data: { action: 'git_commit_approved', commit_sha: SHA } })
    const pending = makeProposal({ id: 'pending', rollback_data: null })

    const found = findMissingBranchProposals(
      [missing, tracked, pending],
      [makeExisting()],
    )

    expect(found).toHaveLength(1)
    expect(found[0].proposal.id).toBe('missing')
    expect(found[0].existing.commitSha).toBe(SHA)
  })

  it('returns empty array when all proposals are tracked', () => {
    const proposals = [
      makeProposal({ id: 'a', rollback_data: { commit_sha: SHA } }),
      makeProposal({ id: 'b', rollback_data: { commit_sha: 'other-sha' } }),
    ]
    expect(findMissingBranchProposals(proposals, [makeExisting()])).toHaveLength(0)
  })

  it('returns empty array when missing proposals have no matching branch on remote', () => {
    // The push hasn't happened yet (pending) — no remote branch, no recovery needed.
    const proposal = makeProposal({ rollback_data: { action: 'git_commit_approved' } })
    expect(findMissingBranchProposals([proposal], [])).toHaveLength(0)
  })

  it('handles multiple missing proposals across different branches', () => {
    const propA = makeProposal({ id: 'a', rollback_data: null, proposed_change: { target_branch: 'auto/branch-a' } })
    const propB = makeProposal({ id: 'b', rollback_data: null, proposed_change: { target_branch: 'auto/branch-b' } })
    const existingBranches: ExistingBranchInfo[] = [
      { branch: 'auto/branch-a', commitSha: 'sha-a' },
      { branch: 'auto/branch-b', commitSha: 'sha-b' },
    ]

    const found = findMissingBranchProposals([propA, propB], existingBranches)

    expect(found).toHaveLength(2)
    const ids = found.map(f => f.proposal.id)
    expect(ids).toContain('a')
    expect(ids).toContain('b')
    // Each proposal is paired with its own branch info, not a cross-match.
    const foundA = found.find(f => f.proposal.id === 'a')!
    expect(foundA.existing.commitSha).toBe('sha-a')
  })
})
