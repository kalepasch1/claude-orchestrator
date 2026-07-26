import { createError, getQuery } from 'h3'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const slug = query.slug as string

  const client = await useSupabaseClient(event)

  try {
    // Fetch latest state snapshot for polling clients
    const [cascadeResult, agentResult, logResult] = await Promise.all([
      client
        .from('cascade_operations')
        .select('id, name, status, completed_steps, total_steps, active_agents')
        .in('status', ['running', 'queued'])
        .limit(10),
      client
        .from('fleet_agents')
        .select('id, name, status, current_task')
        .eq('status', 'active')
        .limit(20),
      client
        .from('terminal_logs')
        .select('id, timestamp, level, source, message')
        .order('timestamp', { ascending: false })
        .limit(50)
    ])

    return {
      type: 'state_update',
      cascades: cascadeResult.data || [],
      agents: agentResult.data || [],
      logs: logResult.data || []
    }
  } catch (e: any) {
    if (e.code === '42P01' || e.message?.includes('does not exist')) {
      return { type: 'state_update', cascades: [], agents: [], logs: [] }
    }
    throw createError({ statusCode: 500, message: e.message })
  }
})
