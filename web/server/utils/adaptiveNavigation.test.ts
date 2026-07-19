import { describe, expect, it } from 'vitest'
import { nextBestActions } from '../../utils/adaptiveNavigation'

const base = { role: 'operator' as const, objective: 'operate' as const, permissions: ['*'], runnerCount: 1, pendingApprovals: 0, blockedTasks: 0, readyConnectors: 1 }
describe('adaptive navigation', () => {
  it('prioritizes urgent work without changing canonical navigation', () => { const result = nextBestActions({ ...base, pendingApprovals: 4 }); expect(result[0].to).toBe('/sign-offs'); expect(result[0].urgent).toBe(true) })
  it('respects permissions', () => { const result = nextBestActions({ ...base, permissions: ['tasks:read'], pendingApprovals: 4 }); expect(result.some(item => item.label.startsWith('Review 4'))).toBe(false) })
  it('provides a stable training sequence', () => { const result = nextBestActions({ ...base, objective: 'learn' }); expect(result.map(item => item.to)).toEqual(['/', '/connectors', '/digital-twin']) })
  it('surfaces connection setup when capabilities are unavailable', () => { const result = nextBestActions({ ...base, objective: 'connect', readyConnectors: 0 }); expect(result[0].to).toBe('/connectors') })
})
