// NL analytics edge function — wraps ask.py logic in Deno.
// Accepts POST {question: string}, pulls live telemetry, calls Claude, returns {answer: string}.
// Deploy: supabase functions deploy ask
// Env vars to set in Supabase dashboard: ANTHROPIC_API_KEY

import { createClient } from 'npm:@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })

  const { question } = await req.json()
  if (!question) return new Response(JSON.stringify({ error: 'question required' }), { status: 400, headers: corsHeaders })

  const supabaseUrl = Deno.env.get('SUPABASE_URL')!
  const supabaseKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
  const anthropicKey = Deno.env.get('ANTHROPIC_API_KEY')!

  if (!anthropicKey) {
    return new Response(JSON.stringify({ error: 'ANTHROPIC_API_KEY not set in edge function env' }), {
      status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    })
  }

  const sb = createClient(supabaseUrl, supabaseKey)

  const [health, inbox, openTasks, outcomes] = await Promise.all([
    sb.from('v_project_health').select('*'),
    sb.from('v_action_inbox').select('*').limit(30),
    sb.from('tasks').select('project_id,slug,state,note,updated_at')
      .in('state', ['RUNNING', 'QUEUED', 'WAITING', 'BLOCKED']),
    sb.from('outcomes').select('project,usd,integrated,tests_passed').limit(1000),
  ])

  // compute simple ROI per project inline
  const roiAgg: Record<string, { spend: number; merged: number; tasks: number }> = {}
  for (const r of outcomes.data || []) {
    const a = roiAgg[r.project] ??= { spend: 0, merged: 0, tasks: 0 }
    a.spend += Number(r.usd || 0)
    a.tasks++
    if (r.integrated) a.merged++
  }
  const roi = Object.entries(roiAgg).map(([project, a]) => ({
    project, spend: a.spend.toFixed(4), merged: a.merged,
    cost_per_merge: a.merged ? (a.spend / a.merged).toFixed(4) : null,
  }))

  const snap = JSON.stringify({
    health: health.data ?? [],
    inbox: inbox.data ?? [],
    open_tasks: openTasks.data ?? [],
    roi,
  }).slice(0, 60000)

  const prompt = `You are an analyst for a multi-project autonomous build system. Using ONLY this telemetry JSON, answer the question concisely with specific projects/numbers.\nQUESTION: ${question}\nTELEMETRY: ${snap}`

  const resp = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': anthropicKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 1024,
      messages: [{ role: 'user', content: prompt }],
    }),
  })

  const data = await resp.json()
  const answer = (data.content?.[0]?.text as string) ?? `(API error: ${data.error?.message ?? 'unknown'})`

  return new Response(JSON.stringify({ answer }), {
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  })
})
