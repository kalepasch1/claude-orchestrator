/**
 * branchDetection.ts — Enhanced branch detection utilities.
 */
export function isAgentBranch(name: string): boolean {
  return name.startsWith('agent/')
}

export function isStagingBranch(name: string): boolean {
  return name.includes('/staging') || name === 'staging'
}

export function classifyBranchType(name: string): 'agent' | 'staging' | 'main' | 'other' {
  if (isAgentBranch(name)) return 'agent'
  if (isStagingBranch(name)) return 'staging'
  if (name === 'main' || name === 'master') return 'main'
  return 'other'
}
