import { serviceClient } from '../../utils/fleetSupabase'
import { requireConnectorUser } from '../../utils/connectorFabric'
import { dialectFor, isCredentialReference, mapConnectorToProvider, maskSource } from '../../utils/dbSteering'

/**
 * Register (or re-register) a database source by REFERENCE. Body:
 *   { provider, label, project?, ref, region?, config?, connector_account_id? | credential_ref? }
 * `provider` accepts a runner id (aws_rds) or a connector id (aws-rds; aurora:true → aws_aurora).
 * Exactly one of connector_account_id / credential_ref may be given (neither is fine for
 * supabase, which the runner reaches with the fleet Management API token). A credential_ref
 * must name where a secret lives — env:, keychain:, doppler:, onepassword:, vault:, file: —
 * and is refused when it carries a user:pass@ URL, because a DSN is a value, not a reference.
 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export default defineEventHandler(async (event) => {
  const user = await requireConnectorUser(event); const body = await readBody<any>(event) || {}
  const provider = mapConnectorToProvider(String(body.provider || ''), { aurora: body.aurora === true })
  if (!provider) throw createError({ statusCode: 422, message: 'valid_provider_required' })
  const ref = String(body.ref || '').trim(); if (!ref || ref.length > 300) throw createError({ statusCode: 422, message: 'ref_required' })
  if (/:\/\/[^/\s]*:[^/\s]*@/.test(ref)) throw createError({ statusCode: 422, message: 'ref_must_not_contain_credentials' })
  const label = String(body.label || ref).trim().slice(0, 120); const project = body.project ? String(body.project).trim().slice(0, 120) : null
  const region = body.region ? String(body.region).trim().slice(0, 80) : null
  const config = body.config && typeof body.config === 'object' && !Array.isArray(body.config) ? body.config : {}
  for (const key of Object.keys(config)) if (/password|secret|token|private|dsn|service_account/i.test(key)) throw createError({ statusCode: 422, message: `config_must_not_carry_secrets:${key}` })
  const accountId = body.connector_account_id ? String(body.connector_account_id).trim() : ''; const givenRef = body.credential_ref ? String(body.credential_ref).trim() : ''
  if (accountId && givenRef) throw createError({ statusCode: 422, message: 'one_credential_source_only' })
  if (!accountId && !givenRef && provider !== 'supabase') throw createError({ statusCode: 422, message: 'credential_reference_required' })
  let credential_ref: string | null = null
  if (accountId) {
    if (!UUID.test(accountId)) throw createError({ statusCode: 422, message: 'valid_connector_account_id_required' })
    const { data: account, error } = await serviceClient().from('connector_accounts').select('id,user_id,provider').eq('id', accountId).eq('user_id', user.id).maybeSingle()
    if (error) throw createError({ statusCode: 500, message: 'connector_account_lookup_failed' })
    if (!account) throw createError({ statusCode: 404, message: 'connector_account_not_found' })
    credential_ref = `vault:${account.id}`
  } else if (givenRef) {
    if (!isCredentialReference(givenRef)) throw createError({ statusCode: 422, message: 'credential_must_be_a_reference' })
    credential_ref = givenRef.slice(0, 500)
  }
  const now = new Date().toISOString()
  const { data, error } = await serviceClient().from('db_sources').upsert({ provider, dialect: dialectFor(provider, config), ref, label, project, region, config, credential_ref, discovered_via: 'web_connector', status: 'active', enabled: true, updated_at: now }, { onConflict: 'provider,ref' }).select('id,project,label,provider,dialect,ref,region,credential_ref,config,discovered_via,status,enabled,last_scan_at,last_ok_at,last_error,created_at,updated_at').single()
  if (error) throw createError({ statusCode: 500, message: 'db_source_persistence_failed' })
  return { ok: true, source: maskSource(data) }
})
