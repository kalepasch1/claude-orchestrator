import type { FleetHealth } from '../../types/fleet-health'

export interface RunnerHeartbeat {
  runner_id?: string | null
  hostname?: string | null
  last_seen?: string | null
  code_sha?: string | null
  contract_hash?: string | null
}

const DEFAULT_FRESHNESS_SECONDS = 300

/** Summarize the shared heartbeat ledger rather than a Vercel-local file. */
export function summarizeFleetHealth(
  rows: RunnerHeartbeat[],
  nowMs = Date.now(),
  freshnessSeconds = DEFAULT_FRESHNESS_SECONDS,
): FleetHealth {
  const valid = rows
    .map((row) => ({ row, seenMs: Date.parse(String(row.last_seen || '')) }))
    .filter((entry) => Number.isFinite(entry.seenMs))
    .sort((a, b) => b.seenMs - a.seenMs)

  const latest = valid[0]
  const heartbeatSeconds = latest
    ? Math.max(0, Math.round((nowMs - latest.seenMs) / 1000))
    : null
  const live = valid.filter((entry) => nowMs - entry.seenMs <= freshnessSeconds * 1000)
  const physicalHosts = new Set(
    live.map(({ row }) => String(row.hostname || row.runner_id || 'unknown').split(' lane ', 1)[0]),
  )
  const contracts = new Set(
    live.map(({ row }) => `${row.code_sha || 'unknown'}:${row.contract_hash || 'unknown'}`),
  )
  const contractConsistent = live.length > 0
    && contracts.size === 1
    && ![...contracts][0].includes('unknown')

  return {
    db_up: live.length > 0,
    status: live.length === 0 ? 'down' : contractConsistent ? 'healthy' : 'degraded',
    heartbeat_seconds: heartbeatSeconds,
    machines_live: physicalHosts.size,
    contract_consistent: contractConsistent,
  }
}
