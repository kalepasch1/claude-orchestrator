import{organizationContext,requireOrgAdmin}from'../../../utils/adaptiveFabric'
import{requireConnectorUser}from'../../../utils/connectorFabric'
import{attestThresholdCeremony}from'../../../utils/providerNetworkExecutionStore'
export default defineEventHandler(async event=>{const user=await requireConnectorUser(event),context=await organizationContext(user);requireOrgAdmin(context);const body=await readBody<any>(event);if(!body.ceremony||!Array.isArray(body.attestations))throw createError({statusCode:422,message:'ceremony_attestations_required'});return{ceremony:await attestThresholdCeremony(context.membership.organization_id,body)}})
