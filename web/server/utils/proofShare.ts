import { createHash, randomBytes } from 'node:crypto'

export function createProofShareToken() {
  return randomBytes(24).toString('base64url')
}

export function hashProofShareToken(token: string) {
  return createHash('sha256').update(token).digest('hex')
}

export function proofShareExpiry(days: unknown, now = Date.now()) {
  const requested = Number(days)
  const boundedDays = Number.isFinite(requested) ? Math.max(1, Math.min(90, requested)) : 7
  return new Date(now + boundedDays * 86_400_000).toISOString()
}
