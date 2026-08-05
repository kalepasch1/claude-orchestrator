/**
 * Wiring guards for the scoped proof exception.
 *
 * The unit tests next door prove the matcher is narrow. These prove the narrow
 * matcher is actually the thing both gates call, and that the exception has not
 * been widened somewhere else — a regression here would silently either break
 * every proof link the operator has sent, or open the private property.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { isPublicProofApiPath, isPublicProofPath } from '../../utils/proofLink'

const webRoot = resolve(__dirname, '../..')
const read = (relative: string) => readFileSync(resolve(webRoot, relative), 'utf8')

const appVue = read('app.vue')
const middleware = read('server/middleware/auth.ts')
const proofPage = read('pages/proof/[token].vue')
const proofApi = read('server/api/public/proof/[token].get.ts')
const robots = read('public/robots.txt')
const sitemap = read('public/sitemap.xml')

const TOKEN = 'Yk8sQ2pWbXJUdzlfLTNhQmNEZUZnSGk'

describe('client gate — /proof/<token> renders, everything else stays behind the session gate', () => {
  it('uses the shared single-segment matcher rather than an ad hoc string test', () => {
    expect(appVue).toContain('proofPageSegment')
    expect(appVue).not.toMatch(/startsWith\(\s*['"`]\/proof/)
  })

  it('still falls through to the marketing landing for logged-out visitors', () => {
    expect(appVue).toContain('v-else-if="!user"')
    expect(appVue).toContain('<LegoraLanding')
  })

  it('opens for a scoped proof URL and for nothing else', () => {
    expect(isPublicProofPath(`/proof/${TOKEN}`)).toBe(true)
    for (const path of ['/', '/fleet', '/inbox', '/queue', '/admin', '/spend', '/health', '/proof', '/proof/', '/auth/callback']) {
      expect(isPublicProofPath(path)).toBe(false)
    }
  })
})

describe('server gate — the API exemption is a single path, not a prefix', () => {
  it('is granted through the shared matcher', () => {
    expect(middleware).toContain('isPublicProofApiPath')
  })

  it('does not introduce a prefix wildcard for proof or public routes', () => {
    expect(middleware).not.toMatch(/startsWith\(\s*['"`]\/api\/public/)
    expect(middleware).not.toMatch(/startsWith\(\s*['"`]\/api\/public\/proof/)
  })

  it('accepts only a well-formed proof lookup', () => {
    expect(isPublicProofApiPath(`/api/public/proof/${TOKEN}`)).toBe(true)
    for (const path of ['/api/public/proof', '/api/public/proof/list', '/api/fleet/analytics', '/api/admin/users']) {
      expect(isPublicProofApiPath(path)).toBe(false)
    }
  })
})

describe('the proof API verifies the token server-side and reveals nothing on failure', () => {
  it('rejects a request whose token is not a well-formed share token', () => {
    expect(proofApi).toContain('isProofToken')
  })

  it('checks expiry and revocation through the shared predicate', () => {
    expect(proofApi).toContain('proofLinkIsServable')
  })

  it('returns one indistinguishable failure for unknown, expired and revoked', () => {
    // Every lookup failure path funnels through the same factory...
    expect((proofApi.match(/linkNotAvailable\(\)/g) || []).length).toBeGreaterThanOrEqual(4)
    // ...and no response message hints at which cause it was.
    expect(proofApi).not.toMatch(/(message|statusMessage):\s*['"][^'"]*(expired|revoked|unknown|not_found)/i)
    expect(proofApi).not.toMatch(/statusCode:\s*5\d\d/)
  })

  it('rate limits lookups and never keys anything on the token value', () => {
    expect(proofApi).toContain('consumeProofLookup')
    expect(proofApi).not.toMatch(/console\.(log|info|warn|error)/)
  })

  it('builds the response from the allow-list rather than spreading a row', () => {
    expect(proofApi).toContain('buildProofView')
    expect(proofApi).not.toContain('select(\'*\')')
    expect(proofApi).not.toContain('...proof')
    expect(proofApi).not.toContain('...link')
  })
})

describe('scoped proof pages are private, not public pages', () => {
  it('carries noindex, nofollow', () => {
    expect(proofPage).toContain('noindex, nofollow')
  })

  it('is disallowed in robots.txt', () => {
    expect(robots).toMatch(/^Disallow:\s*\/proof\/?$/m)
  })

  it('is absent from the sitemap', () => {
    expect(sitemap).not.toContain('/proof')
  })

  it('shows the brand mark without the internal sub-wordmark', () => {
    expect(proofPage).toContain('<MadeusLogo compact />')
  })

  it('does not name internal machinery anywhere a reviewer can read it', () => {
    const visible = proofPage.split('<style')[0].toLowerCase()
    for (const term of ['supabase', 'orchestrator', 'runner', 'executor', 'merge train', 'anthropic', 'openai', 'claude']) {
      expect(visible).not.toContain(term)
    }
  })
})
