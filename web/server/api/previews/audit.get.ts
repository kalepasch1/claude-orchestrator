import { PREVIEW_TARGETS } from '~/config/previewTargets'
import { requireConnectorUser } from '../../utils/connectorFabric'
import { framePolicyAllows } from '../../utils/previewGateway'

export default defineEventHandler(async event => {
  await requireConnectorUser(event)
  const parentOrigin = getRequestURL(event).origin
  const checks = await Promise.all(Object.entries(PREVIEW_TARGETS).map(async ([app, target]) => {
    const checkedAt = new Date().toISOString()
    try {
      const response = await fetch(target.url, { method: 'HEAD', redirect: 'follow', signal: AbortSignal.timeout(8_000), headers: { 'user-agent': 'MadeusEmbedContract/1.0' } })
      const csp = response.headers.get('content-security-policy') || ''
      const xFrame = (response.headers.get('x-frame-options') || '').toLowerCase()
      const targetOrigin = new URL(response.url || target.url).origin
      const nativeEmbed = response.ok && framePolicyAllows(csp, xFrame, parentOrigin, targetOrigin)
      return { app, url: response.url || target.url, ok: response.ok, status: response.status, nativeEmbed, gatewayReady: response.ok, checkedAt, deploymentId: response.headers.get('x-vercel-id') }
    } catch (error: any) {
      return { app, url: target.url, ok: false, status: 0, nativeEmbed: false, gatewayReady: false, checkedAt, error: error?.message || 'unreachable' }
    }
  }))
  return { checkedAt: new Date().toISOString(), healthy: checks.filter(check => check.ok).length, total: checks.length, checks }
})
