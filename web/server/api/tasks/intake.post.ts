import { requireConnectorUser } from '../../utils/connectorFabric'
import { serviceClient } from '../../utils/fleetSupabase'

function slugify(value: string) {
  const base = value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 52)
  return base || `objective-${Date.now()}`
}

function inferKind(intent: string) {
  if (/\b(research|investigate|compare|evaluate|explore)\b/i.test(intent)) return 'research'
  if (/\b(fix|bug|broken|regression|repair)\b/i.test(intent)) return 'fix'
  if (/\b(deploy|release|ship to prod|production)\b/i.test(intent)) return 'deploy'
  if (/\b(test|qa|verify|audit)\b/i.test(intent)) return 'qa'
  return 'build'
}

export default defineEventHandler(async (event) => {
  await requireConnectorUser(event)
  const body = await readBody<any>(event)
  const intent = String(body?.intent || '').trim()
  if (intent.length < 3) throw createError({ statusCode: 400, message: 'Describe the outcome you want.' })
  if (intent.length > 20_000) throw createError({ statusCode: 400, message: 'Keep the objective under 20,000 characters.' })

  const sb = serviceClient()
  const { data: projects, error: projectError } = await sb.from('projects').select('id,name,repo_path').order('name')
  if (projectError || !projects?.length) throw createError({ statusCode: 503, message: 'No execution workspace is available.' })

  const normalized = intent.toLowerCase()
  const explicitlySelected = body?.project_id ? projects.find((project: any) => project.id === String(body.project_id)) : null
  if (body?.project_id && !explicitlySelected) throw createError({ statusCode: 400, message: 'The selected project is unavailable.' })
  const mentionedProjects = projects.filter((project: any) => {
    const name = String(project.name || '').toLowerCase()
    return name && new RegExp(`(^|[^a-z0-9])${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-z0-9]|$)`).test(normalized)
  })
  const preferred = projects.find((project: any) => String(project.name).toLowerCase() === 'beethoven')
  const portfolioIntent = /\b(portfolio|fleet|all apps|across apps|madeus|orchestrator platform)\b/i.test(intent)
  const inferred = explicitlySelected || (mentionedProjects.length === 1 ? mentionedProjects[0] : portfolioIntent ? preferred : null)
  if (!inferred && projects.length > 1) {
    throw createError({
      statusCode: 409,
      statusMessage: 'Project selection required',
      data: {
        code: 'project_required',
        message: mentionedProjects.length > 1 ? 'This objective appears to reference more than one project. Choose the primary workspace.' : 'Which project should Madeus change?',
        projects: projects.map((project: any) => ({ id: project.id, name: project.name })),
      },
    })
  }
  const project = inferred || projects[0]
  const kind = inferKind(intent)
  const slug = slugify(intent)
  const prompt = [
    '# User objective',
    intent,
    '',
    '# Autopilot intake contract',
    'Infer the necessary research, plan, capability specialists, implementation slices, and verification from the objective.',
    'Select provider, model, agent, branch/worktree, context budget, and retry policy through the learned triage, Colosseum, and outcome-routing layers.',
    'Use the configured design capability when the objective affects interface, brand, content hierarchy, accessibility, or interaction design.',
    'Finish with independent QA, integration, and the normal release train. Ask the operator only for a true permission, secret, irreversible action, or material legal posture decision.',
  ].join('\n')

  const { data: task, error } = await sb.from('tasks').insert({
    project_id: project.id,
    slug,
    prompt,
    kind,
    state: 'QUEUED',
    note: 'source:intent-console; route:auto; model:auto; vendor:auto; branch:auto; qa:auto; release:auto',
  }).select('id,slug,state,kind,project_id,created_at').single()
  if (error) throw createError({ statusCode: 500, message: error.message })

  return {
    ok: true,
    task,
    project: { id: project.id, name: project.name, inferred: !explicitlySelected },
    route: {
      mode: 'autopilot',
      summary: 'Triage will classify the work, Colosseum will select the strongest available route, and the release train will verify and ship it.',
      stages: ['Clarify', 'Plan', 'Build', 'Independent QA', 'Integrate', 'Release'],
    },
  }
})
