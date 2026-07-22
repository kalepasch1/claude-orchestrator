import { describe, expect, it } from 'vitest'
import { calculateReadiness, detectRegulatoryActivities, noLicenseAlternatives, priceSponsorRelationship } from './regulatoryCapability'

describe('regulatory capability compiler', () => {
  it('detects regulated activity from bounded product and marketing descriptions', () => {
    const securities = detectRegulatoryActivities({ summary: 'Pay a partner a percentage of capital raised for investor introductions.' })
    expect(securities.some(item => item.rule.activity === 'securities_intermediation')).toBe(true)
    const payments = detectRegulatoryActivities({ summary: 'Hold customer funds in a wallet before payout.' })
    expect(payments.some(item => item.rule.activity === 'money_transmission')).toBe(true)
  })

  it('returns bounded operating alternatives instead of claiming a license exemption', () => {
    const alternatives = noLicenseAlternatives('us-securities-intermediation')
    expect(alternatives.map(item => item.type)).toContain('referral')
    expect(alternatives.every(item => item.boundary.length > 20)).toBe(true)
  })

  it('scores only required, verified readiness evidence', () => {
    const result = calculateReadiness([
      { key: 'history', label: 'Operating history', kind: 'history', required: true },
      { key: 'policy', label: 'Policy', kind: 'document', required: true },
      { key: 'optional', label: 'Optional', kind: 'evidence', required: false },
    ], { history: { verified: true, ref: 'receipt-1' }, optional: true })
    expect(result.readiness_score).toBe(50)
    expect(result.blockers).toEqual([{ key: 'policy', label: 'Policy' }])
  })

  it('prices supervision from workload, risk, capital and evidence', () => {
    const base = priceSponsorRelationship({ monitoring_hours: 10, expected_monthly_transactions: 1_000, complaint_rate: .01, capital_consumption_cents: 1_000_000 })
    const proven = priceSponsorRelationship({ monitoring_hours: 10, expected_monthly_transactions: 1_000, complaint_rate: .01, capital_consumption_cents: 1_000_000, clean_months: 18 })
    expect(base.monthly_price_cents).toBeGreaterThan(base.drivers.base_cents)
    expect(proven.monthly_price_cents).toBeLessThan(base.monthly_price_cents)
  })
})
