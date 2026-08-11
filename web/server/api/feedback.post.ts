import { randomUUID } from 'node:crypto'
import { requireConnectorUser } from '../utils/connectorFabric'
import { serviceClient } from '../utils/fleetSupabase'

const CATEGORIES = new Set([
  'context', 'model', 'prompt', 'tooling', 'guardrail', 'strategy', 'rate_limit',
  'efficiency', 'quality', 'reliability', 'cost', 'other', 'general',
])
const SEVERITIES = new Set(['low', 'med', 'high'])

function text(value: unknown, max: number) {
  return String(value || '').trim().slice(0, max)
}

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const body = await readBody<any>(event)
  const observation = text(body?.observation, 2_000)
  const suggestion = text(body?.suggestion, 2_000)
  if (observation.length < 3) throw createError({ statusCode: 400, message: 'Describe the improvement you want.' })

  const categoryRaw = text(body?.category, 40).toLowerCase()
  const severityRaw = text(body?.severity, 20).toLowerCase()
  const category = CATEGORIES.has(categoryRaw) ? categoryRaw : 'other'
  const severity = severityRaw === 'critical' ? 'high' : SEVERITIES.has(severityRaw) ? severityRaw : 'med'
  const sb = serviceClient()
  const { data: projects, error: projectError } = await sb.from('projects').select('id,name').order('name')
  if (projectError || !projects?.length) throw createError({ statusCode: 503, message: 'No execution workspace is available.' })

  const requestedProject = body?.project_id
    ? projects.find((project: any) => project.id === String(body.project_id))
    : null
  if (body?.project_id && !requestedProject) throw createError({ statusCode: 400, message: 'The selected project is unavailable.' })
  const project = requestedProject
    || projects.find((item: any) => String(item.name).toLowerCase() === 'beethoven')
    || projects[0]
  const slug = `operator-improvement-${Date.now()}-${randomUUID().slice(0, 8)}`
  const prompt = [
    '# Operator improvement',
    observation,
    suggestion ? `\n# Suggested direction\n${suggestion}` : '',
    '',
    '# Delivery contract',
    'Treat this authenticated operator request as product work, not advisory feedback.',
    'Inspect the existing implementation and preserve every independently improved behavior.',
    'Layer compatible changes; if two edits overlap semantically, choose or synthesize the implementation with the strongest verified behavior.',
    'Run targeted tests, the production build, independent regression review, integration, and the verified release train.',
    'Do not mark the work shipped without an integrated commit and deployment evidence.',
  ].filter(Boolean).join('\n')

  // The executable task is the durable receipt. Feedback review may enrich or cluster it,
  // but cannot be the only path to implementation.
  const { data: task, error: taskError } = await sb.from('tasks').insert({
    project_id: project.id,
    slug,
    prompt,
    kind: 'improvement',
    state: 'QUEUED',
    priority: 10,
    note: `source:operator-feedback; category:${category}; severity:${severity}; qa:independent; release:verified`,
    submitted_by: user.id,
    submitted_by_label: user.email || user.id,
  }).select('id,slug,state,kind,project_id,created_at').single()
  if (taskError) throw createError({ statusCode: 500, message: `Improvement was not queued: ${taskError.message}` })

  const { data: feedback, error: feedbackError } = await sb.from('orchestrator_feedback').insert({
    task_id: task.id,
    project: project.name,
    slug: task.slug,
    source: 'human',
    category,
    severity,
    observation,
    suggestion,
    evidence: `Authenticated task receipt ${task.id}`,
    status: 'triaged',
  }).select('id,status,created_at').single()

  return {
    ok: true,
    task,
    feedback: feedback || null,
    warning: feedbackError ? `Task queued, but feedback indexing failed: ${feedbackError.message}` : null,
    project: { id: project.id, name: project.name },
  }
})
