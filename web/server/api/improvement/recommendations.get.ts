import { requireConnectorUser } from '../../utils/connectorFabric'
import { serviceClient } from '../../utils/fleetSupabase'
import { recommendationFor, type ImprovementScope } from '../../utils/scopedImprovement'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const query = getQuery(event)
  const scopeType = String(query.scope_type || 'portfolio') as ImprovementScope
  const scopeRef = String(query.scope_ref || 'portfolio')
  const label = String(query.label || (scopeType === 'portfolio' ? 'Entire orchestrator portfolio' : scopeRef))
  const sb = serviceClient()
  const [{ data: outcomes }, { data: tasks }, { data: loops }, { data: contributions }] = await Promise.all([
    sb.from('outcomes').select('project,slug,tests_passed,integrated,usd,created_at').order('created_at', { ascending: false }).limit(500),
    sb.from('tasks').select('project_id,slug,state,kind,created_at').order('created_at', { ascending: false }).limit(300),
    sb.from('scoped_improvement_loops').select('*').eq('owner_id', user.id).order('updated_at', { ascending: false }),
    sb.from('hivemind_contributions').select('status,rebate_credits,verified_value_usd').eq('owner_id', user.id),
  ])
  const recommendation = recommendationFor({ scopeType, scopeRef, label, outcomes: outcomes || [], tasks: tasks || [] })
  return {
    recommendation: { scopeType, scopeRef, label, ...recommendation },
    loops: loops || [],
    credits: (contributions || []).reduce((sum: number, row: any) => sum + Number(row.rebate_credits || 0), 0),
    architecture: ['observe', 'propose', 'shadow', 'verify', 'graduate', 'share'],
  }
})

