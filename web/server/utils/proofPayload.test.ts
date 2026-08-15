import { describe, expect, it } from 'vitest'
import {
  buildProofView,
  presentableLabel,
  proofLinkIsServable,
  scopeEvidence,
  scrubInternalTerms,
} from './proofPayload'

const HOUR = 3_600_000
const NOW = Date.parse('2026-08-05T12:00:00.000Z')

describe('link servability — expired and revoked are not distinguishable from unknown', () => {
  it('serves a live, unrevoked link', () => {
    expect(proofLinkIsServable({ expires_at: new Date(NOW + HOUR).toISOString() }, NOW)).toBe(true)
  })

  it('refuses an expired link', () => {
    expect(proofLinkIsServable({ expires_at: new Date(NOW - HOUR).toISOString() }, NOW)).toBe(false)
  })

  it('refuses a revoked link even while it is still inside its window', () => {
    expect(proofLinkIsServable(
      { expires_at: new Date(NOW + HOUR).toISOString(), revoked_at: new Date(NOW - HOUR).toISOString() },
      NOW,
    )).toBe(false)
  })

  it('refuses an unknown link and a link with no usable expiry', () => {
    expect(proofLinkIsServable(null, NOW)).toBe(false)
    expect(proofLinkIsServable(undefined, NOW)).toBe(false)
    expect(proofLinkIsServable({ expires_at: 'not-a-date' }, NOW)).toBe(false)
    expect(proofLinkIsServable({}, NOW)).toBe(false)
  })
})

describe('internal machinery never reaches a reviewer', () => {
  it('replaces vendor and infrastructure names', () => {
    const out = scrubInternalTerms('Claude and GPT-4o wrote to Supabase via the orchestrator runner fleet')
    for (const term of ['claude', 'gpt-4o', 'supabase', 'orchestrator', 'runner', 'fleet']) {
      expect(out.toLowerCase()).not.toContain(term)
    }
    expect(out).toContain('[internal]')
  })

  it('replaces merge-train / executor / worktree machinery in any spelling', () => {
    const out = scrubInternalTerms('merge train, merge-train, merge_queue, executors, sub-agent, worktrees')
    expect(out.toLowerCase()).not.toContain('merge train')
    expect(out.toLowerCase()).not.toContain('merge-train')
    expect(out.toLowerCase()).not.toContain('merge_queue')
    expect(out.toLowerCase()).not.toContain('executors')
    expect(out.toLowerCase()).not.toContain('worktrees')
  })

  it('leaves ordinary outcome language intact', () => {
    const text = 'Reduced invoice processing time from 4 days to 6 hours across 212 vendors.'
    expect(scrubInternalTerms(text)).toBe(text)
  })

  it('does not mangle words that merely contain a term', () => {
    expect(scrubInternalTerms('management agentic reagent')).toBe('management agentic reagent')
  })

  it('redacts credential-shaped strings wherever they appear', () => {
    const out = scrubInternalTerms('key sk-abcdefghijklmnop and eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIx')
    expect(out).not.toContain('sk-abcdefghijklmnop')
    expect(out).not.toContain('eyJhbGciOiJIUzI1NiIs')
    expect(out).toContain('[redacted]')
  })
})

describe('evidence scoping — a link exposes only its own evidence', () => {
  it('drops identifiers that would let a reviewer pivot to another record', () => {
    const scoped = scopeEvidence({
      id: 'a', proof_id: 'b', organization_id: 'c', user_id: 'd', project: 'e',
      created_by: 'f', task_id: 'g', uuid: 'h', summary: 'Renewal secured',
    })
    expect(Object.keys(scoped)).toEqual(['summary'])
    expect(scoped.summary).toBe('Renewal secured')
  })

  it('drops credential-bearing keys entirely', () => {
    const scoped = scopeEvidence({
      access_token: 'x', api_key: 'y', password: 'z', session: 'q',
      authorization: 'r', email: 's', webhook_url: 't', outcome: 'kept',
    })
    expect(Object.keys(scoped)).toEqual(['outcome'])
  })

  it('drops keys named after machinery and scrubs values under allowed keys', () => {
    const scoped = scopeEvidence({
      steps: [{ runner_note: 'internal', agent: 'internal', note: 'dispatched by the orchestrator' }],
    })
    const serialized = JSON.stringify(scoped).toLowerCase()
    expect(serialized).not.toContain('orchestrator')
    expect(serialized).not.toContain('runner')
    expect(serialized).not.toContain('agent')
    expect(scoped.steps[0].note).toBe('dispatched by the [internal]')
  })

  it('bounds depth, breadth and string length', () => {
    const deep: any = { a: { b: { c: { d: { e: { f: 'too deep' } } } } } }
    expect(JSON.stringify(scopeEvidence(deep))).not.toContain('too deep')

    const wide: Record<string, number> = {}
    for (let i = 0; i < 200; i += 1) wide[`k${i}`] = i
    expect(Object.keys(scopeEvidence(wide)).length).toBeLessThanOrEqual(60)

    expect(scopeEvidence({ long: 'x'.repeat(5000) }).long.length).toBeLessThanOrEqual(2001)
    expect(scopeEvidence({ arr: new Array(500).fill('v') }).arr.length).toBeLessThanOrEqual(40)
  })
})

describe('reviewer payload is an explicit allow-list', () => {
  const link = {
    proof_id: '11111111-1111-1111-1111-111111111111',
    audience: 'Prospective investor',
    expires_at: new Date(NOW + HOUR).toISOString(),
    revoked_at: null,
  }
  const proof = {
    id: '22222222-2222-2222-2222-222222222222',
    organization_id: '33333333-3333-3333-3333-333333333333',
    action_type: 'contract_renewal',
    intent: 'Renew the enterprise agreement',
    status: 'completed',
    proof_digest: 'sha256:9f2b7c1d4e5a6b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c',
    prediction: { expected: 'renewal at parity', confidence: 0.82 },
    permissions: ['read:contracts', 'write:contracts'],
    rollback_plan: { action: 'revert to prior terms' },
    created_at: '2026-08-01T09:30:00.000Z',
  }

  it('returns only the fields the proof view renders', () => {
    const view = buildProofView(link, proof)
    expect(Object.keys(view).sort()).toEqual(['audience', 'expires_at', 'proof', 'verification'])
    expect(Object.keys(view.proof).sort()).toEqual([
      'action_type', 'created_at', 'intent', 'prediction', 'proof_digest', 'rollback_plan', 'status',
    ])
  })

  it('emits no identifiers and no permission taxonomy', () => {
    const serialized = JSON.stringify(buildProofView(link, proof))
    expect(serialized).not.toContain('11111111')
    expect(serialized).not.toContain('22222222')
    expect(serialized).not.toContain('33333333')
    expect(serialized).not.toContain('read:contracts')
    expect(serialized).not.toContain('proof_id')
    expect(serialized).not.toContain('organization')
  })

  it('presents slugs as readable labels', () => {
    const view = buildProofView(link, proof)
    expect(view.proof.action_type).toBe('contract renewal')
    expect(view.proof.status).toBe('completed')
    expect(view.audience).toBe('Prospective investor')
    expect(view.verification.digest_present).toBe(true)
  })

  it('never trusts a malformed digest', () => {
    const view = buildProofView(link, { ...proof, proof_digest: '<script>alert(1)</script>' })
    expect(view.proof.proof_digest).toBeNull()
    expect(view.verification.digest_present).toBe(false)
  })

  it('degrades cleanly when columns are empty rather than throwing', () => {
    const view = buildProofView({ expires_at: null }, {})
    expect(view.proof.created_at).toBeNull()
    expect(view.audience).toBe('Authorized reviewer')
    expect(view.proof.prediction).toEqual({})
  })
})

describe('presentableLabel', () => {
  it('drops the internal taxonomy namespace from a slug', () => {
    expect(presentableLabel('constitution:institutional_case')).toBe('institutional case')
    expect(presentableLabel('constitution:compile_policy')).toBe('compile policy')
  })

  it('leaves a prose colon intact', () => {
    expect(presentableLabel('Renewal secured: at parity')).toBe('Renewal secured: at parity')
    expect(presentableLabel('institutional case: Evaluate the next capability'))
      .toBe('institutional case: Evaluate the next capability')
  })

  it('caps runaway labels', () => {
    expect(presentableLabel('a'.repeat(1000)).length).toBeLessThanOrEqual(240)
  })
  it('returns an empty string for non-strings', () => {
    expect(presentableLabel(null)).toBe('')
    expect(presentableLabel(7)).toBe('')
  })
})
