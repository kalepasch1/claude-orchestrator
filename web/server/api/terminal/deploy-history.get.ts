import { createError, getQuery } from 'h3'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const project = query.project as string | undefined
  const limit = Math.min(Number(query.limit) || 20, 100)

  const client = await useSupabaseClient(event)

  try {
    let q = client
      .from('fleet_deployments')
      .select('id, project, version, status, started_at, completed_at, triggered_by, commit_hash')
      .order('started_at', { ascending: false })
      .limit(limit)

    if (project) {
      q = q.eq('project', project)
    }

    const { data, error } = await q
    if (error) throw error

    return {
      records: (data || []).map(d => ({
        id: d.id,
        project: d.project,
        version: d.version,
        status: d.status,
        startedAt: d.started_at,
        completedAt: d.completed_at,
        triggeredBy: d.triggered_by,
        commitHash: d.commit_hash
      }))
    }
  } catch (e: any) {
    if (e.code === '42P01' || e.message?.includes('does not exist')) {
      return { records: [] }
    }
    throw createError({ statusCode: 500, message: e.message })
  }
})
