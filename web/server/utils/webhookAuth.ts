import { createHmac, timingSafeEqual } from 'node:crypto'

export function verifyHmac(raw: string, signature: string | undefined, secret: string, prefix = ''): boolean {
  if (!raw || !signature || !secret) return false
  const supplied = signature.startsWith(prefix) ? signature.slice(prefix.length) : signature
  if (!/^[a-f0-9]{64}$/i.test(supplied)) return false
  const expected = createHmac('sha256', secret).update(raw).digest('hex')
  const a = Buffer.from(expected, 'hex'); const b = Buffer.from(supplied, 'hex')
  return a.length === b.length && timingSafeEqual(a, b)
}
