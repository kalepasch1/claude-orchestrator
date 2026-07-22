/**
 * branchRetryManager.ts — Branch fetch retry management.
 * Env gate: BRANCH_RETRY_MANAGER_ENABLED (default OFF).
 */

const ENABLED = process.env.BRANCH_RETRY_MANAGER_ENABLED === 'true'

export interface RetryConfig {
  maxRetries: number
  backoffMs: number
  branch: string
}

export function shouldRetryFetch(config: RetryConfig, attempt: number): boolean {
  if (!ENABLED) return false
  return attempt < config.maxRetries
}

export function computeBackoff(config: RetryConfig, attempt: number): number {
  return Math.min(config.backoffMs * Math.pow(2, attempt), 30000)
}

export function defaultRetryConfig(branch: string): RetryConfig {
  return { maxRetries: 3, backoffMs: 1000, branch }
}
