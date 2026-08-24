import { serviceClient } from '../utils/fleetSupabase'
import { summarizeFleetHealth } from '../utils/fleetHealth'

export default defineEventHandler(async () => {
  try {
    const { data, error } = await serviceClient()
      .from('runner_heartbeats')
      .select('runner_id,hostname,last_seen,code_sha,contract_hash')
      .order('last_seen', { ascending: false })
      .limit(500)
    if (error) throw error
    return summarizeFleetHealth(data ?? [])
  } catch {
    return {
      db_up: false,
      status: 'unknown' as const,
      heartbeat_seconds: null,
      machines_live: 0,
      contract_consistent: false,
    }
  }
})
