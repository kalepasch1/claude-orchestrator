import { CONNECTOR_BY_ID } from '~/config/connectors'
import { organizationContext } from '../../utils/adaptiveFabric'
import { auditConnector, encryptSecret, hashState, requireConnectorUser, safeAccount } from '../../utils/connectorFabric'
import { serviceClient } from '../../utils/fleetSupabase'

export default defineEventHandler(async (event) => {
  const user = await requireConnectorUser(event); const body = await readBody<any>(event); const definition = CONNECTOR_BY_ID[body?.provider]
  if (!definition || !['api-key','service-account'].includes(definition.auth)) throw createError({ statusCode: 400, message: 'valid_provider_required' })
  const credentialFields = definition.credentialFields || []; const credentials = body?.credentials && typeof body.credentials === 'object' ? body.credentials : null
  const credentialRef = String(body?.credential_ref || '').trim(); const brokered = credentialRef.length >= 8
  let secret = typeof body.secret === 'string' ? body.secret : ''
  if (brokered) {
    if (!process.env.CONNECTOR_CREDENTIAL_BROKER_URL || !process.env.CONNECTOR_CREDENTIAL_BROKER_PUBLIC_KEY) throw createError({ statusCode: 503, message: 'credential_broker_not_configured' })
    secret = JSON.stringify({ credential_ref: credentialRef })
  } else if (credentialFields.length) {
    const missing = credentialFields.filter(field => field.required && !String(credentials?.[field.key] || '').trim()).map(field => field.key)
    if (missing.length) throw createError({ statusCode: 422, message: `missing_connector_credentials:${missing.join(',')}` })
    for (const field of credentialFields) if (field.options?.length && credentials?.[field.key] && !field.options.includes(credentials[field.key])) throw createError({ statusCode: 422, message: `invalid_connector_credential:${field.key}` })
    secret = JSON.stringify(Object.fromEntries(credentialFields.map(field => [field.key, String(credentials?.[field.key] || '').trim()])))
  }
  if (secret.length < 12) throw createError({ statusCode: 400, message: 'valid_provider_secret_required' })
  const context = await organizationContext(user); const label = String(body.label || 'Primary').slice(0, 80); const environment = String(credentials?.environment || body.environment || 'sandbox')
  if (!['sandbox','production'].includes(environment)) throw createError({ statusCode: 422, message: 'valid_connector_environment_required' })
  const metadata = { credential_type: brokered ? 'hsm_ref' : credentialFields.length ? 'credential_bundle' : 'api_key', credential_ref: brokered ? credentialRef : undefined, credential_fields: brokered ? [] : credentialFields.map(field => field.key), secret_last_four: credentialFields.length || brokered ? undefined : secret.slice(-4), token_type: 'Bearer', max_lease_seconds: brokered ? 900 : undefined }
  const { data, error } = await serviceClient().from('connector_accounts').upsert({ organization_id: context.membership.organization_id, user_id: user.id, provider: definition.id, kind: definition.kind, label, status: 'connected', environment, scopes: definition.defaultScopes, token_audience: definition.tokenAudience, access_token_ciphertext: brokered ? `hsm-ref:${hashState(credentialRef)}` : encryptSecret(secret), metadata, updated_at: new Date().toISOString() }, { onConflict: 'user_id,provider,label' }).select().single()
  if (error) throw createError({ statusCode: 500, message: 'credential_persistence_failed' })
  await auditConnector(user.id, definition.id, brokered ? 'hsm_credential_reference_connected' : 'credential_connected', 'success', definition.defaultScopes, definition.tokenAudience, data.id, { organization_id: context.membership.organization_id, environment, credential_mode: brokered ? 'short_lived_lease' : 'encrypted_static' })
  return { account: safeAccount(data) }
})
