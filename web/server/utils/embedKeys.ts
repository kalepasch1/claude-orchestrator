/**
 * embedKeys.ts — where embed key records come from.
 *
 * Split out from embedProtocol.ts on purpose: the protocol is pure and testable
 * with no I/O, and this is the part that touches config/DB. Keeping them apart
 * is what lets the auth logic be tested exhaustively without a database.
 *
 * Resolution order, most explicit first:
 *   1. ORCH_EMBED_KEYS — JSON array in env, for local dev and for the founding
 *      tenant before any tenant admin UI exists.
 *   2. the embed_keys table, when reachable.
 *
 * Fail-soft returns an EMPTY list, and an empty list authorises nothing. That
 * is the correct failure direction here: if we cannot read the key table, no
 * host gets in, rather than every host getting in.
 */
import type { EmbedKeyRecord, EmbedSurface } from './embedProtocol'
import { EMBED_SURFACES } from './embedProtocol'

function coerce(raw: unknown): EmbedKeyRecord | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const tenantId = typeof r.tenantId === 'string' ? r.tenantId : (typeof r.tenant_id === 'string' ? r.tenant_id : '')
  const keyHash = typeof r.keyHash === 'string' ? r.keyHash : (typeof r.key_hash === 'string' ? r.key_hash : '')
  if (!tenantId || !/^[a-f0-9]{64}$/i.test(keyHash)) return null

  const originsRaw = (r.allowedOrigins ?? r.allowed_origins) as unknown
  const surfacesRaw = (r.surfaces ?? r.allowed_surfaces) as unknown
  const allowedOrigins = Array.isArray(originsRaw)
    ? originsRaw.filter((o): o is string => typeof o === 'string' && !!o.trim())
    : []
  const surfaces = Array.isArray(surfacesRaw)
    ? surfacesRaw.filter((s): s is EmbedSurface => EMBED_SURFACES.includes(s as EmbedSurface))
    : []

  return {
    tenantId,
    keyHash: keyHash.toLowerCase(),
    allowedOrigins,
    surfaces,
    revoked: r.revoked === true,
  }
}

function fromEnv(): EmbedKeyRecord[] {
  const raw = process.env.ORCH_EMBED_KEYS
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.map(coerce).filter((r): r is EmbedKeyRecord => r !== null)
  } catch {
    // A malformed env var must not authorise anything, and must not throw
    // during a request either.
    return []
  }
}

/**
 * All key records the server will consider.
 *
 * `loader` is injectable so the handler tests can drive this without a DB;
 * production passes nothing and gets env + table.
 */
export async function loadEmbedKeys(
  loader?: () => Promise<unknown[]>,
): Promise<EmbedKeyRecord[]> {
  const env = fromEnv()
  if (!loader) return env
  try {
    const rows = await loader()
    const fromDb = (Array.isArray(rows) ? rows : []).map(coerce).filter((r): r is EmbedKeyRecord => r !== null)
    // env first: an operator overriding locally should win over a stale row.
    const seen = new Set(env.map((r) => r.keyHash))
    return [...env, ...fromDb.filter((r) => !seen.has(r.keyHash))]
  } catch {
    return env
  }
}
