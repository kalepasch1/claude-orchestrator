import { describe, expect, it } from 'vitest'
import { canBulkApprove, deriveDecisionBrief } from '../../utils/decisionBrief'

const cases = [
  ['secret', 'Set API token', 'Credential', true], ['operator', 'Run database migration', 'Migration', true],
  ['deploy', 'Deploy production', 'Deployment', true], ['legal', 'Counsel sign-off', 'Legal', true],
  ['operator', 'Configure OAuth login', 'OAuth', true], ['operator', 'Acknowledge notice already applied', 'Operational', false],
  ['secret', 'Rotate client secret', 'Credential', true], ['operator', 'Change schema', 'Migration', true],
  ['operator', 'Release app', 'Deployment', true], ['operator', 'Binding terms approval', 'Legal', true],
  ['operator', 'Account consent required', 'OAuth', true], ['operator', 'Routine queue retry', 'Operational', false],
  ['secret', 'Provision credential', 'Credential', true], ['operator', 'Production config change', 'Deployment', true],
  ['operator', 'Database backup', 'Migration', true], ['operator', 'Regulatory approval', 'Legal', true],
  ['operator', 'OAuth scopes', 'OAuth', true], ['operator', 'Informational notice', 'Operational', false],
  ['operator', 'Deploy preview', 'Deployment', true], ['secret', 'API key request', 'Credential', true],
] as const

describe('decision brief', () => {
  it.each(cases)('%s / %s', (kind, title, classification, material) => {
    const brief = deriveDecisionBrief({ kind, title })
    expect(brief.classification).toContain(classification)
    expect(brief.material).toBe(material)
    expect(brief.authorizationMeaning).toContain('not evidence')
    expect(brief.verification.length).toBeGreaterThan(0)
  })

  it('produces a specific Medium decision brief', () => {
    const brief = deriveDecisionBrief({ kind: 'secret', title: 'Set MEDIUM_INTEGRATION_TOKEN + website base URL; deploy cade-publish-store migration', detail: 'Publishing human-reviewed until CADE_PUBLISH_AUTONOMOUS=true.' })
    expect(brief.recommendation).toBe('APPROVE WITH CONDITIONS')
    expect(brief.confidence).toBe(88)
    expect(brief.proposedChanges).toHaveLength(4)
    expect(brief.risks.some(risk => risk.category === 'Content and legal')).toBe(true)
    expect(brief.authorizationMeaning).toContain('does not mean')
  })

  it('blocks material bulk approvals', () => {
    expect(canBulkApprove([{ kind: 'operator', title: 'informational notice' }])).toBe(true)
    expect(canBulkApprove([{ kind: 'operator', title: 'informational notice' }, { kind: 'secret', title: 'token' }])).toBe(false)
  })
})
