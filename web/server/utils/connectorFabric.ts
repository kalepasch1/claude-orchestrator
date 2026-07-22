import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto'
import { serverSupabaseUser } from '#supabase/server'
import type { H3Event } from 'h3'
import { CONNECTOR_BY_ID } from '~/config/connectors'
import { serviceClient } from './fleetSupabase'
import { resolveDelegatedProvider } from './adaptiveFabric'

type OAuthConfig = { authorize: string; token: string; clientEnv: string; secretEnv?: string; extra?: Record<string, string>; tokenEncoding?: 'form' | 'json'; basicAuth?: boolean }
const OAUTH_CONFIG: Record<string, OAuthConfig> = {
  google: { authorize: 'https://accounts.google.com/o/oauth2/v2/auth', token: 'https://oauth2.googleapis.com/token', clientEnv: 'GOOGLE_CONNECTOR_CLIENT_ID', secretEnv: 'GOOGLE_CONNECTOR_CLIENT_SECRET', extra: { access_type: 'offline', prompt: 'consent' } },
  microsoft: { authorize: 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize', token: 'https://login.microsoftonline.com/common/oauth2/v2.0/token', clientEnv: 'MICROSOFT_CONNECTOR_CLIENT_ID', secretEnv: 'MICROSOFT_CONNECTOR_CLIENT_SECRET' },
  github: { authorize: 'https://github.com/login/oauth/authorize', token: 'https://github.com/login/oauth/access_token', clientEnv: 'GITHUB_CONNECTOR_CLIENT_ID', secretEnv: 'GITHUB_CONNECTOR_CLIENT_SECRET' },
  slack: { authorize: 'https://slack.com/oauth/v2/authorize', token: 'https://slack.com/api/oauth.v2.access', clientEnv: 'SLACK_CONNECTOR_CLIENT_ID', secretEnv: 'SLACK_CONNECTOR_CLIENT_SECRET' },
  atlassian: { authorize: 'https://auth.atlassian.com/authorize', token: 'https://auth.atlassian.com/oauth/token', clientEnv: 'ATLASSIAN_CONNECTOR_CLIENT_ID', secretEnv: 'ATLASSIAN_CONNECTOR_CLIENT_SECRET', extra: { audience: 'api.atlassian.com' }, tokenEncoding: 'json' },
  notion: { authorize: 'https://api.notion.com/v1/oauth/authorize', token: 'https://api.notion.com/v1/oauth/token', clientEnv: 'NOTION_CONNECTOR_CLIENT_ID', secretEnv: 'NOTION_CONNECTOR_CLIENT_SECRET', basicAuth: true },
  figma: { authorize: 'https://www.figma.com/oauth', token: 'https://api.figma.com/v1/oauth/token', clientEnv: 'FIGMA_CONNECTOR_CLIENT_ID', secretEnv: 'FIGMA_CONNECTOR_CLIENT_SECRET', basicAuth: true },
  canva: { authorize: 'https://www.canva.com/api/oauth/authorize', token: 'https://api.canva.com/rest/v1/oauth/token', clientEnv: 'CANVA_CONNECTOR_CLIENT_ID', secretEnv: 'CANVA_CONNECTOR_CLIENT_SECRET', basicAuth: true },
  miro: { authorize: 'https://miro.com/oauth/authorize', token: 'https://api.miro.com/v1/oauth/token', clientEnv: 'MIRO_CONNECTOR_CLIENT_ID', secretEnv: 'MIRO_CONNECTOR_CLIENT_SECRET' },
  webflow: { authorize: 'https://webflow.com/oauth/authorize', token: 'https://api.webflow.com/oauth/access_token', clientEnv: 'WEBFLOW_CONNECTOR_CLIENT_ID', secretEnv: 'WEBFLOW_CONNECTOR_CLIENT_SECRET' },
}

function vaultKey() {
  const raw = process.env.CONNECTOR_VAULT_KEY || ''
  if (!raw) throw createError({ statusCode: 503, message: 'connector_vault_not_configured' })
  return createHash('sha256').update(raw).digest()
}
export function encryptSecret(value: string) { const iv = randomBytes(12); const cipher = createCipheriv('aes-256-gcm', vaultKey(), iv); const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]); return [iv.toString('base64url'), cipher.getAuthTag().toString('base64url'), encrypted.toString('base64url')].join('.') }
export function decryptSecret(value: string) { const [iv, tag, body] = value.split('.'); const decipher = createDecipheriv('aes-256-gcm', vaultKey(), Buffer.from(iv, 'base64url')); decipher.setAuthTag(Buffer.from(tag, 'base64url')); return Buffer.concat([decipher.update(Buffer.from(body, 'base64url')), decipher.final()]).toString('utf8') }
export function hashState(value: string) { return createHash('sha256').update(value).digest('hex') }
export function pkceChallenge(verifier: string) { return createHash('sha256').update(verifier).digest('base64url') }

export async function requireConnectorUser(event: H3Event) { const user = await serverSupabaseUser(event); if (!user) throw createError({ statusCode: 401, message: 'authentication_required' }); return user }
export function providerConfigured(provider: string) { const definition = CONNECTOR_BY_ID[provider]; if (['api-key','service-account'].includes(String(definition?.auth)) || provider === 'remote-mcp') return !!process.env.CONNECTOR_VAULT_KEY||!!(process.env.CONNECTOR_CREDENTIAL_BROKER_URL&&process.env.CONNECTOR_CREDENTIAL_BROKER_PUBLIC_KEY&&process.env.CONNECTOR_CREDENTIAL_BROKER_TOKEN); const config = OAUTH_CONFIG[provider]; return !!(config && process.env[config.clientEnv] && process.env.CONNECTOR_VAULT_KEY) }
export function safeAccount(row: any) { const { access_token_ciphertext, refresh_token_ciphertext, ...safe } = row; return { ...safe, has_access_token: !!access_token_ciphertext, has_refresh_token: !!refresh_token_ciphertext } }

export async function beginOAuth(event: H3Event, provider: string, scopes: string[], resource?: string) {
  const user = await requireConnectorUser(event); const definition = CONNECTOR_BY_ID[provider]; const config = OAUTH_CONFIG[provider]
  if (!definition || !config) throw createError({ statusCode: 400, message: 'provider_does_not_support_oauth' })
  const delegated = await resolveDelegatedProvider(user.id, provider); const clientId = delegated?.client_id || process.env[config.clientEnv]; if (!clientId) throw createError({ statusCode: 503, message: 'provider_oauth_not_configured' })
  const origin = getRequestURL(event).origin; const redirectUri = `${origin}/api/connectors/oauth/callback`; const state = randomBytes(32).toString('base64url'); const verifier = randomBytes(48).toString('base64url')
  const requested = [...new Set([...(definition.defaultScopes || []), ...scopes])]
  const sb = serviceClient(); const { error } = await sb.from('connector_oauth_states').insert({ state_hash: hashState(state), user_id: user.id, provider, verifier_ciphertext: encryptSecret(verifier), redirect_uri: redirectUri, requested_scopes: requested, resource: resource || definition.tokenAudience, expires_at: new Date(Date.now() + 10 * 60_000).toISOString() })
  if (error) throw createError({ statusCode: 500, message: 'oauth_state_persistence_failed' })
  const params = new URLSearchParams({ response_type: 'code', client_id: clientId, redirect_uri: redirectUri, state, code_challenge: pkceChallenge(verifier), code_challenge_method: 'S256', scope: requested.join(' '), ...config.extra })
  if (resource) params.set('resource', resource)
  return { authorization_url: `${config.authorize}?${params}`, expires_in: 600, provider, scopes: requested }
}

export async function exchangeOAuth(event: H3Event, state: string, code: string) {
  const sb = serviceClient(); const stateHash = hashState(state); const { data: pending } = await sb.from('connector_oauth_states').select('*').eq('state_hash', stateHash).is('consumed_at', null).gt('expires_at', new Date().toISOString()).maybeSingle()
  if (!pending) throw createError({ statusCode: 400, message: 'invalid_or_expired_oauth_state' })
  const mcpId = String(pending.provider).startsWith('mcp:') ? String(pending.provider).slice(4) : ''
  const { data: mcp } = mcpId ? await sb.from('connector_mcp_servers').select('*').eq('id', mcpId).eq('user_id', pending.user_id).maybeSingle() : { data: null }
  const mcpMetadata: any = mcp?.metadata || {}
  const config: OAuthConfig = mcp ? { authorize: mcpMetadata.authorization_endpoint, token: mcpMetadata.token_endpoint, clientEnv: '' } : OAUTH_CONFIG[pending.provider]
  if (!config?.token) throw createError({ statusCode: 400, message: 'oauth_provider_metadata_unavailable' })
  const delegated = !mcp ? await resolveDelegatedProvider(pending.user_id, pending.provider) : null
  const clientId = mcp ? mcpMetadata.client_id : (delegated?.client_id || process.env[config.clientEnv] || '')
  const clientSecret = mcp ? (mcpMetadata.client_secret_ciphertext ? decryptSecret(mcpMetadata.client_secret_ciphertext) : undefined) : (delegated?.client_secret_ciphertext ? decryptSecret(delegated.client_secret_ciphertext) : (config.secretEnv ? process.env[config.secretEnv] : undefined))
  const body: Record<string, string> = { grant_type: 'authorization_code', code, redirect_uri: pending.redirect_uri, client_id: clientId, code_verifier: decryptSecret(pending.verifier_ciphertext) }; if (clientSecret) body.client_secret = clientSecret; if (pending.resource) body.resource = pending.resource
  const headers: Record<string, string> = { accept: 'application/json', 'content-type': config.tokenEncoding === 'json' ? 'application/json' : 'application/x-www-form-urlencoded' }
  if (config.basicAuth && clientSecret) { headers.authorization = `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString('base64')}`; delete body.client_secret }
  const token: any = await $fetch(config.token, { method: 'POST', body: config.tokenEncoding === 'json' ? body : new URLSearchParams(body), headers })
  if (!token?.access_token) throw createError({ statusCode: 502, message: 'provider_token_exchange_failed' })
  const expiresAt = token.expires_in ? new Date(Date.now() + Number(token.expires_in) * 1000).toISOString() : null
  const provider = mcp ? 'remote-mcp' : pending.provider
  const label = mcp?.name || token.team?.name || token.workspace_name || 'Primary'
  const { data, error } = await sb.from('connector_accounts').upsert({ user_id: pending.user_id, provider, kind: mcp ? 'remote-mcp' : 'saas-oauth', label, status: 'connected', scopes: pending.requested_scopes, token_audience: pending.resource, access_token_ciphertext: encryptSecret(token.access_token), refresh_token_ciphertext: token.refresh_token ? encryptSecret(token.refresh_token) : null, expires_at: expiresAt, metadata: { token_type: token.token_type || 'Bearer', ...(mcp ? { mcp_server_id: mcp.id, server_url: mcp.server_url } : {}) }, updated_at: new Date().toISOString() }, { onConflict: 'user_id,provider,label' }).select().single()
  if (error) throw createError({ statusCode: 500, message: 'connector_account_persistence_failed' })
  await sb.from('connector_oauth_states').update({ consumed_at: new Date().toISOString() }).eq('state_hash', stateHash)
  if (mcp) await sb.from('connector_mcp_servers').update({ status: 'connected' }).eq('id', mcp.id)
  await auditConnector(pending.user_id, provider, 'oauth_connected', 'success', pending.requested_scopes, pending.resource, data.id)
  return safeAccount(data)
}

function assertPublicHttps(raw: string) {
  let url: URL
  try { url = new URL(raw) } catch { throw createError({ statusCode: 400, message: 'valid_mcp_url_required' }) }
  if (url.protocol !== 'https:' || url.username || url.password) throw createError({ statusCode: 400, message: 'mcp_url_must_be_public_https' })
  const host = url.hostname.toLowerCase()
  if (host === 'localhost' || host.endsWith('.local') || host === '::1' || /^127\./.test(host) || /^10\./.test(host) || /^192\.168\./.test(host) || /^169\.254\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)) throw createError({ statusCode: 400, message: 'private_mcp_hosts_are_not_allowed' })
  return url
}

export async function discoverMcp(event: H3Event, name: string, rawServerUrl: string) {
  const user = await requireConnectorUser(event); const serverUrl = assertPublicHttps(rawServerUrl); const canonicalResource = serverUrl.toString().replace(/\/$/, '')
  const resourceMetaUrl = new URL('/.well-known/oauth-protected-resource', serverUrl.origin); if (serverUrl.pathname !== '/') resourceMetaUrl.pathname += serverUrl.pathname
  const resource: any = await $fetch(resourceMetaUrl.toString(), { headers: { accept: 'application/json' } }).catch(() => null)
  const issuer = resource?.authorization_servers?.[0]
  if (!issuer) throw createError({ statusCode: 422, message: 'mcp_protected_resource_metadata_missing' })
  const issuerUrl = assertPublicHttps(issuer); const authMetaUrl = new URL('/.well-known/oauth-authorization-server', issuerUrl)
  const auth: any = await $fetch(authMetaUrl.toString(), { headers: { accept: 'application/json' } }).catch(() => null)
  if (!auth?.authorization_endpoint || !auth?.token_endpoint) throw createError({ statusCode: 422, message: 'mcp_authorization_metadata_missing' })
  assertPublicHttps(auth.authorization_endpoint); assertPublicHttps(auth.token_endpoint)
  const origin = getRequestURL(event).origin; const redirectUri = `${origin}/api/connectors/oauth/callback`
  let clientId = process.env.MCP_CONNECTOR_CLIENT_ID || ''; let clientSecret = process.env.MCP_CONNECTOR_CLIENT_SECRET || ''
  if (!clientId && auth.registration_endpoint) {
    assertPublicHttps(auth.registration_endpoint)
    const registration: any = await $fetch(auth.registration_endpoint, { method: 'POST', body: { client_name: 'Madeus Orchestrator', redirect_uris: [redirectUri], grant_types: ['authorization_code', 'refresh_token'], response_types: ['code'], token_endpoint_auth_method: 'none' }, headers: { accept: 'application/json' } })
    clientId = registration?.client_id || ''; clientSecret = registration?.client_secret || ''
  }
  if (!clientId) throw createError({ statusCode: 422, message: 'mcp_client_registration_unavailable' })
  const metadata = { authorization_endpoint: auth.authorization_endpoint, token_endpoint: auth.token_endpoint, scopes_supported: auth.scopes_supported || resource.scopes_supported || [], client_id: clientId, ...(clientSecret ? { client_secret_ciphertext: encryptSecret(clientSecret) } : {}) }
  const { data, error } = await serviceClient().from('connector_mcp_servers').upsert({ user_id: user.id, name: String(name || serverUrl.hostname).slice(0, 100), server_url: serverUrl.toString(), canonical_resource: resource.resource || canonicalResource, authorization_server: issuer, status: 'discovered', metadata }, { onConflict: 'user_id,canonical_resource' }).select().single()
  if (error) throw createError({ statusCode: 500, message: 'mcp_discovery_persistence_failed' })
  await auditConnector(user.id, 'remote-mcp', 'server_discovered', 'success', [], data.canonical_resource, undefined, { server_id: data.id })
  return { server: { id: data.id, name: data.name, server_url: data.server_url, resource: data.canonical_resource, scopes_supported: metadata.scopes_supported } }
}

export async function beginMcpOAuth(event: H3Event, serverId: string, scopes: string[]) {
  const user = await requireConnectorUser(event); const sb = serviceClient(); const { data: server } = await sb.from('connector_mcp_servers').select('*').eq('id', serverId).eq('user_id', user.id).maybeSingle()
  if (!server) throw createError({ statusCode: 404, message: 'mcp_server_not_found' })
  const metadata: any = server.metadata || {}; const requested = [...new Set(scopes.filter((scope: string) => (metadata.scopes_supported || []).includes(scope)))]
  const origin = getRequestURL(event).origin; const redirectUri = `${origin}/api/connectors/oauth/callback`; const state = randomBytes(32).toString('base64url'); const verifier = randomBytes(48).toString('base64url')
  const { error } = await sb.from('connector_oauth_states').insert({ state_hash: hashState(state), user_id: user.id, provider: `mcp:${server.id}`, verifier_ciphertext: encryptSecret(verifier), redirect_uri: redirectUri, requested_scopes: requested, resource: server.canonical_resource, expires_at: new Date(Date.now() + 10 * 60_000).toISOString() })
  if (error) throw createError({ statusCode: 500, message: 'oauth_state_persistence_failed' })
  const params = new URLSearchParams({ response_type: 'code', client_id: metadata.client_id, redirect_uri: redirectUri, state, code_challenge: pkceChallenge(verifier), code_challenge_method: 'S256', resource: server.canonical_resource }); if (requested.length) params.set('scope', requested.join(' '))
  return { authorization_url: `${metadata.authorization_endpoint}?${params}`, expires_in: 600, scopes: requested }
}

export async function resolveConnectorCredential(userId: string, accountId: string, requestedScopes: string[] = [], audience?: string) {
  const sb = serviceClient(); let { data } = await sb.from('connector_accounts').select('*').eq('id', accountId).eq('user_id', userId).eq('status', 'connected').maybeSingle()
  if (!data || !data.access_token_ciphertext) throw createError({ statusCode: 404, message: 'connected_account_not_found' })
  if (data.expires_at && new Date(data.expires_at).getTime() <= Date.now() + 5 * 60_000 && data.refresh_token_ciphertext) data = await refreshConnectorAccount(userId, data.id)
  if (data.expires_at && new Date(data.expires_at).getTime() <= Date.now()) throw createError({ statusCode: 401, message: 'connector_credential_expired' })
  if (audience && data.token_audience !== audience) throw createError({ statusCode: 403, message: 'connector_audience_mismatch' })
  if (requestedScopes.some(scope => !data.scopes.includes(scope))) throw createError({ statusCode: 403, message: 'connector_scope_step_up_required' })
  await sb.from('connector_accounts').update({ last_used_at: new Date().toISOString() }).eq('id', data.id)
  await auditConnector(userId, data.provider, 'credential_resolved', 'success', requestedScopes, audience, data.id)
  return { token: decryptSecret(data.access_token_ciphertext), tokenType: data.metadata?.token_type || 'Bearer', provider: data.provider, metadata: data.metadata }
}

export async function refreshConnectorAccount(userId: string, accountId: string) {
  const sb = serviceClient(); const { data } = await sb.from('connector_accounts').select('*').eq('id', accountId).eq('user_id', userId).eq('status', 'connected').maybeSingle()
  if (!data?.refresh_token_ciphertext) throw createError({ statusCode: 409, message: 'connector_refresh_unavailable' })
  const config = OAUTH_CONFIG[data.provider]; if (!config?.token) throw createError({ statusCode: 409, message: 'provider_refresh_unsupported' })
  const delegated = await resolveDelegatedProvider(userId, data.provider); const clientId = delegated?.client_id || process.env[config.clientEnv] || ''; const clientSecret = delegated?.client_secret_ciphertext ? decryptSecret(delegated.client_secret_ciphertext) : (config.secretEnv ? process.env[config.secretEnv] : undefined)
  const body: Record<string, string> = { grant_type: 'refresh_token', refresh_token: decryptSecret(data.refresh_token_ciphertext), client_id: clientId }; if (clientSecret) body.client_secret = clientSecret
  const headers: Record<string, string> = { accept: 'application/json', 'content-type': config.tokenEncoding === 'json' ? 'application/json' : 'application/x-www-form-urlencoded' }; if (config.basicAuth && clientSecret) { headers.authorization = `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString('base64')}`; delete body.client_secret }
  try {
    const token: any = await $fetch(config.token, { method: 'POST', body: config.tokenEncoding === 'json' ? body : new URLSearchParams(body), headers }); if (!token?.access_token) throw new Error('missing_access_token')
    const expiresAt = token.expires_in ? new Date(Date.now() + Number(token.expires_in) * 1000).toISOString() : data.expires_at; const updates = { access_token_ciphertext: encryptSecret(token.access_token), refresh_token_ciphertext: token.refresh_token ? encryptSecret(token.refresh_token) : data.refresh_token_ciphertext, expires_at: expiresAt, updated_at: new Date().toISOString(), metadata: { ...(data.metadata || {}), token_type: token.token_type || data.metadata?.token_type || 'Bearer', last_refreshed_at: new Date().toISOString() } }
    const { data: refreshed, error } = await sb.from('connector_accounts').update(updates).eq('id', data.id).select().single(); if (error) throw error
    const { data: membership } = await sb.from('orchestrator_org_memberships').select('organization_id').eq('user_id', userId).eq('status', 'active').limit(1).maybeSingle(); await sb.from('connector_lifecycle_events').insert({ connector_account_id: data.id, organization_id: membership?.organization_id, provider: data.provider, event: 'refreshed', status: 'healthy', next_action_at: expiresAt ? new Date(new Date(expiresAt).getTime() - 10 * 60_000).toISOString() : null, metadata: { rotated_refresh_token: !!token.refresh_token } }); await auditConnector(userId, data.provider, 'credential_refreshed', 'success', data.scopes, data.token_audience, data.id); return refreshed
  } catch (error: any) { const { data: membership } = await sb.from('orchestrator_org_memberships').select('organization_id').eq('user_id', userId).eq('status', 'active').limit(1).maybeSingle(); await sb.from('connector_lifecycle_events').insert({ connector_account_id: data.id, organization_id: membership?.organization_id, provider: data.provider, event: 'refresh_failed', status: 'attention', next_action_at: new Date(Date.now() + 30 * 60_000).toISOString(), metadata: { reason: String(error?.data?.error || error?.message || 'provider_refresh_failed').slice(0, 160) } }); throw createError({ statusCode: 502, message: 'connector_refresh_failed' }) }
}

export async function inspectConnectorLifecycle(userId: string) {
  const sb = serviceClient(); const { data: accounts } = await sb.from('connector_accounts').select('*').eq('user_id', userId).eq('status', 'connected'); const { data: membership } = await sb.from('orchestrator_org_memberships').select('organization_id').eq('user_id', userId).eq('status', 'active').limit(1).maybeSingle(); const results: any[] = []
  for (const account of accounts || []) { const expires = account.expires_at ? new Date(account.expires_at).getTime() : null; const due = expires != null && expires <= Date.now() + 10 * 60_000; let status = expires == null ? 'non_expiring' : due ? 'expiring' : 'healthy'; if (due && account.refresh_token_ciphertext) { try { await refreshConnectorAccount(userId, account.id); status = 'refreshed' } catch { status = 'attention' } } else await sb.from('connector_lifecycle_events').insert({ connector_account_id: account.id, organization_id: membership?.organization_id, provider: account.provider, event: due ? 'expiring' : 'healthy', status, next_action_at: expires ? new Date(Math.max(Date.now(), expires - 10 * 60_000)).toISOString() : null, metadata: { automatic_refresh_available: !!account.refresh_token_ciphertext } }); results.push({ account_id: account.id, provider: account.provider, status, expires_at: account.expires_at, automatic_refresh: !!account.refresh_token_ciphertext }) }
  return results
}

export async function auditConnector(userId: string, provider: string, event: string, outcome: string, scopes: string[] = [], audience?: string, accountId?: string, metadata: any = {}) { await serviceClient().from('connector_audit_log').insert({ user_id: userId, connector_account_id: accountId, provider, event, outcome, scopes, audience, metadata }) }
