/**
 * Reviewer-facing shaping for scoped proof links.
 *
 * Whoever opens a proof link is NOT a tenant of the workspace — they presented
 * nothing but the token in the URL. Two consequences drive this module:
 *
 * 1. SCOPE. The response is assembled field by field from the single row the
 *    token resolved to. Nothing is ever spread from a database row, and no
 *    identifier that could be used to pivot to another proof, project,
 *    organization or person is emitted. Manipulating the token or adding query
 *    parameters cannot widen the response, because the response shape is fixed
 *    here and reads no request input at all.
 *
 * 2. DISCRETION. Evidence bodies are operator-authored free text and can name
 *    infrastructure, tooling or vendors in passing. A scoped proof page exists
 *    to show the outcome and the evidence for it, not how the work was produced
 *    or on whose systems. Recognised internal terms are replaced with
 *    `[internal]`, and anything shaped like a credential with `[redacted]`.
 */

/** Vendor, infrastructure and internal-machinery vocabulary kept out of view. */
const INTERNAL_TERMS = [
  // Model vendors / products
  'gpt[\\w-]*',
  'anthropic',
  'openai',
  'chatgpt',
  'claude',
  'gemini',
  'llama',
  'mistral',
  'bedrock',
  'copilot',
  // Infrastructure
  'supabase',
  'postgres',
  'postgresql',
  'rls',
  'service[_ -]?role',
  'nitro',
  // Execution machinery
  'orchestrator',
  'orchestrators',
  'runner',
  'runners',
  'executor',
  'executors',
  'sub[_ -]?agent',
  'sub[_ -]?agents',
  'agent',
  'agents',
  'worktree',
  'worktrees',
  'merge[_ -]?train',
  'merge[_ -]?trains',
  'merge[_ -]?queue',
  'task[_ -]?queue',
  'job[_ -]?queue',
  'queue[_ -]?worker',
  'fleet',
]

// Lookarounds rather than \b so hyphenated forms ("gpt-4", "merge-train") are
// consumed whole instead of leaving a dangling fragment on the page.
const INTERNAL_PATTERN = new RegExp(
  `(?<![\\w-])(?:${INTERNAL_TERMS.join('|')})(?![\\w-])`,
  'gi',
)

/** Non-global twin used for stateless single-word key checks. */
const INTERNAL_KEY_PART = new RegExp(`^(?:${INTERNAL_TERMS.join('|')})$`, 'i')

/** Shapes that look like credentials, regardless of the key they arrived under. */
const SECRET_PATTERN =
  /(?<![\w-])(?:(?:sk|pk|rk|ghp|gho|ghs|xox[abps])-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}[.\w-]*)/g

/** Keys never forwarded, whatever their value. */
const SENSITIVE_KEY =
  /(token|secret|password|passwd|credential|api[_-]?key|access[_-]?key|private[_-]?key|authorization|bearer|cookie|session|email|webhook)/i

/** Identifier keys — dropped so a reviewer holds no handle on any other record. */
const IDENTIFIER_KEY = /(?:^|_)(?:id|ids|uuid|guid)$/i

/** Named references to other entities in the workspace. */
const RELATION_KEY = new Set([
  'organization',
  'organisation',
  'org',
  'tenant',
  'account',
  'workspace',
  'user',
  'users',
  'owner',
  'operator',
  'created_by',
  'updated_by',
  'actor',
  'assignee',
  'project',
  'projects',
  'task',
  'tasks',
])

const MAX_STRING = 2000
const MAX_DEPTH = 4
const MAX_KEYS = 60
const MAX_ITEMS = 40
const MAX_LABEL = 240

/** Replace recognised internal machinery and credential shapes in free text. */
export function scrubInternalTerms(value: string): string {
  if (typeof value !== 'string' || !value) return ''
  return value.replace(SECRET_PATTERN, '[redacted]').replace(INTERNAL_PATTERN, '[internal]')
}

/**
 * Internal taxonomy namespace prefix, e.g. `constitution:institutional_case`.
 * The namespace is a routing detail of the system, not part of the outcome a
 * reviewer came to read, so it is dropped. A prose colon ("Renewal: parity")
 * is left alone because the pattern requires an unbroken lowercase slug.
 */
const TAXONOMY_PREFIX = /^[a-z0-9_.-]+:\s*/

/** Short, human-facing label: scrubbed, de-slugged, length-capped. */
export function presentableLabel(value: unknown): string {
  if (typeof value !== 'string') return ''
  const scrubbed = scrubInternalTerms(value)
    .replace(TAXONOMY_PREFIX, '')
    .replace(/_+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return scrubbed.length > MAX_LABEL ? `${scrubbed.slice(0, MAX_LABEL - 1)}…` : scrubbed
}

function keyIsAllowed(key: string): boolean {
  if (!key || key.startsWith('_')) return false
  if (SENSITIVE_KEY.test(key)) return false
  if (IDENTIFIER_KEY.test(key)) return false
  if (RELATION_KEY.has(key.toLowerCase())) return false
  // A key named after internal machinery (`runner_note`, `agent_step`) is
  // dropped rather than rewritten — a JSON key reading `[internal]_note` would
  // be worse to look at than the field simply not being there.
  if (key.split(/[_\-\s]+/).some((part) => INTERNAL_KEY_PART.test(part))) return false
  return true
}

/**
 * Recursively copy an evidence body into a bounded, scrubbed structure.
 * Unknown value types are dropped rather than passed through.
 */
export function scopeEvidence(value: unknown, depth = 0): any {
  if (depth > MAX_DEPTH) return null
  if (value === null || value === undefined) return null

  if (typeof value === 'string') {
    const scrubbed = scrubInternalTerms(value)
    return scrubbed.length > MAX_STRING ? `${scrubbed.slice(0, MAX_STRING)}…` : scrubbed
  }
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'boolean') return value

  if (Array.isArray(value)) {
    return value.slice(0, MAX_ITEMS).map((item) => scopeEvidence(item, depth + 1))
  }

  if (typeof value === 'object') {
    const out: Record<string, any> = {}
    let kept = 0
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (kept >= MAX_KEYS) break
      if (!keyIsAllowed(key)) continue
      out[key] = scopeEvidence(item, depth + 1)
      kept += 1
    }
    return out
  }

  return null
}

export type ProofLinkRow = {
  proof_id?: string | null
  audience?: string | null
  expires_at?: string | null
  revoked_at?: string | null
}

export type ProofRow = {
  action_type?: string | null
  intent?: string | null
  status?: string | null
  proof_digest?: string | null
  prediction?: unknown
  rollback_plan?: unknown
  created_at?: string | null
}

/**
 * A link is servable only while it is neither revoked nor past expiry.
 * Callers must treat "not servable" and "never existed" identically — the
 * reviewer is told the link is not valid, never which of the two it was.
 */
export function proofLinkIsServable(
  link: ProofLinkRow | null | undefined,
  now: number = Date.now(),
): boolean {
  if (!link) return false
  if (link.revoked_at) return false
  const expiresAt = Date.parse(String(link.expires_at ?? ''))
  return Number.isFinite(expiresAt) && expiresAt > now
}

/** Digests are opaque hex/base64 with an optional algorithm prefix. */
const DIGEST_PATTERN = /^[A-Za-z0-9+/=:_-]{16,256}$/

function isoOrNull(value: unknown): string | null {
  const parsed = Date.parse(String(value ?? ''))
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : null
}

/**
 * The complete reviewer payload. Every field is named explicitly, so adding a
 * column to either table cannot leak it into this response by accident.
 */
export function buildProofView(link: ProofLinkRow, proof: ProofRow) {
  const digest =
    typeof proof.proof_digest === 'string' && DIGEST_PATTERN.test(proof.proof_digest)
      ? proof.proof_digest
      : null

  return {
    proof: {
      intent: presentableLabel(proof.intent),
      action_type: presentableLabel(proof.action_type),
      status: presentableLabel(proof.status),
      proof_digest: digest,
      prediction: scopeEvidence(proof.prediction) ?? {},
      rollback_plan: scopeEvidence(proof.rollback_plan) ?? {},
      created_at: isoOrNull(proof.created_at),
    },
    audience: presentableLabel(link.audience) || 'Authorized reviewer',
    expires_at: isoOrNull(link.expires_at),
    verification: { digest_present: digest !== null },
  }
}
