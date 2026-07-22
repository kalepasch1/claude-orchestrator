import { describe, expect, it } from 'vitest'
import contract from '../../config/journey-contracts.json'
import { CANONICAL_NAVIGATION } from '../../config/navigation'

describe('synthetic journey contract', () => {
  it('keeps critical journey destinations canonical', () => {
    const routes = new Set(CANONICAL_NAVIGATION.map(item => item.to))
    for (const journey of contract.journeys.filter(item => !item.route.startsWith('/admin'))) expect(routes.has(journey.route)).toBe(true)
  })
  it('keeps one stable route per journey', () => expect(new Set(contract.journeys.map(item => item.route)).size).toBe(contract.journeys.length))
  it('protects every capability evolution action', () => expect(contract.criticalActions.find(item => item.file.includes('CapabilityEvolution'))?.mustContain).toEqual(expect.arrayContaining(['Simulate adaptive interface', 'Inspect and refresh now', 'Save privacy controls', 'Apply accessibility profile'])))
  it('protects universal access and constitutional execution', () => { expect(contract.version).toBe(10); expect(contract.criticalActions.find(item => item.file.includes('UniversalCommand'))?.mustContain).toEqual(expect.arrayContaining(['Continue with this outcome', 'command/context', 'madeus:pending-command'])); expect(contract.criticalActions.find(item => item.file.includes('ExecutionConstitution'))?.mustContain).toEqual(expect.arrayContaining(['Capture current world','Run certification','Preview latest replay'])) })
  it('protects every constitutional autonomy action', () => expect(contract.criticalActions.find(item => item.file.includes('ConstitutionalAutonomy'))?.mustContain).toEqual(expect.arrayContaining(['Establish institution','Record privacy-safe evidence','Propose evidence-weighted allocation','Issue committed credential','Generate least-disruptive response','Compile and contract-test policy','Seal encrypted continuity capsule','Run adversarial contract matrix'])))
  it('protects every federation assurance action', () => expect(contract.criticalActions.find(item => item.file.includes('FederationAssurance'))?.mustContain).toEqual(expect.arrayContaining(['Propose sovereign trust','Prepare selective evidence exchange','Update causal twin','Attest latest execution chain','Delegate attenuated authority','Propose verified-outcome contract','Compile operating memory','Predict inclusion barriers','Convene adversarial court'])))
})
