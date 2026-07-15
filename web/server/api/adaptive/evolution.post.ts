import { requireConnectorUser } from '../../utils/connectorFabric'
import { issueFederatedCredential, recordSkillEvidence, simulateInterfaceTwin, updateEvolutionPreferences } from '../../utils/capabilityEvolution'
export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event); const body = await readBody<any>(event); const action = String(body?.action || '')
  if (action === 'simulate_interface') return { simulation: await simulateInterfaceTwin(user, String(body.objective || 'operate')) }
  if (action === 'update_privacy') return { privacy: await updateEvolutionPreferences(user, 'privacy', body.values || {}) }
  if (action === 'update_accessibility') return { accessibility: await updateEvolutionPreferences(user, 'accessibility', body.values || {}) }
  if (action === 'record_skill') return { evidence: await recordSkillEvidence(user, body.values || {}) }
  if (action === 'issue_federated_credential') return { credential: await issueFederatedCredential(user, body.values || {}) }
  throw createError({ statusCode: 400, message: 'unsupported_evolution_action' })
})
