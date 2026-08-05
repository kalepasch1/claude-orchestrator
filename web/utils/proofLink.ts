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

/** Longest single segment we will even look at, to keep absurd URLs out. */
const MAX_SEGMENT = 512

/**
 * Returns the single path segment following `prefix`, or null when `pathname`
 * is not `<prefix><segment>` exactly. Query strings must already be stripped by
 * the caller (use `route.path` / `event.path.split('?')[0]`).
 */
function singleSegment(pathname: string, prefix: string): string | null {
  if (typeof pathname !== 'string' || !pathname.startsWith(prefix)) return null

  const rest = pathname.slice(prefix.length)
  // Reject empty, nested, and trailing-slash forms before decoding, so an
  // encoded separator cannot smuggle a second segment past this check.
  if (!rest || rest.length > MAX_SEGMENT) return null
  if (rest.includes('/') || rest.includes('?') || rest.includes('#')) return null

  let decoded: string
  try {
    decoded = decodeURIComponent(rest)
  } catch {
    return null
  }

  return decoded.includes('/') ? null : decoded
}

function singleSegmentToken(pathname: string, prefix: string): string | null {
  const segment = singleSegment(pathname, prefix)
  return segment !== null && isProofToken(segment) ? segment : null
}

/**
 * The PAGE gate: any single segment under `/proof/`, whether or not it is a
 * well-formed token.
 *
 * This is deliberately looser than the API gate. A reviewer whose link arrived
 * truncated or line-wrapped by their mail client must land on "this link is not
 * valid or has expired" — showing them the marketing site instead would be
 * indistinguishable from the bug this whole change exists to fix.
 *
 * It is safe to be looser here because the page ships no data of its own: it
 * renders the invalid state unless `/api/public/proof/<token>` — which still
 * demands a well-formed token and verifies it — hands it something. `/proof`
 * and `/proof/` remain 404s, and nothing nested can be reached.
 */
export function proofPageSegment(pathname: string): string | null {
  return singleSegment(pathname, '/proof/')
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
