// POST /api/embed/submit — a host app hands an outcome to the one fleet.
//
// Thin on purpose: the logic (and every deny path) lives in
// server/utils/embedHandlers.ts so it is testable without a server. This file
// only translates HTTP to that call and back.
import { serviceClient } from '../../utils/fleetSupabase'
import { handleSubmit } from '../../utils/embedHandlers'
import { loadEmbedKeys } from '../../utils/embedKeys'

export default defineEventHandler(async event => {
  const key = getHeader(event, 'x-madeus-embed-key')
  // Origin is set by the browser and cannot be spoofed by page JS; it is the
  // load-bearing half of the handshake, not decoration.
  const origin = getHeader(event, 'origin')
  const surface = getHeader(event, 'x-madeus-surface') || 'universal_command'
  const body = await readBody<unknown>(event)

  const sb = serviceClient()
  const keys = await loadEmbedKeys(async () => {
    const { data } = await sb.from('embed_keys').select('*')
    return data || []
  })

  const result = await handleSubmit({ key, origin, surface, body }, {
    keys,
    enqueue: async submission => {
      const { data, error } = await sb.from('orch_embed_outcomes').insert({
        tenant_id: submission.tenantId,
        host_app: submission.hostApp,
        entity_id: submission.entityId ?? null,
        department: submission.department ?? null,
        outcome: submission.outcome,
        state: 'queued',
      }).select('id').single()
      if (error) throw new Error(error.message)
      return String(data?.id ?? '')
    },
  })

  setResponseStatus(event, result.status)
  return result.body
})
