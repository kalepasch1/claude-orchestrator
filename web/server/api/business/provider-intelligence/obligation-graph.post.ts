import{organizationContext,requireOrgAdmin}from'../../../utils/adaptiveFabric'
import{requireConnectorUser}from'../../../utils/connectorFabric'
import{rebuildObligationGraph}from'../../../utils/providerNetworkExecutionStore'
export default defineEventHandler(async event=>{const user=await requireConnectorUser(event),context=await organizationContext(user);requireOrgAdmin(context);const graph=await rebuildObligationGraph(context.membership.organization_id);return{graph,blocked_duplicates:graph.duplicate_clusters?.length||0,execution:'analysis_only'}})
