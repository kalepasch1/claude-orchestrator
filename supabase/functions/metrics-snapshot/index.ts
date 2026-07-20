// metrics-snapshot — canary health endpoint for deploy_window.py
// Returns JSON: { error_rate, p95_ms, conversion }
// error_rate:  % of outcomes that failed tests in the last 24h
// p95_ms:      p95 wall_ms from outcomes table in the last 24h
// conversion:  % of outcomes that reached integrated
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

  // Query outcomes table (has wall_ms, tests_passed, integrated)
  const { data: outcomes, error: err1 } = await sb
    .from('outcomes')
    .select('id, model, tests_passed, integrated, wall_ms, created_at')
    .gte('created_at', since)
    .order('created_at', { ascending: false })
    .limit(5000)

  if (err1) {
    return new Response(JSON.stringify({ error: err1.message }), {
      status: 500, headers: corsHeaders,
    })
  }

  const rows = outcomes || []
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

  // error_rate: % of outcomes where tests failed
  const failed = rows.filter(r => r.tests_passed === false).length
  const error_rate = (failed / total) * 100

  // p95 wall_ms (filter out zero-runtime merge receipts)
  const wallTimes = rows
    .map(r => r.wall_ms)
    .filter((w): w is number => typeof w === 'number' && w > 0)
    .sort((a, b) => a - b)
  const p95_ms = wallTimes.length > 0
    ? wallTimes[Math.floor(wallTimes.length * 0.95)]
    : 0

  // conversion: % of outcomes that reached integrated
  const integrated = rows.filter(r => r.integrated === true).length
  const conversion = total > 0 ? (integrated / total) * 100 : 100

  return new Response(JSON.stringify({
    error_rate: Math.round(error_rate * 100) / 100,
    p95_ms: Math.round(p95_ms),
    conversion: Math.round(conversion * 100) / 100,
    sample_size: total,
    since,
  }), { headers: corsHeaders })
})
