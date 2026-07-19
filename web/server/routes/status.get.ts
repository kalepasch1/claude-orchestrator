import { createClient } from '@supabase/supabase-js'

export default defineEventHandler(async () => {
  const checkedAt = new Date().toISOString()
  const url = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!url || !key) return { status: 'degraded', checked_at: checkedAt, services: { control_plane: true, data_plane: false } }
  try {
    const sb = createClient(url, key)
    const { data, error } = await sb.from('runner_heartbeats').select('last_seen').order('last_seen', { ascending: false }).limit(1)
    const seconds = data?.[0]?.last_seen ? Math.round((Date.now() - new Date(data[0].last_seen).getTime()) / 1000) : null
    const fleet = !error && seconds != null && seconds < 300
    return { status: error ? 'degraded' : 'operational', checked_at: checkedAt, services: { control_plane: true, data_plane: !error, orchestration_fleet: fleet }, heartbeat_seconds: seconds }
  } catch {
    return { status: 'degraded', checked_at: checkedAt, services: { control_plane: true, data_plane: false, orchestration_fleet: false } }
  }
})
