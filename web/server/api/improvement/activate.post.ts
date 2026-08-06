import { requireConnectorUser } from '../../utils/connectorFabric'
import { serviceClient } from '../../utils/fleetSupabase'
import { activationPrompt, LOCKED_INVARIANTS, recommendationFor, type ImprovementScope } from '../../utils/scopedImprovement'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const body = await readBody<any>(event)
  const scopeType = String(body?.scope_type || '') as ImprovementScope
  if (!['portfolio','application','orchestrator','workflow','code','component'].includes(scopeType)) throw createError({ statusCode: 400, message: 'Choose a valid improvement scope.' })
  const scopeRef = String(body?.scope_ref || '').trim()
  const label = String(body?.label || scopeRef).trim()
  if (!scopeRef || !label) throw createError({ statusCode: 400, message: 'Name the exact surface this loop may improve.' })
  const mode = ['observe','shadow','bounded_autonomy'].includes(body?.mode) ? body.mode : 'shadow'
  const sb = serviceClient()
  let projectId = body?.project_id || null
  if (!projectId) {
    const { data: projects } = await sb.from('projects').select('id,name').order('name')
    projectId = projects?.find((project: any) => String(project.name).toLowerCase() === 'beethoven')?.id || projects?.[0]?.id || null
  }
  const recommendation = recommendationFor({ scopeType, scopeRef, label })
  const loopRow = {
    owner_id: user.id, project_id: projectId, scope_type: scopeType, scope_ref: scopeRef, label, mode,
    target_kpi: body?.target_kpi || recommendation.targetKpi, status: 'active', allocation_pct: mode === 'observe' ? 0 : 2,
    rollback_threshold: Math.max(1, Math.min(50, Number(body?.rollback_threshold || 10))),
    locked_invariants: LOCKED_INVARIANTS, recommendation,
  }
  const { data: loop, error } = await sb.from('scoped_improvement_loops').upsert(loopRow, { onConflict: 'owner_id,scope_type,scope_ref' }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  let task = null
  if (projectId) {
    const taskResult = await sb.from('tasks').insert({
      project_id: projectId,
      slug: `${`operator-improve-${scopeType}-${scopeRef}`.toLowerCase().replace(/[^a-z0-9-]+/g, '-').slice(0, 58)}-${Date.now()}`,
      prompt: activationPrompt(loop), kind: 'improvement', state: 'QUEUED',
      priority: 10,
      note: `source:operator-scoped-improvement; loop:${loop.id}; mode:${mode}; qa:independent; rollback:auto; release:verified`,
      submitted_by: user.id,
      submitted_by_label: user.email || user.id,
    }).select('id,slug,state,kind,project_id,created_at').single()
    if (taskResult.error) throw createError({ statusCode: 500, message: `Improvement loop was saved but execution was not queued: ${taskResult.error.message}` })
    task = taskResult.data
  }
  return { ok: true, loop, task, receipt: { action: 'improvement_loop_activated', scope: `${scopeType}:${scopeRef}`, task_id: task?.id || null, task_slug: task?.slug || null, invariants: LOCKED_INVARIANTS, at: new Date().toISOString() } }
})
