import { describe, expect, it } from 'vitest'
import { accessHash, grantToken, referralCode } from './accessAdmission'

describe('access admission credentials', () => {
  it('normalizes referral codes without storing the raw value', () => {
    expect(accessHash(' mds-founder01 ')).toBe(accessHash('MDS-FOUNDER01'))
    expect(accessHash('MDS-FOUNDER01')).toMatch(/^[a-f0-9]{64}$/)
  })

  it('issues branded referral codes with enough entropy', () => {
    const codes = new Set(Array.from({ length: 100 }, () => referralCode()))
    expect(codes.size).toBe(100)
    for (const code of codes) expect(code).toMatch(/^MDS-[A-F0-9]{10}$/)
  })

  it('issues unique, URL-safe one-time grant tokens', () => {
    const tokens = new Set(Array.from({ length: 100 }, () => grantToken()))
    expect(tokens.size).toBe(100)
    for (const token of tokens) expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/)
  })
})
