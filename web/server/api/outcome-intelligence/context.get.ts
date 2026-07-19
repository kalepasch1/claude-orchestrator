import { requireConnectorUser } from '../../utils/connectorFabric'
import { organizationContext } from '../../utils/adaptiveFabric'
import { serviceClient } from '../../utils/fleetSupabase'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event); const context = await organizationContext(user); const sb = serviceClient(); const organizationId = context.membership.organization_id
  const [events, routes, evidence, shadows, drifts, decisions, proofs] = await Promise.all([
    sb.from('interface_learning_events').select('route,event,created_at').eq('organization_id', organizationId).order('created_at',{ascending:false}).limit(500),
    sb.from('capability_route_outcomes').select('provider,succeeded,quality,latency_ms,realized_cost_usd,created_at').eq('organization_id', organizationId).order('created_at',{ascending:false}).limit(500),
    sb.from('causal_outcome_evidence').select('intervention,estimated_effect,confidence,created_at').eq('organization_id', organizationId).order('created_at',{ascending:false}).limit(20),
    sb.from('outcome_shadow_experiments').select('*').eq('organization_id', organizationId).order('created_at',{ascending:false}).limit(10),
    sb.from('outcome_drift_snapshots').select('*').eq('organization_id', organizationId).order('created_at',{ascending:false}).limit(10),
    sb.from('collective_intent_sessions').select('id,objective,status,decision,conflicts,created_at').eq('organization_id', organizationId).order('created_at',{ascending:false}).limit(10),
    sb.from('execution_proof_envelopes').select('id,action_type,status,proof_digest,created_at').eq('organization_id', organizationId).order('created_at',{ascending:false}).limit(10),
  ])
  const routeRows = routes.data || []; const eventRows = events.data || []
  return {
    organization: context.membership.organization,
    live_twin: { observed_events: eventRows.length, active_routes: new Set(eventRows.map((r:any)=>r.route).filter(Boolean)).size, route_runs: routeRows.length, reliability: routeRows.length ? routeRows.filter((r:any)=>r.succeeded).length/routeRows.length : null, average_quality: routeRows.length ? routeRows.reduce((s:number,r:any)=>s+Number(r.quality||0),0)/routeRows.length : null },
    causal_evidence: evidence.data || [], shadows: shadows.data || [], drifts: drifts.data || [], decisions: decisions.data || [], proofs: proofs.data || [],
    refreshed_at: new Date().toISOString(), privacy: { raw_user_records_disclosed: false, connector_secrets_disclosed: false, aggregate_only: true },
  }
})
