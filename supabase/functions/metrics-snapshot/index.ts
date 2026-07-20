// metrics-snapshot — canary health endpoint for deploy_window.py
// Returns JSON: { error_rate, p95_ms, conversion }
// error_rate:  % of tasks that failed in the last 24h
// p95_ms:      p95 wall_ms of completed tasks in the last 24h
// conversion:  merge rate (% of completed tasks that reached integrated+deployed)
// Deploy: supabase functions deploy metrics-snapshot

import { createClient } from 'npm:@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Content-Type': 'application/json',
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })

  const supabaseUrl = Deno.env.get('SUPABASE_URL')!
  const supabaseKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  const sb = createClient(supabaseUrl, supabaseKey)

  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()

  // Completed tasks in the last 24h (any terminal state)
  const { data: completed, error: err1 } = await sb
    .from('tasks')
    .select('id, state, wall_ms, integrated, deployed')
    .in('state', ['DONE', 'FAILED', 'MERGED', 'DEPLOYED', 'SKIPPED', 'QUARANTINED'])
    .gte('updated_at', since)

  if (err1) {
    return new Response(JSON.stringify({ error: err1.message }), {
      status: 500, headers: corsHeaders,
    })
  }

  const rows = completed || []
  const total = rows.length

  if (total === 0) {
    // No data — report healthy defaults so canary doesn't block on quiet periods
    return new Response(JSON.stringify({
      error_rate: 0,
      p95_ms: 0,
      conversion: 100,
      sample_size: 0,
      since,
    }), { headers: corsHeaders })
  }

  // error_rate: % of tasks in FAILED or QUARANTINED state
  const failed = rows.filter(r =>
    r.state === 'FAILED' || r.state === 'QUARANTINED'
  ).length
  const error_rate = (failed / total) * 100

  // p95 wall_ms
  const wallTimes = rows
    .map(r => r.wall_ms)
    .filter((w): w is number => typeof w === 'number' && w > 0)
    .sort((a, b) => a - b)
  const p95_ms = wallTimes.length > 0
    ? wallTimes[Math.floor(wallTimes.length * 0.95)]
    : 0

  // conversion: % of non-failed tasks that reached deployed or integrated
  const eligible = rows.filter(r => r.state !== 'FAILED' && r.state !== 'QUARANTINED' && r.state !== 'SKIPPED')
  const converted = eligible.filter(r => r.deployed || r.integrated).length
  const conversion = eligible.length > 0
    ? (converted / eligible.length) * 100
    : 100

  return new Response(JSON.stringify({
    error_rate: Math.round(error_rate * 100) / 100,
    p95_ms: Math.round(p95_ms),
    conversion: Math.round(conversion * 100) / 100,
    sample_size: total,
    since,
  }), { headers: corsHeaders })
})
