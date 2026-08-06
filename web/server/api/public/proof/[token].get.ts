/**
 * Scoped proof portal — the only unauthenticated read on madeus.cc.
 *
 * The token in the path IS the credential. It is verified here, server-side,
 * against a hash held in the database before a single field of evidence is
 * returned; the page never queries the database itself and never holds an
 * anonymous key. Unknown, malformed, expired and revoked tokens all produce the
 * identical 404 so a probe learns nothing about which of those it hit.
 *
 * The token value is never logged, never echoed in an error, and never used as
 * a cache or rate-limit key.
 */
import { serviceClient } from '../../../utils/fleetSupabase'
import { hashProofShareToken } from '../../../utils/proofShare'
import { buildProofView, proofLinkIsServable } from '../../../utils/proofPayload'
import { consumeProofLookup, proofClientKey } from '../../../utils/proofRateLimit'
import { isProofToken } from '../../../../utils/proofLink'

/** One indistinguishable failure for every reason a link may not be servable. */
function linkNotAvailable() {
  return createError({
    statusCode: 404,
    statusMessage: 'Not Found',
    message: 'proof_link_not_available',
  })
}

export default defineEventHandler(async (event) => {
  // Private links: never indexed, never cached by an intermediary.
  setHeader(event, 'x-robots-tag', 'noindex, nofollow')
  setHeader(event, 'cache-control', 'no-store, max-age=0')
  setHeader(event, 'referrer-policy', 'no-referrer')

  const client = proofClientKey({
    forwardedFor: getRequestHeader(event, 'x-forwarded-for'),
    realIp: getRequestHeader(event, 'x-real-ip'),
    remoteAddress: event.node?.req?.socket?.remoteAddress,
  })
  const rate = consumeProofLookup(client)
  if (!rate.allowed) {
    // h3 types 'retry-after' as a number, so String() was the type error (TS2345).
    setHeader(event, 'retry-after', rate.retryAfterSeconds)
    throw createError({
      statusCode: 429,
      statusMessage: 'Too Many Requests',
      message: 'too_many_proof_lookups',
    })
  }

  const token = String(getRouterParam(event, 'token') || '')
  if (!isProofToken(token)) throw linkNotAvailable()

  // A misconfigured environment must still look like an ordinary bad link to a
  // reviewer — never a stack trace, never a 500 on a page an investor is reading.
  let sb: ReturnType<typeof serviceClient>
  try {
    sb = serviceClient()
  } catch {
    throw linkNotAvailable()
  }

  const { data: link, error: linkError } = await sb
    .from('proof_share_links')
    .select('proof_id,expires_at,revoked_at,audience')
    .eq('token_hash', hashProofShareToken(token))
    .maybeSingle()

  // A database fault must not surface as a 500 to a reviewer, and must not be
  // distinguishable from a bad link either.
  if (linkError) throw linkNotAvailable()
  if (!proofLinkIsServable(link)) throw linkNotAvailable()

  const { data: proof, error: proofError } = await sb
    .from('execution_proof_envelopes')
    .select('action_type,intent,status,proof_digest,prediction,rollback_plan,created_at')
    .eq('id', link!.proof_id)
    .maybeSingle()

  if (proofError || !proof) throw linkNotAvailable()

  return buildProofView(link!, proof)
})
