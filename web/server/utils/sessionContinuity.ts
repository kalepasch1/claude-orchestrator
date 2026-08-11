/**
 * Session continuity — one shard per Nuxt app.
 *
 * A Nuxt server restart or a Vercel deployment replaces the process, so any
 * session state held in module memory disappears and the user is silently
 * logged out mid-task. This module keeps that state in a *shard*: one durable
 * namespace per app id, versioned by the deployment that wrote it, so a new
 * build can rehydrate what the previous build left behind.
 *
 * Design rules (match the repo's fail-soft convention):
 *  - Every exported function returns a sensible default on bad input and never
 *    throws — a store outage must degrade the session, not wedge the request.
 *  - Sync is revision-guarded, not clobbering: a stale writer cannot overwrite
 *    a newer revision, so two instances behind a load balancer converge.
 *  - Writes are coalesced per session (dirty-set flush) rather than one round
 *    trip per mutation.
 */

export interface SessionRecord {
  sessionId: string
  userId: string
  /** Arbitrary app state to survive a restart (draft form, wizard step, …). */
  data: Record<string, unknown>
  /** Monotonic per-session counter used to reject stale writes. */
  revision: number
  /** Deployment id that last wrote this record. */
  deploymentId: string
  updatedAt: number
  expiresAt: number
}

export interface ShardStore {
  read(shardKey: string): Promise<Record<string, SessionRecord> | null>
  write(shardKey: string, records: Record<string, SessionRecord>): Promise<void>
}

export interface ShardOptions {
  appId: string
  deploymentId?: string
  /** Session lifetime in ms. Default 12h. */
  ttlMs?: number
  now?: () => number
}

export const SHARD_PREFIX = 'session-shard'
const DEFAULT_TTL_MS = 12 * 60 * 60 * 1000

function str(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return fallback
}

function isRecord(value: unknown): value is SessionRecord {
  if (!value || typeof value !== 'object') return false
  const r = value as Partial<SessionRecord>
  return typeof r.sessionId === 'string' && r.sessionId.length > 0
    && typeof r.revision === 'number' && Number.isFinite(r.revision)
}

/**
 * Deterministic shard key for a Nuxt app. Exactly one shard per app id, so a
 * redeploy of the same app reads back the shard its predecessor wrote.
 */
export function shardKey(appId: unknown): string {
  const slug = str(appId).trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
  return `${SHARD_PREFIX}:${slug || 'default'}`
}

/** In-memory store. Correct within one process; used as the test/dev default. */
export function createMemoryStore(seed?: Record<string, Record<string, SessionRecord>>): ShardStore {
  const mem = new Map<string, Record<string, SessionRecord>>(Object.entries(seed || {}))
  return {
    async read(key) {
      const found = mem.get(key)
      return found ? JSON.parse(JSON.stringify(found)) : null
    },
    async write(key, records) {
      mem.set(key, JSON.parse(JSON.stringify(records)))
    },
  }
}

/** Drop records whose ttl elapsed. Pure; safe on malformed entries. */
export function pruneExpired(
  records: Record<string, SessionRecord> | null | undefined,
  now: number,
): Record<string, SessionRecord> {
  const out: Record<string, SessionRecord> = {}
  for (const [id, rec] of Object.entries(records || {})) {
    if (!isRecord(rec)) continue
    if (typeof rec.expiresAt === 'number' && rec.expiresAt <= now) continue
    out[id] = rec
  }
  return out
}

/**
 * Revision-guarded merge. `incoming` wins only when strictly newer; equal
 * revisions from different deployments tie-break on updatedAt so two instances
 * that raced converge to the same record.
 */
export function mergeRecord(existing: SessionRecord | undefined, incoming: SessionRecord): SessionRecord {
  if (!existing || !isRecord(existing)) return incoming
  if (incoming.revision > existing.revision) return incoming
  if (incoming.revision < existing.revision) return existing
  return incoming.updatedAt >= existing.updatedAt ? incoming : existing
}

export class SessionShard {
  readonly appId: string
  readonly key: string
  readonly deploymentId: string
  private readonly store: ShardStore
  private readonly ttlMs: number
  private readonly now: () => number
  private records: Record<string, SessionRecord> = {}
  private dirty = new Set<string>()
  private loaded = false
  /** Sessions that were written by a previous deployment and rehydrated here. */
  recoveredIds: string[] = []
  lastError: string | null = null

  constructor(store: ShardStore, opts: ShardOptions) {
    this.store = store
    this.appId = str(opts?.appId, 'default')
    this.key = shardKey(this.appId)
    this.deploymentId = str(opts?.deploymentId, 'local')
    this.ttlMs = typeof opts?.ttlMs === 'number' && opts.ttlMs > 0 ? opts.ttlMs : DEFAULT_TTL_MS
    this.now = typeof opts?.now === 'function' ? opts.now : () => Date.now()
  }

  /**
   * Rehydrate the shard. Called once on first use (and again after a deploy,
   * since the new process starts with `loaded === false`). Never throws: an
   * unreachable store yields an empty shard and a populated `lastError`.
   */
  async load(): Promise<SessionRecord[]> {
    if (this.loaded) return Object.values(this.records)
    try {
      const raw = await this.store.read(this.key)
      this.records = pruneExpired(raw, this.now())
      this.recoveredIds = Object.values(this.records)
        .filter(r => r.deploymentId !== this.deploymentId)
        .map(r => r.sessionId)
      this.lastError = null
    } catch (err) {
      this.records = {}
      this.recoveredIds = []
      this.lastError = err instanceof Error ? err.message : String(err)
    }
    this.loaded = true
    return Object.values(this.records)
  }

  async get(sessionId: unknown): Promise<SessionRecord | null> {
    const id = str(sessionId)
    if (!id) return null
    await this.load()
    const rec = this.records[id]
    if (!rec) return null
    if (rec.expiresAt <= this.now()) {
      delete this.records[id]
      this.dirty.add(id)
      return null
    }
    return rec
  }

  /**
   * Create or update a session. Marks the record dirty; call `flush()` (or
   * `save()`) to persist. Returns the stored record, or null on bad input.
   */
  async put(sessionId: unknown, userId: unknown, data?: Record<string, unknown>): Promise<SessionRecord | null> {
    const id = str(sessionId)
    if (!id) return null
    await this.load()
    const ts = this.now()
    const prev = this.records[id]
    const next: SessionRecord = {
      sessionId: id,
      userId: str(userId, prev?.userId || ''),
      data: { ...(prev?.data || {}), ...(data && typeof data === 'object' ? data : {}) },
      revision: (prev?.revision || 0) + 1,
      deploymentId: this.deploymentId,
      updatedAt: ts,
      expiresAt: ts + this.ttlMs,
    }
    this.records[id] = mergeRecord(prev, next)
    this.dirty.add(id)
    return this.records[id]
  }

  async remove(sessionId: unknown): Promise<boolean> {
    const id = str(sessionId)
    if (!id) return false
    await this.load()
    if (!(id in this.records)) return false
    delete this.records[id]
    this.dirty.add(id)
    return true
  }

  /**
   * Persist pending writes in one round trip. Re-reads the shard first and
   * merges, so a concurrent instance's newer revisions are not clobbered.
   * Returns false (and sets `lastError`) instead of throwing on store failure.
   */
  async flush(): Promise<boolean> {
    if (!this.dirty.size) return true
    try {
      const remote = pruneExpired(await this.store.read(this.key), this.now())
      const merged: Record<string, SessionRecord> = { ...remote }
      for (const id of this.dirty) {
        const local = this.records[id]
        if (!local) delete merged[id]
        else merged[id] = mergeRecord(remote[id], local)
      }
      for (const [id, rec] of Object.entries(this.records)) {
        if (!(id in merged) && !this.dirty.has(id)) merged[id] = mergeRecord(remote[id], rec)
      }
      await this.store.write(this.key, merged)
      this.records = merged
      this.dirty.clear()
      this.lastError = null
      return true
    } catch (err) {
      this.lastError = err instanceof Error ? err.message : String(err)
      return false
    }
  }

  /** Alias kept for call sites that read better as "save". */
  save(): Promise<boolean> {
    return this.flush()
  }

  /** Snapshot of live sessions. Empty array before load or on store failure. */
  list(): SessionRecord[] {
    return Object.values(this.records)
  }

  stats(): { appId: string; key: string; deploymentId: string; sessions: number; recovered: number; pending: number; error: string | null } {
    return {
      appId: this.appId,
      key: this.key,
      deploymentId: this.deploymentId,
      sessions: Object.keys(this.records).length,
      recovered: this.recoveredIds.length,
      pending: this.dirty.size,
      error: this.lastError,
    }
  }
}

/**
 * Open the shard for one Nuxt app and rehydrate it. This is the call a Nitro
 * plugin makes on boot: after a deployment it returns the sessions the previous
 * build left behind, already pruned of anything expired.
 */
export async function openShard(store: ShardStore, opts: ShardOptions): Promise<SessionShard> {
  const shard = new SessionShard(store, opts)
  await shard.load()
  return shard
}
