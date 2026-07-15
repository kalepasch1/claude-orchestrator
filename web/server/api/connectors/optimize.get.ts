import { CONNECTORS } from '~/config/connectors'
import { organizationContext } from '../../utils/adaptiveFabric'
import { providerConfigured, requireConnectorUser } from '../../utils/connectorFabric'
import { optimizeConnectors } from '../../utils/connectorOptimizer'
import { serviceClient } from '../../utils/fleetSupabase'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const context = await organizationContext(user)
  const sb = serviceClient()
  const [{ data: accounts }, { data: outcomes }, { data: delegated }] = await Promise.all([
    sb.from('connector_accounts').select('provider,status').eq('user_id', user.id),
    sb.from('capability_route_outcomes').select('provider,succeeded,quality,realized_cost_usd,policy_incidents').eq('organization_id', context.membership.organization_id).limit(1000),
    sb.from('connector_provider_configs').select('provider,enabled').eq('organization_id', context.membership.organization_id).eq('enabled', true),
  ])
  const connected = new Set((accounts || []).filter((row: any) => row.status === 'connected').map((row: any) => row.provider))
  const configured = new Set((delegated || []).map((row: any) => row.provider))
  const inputs = CONNECTORS.map(connector => {
    const history = (outcomes || []).filter((row: any) => row.provider === connector.id)
    return {
      provider: connector.id,
      connected: connected.has(connector.id),
      configured: configured.has(connector.id) || providerConfigured(connector.id),
      samples: history.length,
      succeeded: history.filter((row: any) => row.succeeded).length,
      qualityTotal: history.reduce((sum: number, row: any) => sum + Number(row.quality || 0), 0),
      costTotal: history.reduce((sum: number, row: any) => sum + Number(row.realized_cost_usd || 0), 0),
      policyIncidents: history.reduce((sum: number, row: any) => sum + Number(row.policy_incidents || 0), 0),
      capabilities: connector.capabilities,
    }
  })
  const recommendations = optimizeConnectors(inputs)
  return {
    recommendations,
    summary: {
      prefer: recommendations.filter(item => item.recommendation === 'prefer').length,
      activate: recommendations.filter(item => item.recommendation === 'activate').length,
      observe: recommendations.filter(item => item.recommendation === 'observe').length,
      deprioritize: recommendations.filter(item => item.recommendation === 'deprioritize').length,
    },
    policy: 'Recommendations never grant access or revoke credentials. Operator confirmation remains required.',
  }
})

