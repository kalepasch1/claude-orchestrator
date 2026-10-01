/**
 * /api/_fleet-relay FAILS CLOSED: every request is refused 401 unless
 * FLEET_RELAY_KEY is set AND x-fleet-relay-key matches it. Before 2026-10-01 an
 * unset key meant "no gate", i.e. an open transport to the allowlisted
 * Supabase projects. Runs the real handler; upstream fetch is stubbed and must
 * not be reached on a refusal.
 */
import { IncomingMessage, ServerResponse } from 'node:http'
import { Socket } from 'node:net'
import * as h3 from 'h3'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fleetRelayKeyMatches } from '../fleetRelayKey'

const KEY = 'k'.repeat(43)
const upstream = vi.fn(async () => new Response('[]', { status: 200, headers: { 'content-type': 'application/json' } }))

async function call (headers: Record<string, string>, path = 'rest/v1/tasks') {
  const req = new IncomingMessage(new Socket())
  req.method = 'GET'
  req.url = `/api/_fleet-relay/${path}`
  req.headers = { host: 'www.madeus.cc', ...headers }
  const res = new ServerResponse(req)
  const e = h3.createEvent(req, res)
  e.context.params = { path }
  const handler = (await import('../../api/_fleet-relay/[...path].ts')).default as (e: unknown) => Promise<any>
  const out = await handler(e)
  return { out, status: res.statusCode }
}

beforeEach(() => { upstream.mockClear(); vi.stubGlobal('fetch', upstream) })
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals() })

describe('the fleet relay gate', () => {
  it('refuses everything when FLEET_RELAY_KEY is unset, even a request carrying a key', async () => {
    vi.stubEnv('FLEET_RELAY_KEY', '')
    for (const headers of [{}, { 'x-fleet-relay-key': KEY }]) {
      const { status, out } = await call(headers)
      expect(status).toBe(401)
      expect(out).toEqual({ error: 'relay key required' })
    }
    expect((await call({}, 'healthz')).status).toBe(401)
    expect(upstream).not.toHaveBeenCalled()
  })

  it('refuses a missing or wrong key when one is configured', async () => {
    vi.stubEnv('FLEET_RELAY_KEY', KEY)
    expect((await call({})).status).toBe(401)
    expect((await call({ 'x-fleet-relay-key': KEY + 'x' })).status).toBe(401)
    expect((await call({ 'x-fleet-relay-key': KEY.slice(1) })).status).toBe(401)
    expect(upstream).not.toHaveBeenCalled()
  })

  it('admits the matching key (healthz answers without reaching upstream)', async () => {
    vi.stubEnv('FLEET_RELAY_KEY', KEY)
    const { status, out } = await call({ 'x-fleet-relay-key': KEY }, 'healthz')
    expect(status).toBe(200)
    expect(out.ok).toBe(true)
  })

  it('compares without short-circuiting on length', () => {
    expect(fleetRelayKeyMatches(KEY, KEY)).toBe(true)
    expect(fleetRelayKeyMatches('', KEY)).toBe(false)
    expect(fleetRelayKeyMatches(KEY, '')).toBe(false)
    expect(fleetRelayKeyMatches(KEY, '   ')).toBe(false)
    expect(fleetRelayKeyMatches(undefined, KEY)).toBe(false)
  })
})
