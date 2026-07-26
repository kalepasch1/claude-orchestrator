import { createError } from 'h3'

export default defineEventHandler(async (event) => {
  const client = await useSupabaseClient(event)

  try {
    const { data, error } = await client
      .from('cascade_operations')
      .select('status, created_at, updated_at')

    if (error) throw error

    const rows = data || []
    const today = new Date().toISOString().slice(0, 10)

    const totalCascades = rows.length
    const activeCascades = rows.filter(r => r.status === 'running').length
    const todayRows = rows.filter(r => r.created_at?.startsWith(today))
    const completedToday = todayRows.filter(r => r.status === 'completed').length
    const failedToday = todayRows.filter(r => r.status === 'failed').length

    // Compute average duration for completed cascades
    const completedRows = rows.filter(r => r.status === 'completed' && r.updated_at)
    const durations = completedRows.map(r => {
      const start = new Date(r.created_at).getTime()
      const end = new Date(r.updated_at).getTime()
      return end - start
    }).filter(d => d > 0)

    const avgDurationMs = durations.length > 0
      ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
      : 0

    const totalCompleted = rows.filter(r => ['completed', 'failed'].includes(r.status)).length
    const successRate = totalCompleted > 0
      ? Math.round((rows.filter(r => r.status === 'completed').length / totalCompleted) * 100)
      : 100

    return {
      totalCascades,
      activeCascades,
      completedToday,
      failedToday,
      avgDurationMs,
      successRate
    }
  } catch (e: any) {
    if (e.code === '42P01' || e.message?.includes('does not exist')) {
      return {
        totalCascades: 0,
        activeCascades: 0,
        completedToday: 0,
        failedToday: 0,
        avgDurationMs: 0,
        successRate: 100
      }
    }
    throw createError({ statusCode: 500, message: e.message })
  }
})
