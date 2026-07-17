import { timingSafeEqual } from 'node:crypto'
import { runtimeAgreementPolicy, runtimeFeaturePolicy, recordRuntimeEvidence, measureRuntimeObligation } from '../../../utils/regulatoryTemporal'
import { recordAuthoritySource, runtimeDeploymentGate } from '../../../utils/regulatoryFrontier'
import { recordRegulatoryFeedback } from '../../../utils/regulatoryOpportunity'
import { saveExecutionAction } from '../../../utils/regulatoryExecution'
import { saveSovereigntyAction } from '../../../utils/regulatorySovereignty'
import { saveImmuneSystemAction } from '../../../utils/regulatoryImmuneSystem'
import { saveProofMarketAction } from '../../../utils/regulatoryProofMarket'
import { saveAtomicAssuranceAction } from '../../../utils/regulatoryAtomicAssurance'

function authorized(event: any) {
  const expected = Buffer.from(process.env.FLEET_SHARED_SECRET || '')
  const supplied = Buffer.from(getRequestHeader(event, 'x-fleet-secret') || '')
  return expected.length > 0 && supplied.length === expected.length && timingSafeEqual(supplied, expected)
}

export default defineEventHandler(async event => {
  if (!authorized(event)) throw createError({ statusCode: 401, message: 'fleet_authorization_required' })
  const body = await readBody<any>(event)
  const organizationId = String(body?.organization_id || '')
  if (!organizationId) throw createError({ statusCode: 400, message: 'organization_id_required' })
  if (body.action === 'feature_policy') return runtimeFeaturePolicy(organizationId, body)
  if (body.action === 'agreement_policy') return runtimeAgreementPolicy(organizationId, body)
  if (body.action === 'evidence') return recordRuntimeEvidence(organizationId, body)
  if (body.action === 'obligation') return measureRuntimeObligation(organizationId, body)
  if (body.action === 'deployment_gate') return runtimeDeploymentGate(organizationId, body)
  if (body.action === 'authority_source') return recordAuthoritySource(organizationId, body)
  if (body.action === 'feedback_outcome') return recordRegulatoryFeedback(organizationId, body)
  if (body.action === 'launch_telemetry') return saveExecutionAction(organizationId, '00000000-0000-0000-0000-000000000000', 'launch_telemetry', { ...body, explicit_approval: false })
  if (body.action === 'product_attestation') return saveSovereigntyAction(organizationId, 'product_attestation', body)
  if (body.action === 'immune_response') return saveImmuneSystemAction(organizationId, 'immune_response', body)
  if (body.action === 'compile_law') return saveImmuneSystemAction(organizationId, 'compile_law', body)
  if (body.action === 'coordinate_transaction') return saveProofMarketAction(organizationId, 'coordinate_transaction', body)
  if (body.action === 'runtime_receipt') return saveProofMarketAction(organizationId, 'runtime_receipt', body)
  if (body.action === 'customer_outcome_twin') return saveProofMarketAction(organizationId, 'customer_outcome_twin', body)
  if (body.action === 'atomic_transaction') return saveAtomicAssuranceAction(organizationId, 'atomic_transaction', body)
  if (body.action === 'verify_zk_proof') return saveAtomicAssuranceAction(organizationId, 'verify_zk_proof', body)
  if (body.action === 'capacity_performance') return saveAtomicAssuranceAction(organizationId, 'capacity_performance', body)
  throw createError({ statusCode: 400, message: 'unknown_regulatory_runtime_action' })
})
