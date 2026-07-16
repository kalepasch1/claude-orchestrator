import{organizationContext}from'../../../utils/adaptiveFabric'
import{requireConnectorUser}from'../../../utils/connectorFabric'
import{providerIntelligenceDashboard}from'../../../utils/providerIntelligenceStore'
export default defineEventHandler(async event=>{const user=await requireConnectorUser(event),context=await organizationContext(user);return providerIntelligenceDashboard(context.membership.organization_id)})
