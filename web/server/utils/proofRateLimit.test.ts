import { beforeEach, describe, expect, it } from 'vitest'
import { consumeProofLookup, proofClientKey, resetProofRateLimit } from './proofRateLimit'

describe('proof lookup rate limiting', () => {
  beforeEach(() => resetProofRateLimit())

  it('allows a normal reviewer and blocks a sweep from one client', () => {
    const now = Date.now()
    for (let i = 0; i < 30; i += 1) {
      expect(consumeProofLookup('203.0.113.9', now + i).allowed).toBe(true)
    }
    const blocked = consumeProofLookup('203.0.113.9', now + 30)
    expect(blocked.allowed).toBe(false)
    expect(blocked.retryAfterSeconds).toBeGreaterThan(0)
  })

  it('does not penalise an unrelated client', () => {
    const now = Date.now()
    for (let i = 0; i < 40; i += 1) consumeProofLookup('203.0.113.9', now + i)
    expect(consumeProofLookup('198.51.100.4', now + 41).allowed).toBe(true)
  })

  it('reopens the window once it has rolled past', () => {
    const now = Date.now()
    for (let i = 0; i < 30; i += 1) consumeProofLookup('203.0.113.9', now + i)
    expect(consumeProofLookup('203.0.113.9', now + 30).allowed).toBe(false)
    expect(consumeProofLookup('203.0.113.9', now + 61_000).allowed).toBe(true)
  })

  it('derives a client key from proxy headers, preferring the original client', () => {
    expect(proofClientKey({ forwardedFor: '203.0.113.9, 70.0.0.1' })).toBe('203.0.113.9')
    expect(proofClientKey({ forwardedFor: '', realIp: '198.51.100.4' })).toBe('198.51.100.4')
    expect(proofClientKey({ remoteAddress: '10.0.0.2' })).toBe('10.0.0.2')
    expect(proofClientKey({})).toBe('unknown')
  })
})
