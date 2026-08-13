import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

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

/** Sentinel-state file locations, newest-first, for hosts that still write to disk. */
export function fleetHealthPaths(cwd = process.cwd()): string[] {
  return [
    process.env.ORCH_SENTINEL_STATE_PATH,
    resolve(cwd, '../.runtime/sentinel_state.json'),
    resolve(cwd, '.runtime/sentinel_state.json'),
    resolve(cwd, '../runner/sentinel_state.json'),
  ].filter((value): value is string => Boolean(value))
}

/**
 * Legacy on-disk fleet-health read, retained for self-hosted runners that have no
 * access to the shared heartbeat ledger. Serverless deployments should prefer
 * `summarizeFleetHealth` over the heartbeat table; this only reports liveness, so the
 * richer contract fields fall back to their unknown values.
 */
export async function readFleetHealth(paths = fleetHealthPaths()): Promise<FleetHealth> {
  for (const path of paths) {
    try {
      // Node's UTF-8 decoder replaces malformed byte sequences, after which JSON.parse
      // safely rejects the document and the route continues to its fail-soft response.
      const payload = JSON.parse(await readFile(path, 'utf8'))
      const dbUp = payload?.db_up === true
      return {
        db_up: dbUp,
        status: dbUp ? 'healthy' : 'down',
        heartbeat_seconds: null,
        machines_live: dbUp ? 1 : 0,
        contract_consistent: false,
      }
    } catch {
      // A default path may not exist in every runtime. Try the next one without exposing
      // filesystem details or turning a health signal into a 500 response.
    }
  }
  return {
    db_up: false,
    status: 'unknown',
    heartbeat_seconds: null,
    machines_live: 0,
    contract_consistent: false,
  }
}
