/**
 * embedProtocol — the ENVELOPE half of the Madeus embed contract.
 *
 * Split out of server/utils/embedProtocol.ts on 2026-09-04. That file opens by
 * stating the requirement this split exists to honour:
 *
 *     Pure and dependency-free on purpose: no h3, no Nitro, no DB. It is the
 *     contract, so it must be testable without a server and importable from
 *     both the API handlers and the embed page.
 *
 * It could not be imported from the embed page. Line 35 was
 * `import { createHash, timingSafeEqual } from 'node:crypto'` for the AUTH half,
 * and pages/embed/command.vue imports the envelope from the same module, so Rollup
 * pulled node:crypto into the CLIENT bundle and the production build died:
 *
 *     RollupError: server/utils/embedProtocol.ts (35:9): "createHash" is not
 *     exported by "__vite-browser-external", imported by
 *     "server/utils/embedProtocol.ts".
 *
 * Nothing here may import a node: builtin. The auth half -- key hashing, the
 * constant-time compare, origin binding -- stays server-side in
 * server/utils/embedProtocol.ts, which re-exports everything below so every
 * existing server import keeps working unchanged.
 */

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
