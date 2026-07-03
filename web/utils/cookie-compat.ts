type SerializeOptions = {
  domain?: string
  expires?: Date
  httpOnly?: boolean
  maxAge?: number
  path?: string
  sameSite?: boolean | 'lax' | 'strict' | 'none'
  secure?: boolean
}

export function parse(input = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const part of input.split(';')) {
    const trimmed = part.trim()
    if (!trimmed) continue
    const eq = trimmed.indexOf('=')
    if (eq < 0) continue
    const key = trimmed.slice(0, eq).trim()
    const raw = trimmed.slice(eq + 1).trim()
    if (!key) continue
    try {
      out[key] = decodeURIComponent(raw)
    } catch {
      out[key] = raw
    }
  }
  return out
}

export function serialize(name: string, value: string, options: SerializeOptions = {}): string {
  const parts = [`${name}=${encodeURIComponent(value)}`]
  if (options.maxAge != null) parts.push(`Max-Age=${Math.floor(options.maxAge)}`)
  if (options.domain) parts.push(`Domain=${options.domain}`)
  if (options.path) parts.push(`Path=${options.path}`)
  if (options.expires) parts.push(`Expires=${options.expires.toUTCString()}`)
  if (options.httpOnly) parts.push('HttpOnly')
  if (options.secure) parts.push('Secure')
  if (options.sameSite) {
    const sameSite = options.sameSite === true ? 'Strict' : String(options.sameSite)
    parts.push(`SameSite=${sameSite.charAt(0).toUpperCase()}${sameSite.slice(1).toLowerCase()}`)
  }
  return parts.join('; ')
}
