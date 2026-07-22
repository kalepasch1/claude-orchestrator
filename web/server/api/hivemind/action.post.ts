import {requireConnectorUser} from '../../utils/connectorFabric'
import {proposeHivemindImprovement,publishHivemindContribution,updateHivemindPolicy} from '../../utils/hivemindEconomy'
import {adoptWithImmunity,settleCausalRebateGuarded} from '../../utils/hivemindAdvanced'
export default defineEventHandler(async event=>{const user=await requireConnectorUser(event),body=await readBody<any>(event);switch(body?.action){case'policy':return updateHivemindPolicy(user,body);case'improvement':return proposeHivemindImprovement(user,body);case'contribute':return publishHivemindContribution(user,body);case'adopt':return adoptWithImmunity(user,body);case'verify_adoption':return settleCausalRebateGuarded(user,body);default:throw createError({statusCode:400,message:'unknown_hivemind_action'})}})
