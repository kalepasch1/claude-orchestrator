import { beforeEach, describe, expect, it } from 'vitest'
import {
  SHARD_PREFIX,
  SessionShard,
  createMemoryStore,
  mergeRecord,
  openShard,
  pruneExpired,
  shardKey,
  type SessionRecord,
  type ShardStore,
} from './sessionContinuity'

/** A store that outlives the "process", so a redeploy can read it back. */
function durableStore() {
  const disk = new Map<string, string>()
  const store: ShardStore & { failNext: boolean; writes: number } = {
    failNext: false,
    writes: 0,
    async read(key) {
      if (store.failNext) { store.failNext = false; throw new Error('store unreachable') }
      const raw = disk.get(key)
      return raw ? JSON.parse(raw) : null
    },
    async write(key, records) {
      if (store.failNext) { store.failNext = false; throw new Error('store unreachable') }
      store.writes += 1
      disk.set(key, JSON.stringify(records))
    },
  }
  return store
}

let clock = 1_000_000
const now = () => clock

beforeEach(() => { clock = 1_000_000 })

describe('shardKey', () => {
  it('is one deterministic shard per app id', () => {
    expect(shardKey('web')).toBe(`${SHARD_PREFIX}:web`)
    expect(shardKey('web')).toBe(shardKey('web'))
    expect(shardKey('Web App!')).toBe(`${SHARD_PREFIX}:web-app`)
  })

  it('never collides across different apps', () => {
    expect(shardKey('orchestrator')).not.toBe(shardKey('marketing'))
  })

  it('falls back for empty or non-string input', () => {
    for (const bad of ['', '   ', null, undefined, {}, 0]) {
      expect(shardKey(bad)).toBe(`${SHARD_PREFIX}:default`)
    }
  })
})

describe('pruneExpired', () => {
  const rec = (id: string, expiresAt: number): SessionRecord => ({
    sessionId: id, userId: 'u', data: {}, revision: 1, deploymentId: 'd', updatedAt: 0, expiresAt,
  })

  it('drops elapsed records and keeps live ones', () => {
    const out = pruneExpired({ a: rec('a', 500), b: rec('b', 5000) }, 1000)
    expect(Object.keys(out)).toEqual(['b'])
  })

  it('is fail-soft on null and malformed entries', () => {
    expect(pruneExpired(null, 1)).toEqual({})
    expect(pruneExpired({ a: 'junk' as never, b: null as never }, 1)).toEqual({})
  })
})

describe('mergeRecord', () => {
  const at = (revision: number, updatedAt: number, deploymentId = 'd'): SessionRecord => ({
    sessionId: 's', userId: 'u', data: { revision }, revision, deploymentId, updatedAt, expiresAt: 9e9,
  })

  it('takes the higher revision', () => {
    expect(mergeRecord(at(1, 10), at(2, 5)).revision).toBe(2)
  })

  it('rejects a stale writer', () => {
    expect(mergeRecord(at(3, 10), at(2, 99)).revision).toBe(3)
  })

  it('tie-breaks equal revisions on updatedAt', () => {
    expect(mergeRecord(at(2, 50, 'old'), at(2, 20, 'new')).deploymentId).toBe('old')
    expect(mergeRecord(at(2, 20, 'old'), at(2, 50, 'new')).deploymentId).toBe('new')
  })

  it('accepts incoming when there is no existing record', () => {
    expect(mergeRecord(undefined, at(1, 1)).revision).toBe(1)
  })
})

describe('SessionShard basics', () => {
  it('stores, reads back and expires sessions', async () => {
    const shard = new SessionShard(createMemoryStore(), { appId: 'web', ttlMs: 1000, now })
    await shard.put('s1', 'user-1', { step: 3 })
    expect((await shard.get('s1'))?.data).toEqual({ step: 3 })

    clock += 1001
    expect(await shard.get('s1')).toBeNull()
  })

  it('merges data across writes and bumps the revision', async () => {
    const shard = new SessionShard(createMemoryStore(), { appId: 'web', now })
    await shard.put('s1', 'user-1', { step: 1 })
    const second = await shard.put('s1', 'user-1', { draft: 'hello' })
    expect(second?.data).toEqual({ step: 1, draft: 'hello' })
    expect(second?.revision).toBe(2)
  })

  it('returns null / false on bad input instead of throwing', async () => {
    const shard = new SessionShard(createMemoryStore(), { appId: 'web', now })
    expect(await shard.put('', 'u')).toBeNull()
    expect(await shard.put(null, 'u')).toBeNull()
    expect(await shard.get(undefined)).toBeNull()
    expect(await shard.remove('missing')).toBe(false)
  })

  it('removes sessions and persists the removal', async () => {
    const store = durableStore()
    const shard = new SessionShard(store, { appId: 'web', now })
    await shard.put('s1', 'u')
    await shard.flush()
    expect(await shard.remove('s1')).toBe(true)
    await shard.flush()

    const reopened = await openShard(store, { appId: 'web', now })
    expect(reopened.list()).toHaveLength(0)
  })
})

describe('efficient synchronization', () => {
  it('coalesces many mutations into a single write', async () => {
    const store = durableStore()
    const shard = new SessionShard(store, { appId: 'web', now })
    for (let i = 0; i < 25; i += 1) await shard.put(`s${i}`, 'u', { i })
    expect(store.writes).toBe(0)
    expect(await shard.flush()).toBe(true)
    expect(store.writes).toBe(1)
  })

  it('flushing with nothing pending does no io', async () => {
    const store = durableStore()
    const shard = new SessionShard(store, { appId: 'web', now })
    await shard.load()
    expect(await shard.flush()).toBe(true)
    expect(store.writes).toBe(0)
  })

  it('does not clobber a concurrent instance behind the load balancer', async () => {
    const store = durableStore()
    const a = await openShard(store, { appId: 'web', deploymentId: 'inst-a', now })
    const b = await openShard(store, { appId: 'web', deploymentId: 'inst-b', now })

    await a.put('shared', 'u', { from: 'a' })
    await a.flush()
    await b.put('only-b', 'u', { from: 'b' })
    await b.flush()

    const reader = await openShard(store, { appId: 'web', deploymentId: 'inst-c', now })
    expect(reader.list().map(r => r.sessionId).sort()).toEqual(['only-b', 'shared'])
  })

  it('a stale writer cannot overwrite a newer revision', async () => {
    const store = durableStore()
    const fresh = await openShard(store, { appId: 'web', deploymentId: 'new', now })
    await fresh.put('s1', 'u', { v: 1 })
    await fresh.put('s1', 'u', { v: 2 })
    await fresh.put('s1', 'u', { v: 3 })
    await fresh.flush()

    const stale = await openShard(store, { appId: 'web', deploymentId: 'old', now })
    // stale opened after the fact; force it to hold an older revision
    ;(stale as unknown as { records: Record<string, SessionRecord> }).records.s1 = {
      sessionId: 's1', userId: 'u', data: { v: 0 }, revision: 1,
      deploymentId: 'old', updatedAt: clock, expiresAt: clock + 9e6,
    }
    ;(stale as unknown as { dirty: Set<string> }).dirty.add('s1')
    await stale.flush()

    const reader = await openShard(store, { appId: 'web', now })
    expect((await reader.get('s1'))?.data).toEqual({ v: 3 })
  })
})

describe('integration: recovery after a simulated deployment', () => {
  it('rehydrates sessions written by the previous build', async () => {
    const store = durableStore()

    // --- build v1 serves traffic ---
    const v1 = await openShard(store, { appId: 'web', deploymentId: 'build-v1', ttlMs: 60_000, now })
    await v1.put('sess-alice', 'alice', { cart: ['a'], step: 2 })
    await v1.put('sess-bob', 'bob', { step: 5 })
    await v1.flush()

    // --- deployment: process replaced, module memory gone ---
    clock += 30_000
    const v2 = await openShard(store, { appId: 'web', deploymentId: 'build-v2', ttlMs: 60_000, now })

    expect(v2.recoveredIds.sort()).toEqual(['sess-alice', 'sess-bob'])
    expect((await v2.get('sess-alice'))?.data).toEqual({ cart: ['a'], step: 2 })
    expect(v2.stats()).toMatchObject({ appId: 'web', sessions: 2, recovered: 2, deploymentId: 'build-v2' })
  })

  it('does not resurrect sessions that expired during the deploy window', async () => {
    const store = durableStore()
    const v1 = await openShard(store, { appId: 'web', deploymentId: 'v1', ttlMs: 10_000, now })
    await v1.put('short', 'u')
    await v1.flush()

    clock += 20_000
    const v2 = await openShard(store, { appId: 'web', deploymentId: 'v2', ttlMs: 10_000, now })
    expect(v2.list()).toHaveLength(0)
    expect(v2.recoveredIds).toEqual([])
  })

  it('keeps app shards isolated across a fleet-wide redeploy', async () => {
    const store = durableStore()
    const webV1 = await openShard(store, { appId: 'web', deploymentId: 'v1', now })
    const adminV1 = await openShard(store, { appId: 'admin', deploymentId: 'v1', now })
    await webV1.put('s-web', 'u', { app: 'web' })
    await adminV1.put('s-admin', 'u', { app: 'admin' })
    await webV1.flush()
    await adminV1.flush()

    const webV2 = await openShard(store, { appId: 'web', deploymentId: 'v2', now })
    const adminV2 = await openShard(store, { appId: 'admin', deploymentId: 'v2', now })
    expect(webV2.list().map(r => r.sessionId)).toEqual(['s-web'])
    expect(adminV2.list().map(r => r.sessionId)).toEqual(['s-admin'])
  })

  it('survives a restart mid-edit: unflushed work is lost, flushed work is not', async () => {
    const store = durableStore()
    const v1 = await openShard(store, { appId: 'web', deploymentId: 'v1', now })
    await v1.put('s1', 'u', { saved: true })
    await v1.flush()
    await v1.put('s1', 'u', { unsaved: true }) // never flushed — process dies here

    const v2 = await openShard(store, { appId: 'web', deploymentId: 'v2', now })
    expect((await v2.get('s1'))?.data).toEqual({ saved: true })
  })
})

describe('error handling', () => {
  it('an unreachable store on load yields an empty shard, not a throw', async () => {
    const store = durableStore()
    store.failNext = true
    const shard = await openShard(store, { appId: 'web', now })
    expect(shard.list()).toEqual([])
    expect(shard.lastError).toBe('store unreachable')
    expect(shard.stats().error).toBe('store unreachable')
  })

  it('a failed flush reports false and keeps the work pending for a retry', async () => {
    const store = durableStore()
    const shard = await openShard(store, { appId: 'web', now })
    await shard.put('s1', 'u', { v: 1 })
    store.failNext = true
    expect(await shard.flush()).toBe(false)
    expect(shard.stats().pending).toBe(1)

    expect(await shard.flush()).toBe(true)
    const reader = await openShard(store, { appId: 'web', now })
    expect((await reader.get('s1'))?.data).toEqual({ v: 1 })
  })

  it('tolerates corrupt shard contents', async () => {
    const store = createMemoryStore({
      [shardKey('web')]: { good: { sessionId: 'good', userId: 'u', data: {}, revision: 1, deploymentId: 'v1', updatedAt: 0, expiresAt: 9e9 }, bad: 'junk' as never },
    })
    const shard = await openShard(store, { appId: 'web', now })
    expect(shard.list().map(r => r.sessionId)).toEqual(['good'])
  })
})
