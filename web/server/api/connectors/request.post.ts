import { CONNECTOR_BY_ID } from '~/config/connectors'
import { requireConnectorUser } from '../../utils/connectorFabric'
import { serviceClient } from '../../utils/fleetSupabase'

function requestSlug(names: string[]) {
  const stem = names.slice(0, 3).join('-').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 38)
  return `connect-${stem || 'integration-suite'}-${Date.now().toString(36)}`
}

export default defineEventHandler(async (event) => {
  const user = await requireConnectorUser(event)
  const body = await readBody<any>(event)
  const ids = [...new Set((Array.isArray(body?.providers) ? body.providers : [body?.provider]).map(String).filter(Boolean))]
  if (!ids.length || ids.length > 40) throw createError({ statusCode: 400, message: 'Choose between 1 and 40 connections.' })
  const definitions = ids.map(id => CONNECTOR_BY_ID[id]).filter(Boolean)
  if (definitions.length !== ids.length) throw createError({ statusCode: 400, message: 'One or more requested connectors are not registered.' })

  const sb = serviceClient()
  const { data: projects } = await sb.from('projects').select('id,name').order('name')
  const project = projects?.find((item: any) => String(item.name).toLowerCase() === 'beethoven') || projects?.[0]
  if (!project) throw createError({ statusCode: 503, message: 'No execution workspace is available.' })

  const inventory = definitions.map(item => `- ${item.name} (${item.auth}): ${item.workflow || item.summary}\n  Documentation: ${item.documentationUrl || 'vendor developer portal'}`).join('\n')
  const prompt = [
    '# Connection activation request',
    `Requested by user ${user.id} through the Madeus governed connector catalog.`,
    '',
    inventory,
    '',
    '# Activation contract',
    'For each provider, verify the current official integration surface and least-privilege scopes, register or configure the production application when administrator credentials are available, set the exact Madeus callback URL, and validate token exchange or API-key health.',
    'Never fabricate a connected state. Ask the account owner only when vendor consent, a secret, billing acceptance, or marketplace review is genuinely required.',
    'After authorization, run a reversible read test and a sandboxed write/generation test where supported, record audit evidence, expose the account to Colosseum routing, and verify revocation and credential refresh.',
    'Finish with independent QA and production deployment evidence. Preserve vendor attribution, licensing, privacy, and content-provenance requirements.',
  ].join('\n')
  const { data: task, error } = await sb.from('tasks').insert({
    project_id: project.id,
    slug: requestSlug(definitions.map(item => item.name)),
    prompt,
    kind: 'build',
    state: 'QUEUED',
    note: `source:connector-catalog; requested:${ids.join(',')}; route:auto; approval:external-consent-only`,
  }).select('id,slug,state,created_at').single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { ok: true, task, requested: definitions.map(item => ({ id: item.id, name: item.name, auth: item.auth })) }
})
