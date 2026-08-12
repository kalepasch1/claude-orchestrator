import { describe, expect, it } from 'vitest'

import { summarizeFleetHealth } from './fleetHealth'

const NOW = Date.parse('2026-08-07T12:00:00Z')

describe('summarizeFleetHealth', () => {
  it('reports a fresh, contract-consistent fleet as healthy', () => {
    expect(summarizeFleetHealth([
      { runner_id: 'runner-a', hostname: 'Mac-A', last_seen: '2026-08-07T11:59:30Z', code_sha: 'abc', contract_hash: 'v1' },
      { runner_id: 'runner-a-lane', hostname: 'Mac-A lane 1', last_seen: '2026-08-07T11:59:20Z', code_sha: 'abc', contract_hash: 'v1' },
    ], NOW)).toEqual({
      db_up: true,
      status: 'healthy',
      heartbeat_seconds: 30,
      machines_live: 1,
      contract_consistent: true,
    })
  })

  it('reports live Macs with mixed runner contracts as degraded', () => {
    expect(summarizeFleetHealth([
      { hostname: 'Mac-A', last_seen: '2026-08-07T11:59:30Z', code_sha: 'abc', contract_hash: 'v1' },
      { hostname: 'Mac-B', last_seen: '2026-08-07T11:59:20Z', code_sha: 'def', contract_hash: 'v2' },
    ], NOW)).toMatchObject({
      db_up: true,
      status: 'degraded',
      machines_live: 2,
      contract_consistent: false,
    })
  })

  it('does not count stale or invalid heartbeats as live', () => {
    expect(summarizeFleetHealth([
      { hostname: 'Mac-A', last_seen: '2026-08-07T11:40:00Z', code_sha: 'abc', contract_hash: 'v1' },
      { hostname: 'Mac-B', last_seen: 'invalid' },
    ], NOW)).toEqual({
      db_up: false,
      status: 'down',
      heartbeat_seconds: 1200,
      machines_live: 0,
      contract_consistent: false,
    })
  })
})
