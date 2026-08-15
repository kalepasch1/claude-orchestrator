import { describe, expect, it } from 'vitest'
import {
  isProofToken,
  proofPageSegment,
  isPublicProofApiPath,
  isPublicProofPath,
  proofApiTokenFromPath,
  proofTokenFromPath,
} from '../../utils/proofLink'

// Shaped exactly like a real share token: randomBytes(24).toString('base64url').
const VALID = 'Yk8sQ2pWbXJUdzlfLTNhQmNEZUZnSGk'
const VALID_2 = 'aZ-_0123456789abcdefghijKLMNOPQ'

describe('proof token shape', () => {
  it('accepts opaque base64url tokens of share-token length', () => {
    expect(isProofToken(VALID)).toBe(true)
    expect(isProofToken(VALID_2)).toBe(true)
  })

  it('rejects anything that is not a long opaque segment', () => {
    for (const bad of ['', 'abc', 'proof', '../../etc/passwd', 'a'.repeat(23), 'a'.repeat(129), 'has space', 'has/slash', 'has.dot', 'has%20pct', null, undefined, 42, {}]) {
      expect(isProofToken(bad as any)).toBe(false)
    }
  })
})

describe('page route matching — only /proof/<token> opens', () => {
  it('matches a single well-formed token segment', () => {
    expect(proofTokenFromPath(`/proof/${VALID}`)).toBe(VALID)
    expect(isPublicProofPath(`/proof/${VALID}`)).toBe(true)
  })

  it('does not open a listing, an index, or a trailing slash', () => {
    for (const path of ['/proof', '/proof/', '/proofs', '/proof/index', `/proof/${VALID}/`]) {
      expect(proofTokenFromPath(path)).toBeNull()
      expect(isPublicProofPath(path)).toBe(false)
    }
  })

  it('cannot be walked into with extra segments or encoded separators', () => {
    for (const path of [
      `/proof/${VALID}/raw`,
      `/proof/${VALID}/../../admin`,
      `/proof/${VALID}%2Fadmin`,
      `/proof/${VALID}%2f..%2ffleet`,
      '/proof/%2e%2e%2f%2e%2e%2fetc',
    ]) {
      expect(proofTokenFromPath(path)).toBeNull()
    }
  })

  it('does not match any other route on the property', () => {
    const otherRoutes = [
      '/', '/admin', '/auth/callback', '/business', '/connectors', '/digital-twin',
      '/distribution', '/fleet', '/growth', '/health', '/hivemind', '/inbox', '/loops',
      '/orchestrators', '/queue', '/sign-offs', '/spend', '/waves', '/pricing', '/signup',
      '/proofing', '/xproof/abc',
    ]
    for (const path of otherRoutes) {
      expect(isPublicProofPath(path)).toBe(false)
    }
  })

  it('survives a malformed percent-escape without throwing', () => {
    expect(() => proofTokenFromPath('/proof/%E0%A4%A')).not.toThrow()
    expect(proofTokenFromPath('/proof/%E0%A4%A')).toBeNull()
  })
})

describe('page shell gate — a truncated link must never show the marketing site', () => {
  it('opens the portal shell for any single segment, well-formed or not', () => {
    for (const segment of [VALID, 'short', 'not-a-token', 'a'.repeat(200)]) {
      expect(proofPageSegment(`/proof/${segment}`)).toBe(segment)
    }
  })

  it('still refuses an index, a trailing slash and anything nested', () => {
    for (const path of ['/proof', '/proof/', `/proof/${VALID}/raw`, `/proof/${VALID}%2Fadmin`, '/', '/fleet']) {
      expect(proofPageSegment(path)).toBeNull()
    }
  })

  it('refuses an absurdly long segment', () => {
    expect(proofPageSegment(`/proof/${'a'.repeat(600)}`)).toBeNull()
  })

  it('is looser than the API gate, which still demands a real token', () => {
    expect(proofPageSegment('/proof/short')).toBe('short')
    expect(isPublicProofApiPath('/api/public/proof/short')).toBe(false)
  })
})

describe('API route matching — the auth middleware exemption', () => {
  it('exempts exactly one well-formed proof lookup', () => {
    expect(proofApiTokenFromPath(`/api/public/proof/${VALID}`)).toBe(VALID)
    expect(isPublicProofApiPath(`/api/public/proof/${VALID}`)).toBe(true)
  })

  it('is not a prefix wildcard', () => {
    for (const path of [
      '/api/public/proof',
      '/api/public/proof/',
      '/api/public/proof/list',
      `/api/public/proof/${VALID}/all`,
      '/api/public/proofs',
      '/api/public/access/status',
      '/api/fleet/analytics',
      '/api/outcome-intelligence/action',
      '/api/admin',
    ]) {
      expect(isPublicProofApiPath(path)).toBe(false)
    }
  })
})
