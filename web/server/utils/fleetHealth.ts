import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import type { FleetHealth } from '../../types/fleet-health'

export function fleetHealthPaths(cwd = process.cwd()): string[] {
  return [
    process.env.ORCH_SENTINEL_STATE_PATH,
    resolve(cwd, '../.runtime/sentinel_state.json'),
    resolve(cwd, '.runtime/sentinel_state.json'),
    resolve(cwd, '../runner/sentinel_state.json'),
  ].filter((value): value is string => Boolean(value))
}

export async function readFleetHealth(paths = fleetHealthPaths()): Promise<FleetHealth> {
  for (const path of paths) {
    try {
      // Node's UTF-8 decoder replaces malformed byte sequences, after which JSON.parse
      // safely rejects the document and the route continues to its fail-soft response.
      const payload = JSON.parse(await readFile(path, 'utf8'))
      return { db_up: payload?.db_up === true }
    } catch {
      // A default path may not exist in every runtime. Try the next one without exposing
      // filesystem details or turning a health signal into a 500 response.
    }
  }
  return { db_up: false }
}
