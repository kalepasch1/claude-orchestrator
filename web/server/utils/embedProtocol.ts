/**
 * embedProtocol.ts — the envelope and the auth for the Madeus embed SDK.
 *
 * WHAT THIS IS
 * ------------
 * Madeus is the brain; every portfolio app should be able to mount a piece of it
 * (the UniversalCommand outcome box, the fleet-status/approvals strip) so work
 * can be initiated anywhere and still land in ONE fleet. That requires two
 * agreements between a host page on another origin and this server:
 *
 *   1. an AUTH handshake — tenant-scoped API keys, so a host can only see and
 *      steer its own tenant's work, and
 *   2. an ENVELOPE — one message shape for postMessage in both directions, so
 *      apparently/tomorrow/pareto (and later a tenant's own app) mount the same
 *      strip without each inventing a protocol.
 *
 * Pure and dependency-free on purpose: no h3, no Nitro, no DB. It is the
 * contract, so it must be testable without a server and importable from both
 * the API handlers and the embed page.
 *
 * WHY THE KEY IS HASHED AND COMPARED IN CONSTANT TIME
 * ---------------------------------------------------
 * An embed key travels in a header from a third-party origin and identifies a
 * whole tenant. Storing it raw would make a read of one table equivalent to
 * impersonating every host; comparing it with === leaks its prefix through
 * timing. Neither costs anything to avoid, so neither is acceptable here.
 *
 * WHY ORIGIN IS PART OF AUTH AND NOT JUST CORS
 * --------------------------------------------
 * A leaked key is a key. Binding each key to an allow-list of origins means a
 * stolen key is only useful from a page the tenant already declared, which
 * turns a total compromise into a much narrower one. CORS is a browser
 * courtesy; this check is server-side and is the real gate.
 */
import { createHash, timingSafeEqual } from 'node:crypto'

// ── Envelope ────────────────────────────────────────────────────────────────

/** Surfaces a host may mount. Mirrors EmbedSurface in web/types/madeus-embed.ts. */
export const EMBED_SURFACES = [
  'strip',
  'universal_command',
  'fleet_dashboard',
  'waves_dashboard',
  'signoffs',
  'steering',
  'tenancy_admin',
  'intercompany',
  'department_fleet_init',
] as const
export type EmbedSurface = (typeof EMBED_SURFACES)[number]

export type EmbedDirection = 'host_to_embed' | 'embed_to_host'

/**
 * The postMessage envelope, in BOTH directions.
 *
 * `v` is first and mandatory: a host page pinned to an old bundle will keep
 * posting yesterday's shape long after this server moves on, and a version tag
 * is the difference between rejecting it cleanly and misreading it.
 */
export interface EmbedEnvelope<T = unknown> {
  /** Protocol version. Bump on any breaking shape change. */
  v: 1
  direction: EmbedDirection
  /** Dotted verb, e.g. 'outcome.submit', 'approval.decide', 'host.navigate'. */
  kind: string
  tenantId: string
  surface: EmbedSurface
  /** Correlates a reply to its request. Absent on fire-and-forget. */
  correlationId?: string
  sentAt: number
  payload: T
}

export const EMBED_PROTOCOL_VERSION = 1 as const

/**
 * Structural validation of an inbound envelope.
 *
 * Returns a reason rather than a bare false: an embed that silently drops
 * messages is the hardest kind of integration to debug from the host side.
 */
export function parseEnvelope(raw: unknown): { ok: true; envelope: EmbedEnvelope } | { ok: false; reason: string } {
  if (!raw || typeof raw !== 'object') return { ok: false, reason: 'envelope must be an object' }
  const e = raw as Record<string, unknown>
  if (e.v !== EMBED_PROTOCOL_VERSION) return { ok: false, reason: `unsupported protocol version ${String(e.v)}` }
  if (e.direction !== 'host_to_embed' && e.direction !== 'embed_to_host') {
    return { ok: false, reason: 'direction must be host_to_embed or embed_to_host' }
  }
  if (typeof e.kind !== 'string' || !e.kind.trim()) return { ok: false, reason: 'kind is required' }
  if (typeof e.tenantId !== 'string' || !e.tenantId.trim()) return { ok: false, reason: 'tenantId is required' }
  if (!EMBED_SURFACES.includes(e.surface as EmbedSurface)) {
    return { ok: false, reason: `unknown surface ${String(e.surface)}` }
  }
  if (typeof e.sentAt !== 'number' || !Number.isFinite(e.sentAt)) {
    return { ok: false, reason: 'sentAt must be a number' }
  }
  return { ok: true, envelope: e as unknown as EmbedEnvelope }
}

export function makeEnvelope<T>(
  direction: EmbedDirection,
  kind: string,
  tenantId: string,
  surface: EmbedSurface,
  payload: T,
  correlationId?: string,
  now = Date.now(),
): EmbedEnvelope<T> {
  return { v: EMBED_PROTOCOL_VERSION, direction, kind, tenantId, surface, payload, correlationId, sentAt: now }
}

// ── Tenant-scoped API keys ──────────────────────────────────────────────────

export interface EmbedKeyRecord {
  tenantId: string
  /** sha256 hex of the key. The raw key is never stored. */
  keyHash: string
  /** Exact origins this key may be presented from. Empty = unusable, not open. */
  allowedOrigins: readonly string[]
  /** Surfaces this key may mount. Empty = unusable, not all. */
  surfaces: readonly EmbedSurface[]
  revoked?: boolean
}

export function hashKey(rawKey: string): string {
  return createHash('sha256').update(String(rawKey ?? ''), 'utf8').digest('hex')
}

function constantTimeEqualHex(a: string, b: string): boolean {
  if (!/^[a-f0-9]{64}$/i.test(a) || !/^[a-f0-9]{64}$/i.test(b)) return false
  const ba = Buffer.from(a, 'hex')
  const bb = Buffer.from(b, 'hex')
  return ba.length === bb.length && timingSafeEqual(ba, bb)
}

/** Origins compare exactly, case-insensitively on scheme+host, no trailing slash. */
function normalizeOrigin(origin: string | undefined | null): string {
  if (!origin || typeof origin !== 'string') return ''
  return origin.trim().replace(/\/+$/, '').toLowerCase()
}

export interface AuthResult {
  ok: boolean
  tenantId?: string
  surface?: EmbedSurface
  reason?: string
}

/**
 * The handshake. DENIES on anything it cannot positively confirm.
 *
 * Order matters: revocation and origin are checked before the surface grant so
 * a revoked key never reveals which surfaces it used to hold.
 */
export function authorizeEmbed(
  rawKey: string | undefined,
  origin: string | undefined,
  surface: string | undefined,
  records: readonly EmbedKeyRecord[],
): AuthResult {
  if (!rawKey) return { ok: false, reason: 'missing embed key' }
  if (!EMBED_SURFACES.includes(surface as EmbedSurface)) {
    return { ok: false, reason: `unknown surface ${String(surface)}` }
  }
  const presented = hashKey(rawKey)
  const record = (records || []).find((r) => r && constantTimeEqualHex(r.keyHash || '', presented))
  if (!record) return { ok: false, reason: 'unknown embed key' }
  if (record.revoked) return { ok: false, reason: 'embed key revoked' }

  const want = normalizeOrigin(origin)
  const allowed = (record.allowedOrigins || []).map(normalizeOrigin).filter(Boolean)
  if (!allowed.length) return { ok: false, reason: 'key has no allowed origins' }
  if (!want || !allowed.includes(want)) {
    return { ok: false, reason: `origin ${want || '(none)'} is not allow-listed for this key` }
  }

  if (!(record.surfaces || []).includes(surface as EmbedSurface)) {
    return { ok: false, reason: `key is not granted surface ${surface}` }
  }
  return { ok: true, tenantId: record.tenantId, surface: surface as EmbedSurface }
}

// ── Two-way approvals channel ───────────────────────────────────────────────

/**
 * A decision made in a HOST app (Smarter's fleet inbox already receives our
 * approval cards one-way; this is the return leg).
 *
 * `decidedBy` is mandatory and unforgeable-by-omission: an approval with no
 * decider is an audit hole, and the whole point of routing decisions back here
 * is that steering_events can attribute them.
 */
export interface ApprovalDecision {
  approvalId: string
  decision: 'approved' | 'rejected'
  decidedBy: string
  decidedByLabel?: string
  rationale?: string
  /** Host that collected the decision, for the audit trail. */
  hostApp: string
}

export function validateApprovalDecision(raw: unknown): { ok: true; decision: ApprovalDecision } | { ok: false; reason: string } {
  if (!raw || typeof raw !== 'object') return { ok: false, reason: 'decision must be an object' }
  const d = raw as Record<string, unknown>
  if (typeof d.approvalId !== 'string' || !d.approvalId.trim()) return { ok: false, reason: 'approvalId is required' }
  if (d.decision !== 'approved' && d.decision !== 'rejected') {
    return { ok: false, reason: "decision must be 'approved' or 'rejected'" }
  }
  if (typeof d.decidedBy !== 'string' || !d.decidedBy.trim()) {
    return { ok: false, reason: 'decidedBy is required — an unattributed decision is an audit hole' }
  }
  if (typeof d.hostApp !== 'string' || !d.hostApp.trim()) return { ok: false, reason: 'hostApp is required' }
  return {
    ok: true,
    decision: {
      approvalId: d.approvalId.trim(),
      decision: d.decision,
      decidedBy: d.decidedBy.trim(),
      decidedByLabel: typeof d.decidedByLabel === 'string' ? d.decidedByLabel : undefined,
      rationale: typeof d.rationale === 'string' ? d.rationale.slice(0, 4000) : undefined,
      hostApp: d.hostApp.trim(),
    },
  }
}

// ── Outcome submission ──────────────────────────────────────────────────────

export interface OutcomeSubmission {
  outcome: string
  tenantId: string
  hostApp: string
  entityId?: string
  department?: string
}

export function validateOutcome(raw: unknown, tenantId: string): { ok: true; submission: OutcomeSubmission } | { ok: false; reason: string } {
  if (!raw || typeof raw !== 'object') return { ok: false, reason: 'payload must be an object' }
  const p = raw as Record<string, unknown>
  const outcome = typeof p.outcome === 'string' ? p.outcome.trim() : ''
  if (!outcome) return { ok: false, reason: 'outcome text is required' }
  if (outcome.length > 8000) return { ok: false, reason: 'outcome exceeds 8000 characters' }
  if (typeof p.hostApp !== 'string' || !p.hostApp.trim()) return { ok: false, reason: 'hostApp is required' }
  // tenantId comes from the AUTHENTICATED key, never from the payload: a host
  // that could name its own tenant could name someone else's.
  return {
    ok: true,
    submission: {
      outcome,
      tenantId,
      hostApp: p.hostApp.trim(),
      entityId: typeof p.entityId === 'string' ? p.entityId : undefined,
      department: typeof p.department === 'string' ? p.department : undefined,
    },
  }
}
