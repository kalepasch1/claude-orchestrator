import { describe, expect, it } from 'vitest'
import { framePolicyAllows, gatewayTarget, rewriteGatewayHtml } from './previewGateway'

describe('secure preview gateway', () => {
  it('only resolves paths below a checked-in fleet origin', () => {
    expect(gatewayTarget('apparently', 'dashboard')?.origin).toBe('https://www.apparently.cc')
    expect(gatewayTarget('missing', 'dashboard')).toBeNull()
  })
  it('removes embedded frame policies and rewrites root assets', () => {
    const target = new URL('https://www.apparently.cc/')
    const html = rewriteGatewayHtml('<head><meta http-equiv="content-security-policy" content="frame-ancestors none"><script src="/app.js"></script></head>', 'apparently', target)
    expect(html).not.toContain('frame-ancestors none')
    expect(html).toContain('/api/previews/gateway/apparently/app.js')
    expect(html).toContain('<base href="/api/previews/gateway/apparently/">')
  })
  it('distinguishes same-origin policies from a Madeus allowlist', () => {
    expect(framePolicyAllows("frame-ancestors 'self'", '', 'https://www.madeus.cc', 'https://www.apparently.cc')).toBe(false)
    expect(framePolicyAllows("frame-ancestors 'self' https://www.madeus.cc", '', 'https://www.madeus.cc', 'https://www.apparently.cc')).toBe(true)
  })
})
