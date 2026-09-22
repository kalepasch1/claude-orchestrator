import { describe, expect, it } from 'vitest'

import { formatReleaseLedger } from './terminalReleaseStatus'

describe('formatReleaseLedger', () => {
  it('does not infer a deployment from an empty ledger', () => {
    expect(formatReleaseLedger([])).toContain('No deployment is proven')
  })

  it('preserves the recorded status instead of relabeling it live', () => {
    const output = formatReleaseLedger([{
      id: 'r1', project: 'beethoven', version: 'v1', to_sha: 'abcdef1234567890',
      deploy_status: 'verification_blocked', created_at: '2026-09-21T00:00:00Z',
    }])
    expect(output).toContain('verification_blocked')
    expect(output).not.toContain('This is a live production deployment')
  })

  it('reports a read failure as unknown', () => {
    expect(formatReleaseLedger(null, 'database unavailable')).toMatch(/^Release status UNKNOWN/)
  })
})
