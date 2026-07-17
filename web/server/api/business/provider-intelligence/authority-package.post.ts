import{organizationContext,requireOrgAdmin}from'../../../utils/adaptiveFabric'
import{requireConnectorUser}from'../../../utils/connectorFabric'
import{ingestAuthorityRulePackage}from'../../../utils/providerNetworkExecutionStore'
export default defineEventHandler(async event=>{const user=await requireConnectorUser(event),context=await organizationContext(user);requireOrgAdmin(context);const body=await readBody<any>(event);if(!body.authority_source_id||!body.signature)throw createError({statusCode:422,message:'signed_authority_package_required'});return{package:await ingestAuthorityRulePackage(context.membership.organization_id,body)}})
