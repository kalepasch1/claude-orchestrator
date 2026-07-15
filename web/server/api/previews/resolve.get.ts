import { isDurablePreviewUrl, previewEnvironmentKey, resolvePreviewTarget } from '~/config/previewTargets'
import { requireConnectorUser } from '../../utils/connectorFabric'

function ancestorAllows(policy: string, parentOrigin: string, targetOrigin: string) {
  const directive = policy.split(';').map(value => value.trim()).find(value => value.toLowerCase().startsWith('frame-ancestors'))
  if (!directive) return true
  const sources = directive.split(/\s+/).slice(1)
  if (sources.includes("'none'")) return false
  if (sources.includes('*')) return true
  if (sources.includes("'self'") && parentOrigin === targetOrigin) return true
  if (sources.includes(parentOrigin)) return true
  return sources.some(source => {
    if (!source.startsWith('https://*.')) return false
    const suffix = source.slice('https://*'.length)
    try { return new URL(parentOrigin).hostname.endsWith(suffix) } catch { return false }
  })
}

export default defineEventHandler(async event => {
  await requireConnectorUser(event)
  const app = String(getQuery(event).app || '').toLowerCase()
  const configured = process.env[previewEnvironmentKey(app)]
  // The checked-in durable alias is authoritative. Legacy environment values
  // have repeatedly pointed at pruned Vercel deployments and must not override
  // an app's verified production domain.
  const target = resolvePreviewTarget(app, configured)
  if (!target || !isDurablePreviewUrl(target)) throw createError({ statusCode: 404, message: 'preview_target_not_configured' })

  const parentOrigin = getRequestURL(event).origin
  // Some fleet applications correctly reject obvious bot/curl user agents.
  // The resolver validates the same public document a real browser will load,
  // so identify as the Madeus browser preview rather than a synthetic crawler.
  const previewHeaders = { 'user-agent': 'Mozilla/5.0 (compatible; MadeusBrowserPreview/1.0; +https://www.madeus.cc)' }
  let response: Response
  try {
    response = await fetch(target, { method: 'HEAD', redirect: 'follow', signal: AbortSignal.timeout(8_000), headers: previewHeaders })
    if (response.status === 405) response = await fetch(target, { method: 'GET', redirect: 'follow', signal: AbortSignal.timeout(8_000), headers: { ...previewHeaders, range: 'bytes=0-0' } })
  } catch {
    return { app, available: false, embeddable: false, url: null, external_url: target, reason: 'The live application did not respond. Madeus withheld the broken embed.' }
  }

  if (!response.ok) return { app, available: false, embeddable: false, url: null, external_url: target, status: response.status, reason: `The live application returned HTTP ${response.status}. Madeus withheld the broken embed.` }

  const finalUrl = response.url || target
  const targetOrigin = new URL(finalUrl).origin
  const xFrame = String(response.headers.get('x-frame-options') || '').toLowerCase()
  const policy = String(response.headers.get('content-security-policy') || '')
  const frameAllowed = xFrame !== 'deny' && !(xFrame === 'sameorigin' && parentOrigin !== targetOrigin) && ancestorAllows(policy, parentOrigin, targetOrigin)
  return {
    app,
    available: true,
    embeddable: frameAllowed,
    url: frameAllowed ? finalUrl : null,
    external_url: finalUrl,
    mode: 'verified-production',
    reason: frameAllowed ? 'Verified live production alias.' : 'The application is live but its security policy requires opening it in a separate tab.',
  }
})
