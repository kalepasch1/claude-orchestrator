export const DEFAULT_AUTH_DESTINATION = '/orchestrators'

const PUBLIC_AUTH_PATHS = new Set(['/', '/index', '/auth/callback'])

export function normalizeAuthReturnTo(candidate?: string | null) {
  if (!candidate || !candidate.startsWith('/') || candidate.startsWith('//')) return DEFAULT_AUTH_DESTINATION
  const pathname = candidate.split(/[?#]/, 1)[0]
  return PUBLIC_AUTH_PATHS.has(pathname) ? DEFAULT_AUTH_DESTINATION : candidate
}

export function authCallbackUrl(origin: string) {
  return new URL('/auth/callback', origin).toString()
}
