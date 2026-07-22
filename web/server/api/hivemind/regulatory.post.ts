import { requireConnectorUser } from '../../utils/connectorFabric'
import {
  createRegulatoryRelationship,
  ingestUserRegulatorySource,
  requestRegulatoryAssistance,
  runRegulatoryAutopilot,
  updateRegulatoryProfile,
} from '../../utils/regulatoryCapability'
import { organizationContext, requireOrgAdmin } from '../../utils/adaptiveFabric'
import {
  electCadeSettlement,
  saveAgreementControls,
  saveFeatureControl,
  saveTemporalScenario,
  selectStrategyOption,
} from '../../utils/regulatoryTemporal'
import { executeFrontierRun, grantBoundedRegulatorAccess } from '../../utils/regulatoryFrontier'
import { saveOpportunityAction } from '../../utils/regulatoryOpportunity'
import { saveExecutionAction } from '../../utils/regulatoryExecution'
import { saveSovereigntyAction } from '../../utils/regulatorySovereignty'
import { saveImmuneSystemAction } from '../../utils/regulatoryImmuneSystem'
import { saveProofMarketAction } from '../../utils/regulatoryProofMarket'
import { saveAtomicAssuranceAction } from '../../utils/regulatoryAtomicAssurance'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const body = await readBody<any>(event)
  if (body?.action === 'scan') {
    const context = await organizationContext(user)
    return runRegulatoryAutopilot(context.membership.organization_id, 'operator')
  }
  if (body?.action === 'assess') return ingestUserRegulatorySource(user, body)
  if (body?.action === 'assist') return requestRegulatoryAssistance(user, body)
  if (body?.action === 'configure') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return updateRegulatoryProfile(user, body)
  }
  if (body?.action === 'relationship') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return createRegulatoryRelationship(user, body)
  }
  if (body?.action === 'forecast') {
    const context = await organizationContext(user)
    return saveTemporalScenario(context.membership.organization_id, body)
  }
  if (body?.action === 'agreement_controls') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return saveAgreementControls(context.membership.organization_id, user.id, body)
  }
  if (body?.action === 'feature_control') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return saveFeatureControl(context.membership.organization_id, user.id, body)
  }
  if (body?.action === 'cade_settlement') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return electCadeSettlement(context.membership.organization_id, body)
  }
  if (body?.action === 'select_strategy') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return selectStrategyOption(context.membership.organization_id, String(body.option_id || ''))
  }
  if (['worldline','systemic_risk','examination','acquisition','capital','dispute_prevention'].includes(body?.action)) {
    const context = await organizationContext(user)
    return executeFrontierRun(context.membership.organization_id, body.action, body)
  }
  if (body?.action === 'regulator_access') {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return grantBoundedRegulatorAccess(context.membership.organization_id, user.id, body)
  }
  if (['select_counterfactual','safe_harbor','incident_twin','capacity','match_capacity'].includes(body?.action)) {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return saveOpportunityAction(context.membership.organization_id, user.id, body.action, body)
  }
  if (['operating_perimeter','authority_yield','prepare_launch','launch_telemetry','confidence_bond','settle_confidence_bond','accept_attention','counterfactual_outcome'].includes(body?.action)) {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return saveExecutionAction(context.membership.organization_id, user.id, body.action, body)
  }
  if (['product_attestation','structure','catastrophe','launch_tournament','review_effectiveness'].includes(body?.action)) {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return saveSovereigntyAction(context.membership.organization_id, body.action, body)
  }
  if (['compile_law','swarm_certification','immune_response','authority_clearing','proof_module','evidence_stream','enforcement_rehearsal','authority_decay'].includes(body?.action)) {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return saveImmuneSystemAction(context.membership.organization_id, body.action, body)
  }
  if (['privacy_passport','coordinate_transaction','counterparty_order','provider_swarm','causal_memory','customer_outcome_twin','runtime_receipt','capacity_reservation'].includes(body?.action)) {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return saveProofMarketAction(context.membership.organization_id, body.action, body)
  }
  if (['register_zk_verifier','verify_zk_proof','atomic_transaction','purpose_consent','proof_challenge','liability_attribution','unit_economics','customer_remedy','capacity_performance'].includes(body?.action)) {
    const context = await organizationContext(user); requireOrgAdmin(context)
    return saveAtomicAssuranceAction(context.membership.organization_id, body.action, body)
  }
  throw createError({ statusCode: 400, message: 'unknown_regulatory_action' })
})
