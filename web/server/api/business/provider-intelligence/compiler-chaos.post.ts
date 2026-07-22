import{organizationContext,requireOrgAdmin}from'../../../utils/adaptiveFabric'
import{requireConnectorUser}from'../../../utils/connectorFabric'
import{createChaosAndCompilerEvidence}from'../../../utils/providerNetworkExecutionStore'
export default defineEventHandler(async event=>{const user=await requireConnectorUser(event),context=await organizationContext(user);requireOrgAdmin(context);const body=await readBody<any>(event);if(!body.provider||!body.version)throw createError({statusCode:422,message:'provider_and_version_required'});return await createChaosAndCompilerEvidence(context.membership.organization_id,body)})
