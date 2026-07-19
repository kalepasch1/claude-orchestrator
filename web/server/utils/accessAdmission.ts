import { createHash, randomBytes } from 'node:crypto'
import { createError, getRequestIP } from 'h3'

const attempts = new Map<string, { count: number; resetAt: number }>()

export function accessHash(value: string) {
  return createHash('sha256').update(value.trim().toUpperCase()).digest('hex')
}

export function referralCode() {
  return `MDS-${randomBytes(5).toString('hex').toUpperCase()}`
}

export function grantToken() {
  return randomBytes(32).toString('base64url')
}

export function limitPublicAdmission(event: any, limit = 12) {
  const key = getRequestIP(event, { xForwardedFor: true }) || 'unknown'
  const now = Date.now()
  const current = attempts.get(key)
  if (!current || current.resetAt <= now) {
    attempts.set(key, { count: 1, resetAt: now + 60_000 })
    return
  }
  current.count += 1
  if (current.count > limit) throw createError({ statusCode: 429, message: 'Too many access attempts. Try again in one minute.' })
}
