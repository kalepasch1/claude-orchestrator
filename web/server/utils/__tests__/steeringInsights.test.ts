import { describe, expect, it } from 'vitest'
import { LENSES, RISK_BANDS, rankInsights, shapeMatrix, summariseQuality, tally } from '../steeringInsights'
import { isTypingTarget, reduceKey, type KeyState, type SteeringView } from '../../../utils/steeringKeys'

describe('shapeMatrix', () => {
  const rows = [
    { vertical: 'gaming', lens: 'regulatory_gap', risk_band: 'high', status: 'pending', priority: 'high' },
    { vertical: 'gaming', lens: 'regulatory_gap', risk_band: 'high', status: 'answered', priority: 'high' },
    { vertical: 'data', lens: 'innovation_pathway', risk_band: 'upside', status: 'pending', priority: 'medium' },
    { vertical: 'data', lens: null, risk_band: null, status: 'pending', priority: 'medium' },
  ]
  it('always renders every cell so an empty cell is visible, not absent', () => {
    const m = shapeMatrix(rows)
    expect(m.cells).toHaveLength(LENSES.length * RISK_BANDS.length)
    expect(m.empty).toBe(LENSES.length * RISK_BANDS.length - 2)
    const cell = m.cells.find(c => c.lens === 'regulatory_gap' && c.risk_band === 'high')!
    expect(cell).toMatchObject({ total: 2, pending: 1, answered: 1 })
    expect(m.max).toBe(2)
  })
  it('counts untagged rows instead of guessing, and reports the shares that matter', () => {
    const m = shapeMatrix(rows)
    expect(m.untagged).toBe(1)
    expect(m.innovationShare).toBeCloseTo(0.25)
    expect(m.highPriorityShare).toBeCloseTo(0.5)
    expect(m.byVertical).toEqual({ gaming: { total: 2, answered: 1 }, data: { total: 2, answered: 0 } })
  })
  it('scopes to a vertical and survives no data', () => {
    expect(shapeMatrix(rows, 'data').total).toBe(2)
    const empty = shapeMatrix([])
    expect(empty.total).toBe(0); expect(empty.max).toBe(1); expect(empty.innovationShare).toBe(0)
  })
})

describe('rankInsights / tally', () => {
  it('orders by risk, kind and confidence; newest breaks ties', () => {
    const ranked = rankInsights([
      { id: 'low', kind: 'assumption', risk_band: 'low', confidence: 0.9, created_at: '2026-09-21' },
      { id: 'exist', kind: 'action', risk_band: 'existential', confidence: 0.6, created_at: '2026-09-01' },
      { id: 'up', kind: 'innovation', risk_band: 'upside', confidence: 0.8, created_at: '2026-09-20' },
    ])
    expect(ranked.map(r => r.id)).toEqual(['exist', 'up', 'low'])
    expect(tally(ranked, r => r.kind)).toEqual({ action: 1, innovation: 1, assumption: 1 })
  })
})

describe('summariseQuality', () => {
  it('separates fresh work from cache echo and names the worst habit per caller', () => {
    const q = summariseQuality([
      { operation: 'completion:committees', latency_ms: 0, quality_score: 1, verdict: 'cached:ok' },
      { operation: 'completion:committees', latency_ms: 900, quality_score: 0.5, verdict: 'placeholder' },
      { operation: 'completion:committees', latency_ms: 800, quality_score: 0.6, verdict: 'rubber_stamp' },
      { operation: 'completion:committees', latency_ms: 700, quality_score: 0.5, verdict: 'placeholder' },
      { operation: 'completion', latency_ms: 0, quality_score: null, verdict: null },
    ])
    expect(q).toMatchObject({ rows: 5, graded: 4, replays: 2, meanQuality: 0.65 })
    expect(q.callers[0]).toMatchObject({ caller: 'completion:committees', calls: 4, fresh: 3, flagged: 3, worst: 'placeholder', meanQuality: 0.65 })
    expect(q.callers[1]).toMatchObject({ caller: 'completion', graded: 0, meanQuality: null, worst: 'ok' })
  })
})

describe('reduceKey', () => {
  const views: SteeringView[] = [
    { key: 'o', id: 'overview', label: 'Overview', rows: 0 },
    { key: 'i', id: 'insights', label: 'Insights', rows: 3 },
    { key: 'm', id: 'memos', label: 'Memos', rows: 2 },
  ]
  const start: KeyState = { active: 'overview', row: 0, pendingG: false, focus: 'rail' }
  it('g then a view key jumps and focuses the rail row', () => {
    const a = reduceKey(start, 'g', views)
    expect(a.state.pendingG).toBe(true)
    const b = reduceKey(a.state, 'i', views)
    expect(b.effect).toEqual({ type: 'go', id: 'insights' })
    expect(b.state).toMatchObject({ active: 'insights', focus: 'rail', pendingG: false })
    expect(reduceKey(a.state, 'z', views).state.pendingG).toBe(false)
  })
  it('j / k walk the active section and clamp at both ends; Enter opens', () => {
    let s: KeyState = { active: 'insights', row: 0, pendingG: false, focus: 'rail' }
    const first = reduceKey(s, 'j', views); expect(first.effect).toEqual({ type: 'row', row: 0 }); s = first.state
    s = reduceKey(s, 'j', views).state; s = reduceKey(s, 'j', views).state
    expect(reduceKey(s, 'j', views).state.row).toBe(2)
    expect(reduceKey(s, 'Enter', views).effect).toEqual({ type: 'open', row: 2 })
    expect(reduceKey({ ...s, row: 0 }, 'k', views).state.row).toBe(0)
    expect(reduceKey(start, 'j', views).effect).toEqual({ type: 'none' })
    expect(reduceKey(start, 'Enter', views).effect).toEqual({ type: 'none' })
  })
  it('typing in a field never navigates', () => {
    expect(isTypingTarget('input')).toBe(true); expect(isTypingTarget('DIV', true)).toBe(true); expect(isTypingTarget('DIV')).toBe(false)
    expect(reduceKey({ ...start, pendingG: true }, 'i', views, true)).toEqual({ state: start, effect: { type: 'none' } })
  })
})
