import { describe, expect, it } from 'vitest'
import { CAPABILITY_DESTINATIONS, ORCHESTRATOR_CAPABILITIES, capabilityBySlug } from '../../config/orchestratorCapabilities'

describe('orchestrator capability registry', () => {
  it('keeps every user-facing command center unique and outcome complete', () => {
    expect(new Set(ORCHESTRATOR_CAPABILITIES.map(item => item.slug)).size).toBe(ORCHESTRATOR_CAPABILITIES.length)
    for (const capability of ORCHESTRATOR_CAPABILITIES) {
      expect(capability.actions.length).toBeGreaterThanOrEqual(3)
      expect(capability.outcomes.length).toBeGreaterThanOrEqual(3)
      expect(capability.keywords.length).toBeGreaterThanOrEqual(5)
      expect(capabilityBySlug(capability.slug)).toEqual(capability)
    }
  })

  it('generates canonical command destinations without exposing routing mechanics', () => {
    expect(CAPABILITY_DESTINATIONS.length).toBe(ORCHESTRATOR_CAPABILITIES.length * 4)
    expect(CAPABILITY_DESTINATIONS.every(item => item.to.startsWith('/orchestrators/'))).toBe(true)
    expect(JSON.stringify(CAPABILITY_DESTINATIONS).toLowerCase()).not.toContain('colosseum')
  })
})
