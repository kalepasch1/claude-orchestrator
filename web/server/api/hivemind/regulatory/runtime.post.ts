import { timingSafeEqual } from 'node:crypto'
import { runtimeAgreementPolicy, runtimeFeaturePolicy, recordRuntimeEvidence, measureRuntimeObligation } from '../../../utils/regulatoryTemporal'

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
  throw createError({ statusCode: 400, message: 'unknown_regulatory_runtime_action' })
})
