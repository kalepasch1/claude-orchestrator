/**
 * branchManager.ts — Advanced branch management utilities.
 * Stub for branch lifecycle helpers.
 */
export interface BranchInfo {
  name: string
  age: number      // hours since creation
  isStale: boolean
  isMerged: boolean
}

export function classifyBranch(name: string, ageHours: number, isMerged: boolean): BranchInfo {
  const STALE_THRESHOLD_HOURS = 72
  return {
    name,
    age: ageHours,
    isStale: ageHours > STALE_THRESHOLD_HOURS && !isMerged,
    isMerged,
  }
}

export function filterStaleBranches(branches: BranchInfo[]): BranchInfo[] {
  return branches.filter(b => b.isStale && !b.isMerged)
}
