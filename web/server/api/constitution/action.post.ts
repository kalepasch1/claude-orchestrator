import { requireConnectorUser } from '../../utils/connectorFabric'
import { captureReleaseSnapshot, captureWorld, certifyAccessibility, createOutcomeWarranty, createProofEnvelope, grantTemporaryScopes, installCapabilityOffer, previewReleaseReplay, publishCapabilityOffer, resolveUniversalCommand, synthesizeCollectiveIntent } from '../../utils/executionConstitution'
import { compilePolicy, createContinuityCapsule, detectImmuneIncident, establishInstitution, issueSelectiveCredential, openInstitutionalCase, proposeTreasuryAllocation, recordCausalEvidence, runAdversarialJourneys } from '../../utils/constitutionalAutonomy'
import { assessInclusionRisk, attestExecutionSupplyChain, compileOrganizationalMemory, conveneRedTeamCourt, createOutcomeMarketContract, delegateAuthority, prepareEvidenceExchange, proposeFederationTrust, updateCausalTwin } from '../../utils/federationAssurance'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event); const body = await readBody<any>(event); const action = String(body?.action || ''); const values = body?.values || {}; let result: any
  if (action === 'command') return { command: await resolveUniversalCommand(user, String(values.command || '')) }
  if (action === 'proof') return { proof: await createProofEnvelope(user, values) }
  if (action === 'temporary_scopes') result = { grant: await grantTemporaryScopes(user, values) }
  else if (action === 'capture_world') result = { world: await captureWorld(user, String(values.label || 'Current organization world')) }
  else if (action === 'publish_offer') result = { offer: await publishCapabilityOffer(user, values) }
  else if (action === 'install_offer') result = { settlement: await installCapabilityOffer(user, String(values.offer_id || '')) }
  else if (action === 'collective_intent') result = { intent: await synthesizeCollectiveIntent(user, values) }
  else if (action === 'warranty') result = { warranty: await createOutcomeWarranty(user, values) }
  else if (action === 'accessibility_certification') result = { certification: await certifyAccessibility(user, String(values.deployment_url || getRequestURL(event).origin)) }
  else if (action === 'release_snapshot') result = { release: await captureReleaseSnapshot(user, String(values.label || 'Release checkpoint'), values.deployment_id) }
  else if (action === 'release_replay') result = { replay: await previewReleaseReplay(user, String(values.snapshot_id || '')) }
  else if (action === 'establish_institution') result = { institution: await establishInstitution(user, values) }
  else if (action === 'institutional_case') result = { case: await openInstitutionalCase(user, values) }
  else if (action === 'causal_evidence') result = { evidence: await recordCausalEvidence(user, values) }
  else if (action === 'treasury_proposal') result = { allocation: await proposeTreasuryAllocation(user, values) }
  else if (action === 'selective_credential') result = { credential: await issueSelectiveCredential(user, values) }
  else if (action === 'immune_incident') result = { incident: await detectImmuneIncident(user, values) }
  else if (action === 'compile_policy') result = { policy: await compilePolicy(user, values) }
  else if (action === 'continuity_capsule') result = { capsule: await createContinuityCapsule(user, values) }
  else if (action === 'adversarial_journeys') result = { journey: await runAdversarialJourneys(user, values) }
  else if (action === 'federation_trust') result = { trust: await proposeFederationTrust(user, values) }
  else if (action === 'federated_exchange') result = { exchange: await prepareEvidenceExchange(user, values) }
  else if (action === 'causal_twin_update') result = { twin: await updateCausalTwin(user) }
  else if (action === 'supply_chain_attestation') result = { attestation: await attestExecutionSupplyChain(user) }
  else if (action === 'delegate_authority') result = { delegation: await delegateAuthority(user, values) }
  else if (action === 'outcome_market_contract') result = { contract: await createOutcomeMarketContract(user, values) }
  else if (action === 'compile_memory') result = { memory: await compileOrganizationalMemory(user) }
  else if (action === 'inclusion_assessment') result = { assessment: await assessInclusionRisk(user, values) }
  else if (action === 'red_team_court') result = { court: await conveneRedTeamCourt(user, values) }
  else throw createError({ statusCode: 400, message: 'unsupported_constitution_action' })
  const proof = await createProofEnvelope(user, { action_type: `constitution:${action}`, intent: `${action.replaceAll('_',' ')}: ${String(values.label || values.title || values.objective || values.purpose || 'organizational capability')}`, domain: action === 'warranty' ? 'billing' : 'users_access' })
  return { ...result, execution_proof: { id: proof.id, digest: proof.proof_digest, status: proof.status } }
})
