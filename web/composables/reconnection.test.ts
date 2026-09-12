// Slice 2 acceptance: `npm test -- reconnection`.
//
// Covers the client half of "reconnection and error handling": exponential backoff
// with a capped attempt budget, and a re-sync request once the channel comes back.
// Everything here runs against the pure policy plus a fake Supabase channel, so no
// socket, no component mount, and no wall-clock waiting.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// onMounted/onUnmounted are only meaningful inside a component instance. Mocking the
// module is the only way to intercept them — vue's ESM exports are read-only, so
// vi.spyOn on them throws "Cannot redefine property".
vi.mock('vue', async () => {
  const actual = await vi.importActual<typeof import('vue')>('vue')
  return {
    ...actual,
    onMounted: (fn: any) => fn(),
    onUnmounted: () => undefined,
  }
})

import {
  buildRequestInitialState,
  createReconnectPolicy,
  isDeadStatus,
  nextBackoffDelay,
  RECONNECT_DEFAULTS,
  REQUEST_INITIAL_STATE,
} from './useFleetReconnect'

describe('isDeadStatus', () => {
  it('treats channel error, timeout and close as a dropped connection', () => {
    expect(isDeadStatus('CHANNEL_ERROR')).toBe(true)
    expect(isDeadStatus('TIMED_OUT')).toBe(true)
    expect(isDeadStatus('CLOSED')).toBe(true)
  })

  it('does not treat a successful subscribe as a drop', () => {
    expect(isDeadStatus('SUBSCRIBED')).toBe(false)
  })

  it('never throws on junk input', () => {
    expect(isDeadStatus(undefined as any)).toBe(false)
    expect(isDeadStatus('' as any)).toBe(false)
  })
})

describe('nextBackoffDelay', () => {
  const noJitter = { jitter: 0, baseMs: 1000, factor: 2, maxMs: 30000 }

  it('doubles the delay on each successive attempt', () => {
    expect(nextBackoffDelay(1, noJitter)).toBe(1000)
    expect(nextBackoffDelay(2, noJitter)).toBe(2000)
    expect(nextBackoffDelay(3, noJitter)).toBe(4000)
    expect(nextBackoffDelay(4, noJitter)).toBe(8000)
  })

  it('caps at maxMs instead of growing without bound', () => {
    expect(nextBackoffDelay(20, noJitter)).toBe(30000)
  })

  it('applies symmetric jitter so tabs do not retry in lockstep', () => {
    const low = nextBackoffDelay(1, { ...noJitter, jitter: 0.2 }, () => 0)
    const high = nextBackoffDelay(1, { ...noJitter, jitter: 0.2 }, () => 1)
    expect(low).toBe(800)
    expect(high).toBe(1200)
  })

  it('never returns 0, which would be a busy loop rather than a retry', () => {
    expect(nextBackoffDelay(1, { baseMs: 0, jitter: 0 })).toBeGreaterThan(0)
  })

  it('falls back to defaults on unusable options', () => {
    const delay = nextBackoffDelay(1, { baseMs: NaN as any, jitter: 0 })
    expect(delay).toBe(RECONNECT_DEFAULTS.baseMs)
  })
})

describe('createReconnectPolicy', () => {
  it('returns a growing delay per consecutive failure', () => {
    const policy = createReconnectPolicy({ jitter: 0, baseMs: 100, factor: 2, maxAttempts: 5 })
    expect(policy.fail()).toBe(100)
    expect(policy.fail()).toBe(200)
    expect(policy.fail()).toBe(400)
    expect(policy.attempts).toBe(3)
  })

  it('gives up after maxAttempts consecutive failures', () => {
    const policy = createReconnectPolicy({ jitter: 0, baseMs: 1, maxAttempts: 2 })
    expect(policy.fail()).not.toBeNull()
    expect(policy.fail()).not.toBeNull()
    expect(policy.fail()).toBeNull()
    expect(policy.exhausted).toBe(true)
  })

  it('resets the budget after a successful subscribe', () => {
    const policy = createReconnectPolicy({ jitter: 0, baseMs: 100, maxAttempts: 3 })
    policy.fail()
    policy.fail()
    policy.succeed()
    expect(policy.attempts).toBe(0)
    expect(policy.exhausted).toBe(false)
    expect(policy.fail()).toBe(100)
  })
})

describe('request-initial-state', () => {
  it('carries the last-seen timestamp so the catch-up is incremental', () => {
    const msg = buildRequestInitialState('2026-08-24T05:00:00.000Z', 2)
    expect(msg).toEqual({
      type: REQUEST_INITIAL_STATE,
      since: '2026-08-24T05:00:00.000Z',
      attempts: 2,
    })
  })

  it('uses null rather than undefined when nothing has been seen yet', () => {
    expect(buildRequestInitialState(undefined as any).since).toBeNull()
  })
})

// --- Integration: a dropped connection reconnects after the delay -------------
//
// The composable is driven through its exposed status callback with a fake channel,
// which is exactly what Supabase Realtime does to it in production.

function makeFakeSupabase() {
  const subscribes: Array<(status: string) => void> = []
  const removed: any[] = []
  const channel = {
    on() {
      return channel
    },
    subscribe(cb: (status: string) => void) {
      subscribes.push(cb)
      return channel
    },
  }
  return {
    channel: () => channel,
    removeChannel: (c: any) => removed.push(c),
    _subscribes: subscribes,
    _removed: removed,
  }
}

describe('useFleetWebSocket reconnection', () => {
  let harness: any

  beforeEach(async () => {
    vi.useFakeTimers()
    const fake = makeFakeSupabase()
    // useSupabaseClient and the Vue lifecycle hooks are Nuxt auto-imports; stub them
    // so the composable can be exercised outside a component.
    ;(globalThis as any).useSupabaseClient = () => fake
    harness = { fake }
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    delete (globalThis as any).useSupabaseClient
  })

  async function mount() {
    const mod = await import('./useFleetWebSocket')
    return mod.useFleetWebSocket({ jitter: 0, baseMs: 1000, factor: 2, maxAttempts: 3 })
  }

  it('reconnects after the backoff delay when the connection drops', async () => {
    const ws = await mount()
    ws._onStatus('SUBSCRIBED')
    expect(ws.connected.value).toBe(true)

    ws._onStatus('CHANNEL_ERROR')
    expect(ws.connected.value).toBe(false)
    expect(ws.reconnectAttempt.value).toBe(1)

    // Nothing happens before the delay elapses...
    vi.advanceTimersByTime(999)
    expect(harness.fake._subscribes.length).toBe(1)

    // ...and a fresh subscribe happens once it does.
    vi.advanceTimersByTime(1)
    expect(harness.fake._subscribes.length).toBe(2)
  })

  it('backs off further on each successive failure', async () => {
    const ws = await mount()
    ws._onStatus('SUBSCRIBED')

    ws._onStatus('TIMED_OUT')
    vi.advanceTimersByTime(1000)
    expect(harness.fake._subscribes.length).toBe(2)

    ws._onStatus('TIMED_OUT')
    vi.advanceTimersByTime(1000)
    expect(harness.fake._subscribes.length).toBe(2) // 2000ms delay, not 1000
    vi.advanceTimersByTime(1000)
    expect(harness.fake._subscribes.length).toBe(3)
  })

  it('stops and reports exhaustion instead of retrying forever', async () => {
    const ws = await mount()
    ws._onStatus('SUBSCRIBED')

    for (let i = 0; i < 4; i += 1) {
      ws._onStatus('CHANNEL_ERROR')
      vi.advanceTimersByTime(60000)
    }

    expect(ws.reconnectExhausted.value).toBe(true)
    expect(ws.events.value.some((e: any) => e.topic === 'sync:failed')).toBe(true)
  })

  it('requests initial state after reconnecting, but not on first connect', async () => {
    const ws = await mount()

    ws._onStatus('SUBSCRIBED')
    expect(ws.events.value.some((e: any) => e.topic === 'sync:request')).toBe(false)

    ws._onStatus('CLOSED')
    vi.advanceTimersByTime(1000)
    ws._onStatus('SUBSCRIBED')

    const resync = ws.events.value.find((e: any) => e.topic === 'sync:request')
    expect(resync).toBeTruthy()
    expect(resync.payload.type).toBe(REQUEST_INITIAL_STATE)
    expect(resync.payload.attempts).toBe(1)
  })

  it('removes the dead channel before opening a new one', async () => {
    const ws = await mount()
    ws._onStatus('SUBSCRIBED')
    ws._onStatus('CHANNEL_ERROR')
    vi.advanceTimersByTime(1000)
    expect(harness.fake._removed.length).toBe(1)
  })

  it('cancels a pending retry on teardown', async () => {
    const ws = await mount()
    ws._onStatus('SUBSCRIBED')
    ws._onStatus('CHANNEL_ERROR')
    ws._dispose()
    vi.advanceTimersByTime(60000)
    expect(harness.fake._subscribes.length).toBe(1)
  })
})
