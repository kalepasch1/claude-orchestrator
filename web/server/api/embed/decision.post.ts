// POST /api/embed/decision — the RETURN LEG of the approvals channel.
//
// Smarter's fleet inbox already receives orchestrator approval cards one-way
// (smarter/server/utils/fleetInbox.ts). This is the other direction: a decision
// taken in the host writes decided_by back onto the approval AND lands as an
// attributed steering_events row here, so the audit trail names the human who
// decided rather than "the integration".
//
// apparently/pareto mount the same strip and post the same envelope; the
// envelope is documented in server/utils/embedProtocol.ts.
import { serviceClient } from '../../utils/fleetSupabase'
import { handleDecision } from '../../utils/embedHandlers'
import { loadEmbedKeys } from '../../utils/embedKeys'

export default defineEventHandler(async event => {
  const key = getHeader(event, 'x-madeus-embed-key')
  const origin = getHeader(event, 'origin')
  const surface = getHeader(event, 'x-madeus-surface') || 'signoffs'
  const body = await readBody<unknown>(event)

  const sb = serviceClient()
  const keys = await loadEmbedKeys(async () => {
    const { data } = await sb.from('embed_keys').select('*')
    return data || []
  })

  const result = await handleDecision({ key, origin, surface, body }, {
    keys,
    approvalTenant: async approvalId => {
      const { data } = await sb.from('approvals').select('tenant_id').eq('id', approvalId).maybeSingle()
      if (!data) return null
      // A pre-tenancy approval carries no tenant; it belongs to the founding one.
      return String((data as any).tenant_id ?? 'founding')
    },
    applyDecision: async d => {
      await sb.from('approvals').update({
        state: d.decision === 'approved' ? 'approved' : 'rejected',
        decided_by: d.decidedBy,
        decided_at: new Date().toISOString(),
      }).eq('id', d.approvalId)
    },
    recordSteering: async e => {
      const { error } = await sb.from('steering_events').insert({
        event_type: 'release_decision',
        approval_id: e.approvalId,
        actor_id: e.decidedBy,
        actor_label: e.decidedByLabel ?? e.decidedBy,
        rationale: e.rationale ?? null,
        tenant_id: e.tenantId,
        payload: { host_app: e.hostApp, source: 'embed' },
      })
      return !error
    },
  })

  setResponseStatus(event, result.status)
  return result.body
})
