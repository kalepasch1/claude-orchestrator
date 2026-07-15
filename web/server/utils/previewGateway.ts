import { PREVIEW_TARGETS } from '../../config/previewTargets'

export function gatewayTarget(app: string, rawPath = '', search = '') {
  const configured = PREVIEW_TARGETS[app]?.url
  if (!configured) return null
  const safePath = rawPath.split('/').filter(Boolean).map(segment => encodeURIComponent(decodeURIComponent(segment))).join('/')
  const target = new URL(safePath, `${configured.replace(/\/$/, '')}/`)
  target.search = search
  if (target.origin !== new URL(configured).origin) return null
  return target
}

export function rewriteGatewayHtml(html: string, app: string, target: URL) {
  const gatewayRoot = `/api/previews/gateway/${encodeURIComponent(app)}/`
  const withoutPolicies = html
    .replace(/<meta[^>]+http-equiv=["'](?:content-security-policy|x-frame-options)["'][^>]*>/gi, '')
    .replace(/(<(?:a|link|script|img|source|form)[^>]+(?:href|src|action)=)["']\//gi, `$1"${gatewayRoot}`)
  const base = `<base href="${gatewayRoot}"><meta name="madeus-preview-source" content="${target.origin}">`
  return /<head[^>]*>/i.test(withoutPolicies) ? withoutPolicies.replace(/<head([^>]*)>/i, `<head$1>${base}`) : `${base}${withoutPolicies}`
}

export function framePolicyAllows(policy: string, xFrame: string, parentOrigin: string, targetOrigin: string) {
  const normalizedFrame = xFrame.toLowerCase()
  if (normalizedFrame === 'deny' || (normalizedFrame === 'sameorigin' && parentOrigin !== targetOrigin)) return false
  const directive = policy.split(';').map(value => value.trim()).find(value => value.toLowerCase().startsWith('frame-ancestors'))
  if (!directive) return true
  const sources = directive.split(/\s+/).slice(1)
  if (sources.includes("'none'")) return false
  if (sources.includes('*') || sources.includes(parentOrigin)) return true
  if (sources.includes("'self'") && parentOrigin === targetOrigin) return true
  return sources.some(source => source.startsWith('https://*.') && new URL(parentOrigin).hostname.endsWith(source.slice('https://*'.length)))
}
