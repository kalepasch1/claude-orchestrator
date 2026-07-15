import { describe, expect, it } from 'vitest'
import { deriveProficiency } from './adaptiveProficiency'

describe('adaptive proficiency', () => {
  it('starts with detailed guidance', () => expect(deriveProficiency({ visits: 1, completedActions: 0, expandedGuidance: 0, advancedUses: 0 })).toMatchObject({ stage: 'guided', explanationDepth: 'detailed', showAdvancedByDefault: false }))
  it('progresses from practiced to fluent from observed behavior', () => {
    expect(deriveProficiency({ visits: 4, completedActions: 1, expandedGuidance: 1, advancedUses: 0 }).stage).toBe('practiced')
    expect(deriveProficiency({ visits: 6, completedActions: 3, expandedGuidance: 2, advancedUses: 2 })).toMatchObject({ stage: 'fluent', explanationDepth: 'concise', showAdvancedByDefault: true })
  })
  it('caps the proficiency score', () => expect(deriveProficiency({ visits: 100, completedActions: 100, expandedGuidance: 100, advancedUses: 100 }).score).toBe(100))
})
