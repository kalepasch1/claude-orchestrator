import { createError } from 'h3'

export default defineEventHandler(async (event) => {
  const client = await useSupabaseClient(event)

  try {
    const [agentResult, deployResult] = await Promise.all([
      client
        .from('fleet_agents')
        .select('id, name, status, current_task, cpu_pct, mem_mb')
        .order('status', { ascending: true }),
      client
        .from('fleet_deployments')
        .select('project, status, version, deployed_at')
        .order('deployed_at', { ascending: false })
    ])

    return {
      agents: (agentResult.data || []).map(a => ({
        id: a.id,
        name: a.name,
        status: a.status,
        currentTask: a.current_task,
        cpuPct: a.cpu_pct,
        memMb: a.mem_mb
      })),
      deployments: (deployResult.data || []).map(d => ({
        project: d.project,
        status: d.status,
        version: d.version,
        deployedAt: d.deployed_at
      }))
    }
  } catch (e: any) {
    if (e.code === '42P01' || e.message?.includes('does not exist')) {
      return { agents: [], deployments: [] }
    }
    throw createError({ statusCode: 500, message: e.message })
  }
})
