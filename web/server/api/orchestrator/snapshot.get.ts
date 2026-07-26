import { createClient } from '@supabase/supabase-js'

// GET /api/orchestrator/snapshot
// Returns live queue state, running tasks, cascade metrics, and cost data
// Mirrors what runner/web_console.py's _build_snapshot() does, but reads from Supabase directly.

const STATES = ['QUEUED', 'RUNNING', 'DONE', 'MERGED', 'BLOCKED', 'CONFLICT', 'TESTFAIL', 'BUILDFAIL', 'SHELVED']

export default defineEventHandler(async (_event) => {
  const url = process.env.SUPABASE_URL || process.env.NUXT_SUPABASE_URL || ''
  const key = process.env.SUPABASE_SERVICE_KEY || process.env.NUXT_SUPABASE_SERVICE_KEY || ''
  if (!url || !key) {
    throw createError({ statusCode: 500, message: 'Supabase not configured' })
  }

  const sb = createClient(url, key, { auth: { persistSession: false } })

  // Parallel: state counts + running tasks + recent completions
  const [stateResults, runningResult, recentDoneResult, costResult] = await Promise.all([
    // Count each state
    Promise.all(
      STATES.map(s =>
        sb.from('tasks').select('id', { count: 'exact', head: true }).eq('state', s)
          .then(({ count }) => [s, count ?? 0] as const)
      )
    ),
    // Running tasks (up to 20, oldest first)
    sb.from('tasks')
      .select('id,slug,account,project_id,updated_at,model_tier,cascade_confidence,kind')
      .eq('state', 'RUNNING')
      .order('updated_at', { ascending: true })
      .limit(20),
    // Recently completed (DONE/MERGED)
    sb.from('tasks')
      .select('slug,state,updated_at,cost_usd,kind')
      .in('state', ['DONE', 'MERGED'])
      .order('updated_at', { ascending: false })
      .limit(10),
    // Aggregate cost from recent tasks
    sb.from('tasks')
      .select('cost_usd,model_tier,state')
      .in('state', ['DONE', 'MERGED'])
      .order('updated_at', { ascending: false })
      .limit(100),
  ])

  const queueStates: Record<string, number> = Object.fromEntries(stateResults)
  const runningTasks = (runningResult.data ?? []).map(r => ({
    slug: r.slug,
    account: r.account,
    project_id: r.project_id,
    updated_at: r.updated_at,
    model_tier: r.model_tier ?? null,
    cascade_confidence: r.cascade_confidence ?? null,
    kind: r.kind ?? null,
  }))
  const recentDone = (recentDoneResult.data ?? []).map(r => ({
    slug: r.slug,
    state: r.state,
    updated_at: r.updated_at,
    cost_usd: r.cost_usd ?? null,
  }))

  // Compute cascade metrics from running tasks
  const tasksWithConfidence = runningTasks.filter(t => t.cascade_confidence != null)
  const avgConfidence = tasksWithConfidence.length
    ? tasksWithConfidence.reduce((s, t) => s + (t.cascade_confidence ?? 0), 0) / tasksWithConfidence.length
    : 0

  // Cost metrics
  const costRows = costResult.data ?? []
  const totalCostUsd = costRows.reduce((s, r) => s + (r.cost_usd ?? 0), 0)
  const cheapModelCount = costRows.filter(r => ['claude-haiku', 'deepseek', 'gemini-flash'].some(m => (r.model_tier ?? '').includes(m))).length
  const savesPercent = costRows.length ? Math.round((cheapModelCount / costRows.length) * 100) : 0

  return {
    timestamp: new Date().toISOString(),
    queue_states: queueStates,
    running_tasks: runningTasks,
    recent_completions: recentDone,
    total_queued: queueStates['QUEUED'] ?? 0,
    total_running: queueStates['RUNNING'] ?? 0,
    total_blocked: (queueStates['BLOCKED'] ?? 0) + (queueStates['TESTFAIL'] ?? 0) + (queueStates['BUILDFAIL'] ?? 0),
    cascade: {
      avg_confidence: Math.round(avgConfidence * 100) / 100,
      saves_percent: savesPercent,
      active_tasks: tasksWithConfidence.length,
    },
    metrics: {
      total_cost_usd: Math.round(totalCostUsd * 10000) / 10000,
      completed_count: costRows.length,
      cheap_model_rate: savesPercent,
    },
  }
})
