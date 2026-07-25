export type ImprovementScope = 'portfolio' | 'application' | 'orchestrator' | 'workflow' | 'code' | 'component'

export const LOCKED_INVARIANTS = ['authority', 'secrets', 'privacy', 'budget', 'independent_qa'] as const

export function recommendationFor(input: { scopeType: ImprovementScope; scopeRef: string; label: string; outcomes?: any[]; tasks?: any[] }) {
  const outcomes = input.outcomes || []
  const tasks = input.tasks || []
  const relevant = outcomes.filter(row => !input.scopeRef || input.scopeRef === 'portfolio' || String(row.project || row.slug || '').toLowerCase().includes(input.scopeRef.toLowerCase()))
  const sample = relevant.length ? relevant : outcomes
  const success = sample.length ? sample.filter(row => row.tests_passed && row.integrated !== false).length / sample.length : 0.78
  const failures = tasks.filter(row => ['TESTFAIL', 'RETRY', 'BLOCKED', 'CONFLICT'].includes(row.state)).length
  const score = Math.max(54, Math.min(98, Math.round(62 + (1 - success) * 28 + Math.min(12, failures * 2))))
  const expectedLift = Math.max(4, Math.min(31, Math.round((1 - success) * 24 + failures * 0.7 + 5)))
  const targetKpi = input.scopeType === 'code' || input.scopeType === 'component' ? 'first_pass_rate' : input.scopeType === 'workflow' ? 'avg_wall_min' : 'merge_rate'
  return {
    score,
    expectedLift,
    targetKpi,
    rationale: sample.length
      ? `${sample.length} outcomes show ${Math.round(success * 100)}% verified success with ${failures} recoverable friction signals.`
      : 'CADE recommends an observation baseline before any candidate receives production traffic.',
    mode: sample.length >= 10 ? 'shadow' : 'observe',
    safeguards: [...LOCKED_INVARIANTS, 'instant_rollback', 'control_traffic'],
  }
}

export function activationPrompt(loop: any) {
  return [
    `Operate a governed self-improvement loop for ${loop.label}.`,
    `Scope: ${loop.scope_type}:${loop.scope_ref}. Mode: ${loop.mode}. Target KPI: ${loop.target_kpi}.`,
    'Observe production telemetry, propose a single reversible candidate, preserve a control cohort, and run blind independent QA.',
    `Do not cross locked invariants: ${(loop.locked_invariants || LOCKED_INVARIANTS).join(', ')}.`,
    `Automatically roll back if any protected KPI regresses more than ${loop.rollback_threshold || 10}%.`,
    'Graduate only statistically supported gains; produce a signed evidence receipt and a privacy-safe reusable contribution candidate.',
  ].join('\n')
}

