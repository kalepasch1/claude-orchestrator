// GET /api/portfolio-health — one-glance orchestrator health: deploy + security + growth + spend + runner.
import { createClient } from '@supabase/supabase-js'

export default defineEventHandler(async () => {
  const sb = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY!)
  const [ph, alerts, hb] = await Promise.all([
    sb.from('portfolio_health').select('*'),
    sb.from('runner_alerts').select('*').eq('resolved', false).order('created_at', { ascending: false }).limit(5),
    sb.from('runner_heartbeats').select('last_seen').order('last_seen', { ascending: false }).limit(1),
  ])
  const lastSeen = hb.data?.[0]?.last_seen ? new Date(hb.data[0].last_seen).getTime() : 0
  const runnerSecs = lastSeen ? Math.round((Date.now() - lastSeen) / 1000) : null
  return {
    apps: ph.data ?? [],
    alerts: alerts.data ?? [],
    runner: { seconds_since_heartbeat: runnerSecs, up: runnerSecs != null && runnerSecs < 300 },
  }
})
