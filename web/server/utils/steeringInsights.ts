/**
 * Expert insights — the web half of runner/docket_matrix.py and runner/steering_insights.py.
 * Pure shaping only, so the page and the API can be tested without a database.
 */
export const LENSES = ['regulatory_gap', 'enforcement_trend', 'cross_industry_analog', 'innovation_pathway', 'red_team', 'opportunity'] as const
export const INNOVATION_LENSES = ['cross_industry_analog', 'innovation_pathway', 'opportunity'] as const
export const RISK_BANDS = ['existential', 'high', 'medium', 'low', 'upside'] as const
export const INSIGHT_KINDS = ['action', 'gap', 'tripwire', 'innovation', 'opportunity', 'assumption'] as const
export const LENS_LABEL: Record<string, string> = {
  regulatory_gap: 'Regulatory gap', enforcement_trend: 'Enforcement trend', cross_industry_analog: 'Cross-industry analog',
  innovation_pathway: 'Innovation pathway', red_team: 'Red team', opportunity: 'Opportunity',
}
const RISK_WEIGHT: Record<string, number> = { existential: 1, high: 0.8, upside: 0.7, medium: 0.5, low: 0.25 }
const KIND_WEIGHT: Record<string, number> = { action: 1, gap: 0.9, innovation: 0.85, tripwire: 0.8, opportunity: 0.8, assumption: 0.5 }

export interface DocketRow { vertical?: string | null; lens?: string | null; risk_band?: string | null; status?: string | null; priority?: string | null; origin?: string | null }
export interface MatrixCell { lens: string; risk_band: string; total: number; pending: number; answered: number }
export interface Matrix {
  cells: MatrixCell[]; max: number; total: number; untagged: number; empty: number
  innovationShare: number; highPriorityShare: number; byVertical: Record<string, { total: number; answered: number }>
}

/** Lens × risk-band grid over the docket. Rows without stored tags are counted, not guessed at. */
export function shapeMatrix(rows: DocketRow[], vertical = ''): Matrix {
  const scoped = (rows || []).filter(r => !vertical || r.vertical === vertical)
  const index = new Map<string, MatrixCell>()
  for (const lens of LENSES) for (const risk_band of RISK_BANDS) index.set(`${lens}|${risk_band}`, { lens, risk_band, total: 0, pending: 0, answered: 0 })
  const byVertical: Matrix['byVertical'] = {}
  let untagged = 0, innovation = 0, high = 0
  for (const r of scoped) {
    const v = String(r.vertical || 'unknown')
    byVertical[v] = byVertical[v] || { total: 0, answered: 0 }
    byVertical[v].total++
    if (r.status === 'answered') byVertical[v].answered++
    if (r.priority === 'high') high++
    const cell = index.get(`${r.lens}|${r.risk_band}`)
    if (!cell) { untagged++; continue }
    cell.total++
    if (r.status === 'answered') cell.answered++; else cell.pending++
    if ((INNOVATION_LENSES as readonly string[]).includes(String(r.lens))) innovation++
  }
  const cells = [...index.values()]
  const total = scoped.length
  return {
    cells, max: Math.max(1, ...cells.map(c => c.total)), total, untagged, empty: cells.filter(c => !c.total).length,
    innovationShare: total ? innovation / total : 0, highPriorityShare: total ? high / total : 0, byVertical,
  }
}

export interface InsightRow { id: string; kind: string; risk_band?: string | null; confidence?: number | string | null; created_at?: string | null; [k: string]: unknown }
/** Same ordering idea as steering_insights._score: risk × kind × confidence, newest breaks ties. */
export function rankInsights<T extends InsightRow>(rows: T[]): T[] {
  const score = (r: T) => (RISK_WEIGHT[String(r.risk_band)] ?? 0.5) * (KIND_WEIGHT[r.kind] ?? 0.6) * (0.5 + (Number(r.confidence ?? 0.7) || 0.7) / 2)
  return [...(rows || [])].sort((a, b) => score(b) - score(a) || String(b.created_at).localeCompare(String(a.created_at)))
}
export function tally<T>(rows: T[], key: (row: T) => string | null | undefined): Record<string, number> {
  const out: Record<string, number> = {}
  for (const r of rows || []) { const k = String(key(r) ?? 'unknown'); out[k] = (out[k] || 0) + 1 }
  return out
}

export interface OpRow { operation?: string | null; latency_ms?: number | null; quality_score?: number | string | null; verdict?: string | null }
export interface CallerQuality { caller: string; calls: number; fresh: number; graded: number; meanQuality: number | null; flagged: number; worst: string }
/** Per-caller value of local-model output. A row with latency 0 is a cache replay, not work. */
export function summariseQuality(ops: OpRow[]): { rows: number; graded: number; replays: number; meanQuality: number | null; callers: CallerQuality[] } {
  const by = new Map<string, CallerQuality & { sum: number; verdicts: Record<string, number> }>()
  let graded = 0, replays = 0, sum = 0
  for (const o of ops || []) {
    const caller = String(o.operation || 'completion')
    const c = by.get(caller) || { caller, calls: 0, fresh: 0, graded: 0, meanQuality: null, flagged: 0, worst: 'ok', sum: 0, verdicts: {} }
    c.calls++
    if (o.latency_ms) c.fresh++; else replays++
    const verdict = String(o.verdict || 'ungraded').replace(/^cached:/, '')
    c.verdicts[verdict] = (c.verdicts[verdict] || 0) + 1
    if (o.quality_score != null && !isNaN(Number(o.quality_score))) { c.graded++; c.sum += Number(o.quality_score); graded++; sum += Number(o.quality_score) }
    if (!['ok', 'ungraded'].includes(verdict)) c.flagged++
    by.set(caller, c)
  }
  const callers = [...by.values()].map(({ sum: s, verdicts, ...c }) => ({
    ...c, meanQuality: c.graded ? Math.round((s / c.graded) * 1000) / 1000 : null,
    worst: Object.entries(verdicts).filter(([k]) => !['ok', 'ungraded'].includes(k)).sort((a, b) => b[1] - a[1])[0]?.[0] || 'ok',
  })).sort((a, b) => b.flagged - a.flagged || b.calls - a.calls)
  return { rows: (ops || []).length, graded, replays, meanQuality: graded ? Math.round((sum / graded) * 1000) / 1000 : null, callers }
}
