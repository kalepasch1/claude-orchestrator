import { describe, expect, it } from 'vitest'
import { CANONICAL_NAVIGATION, NAVIGATION_CONTRACT_VERSION } from '../../config/navigation'

const V2 = [
  ['Command Center', '/'], ['Sign-offs', '/sign-offs'], ['Queue', '/queue'],
  ['Orchestrators', '/orchestrators'], ['Business OS', '/business'], ['Connections', '/connectors'],
  ['Digital Twin', '/digital-twin'], ['Spend & ROI', '/spend'], ['Loops', '/loops'],
  ['Inbox', '/inbox'], ['Fleet', '/fleet'], ['Health', '/health'],
]
describe('navigation contract v2', () => {
  it('keeps every versioned destination in its contracted position', () => expect(CANONICAL_NAVIGATION.map(item => [item.label, item.to])).toEqual(V2))
  it('requires compatibility aliases for renamed concepts', () => { expect(CANONICAL_NAVIGATION.find(item => item.to === '/')?.aliases).toContain('/index'); expect(CANONICAL_NAVIGATION.find(item => item.to === '/connectors')?.aliases).toEqual(expect.arrayContaining(['/connections', '/integrations'])) })
  it('has unique labels and destinations', () => { expect(new Set(CANONICAL_NAVIGATION.map(item => item.label)).size).toBe(CANONICAL_NAVIGATION.length); expect(new Set(CANONICAL_NAVIGATION.map(item => item.to)).size).toBe(CANONICAL_NAVIGATION.length) })
  it('increments only through an explicit contract version', () => expect(NAVIGATION_CONTRACT_VERSION).toBe(2))
})
