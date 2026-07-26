import { createError } from 'h3'

export default defineEventHandler(async (event) => {
  const client = await useSupabaseClient(event)

  try {
    const { data, error } = await client
      .from('cascade_operations')
      .select('id, name, status, completed_steps, total_steps, active_agents, created_at, updated_at')
      .order('created_at', { ascending: false })
      .limit(50)

    if (error) throw error

    return {
      cascades: (data || []).map(row => ({
        id: row.id,
        name: row.name,
        status: row.status,
        completedSteps: row.completed_steps,
        totalSteps: row.total_steps,
        activeAgents: row.active_agents,
        createdAt: row.created_at,
        updatedAt: row.updated_at
      }))
    }
  } catch (e: any) {
    // Return empty cascades if table doesn't exist yet (pre-migration)
    if (e.code === '42P01' || e.message?.includes('does not exist')) {
      return { cascades: [] }
    }
    throw createError({ statusCode: 500, message: e.message })
  }
})
