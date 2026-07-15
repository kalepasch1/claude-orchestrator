import { serviceClient } from './fleetSupabase'

export async function organizationContext(user: any) {
  const sb = serviceClient()
  let { data: membership } = await sb.from('orchestrator_org_memberships').select('organization_id,role,status, organization:orchestrator_organizations(id,name,slug)').eq('user_id', user.id).eq('status', 'active').limit(1).maybeSingle()
  if (!membership) {
    const slug = `personal-${String(user.id).slice(0, 12)}`
    const { data: organization, error } = await sb.from('orchestrator_organizations').upsert({ name: user.user_metadata?.full_name ? `${user.user_metadata.full_name}'s organization` : 'My organization', slug, created_by: user.id }, { onConflict: 'slug' }).select().single()
    if (error) throw createError({ statusCode: 500, message: 'organization_bootstrap_failed' })
    await sb.from('orchestrator_org_memberships').upsert({ organization_id: organization.id, user_id: user.id, role: 'owner', status: 'active' })
    membership = { organization_id: organization.id, role: 'owner', status: 'active', organization }
  }
  const { data: passport } = await sb.from('orchestrator_capability_passports').select('*').eq('organization_id', membership.organization_id).maybeSingle()
  if (!passport) {
    const defaults = { organization_id: membership.organization_id, permissions: ['*'], connector_allowlist: [], policies: { least_privilege: true, require_pre_action_guidance: true }, default_objective: 'operate', updated_by: user.id }
    const { data } = await sb.from('orchestrator_capability_passports').upsert(defaults).select().single()
    return { membership, passport: data }
  }
  return { membership, passport }
}

export function requireOrgAdmin(context: any) {
  if (!['owner', 'admin'].includes(context.membership.role)) throw createError({ statusCode: 403, message: 'organization_admin_required' })
}

export async function adaptiveContext(user: any) {
  const sb = serviceClient(); const context = await organizationContext(user)
  const [{ data: events }, { data: progress }, { data: providers }, { data: members }] = await Promise.all([
    sb.from('interface_learning_events').select('route,event,created_at').eq('user_id', user.id).gte('created_at', new Date(Date.now() - 30 * 86400_000).toISOString()).order('created_at', { ascending: false }).limit(500),
    sb.from('onboarding_progress').select('*').eq('user_id', user.id),
    sb.from('connector_provider_configs').select('provider,enabled,updated_at').eq('organization_id', context.membership.organization_id),
    sb.from('orchestrator_org_memberships').select('user_id,role,status,joined_at').eq('organization_id', context.membership.organization_id),
  ])
  const frequencies: Record<string, number> = {}; for (const event of events || []) if (event.route) frequencies[event.route] = (frequencies[event.route] || 0) + 1
  return { organization: context.membership.organization, role: context.membership.role, passport: context.passport, learned_routes: Object.entries(frequencies).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([route, visits]) => ({ route, visits })), onboarding: progress || [], delegated_providers: providers || [], member_count: (members || []).filter((item: any) => item.status === 'active').length }
}

export async function resolveDelegatedProvider(userId: string, provider: string) {
  const sb = serviceClient(); const { data: membership } = await sb.from('orchestrator_org_memberships').select('organization_id').eq('user_id', userId).eq('status', 'active').limit(1).maybeSingle(); if (!membership) return null
  const { data } = await sb.from('connector_provider_configs').select('*').eq('organization_id', membership.organization_id).eq('provider', provider).eq('enabled', true).maybeSingle(); return data
}
