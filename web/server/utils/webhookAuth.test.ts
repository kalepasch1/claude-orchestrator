import { createHmac } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import { verifyHmac } from './webhookAuth'

describe('verifyHmac', () => {
  it('accepts exact signatures and rejects tampering', () => {
    const raw = '{"after":"abc"}'; const secret = 'secret'
    const sig = createHmac('sha256', secret).update(raw).digest('hex')
    expect(verifyHmac(raw, `sha256=${sig}`, secret, 'sha256=')).toBe(true)
    expect(verifyHmac(raw + 'x', `sha256=${sig}`, secret, 'sha256=')).toBe(false)
  })
})
