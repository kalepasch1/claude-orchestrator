import { requireConnectorUser } from '../../utils/connectorFabric'
import { organizationContext } from '../../utils/adaptiveFabric'
import { serviceClient } from '../../utils/fleetSupabase'
export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event); const body = await readBody<any>(event); const receiptId = String(body?.receipt_id || '')
  const context = await organizationContext(user); const sb = serviceClient(); const { data: receipt } = await sb.from('capability_route_receipts').select('id,selected_provider').eq('id', receiptId).eq('user_id', user.id).maybeSingle(); if (!receipt) throw createError({ statusCode: 404, message: 'route_receipt_not_found' })
  const row = { receipt_id: receipt.id, user_id: user.id, organization_id: context.membership.organization_id, provider: receipt.selected_provider || 'none', succeeded: body.succeeded !== false, quality: Math.max(0, Math.min(1, Number(body.quality ?? .8))), latency_ms: body.latency_ms == null ? null : Math.max(0, Number(body.latency_ms)), realized_cost_usd: body.realized_cost_usd == null ? null : Math.max(0, Number(body.realized_cost_usd)), policy_incidents: Math.max(0, Number(body.policy_incidents || 0)), metadata: body.metadata || {} }
  const { data, error } = await sb.from('capability_route_outcomes').upsert(row, { onConflict: 'receipt_id' }).select().single(); if (error) throw createError({ statusCode: 500, message: 'route_outcome_persistence_failed' }); return { outcome: data }
})
