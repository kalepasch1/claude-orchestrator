// GET /api/workspace/slots?tenantId=... — the four integration slots for a
// managed startup's workspace view.
//
// Thin wrapper: all four slots resolve in server/utils/integrationSlots.ts,
// which never throws and always returns four views. This handler's only job is
// to load the tenant's config and supply the probes.
//
// Every probe here is env-gated and fail-open by construction: an unset env var
// simply means the probe is absent, which the resolver renders as
// "not connected" with a link-out rather than as an error.
import { serviceClient } from '../../utils/fleetSupabase'
import { resolveSlots, type TenantIntegrationConfig } from '../../utils/integrationSlots'

export default defineEventHandler(async event => {
  const tenantId = String(getQuery(event).tenantId || 'founding')
  const sb = serviceClient()

  let config: TenantIntegrationConfig = { tenantId }
  try {
    const { data } = await sb.from('tenant_integration_config')
      .select('*').eq('tenant_id', tenantId).maybeSingle()
    if (data) {
      config = {
        tenantId,
        coordination: (data as any).coordination ?? undefined,
        interception: (data as any).interception ?? undefined,
        compliance: (data as any).compliance ?? undefined,
        risk: (data as any).risk ?? undefined,
      }
    }
  } catch {
    // No config row, or the table is not there yet. Defaults apply — which
    // means interception is still advisory, per the default-ON rule.
  }

  const apparentlyBase = process.env.APPARENTLY_S2S_URL
  const apparentlyToken = process.env.APPARENTLY_S2S_TOKEN

  const slots = await resolveSlots(config, {
    coordinationLive: config.coordination?.boardUrl
      ? async () => process.env.SMARTER_EMBED_LIVE === 'true'
      : undefined,

    compliancePull: apparentlyBase && apparentlyToken
      ? async (orgId: string) => {
          const res = await $fetch<any>(`${apparentlyBase.replace(/\/+$/, '')}/api/s2s/compliance-summary`, {
            headers: { authorization: `Bearer ${apparentlyToken}` },
            query: { orgId },
            timeout: 5000,
          })
          return {
            openFindings: Number(res?.openFindings ?? 0),
            filingsStatus: String(res?.filingsStatus ?? 'unknown'),
            radarUrl: res?.radarUrl,
          }
        }
      : undefined,

    materialRisk: async () => {
      // A quantified material risk is a CADE escalate WITH a dollar estimate.
      // Either half alone is not a hedgeable position.
      const { data } = await sb.from('approvals')
        .select('summary, risk_estimate_usd')
        .eq('tenant_id', tenantId).eq('kind', 'legal_gate').eq('state', 'pending')
        .not('risk_estimate_usd', 'is', null)
        .order('risk_estimate_usd', { ascending: false }).limit(1)
      const top = (data || [])[0] as any
      if (!top) return null
      return { estimateUsd: Number(top.risk_estimate_usd || 0), subject: String(top.summary || 'open exposure') }
    },
  })

  return { ok: true, tenantId, slots }
})
