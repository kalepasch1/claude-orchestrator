/**
 * Scoped proof links — the shape of the one logged-out surface on madeus.cc.
 *
 * `/proof/<token>` is the single route that renders without a Madeus session:
 * the opaque token in the path IS the credential, and the server verifies it
 * before any evidence is returned. Because two independent gates have to agree
 * on exactly which paths that covers — the client render gate in `app.vue` and
 * the Nitro auth middleware — the matcher lives here once and is imported by
 * both, so they cannot drift apart.
 *
 * Deliberate properties:
 *   - EXACTLY one path segment after the prefix. `/proof`, `/proof/`,
 *     `/proof/a/b` and any listing-shaped URL do not match.
 *   - No prefix wildcard. A crawler or a curious visitor cannot walk into the
 *     exception by appending segments.
 *   - The segment must look like a share token (opaque base64url, long). A
 *     malformed segment is rejected before it ever reaches the database.
 */

/**
 * Share tokens are 24 random bytes rendered base64url => 32 characters
 * (192 bits of entropy). The accepted range is a little wider than that so a
 * future rotation to a longer token does not silently start 404ing, but it is
 * still narrow enough that nothing resembling a slug, a word, or a numeric id
 * can slip through.
 */
export const PROOF_TOKEN_PATTERN = /^[A-Za-z0-9_-]{24,128}$/

export function isProofToken(value: unknown): value is string {
  return typeof value === 'string' && PROOF_TOKEN_PATTERN.test(value)
}

/**
 * Returns the token when `pathname` is `<prefix><token>` with no further
 * segments, otherwise null. Query strings must already be stripped by the
 * caller (use `route.path` / `event.path.split('?')[0]`).
 */
function singleSegmentToken(pathname: string, prefix: string): string | null {
  if (typeof pathname !== 'string' || !pathname.startsWith(prefix)) return null

  const rest = pathname.slice(prefix.length)
  // Reject empty, nested, and trailing-slash forms before decoding, so an
  // encoded separator cannot smuggle a second segment past this check.
  if (!rest || rest.includes('/') || rest.includes('?') || rest.includes('#')) return null

  let decoded: string
  try {
    decoded = decodeURIComponent(rest)
  } catch {
    return null
  }

  return isProofToken(decoded) ? decoded : null
}

/** `/proof/<token>` -> token, else null. */
export function proofTokenFromPath(pathname: string): string | null {
  return singleSegmentToken(pathname, '/proof/')
}

/** `/api/public/proof/<token>` -> token, else null. */
export function proofApiTokenFromPath(pathname: string): string | null {
  return singleSegmentToken(pathname, '/api/public/proof/')
}

/** True only for a well-formed scoped proof page URL. */
export function isPublicProofPath(pathname: string): boolean {
  return proofTokenFromPath(pathname) !== null
}

/** True only for a well-formed scoped proof API URL. */
export function isPublicProofApiPath(pathname: string): boolean {
  return proofApiTokenFromPath(pathname) !== null
}
