import { serviceClient } from '../../utils/fleetSupabase'
import { requireConnectorUser } from '../../utils/connectorFabric'
import { rankInsights, shapeMatrix, summariseQuality, tally } from '../../utils/steeringInsights'

/**
 * Expert insights read model: what the panels concluded (steering_insights), where the
 * docket sits on the lens × risk matrix, and what the local models' outputs are worth.
 * Internal work product under attorney review; never legal advice.
 * Each source is optional: a control plane without migration 20260921000000 returns empty
 * sections with a `missing` note instead of a 500.
 */
export default defineEventHandler(async (event) => {
  await requireConnectorUser(event)
  const q = getQuery(event); const vertical = q.vertical ? String(q.vertical) : ''
  const sb = serviceClient()
  const [insightsRes, docketRes, opsRes] = await Promise.all([
    sb.from('steering_insights').select('id,card_id,vertical,kind,lens,risk_band,insight,rationale,confidence,created_at').eq('status', 'active').order('created_at', { ascending: false }).limit(600),
    sb.from('legal_docket').select('vertical,lens,risk_band,status,priority,origin').order('created_at', { ascending: false }).limit(5000),
    sb.from('app_operations').select('operation,latency_ms,quality_score,verdict').eq('provider', 'local').order('created_at', { ascending: false }).limit(1000),
  ])
  const missing: string[] = []
  for (const [name, res] of [['steering_insights', insightsRes], ['legal_docket', docketRes], ['app_operations', opsRes]] as const) if ((res as any).error) missing.push(`${name}: ${(res as any).error.message}`)
  const all = ((insightsRes.data as any[]) || []).filter(r => !vertical || r.vertical === vertical)
  const ranked = rankInsights(all)
  return {
    ok: true, vertical: vertical || null, missing,
    insights: { total: all.length, byKind: tally(all, r => r.kind), byRisk: tally(all, r => r.risk_band), top: ranked.slice(0, 60),
      pathways: ranked.filter(r => ['innovation', 'opportunity'].includes(r.kind)).slice(0, 12), gaps: ranked.filter(r => r.kind === 'gap').slice(0, 20) },
    matrix: shapeMatrix((docketRes.data as any[]) || [], vertical),
    quality: summariseQuality((opsRes.data as any[]) || []),
  }
})
