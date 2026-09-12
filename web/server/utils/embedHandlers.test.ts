import { describe, expect, it, vi } from 'vitest'
import { handleDecision, handleStatus, handleSubmit } from './embedHandlers'
import { hashKey, type EmbedKeyRecord } from './embedProtocol'

/**
 * The proof line for §3: a fixture host page on ANOTHER ORIGIN mounts the
 * widget, submits an outcome, and sees it land in the queue — with the auth
 * handshake mocked. That is the first test here.
 *
 * The rest are the ways the same endpoints could leak between tenants, which is
 * the risk that actually matters once a second tenant exists.
 */

const KEY = 'mk_live_hostpage'
const HOST_ORIGIN = 'https://apparently.cc'

const keys: EmbedKeyRecord[] = [{
  tenantId: 'tenant-a',
  keyHash: hashKey(KEY),
  allowedOrigins: [HOST_ORIGIN],
  surfaces: ['strip', 'universal_command', 'signoffs'],
}]

describe('handleSubmit — the fixture host page path', () => {
  it('accepts an outcome from an allow-listed third-party origin and queues it', async () => {
    const queue: unknown[] = []
    const res = await handleSubmit(
      { key: KEY, origin: HOST_ORIGIN, surface: 'universal_command',
        body: { outcome: 'Draft the Q3 compliance pack', hostApp: 'apparently' } },
      { keys, enqueue: async (s) => { queue.push(s); return 'q-1' } },
    )
    expect(res.status).toBe(202)
    expect(res.body.queueId).toBe('q-1')
    expect(queue).toHaveLength(1)
    expect(queue[0]).toMatchObject({ tenantId: 'tenant-a', hostApp: 'apparently' })
  })

  it('stamps the tenant from the KEY even when the payload claims another', async () => {
    const enqueue = vi.fn(async () => 'q-2')
    await handleSubmit(
      { key: KEY, origin: HOST_ORIGIN, surface: 'universal_command',
        body: { outcome: 'x', hostApp: 'apparently', tenantId: 'tenant-b' } },
      { keys, enqueue },
    )
    expect(enqueue.mock.calls[0][0]).toMatchObject({ tenantId: 'tenant-a' })
  })

  it('refuses a submission from an origin the tenant never declared', async () => {
    const enqueue = vi.fn(async () => 'q-3')
    const res = await handleSubmit(
      { key: KEY, origin: 'https://evil.example', surface: 'universal_command',
        body: { outcome: 'x', hostApp: 'apparently' } },
      { keys, enqueue },
    )
    expect(res.status).toBe(403)
    expect(enqueue).not.toHaveBeenCalled()
  })

  it('refuses a surface the key does not hold', async () => {
    const res = await handleSubmit(
      { key: KEY, origin: HOST_ORIGIN, surface: 'tenancy_admin',
        body: { outcome: 'x', hostApp: 'apparently' } },
      { keys, enqueue: async () => 'q' },
    )
    expect(res.status).toBe(403)
  })

  it('rejects a malformed body with 400, not 403', async () => {
    const res = await handleSubmit(
      { key: KEY, origin: HOST_ORIGIN, surface: 'universal_command', body: { hostApp: 'apparently' } },
      { keys, enqueue: async () => 'q' },
    )
    expect(res.status).toBe(400)
  })

  it('reports an enqueue failure instead of returning a hollow 202', async () => {
    const res = await handleSubmit(
      { key: KEY, origin: HOST_ORIGIN, surface: 'universal_command',
        body: { outcome: 'x', hostApp: 'apparently' } },
      { keys, enqueue: async () => { throw new Error('db down') } },
    )
    expect(res.status).toBe(503)
    expect(String(res.body.reason)).toMatch(/db down/)
  })
})

describe('handleStatus', () => {
  it('returns the strip data scoped to the authenticated tenant', async () => {
    const fetchStatus = vi.fn(async () => ({ runningTasks: 2, queuedTasks: 5, pendingApprovals: [] }))
    const res = await handleStatus({ key: KEY, origin: HOST_ORIGIN, surface: 'strip' }, { keys, fetchStatus })
    expect(res.status).toBe(200)
    expect(res.body.tenantId).toBe('tenant-a')
    expect(fetchStatus).toHaveBeenCalledWith('tenant-a')
  })

  it('never calls the fetcher when auth fails', async () => {
    const fetchStatus = vi.fn(async () => ({ runningTasks: 0, queuedTasks: 0, pendingApprovals: [] }))
    const res = await handleStatus({ key: 'wrong', origin: HOST_ORIGIN, surface: 'strip' }, { keys, fetchStatus })
    expect(res.status).toBe(403)
    expect(fetchStatus).not.toHaveBeenCalled()
  })

  it('degrades to 503 rather than throwing at the host', async () => {
    const res = await handleStatus(
      { key: KEY, origin: HOST_ORIGIN, surface: 'strip' },
      { keys, fetchStatus: async () => { throw new Error('timeout') } },
    )
    expect(res.status).toBe(503)
  })
})

describe('handleDecision — the return leg', () => {
  const baseDeps = {
    keys,
    approvalTenant: async () => 'tenant-a',
    applyDecision: vi.fn(async () => {}),
    recordSteering: vi.fn(async () => true),
  }

  it('writes decided_by back and records attributed steering', async () => {
    const applyDecision = vi.fn(async () => {})
    const recordSteering = vi.fn(async () => true)
    const res = await handleDecision(
      { key: KEY, origin: HOST_ORIGIN, surface: 'signoffs',
        body: { approvalId: 'a-1', decision: 'approved', decidedBy: 'u-9',
                decidedByLabel: 'Counsel', rationale: 'ok', hostApp: 'smarter' } },
      { ...baseDeps, applyDecision, recordSteering },
    )
    expect(res.status).toBe(200)
    expect(res.body.steeringRecorded).toBe(true)
    expect(applyDecision).toHaveBeenCalledWith({ approvalId: 'a-1', decision: 'approved', decidedBy: 'u-9' })
    expect(recordSteering.mock.calls[0][0]).toMatchObject({
      decidedByLabel: 'Counsel', hostApp: 'smarter', tenantId: 'tenant-a',
    })
  })

  it('refuses to decide another tenant’s approval, and does not leak its existence', async () => {
    const applyDecision = vi.fn(async () => {})
    const res = await handleDecision(
      { key: KEY, origin: HOST_ORIGIN, surface: 'signoffs',
        body: { approvalId: 'b-1', decision: 'approved', decidedBy: 'u-9', hostApp: 'smarter' } },
      { ...baseDeps, approvalTenant: async () => 'tenant-b', applyDecision },
    )
    expect(res.status).toBe(404) // 404, not 403: existence is not disclosed
    expect(applyDecision).not.toHaveBeenCalled()
  })

  it('404s an approval that does not exist', async () => {
    const res = await handleDecision(
      { key: KEY, origin: HOST_ORIGIN, surface: 'signoffs',
        body: { approvalId: 'nope', decision: 'approved', decidedBy: 'u', hostApp: 'smarter' } },
      { ...baseDeps, approvalTenant: async () => null },
    )
    expect(res.status).toBe(404)
  })

  it('refuses an unattributed decision before touching the approval', async () => {
    const applyDecision = vi.fn(async () => {})
    const res = await handleDecision(
      { key: KEY, origin: HOST_ORIGIN, surface: 'signoffs',
        body: { approvalId: 'a-1', decision: 'approved', hostApp: 'smarter' } },
      { ...baseDeps, applyDecision },
    )
    expect(res.status).toBe(400)
    expect(applyDecision).not.toHaveBeenCalled()
  })

  it('reports a failed audit write without rolling back a human decision', async () => {
    const res = await handleDecision(
      { key: KEY, origin: HOST_ORIGIN, surface: 'signoffs',
        body: { approvalId: 'a-1', decision: 'rejected', decidedBy: 'u-9', hostApp: 'smarter' } },
      { ...baseDeps, recordSteering: async () => false },
    )
    expect(res.status).toBe(200)
    expect(res.body.steeringRecorded).toBe(false)
  })
})
