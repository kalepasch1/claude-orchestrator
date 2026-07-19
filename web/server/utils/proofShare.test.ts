import { describe, expect, it } from 'vitest'
import { createProofShareToken, hashProofShareToken, proofShareExpiry } from './proofShare'

describe('proof share links', () => {
  it('stores a deterministic digest instead of the bearer token', () => {
    const token = createProofShareToken()
    expect(token.length).toBeGreaterThanOrEqual(32)
    expect(hashProofShareToken(token)).toMatch(/^[a-f0-9]{64}$/)
    expect(hashProofShareToken(token)).not.toContain(token)
  })

  it('bounds reviewer access between one and ninety days', () => {
    const now = Date.UTC(2026, 6, 16)
    expect(proofShareExpiry(0, now)).toBe(new Date(now + 86_400_000).toISOString())
    expect(proofShareExpiry(999, now)).toBe(new Date(now + 90 * 86_400_000).toISOString())
    expect(proofShareExpiry('invalid', now)).toBe(new Date(now + 7 * 86_400_000).toISOString())
  })
})
