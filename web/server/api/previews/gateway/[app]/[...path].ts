import { requireConnectorUser } from '../../../../utils/connectorFabric'
import { gatewayTarget, rewriteGatewayHtml } from '../../../../utils/previewGateway'

export default defineEventHandler(async event => {
  await requireConnectorUser(event)
  const method = getMethod(event)
  if (!['GET', 'HEAD'].includes(method)) throw createError({ statusCode: 405, message: 'preview_gateway_read_only' })
  const app = String(getRouterParam(event, 'app') || '').toLowerCase()
  const path = String(getRouterParam(event, 'path') || '')
  const target = gatewayTarget(app, path, getRequestURL(event).search)
  if (!target) throw createError({ statusCode: 404, message: 'preview_target_not_configured' })

  const upstream = await fetch(target, {
    method,
    redirect: 'follow',
    signal: AbortSignal.timeout(12_000),
    headers: { 'user-agent': 'Mozilla/5.0 (compatible; MadeusSecurePreview/1.0; +https://www.madeus.cc)', accept: getHeader(event, 'accept') || '*/*' },
  }).catch(() => null)
  if (!upstream) throw createError({ statusCode: 502, message: 'preview_upstream_unavailable' })

  setResponseStatus(event, upstream.status)
  const contentType = upstream.headers.get('content-type') || 'application/octet-stream'
  setHeader(event, 'content-type', contentType)
  setHeader(event, 'cache-control', contentType.includes('text/html') ? 'private, no-store' : 'public, max-age=300')
  setHeader(event, 'x-madeus-preview-source', target.origin)
  setHeader(event, 'content-security-policy', "default-src * data: blob: 'unsafe-inline' 'unsafe-eval'; frame-ancestors 'self'")
  if (method === 'HEAD') return null
  if (contentType.includes('text/html')) return rewriteGatewayHtml(await upstream.text(), app, target)
  return new Uint8Array(await upstream.arrayBuffer())
})
