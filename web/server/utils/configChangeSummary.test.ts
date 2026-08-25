import { describe, it, expect } from 'vitest'
import { summarizeConfigChanges, STALE_PENDING_MS } from './configChangeSummary'

const NOW = Date.parse('2026-08-25T12:00:00.000Z')
const ago = (ms: number) => new Date(NOW - ms).toISOString()

const req = (over: Partial<Parameters<typeof summarizeConfigChanges>[0][number]> = {}) => ({
  id: 'r1',
  key: 'ORCH_X',
  value: 'true',
  requester: 'bear',
  status: 'pending',
  created_at: ago(60_000),
  ...over,
})

describe('summarizeConfigChanges', () => {
  it('counts each status and ignores unknown ones separately', () => {
    const s = summarizeConfigChanges(
      [
        req({ id: 'a', status: 'pending' }),
        req({ id: 'b', status: 'approved' }),
        req({ id: 'c', status: 'rejected' }),
        req({ id: 'd', status: 'withdrawn' }),
      ],
      [],
      NOW,
    )
    expect(s.counts).toEqual({ pending: 1, approved: 1, rejected: 1, other: 1 })
    expect(s.total).toBe(4)
  })

  it('only lists pending rows as pending', () => {
    const s = summarizeConfigChanges(
      [req({ id: 'a', status: 'pending' }), req({ id: 'b', status: 'approved' })],
      [],
      NOW,
    )
    expect(s.pending.map((p) => p.id)).toEqual(['a'])
  })

  it('flags a pending request older than the stale window, but not one inside it', () => {
    const s = summarizeConfigChanges(
      [
        req({ id: 'old', created_at: ago(STALE_PENDING_MS + 60_000) }),
        req({ id: 'fresh', created_at: ago(STALE_PENDING_MS - 60_000) }),
      ],
      [],
      NOW,
    )
    expect(s.stalePending).toBe(1)
    expect(s.stalePendingIds).toEqual(['old'])
  })

  // An unparseable timestamp read as epoch-0 would age to ~56 years and page someone
  // every refresh, so a row we cannot date must never be the thing that raises an alarm.
  it('never ages or stales a row whose created_at cannot be parsed', () => {
    const s = summarizeConfigChanges(
      [req({ id: 'bad', created_at: 'not-a-date' }), req({ id: 'missing', created_at: null })],
      [],
      NOW,
    )
    expect(s.pending.map((p) => p.ageMs)).toEqual([0, 0])
    expect(s.stalePending).toBe(0)
  })

  it('attaches the newest decision per request and leaves undecided rows null', () => {
    const s = summarizeConfigChanges(
      [req({ id: 'a', status: 'approved' }), req({ id: 'b', status: 'pending' })],
      [
        { request_id: 'a', approver: 'bear', decision: 'approved', decided_at: ago(1_000) },
        { request_id: 'a', approver: 'stale', decision: 'rejected', decided_at: ago(9_000) },
      ],
      NOW,
    )
    const byId = Object.fromEntries(s.recent.map((r) => [r.id, r]))
    expect(byId.a.lastDecision?.approver).toBe('bear')
    expect(byId.b.lastDecision).toBeNull()
  })

  it('passes read errors through so the page can show a partial-read banner', () => {
    const s = summarizeConfigChanges([], [], NOW, ['config_approvals: boom'])
    expect(s.errors).toEqual(['config_approvals: boom'])
    expect(s.counts.pending).toBe(0)
  })

  it('caps the recent and decision lists at 25', () => {
    const many = Array.from({ length: 40 }, (_, i) => req({ id: `r${i}` }))
    const decisions = Array.from({ length: 40 }, (_, i) => ({ request_id: `r${i}`, approver: 'x' }))
    const s = summarizeConfigChanges(many, decisions, NOW)
    expect(s.recent).toHaveLength(25)
    expect(s.decisions).toHaveLength(25)
    expect(s.total).toBe(40)
  })
})
