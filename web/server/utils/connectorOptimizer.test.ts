import { describe, expect, it } from 'vitest'
import { optimizeConnectors } from './connectorOptimizer'

describe('connector optimizer', () => {
  it('prefers proven reliable connected providers', () => {
    const [result] = optimizeConnectors([{ provider: 'proven', connected: true, configured: true, samples: 20, succeeded: 20, qualityTotal: 19, costTotal: .1, policyIncidents: 0, capabilities: ['design'] }])
    expect(result.recommendation).toBe('prefer')
    expect(result.score).toBeGreaterThan(85)
  })
  it('deprioritizes repeated policy incidents', () => {
    const [result] = optimizeConnectors([{ provider: 'unsafe', connected: true, configured: true, samples: 10, succeeded: 7, qualityTotal: 6, costTotal: 2, policyIncidents: 4, capabilities: ['publish'] }])
    expect(result.recommendation).toBe('deprioritize')
  })
  it('keeps unproven providers in shadow observation', () => {
    const [result] = optimizeConnectors([{ provider: 'new', connected: false, configured: false, samples: 0, succeeded: 0, qualityTotal: 0, costTotal: 0, policyIncidents: 0, capabilities: ['research'] }])
    expect(result.recommendation).toBe('observe')
  })
})

