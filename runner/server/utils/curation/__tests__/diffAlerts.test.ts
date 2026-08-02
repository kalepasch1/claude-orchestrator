import { describe, it, expect, beforeEach, vi } from 'vitest'
import { buildAlerts, AlertPayload, AlertSeverity } from '../diffAlerts'

interface CurationDiff {
  newBreaches: Array<{ id: string; constraint: string }>
  worsened: Array<{ id: string; constraint: string; previousStatus: string }>
  improved: Array<{ id: string; constraint: string }>
  resolved: Array<{ id: string; constraint: string }>
}

describe('diffAlerts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('buildAlerts - alert generation', () => {
    it('should build alert from newBreaches diff', () => {
      const diff: CurationDiff = {
        newBreaches: [
          { id: 'breach-1', constraint: 'data-residency' },
          { id: 'breach-2', constraint: 'consent-mapping' }
        ],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(1)
      expect(alerts[0]).toMatchObject({
        type: 'newBreaches',
        severity: 'high',
        changes: 2
      })
      expect(alerts[0].summary).toContain('2 new compliance breaches')
    })

    it('should build alert from worsened diff', () => {
      const diff: CurationDiff = {
        newBreaches: [],
        worsened: [
          { id: 'w-1', constraint: 'encryption', previousStatus: 'warning' }
        ],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(1)
      expect(alerts[0].type).toBe('worsened')
      expect(alerts[0].severity).toBe('high')
      expect(alerts[0].changes).toBe(1)
    })

    it('should build separate alerts for improved and resolved', () => {
      const diff: CurationDiff = {
        newBreaches: [],
        worsened: [],
        improved: [
          { id: 'i-1', constraint: 'audit-logging' },
          { id: 'i-2', constraint: 'access-control' }
        ],
        resolved: [
          { id: 'r-1', constraint: 'data-export' }
        ]
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(2)
      const improvedAlert = alerts.find(a => a.type === 'improved')
      const resolvedAlert = alerts.find(a => a.type === 'resolved')

      expect(improvedAlert).toBeDefined()
      expect(improvedAlert?.severity).toBe('low')
      expect(improvedAlert?.changes).toBe(2)

      expect(resolvedAlert).toBeDefined()
      expect(resolvedAlert?.severity).toBe('low')
      expect(resolvedAlert?.changes).toBe(1)
    })

    it('should omit alert type when no changes', () => {
      const diff: CurationDiff = {
        newBreaches: [],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(0)
    })
  })

  describe('escalation logic - critical severity', () => {
    it('should escalate to critical when both newBreaches and worsened present', () => {
      const diff: CurationDiff = {
        newBreaches: [
          { id: 'breach-1', constraint: 'data-residency' }
        ],
        worsened: [
          { id: 'w-1', constraint: 'encryption', previousStatus: 'warning' }
        ],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(2)
      const criticalAlerts = alerts.filter(a => a.severity === 'critical')
      expect(criticalAlerts).toHaveLength(2)
    })

    it('should escalate to critical when change count exceeds threshold (>5)', () => {
      const diff: CurationDiff = {
        newBreaches: Array.from({ length: 6 }, (_, i) => ({
          id: `breach-${i}`,
          constraint: `constraint-${i}`
        })),
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(1)
      expect(alerts[0].severity).toBe('critical')
      expect(alerts[0].changes).toBe(6)
    })

    it('should remain high severity when newBreaches alone but count <= 5', () => {
      const diff: CurationDiff = {
        newBreaches: Array.from({ length: 3 }, (_, i) => ({
          id: `breach-${i}`,
          constraint: `constraint-${i}`
        })),
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(1)
      expect(alerts[0].severity).toBe('high')
      expect(alerts[0].changes).toBe(3)
    })
  })

  describe('alert payload structure', () => {
    it('should include required fields in alert payload', () => {
      const diff: CurationDiff = {
        newBreaches: [
          { id: 'breach-1', constraint: 'data-residency' }
        ],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts[0]).toHaveProperty('type')
      expect(alerts[0]).toHaveProperty('severity')
      expect(alerts[0]).toHaveProperty('changes')
      expect(alerts[0]).toHaveProperty('summary')
      expect(alerts[0]).toHaveProperty('timestamp')
    })

    it('should include human-readable summary for each alert type', () => {
      const diff: CurationDiff = {
        newBreaches: [{ id: 'b1', constraint: 'pii-handling' }],
        worsened: [{ id: 'w1', constraint: 'encryption', previousStatus: 'warning' }],
        improved: [{ id: 'i1', constraint: 'logging' }],
        resolved: [{ id: 'r1', constraint: 'access' }]
      }

      const alerts = buildAlerts(diff)

      const newBreachesAlert = alerts.find(a => a.type === 'newBreaches')
      expect(newBreachesAlert?.summary).toMatch(/1 new compliance breach/)

      const worsenedAlert = alerts.find(a => a.type === 'worsened')
      expect(worsenedAlert?.summary).toMatch(/1.*worsened/)

      const improvedAlert = alerts.find(a => a.type === 'improved')
      expect(improvedAlert?.summary).toMatch(/1.*improved/)

      const resolvedAlert = alerts.find(a => a.type === 'resolved')
      expect(resolvedAlert?.summary).toMatch(/1.*resolved/)
    })

    it('should timestamp all alerts', () => {
      const diff: CurationDiff = {
        newBreaches: [{ id: 'breach-1', constraint: 'data-residency' }],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      alerts.forEach(alert => {
        expect(alert.timestamp).toBeDefined()
        expect(typeof alert.timestamp).toBe('number')
        expect(alert.timestamp).toBeGreaterThan(0)
      })
    })

    it('should include constraint details in alert payload', () => {
      const diff: CurationDiff = {
        newBreaches: [
          { id: 'breach-1', constraint: 'data-residency' },
          { id: 'breach-2', constraint: 'pii-encryption' }
        ],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts[0]).toHaveProperty('constraints')
      expect(alerts[0].constraints).toContain('data-residency')
      expect(alerts[0].constraints).toContain('pii-encryption')
    })
  })

  describe('edge cases', () => {
    it('should handle empty diff gracefully', () => {
      const diff: CurationDiff = {
        newBreaches: [],
        worsened: [],
        improved: [],
        resolved: []
      }

      expect(() => buildAlerts(diff)).not.toThrow()
      expect(buildAlerts(diff)).toEqual([])
    })

    it('should handle single item per category', () => {
      const diff: CurationDiff = {
        newBreaches: [{ id: 'b1', constraint: 'c1' }],
        worsened: [{ id: 'w1', constraint: 'c2', previousStatus: 's' }],
        improved: [{ id: 'i1', constraint: 'c3' }],
        resolved: [{ id: 'r1', constraint: 'c4' }]
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(4)
      alerts.forEach(alert => {
        expect(alert.changes).toBe(1)
      })
    })

    it('should handle large number of changes', () => {
      const diff: CurationDiff = {
        newBreaches: Array.from({ length: 50 }, (_, i) => ({
          id: `breach-${i}`,
          constraint: `constraint-${i}`
        })),
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(1)
      expect(alerts[0].changes).toBe(50)
      expect(alerts[0].severity).toBe('critical')
    })

    it('should handle worsened without previousStatus gracefully', () => {
      const diff: CurationDiff = {
        newBreaches: [],
        worsened: [{ id: 'w1', constraint: 'c1', previousStatus: '' }],
        improved: [],
        resolved: []
      }

      expect(() => buildAlerts(diff)).not.toThrow()
      const alerts = buildAlerts(diff)
      expect(alerts).toHaveLength(1)
      expect(alerts[0].type).toBe('worsened')
    })
  })

  describe('alert severity levels', () => {
    it('should assign critical severity correctly', () => {
      const diff: CurationDiff = {
        newBreaches: [{ id: 'b1', constraint: 'c1' }],
        worsened: [{ id: 'w1', constraint: 'c2', previousStatus: 's' }],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)
      const severities = alerts.map(a => a.severity)

      expect(severities).toContain('critical')
    })

    it('should assign high severity for newBreaches alone', () => {
      const diff: CurationDiff = {
        newBreaches: [{ id: 'b1', constraint: 'c1' }],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts[0].severity).toBe('high')
    })

    it('should assign high severity for worsened alone', () => {
      const diff: CurationDiff = {
        newBreaches: [],
        worsened: [{ id: 'w1', constraint: 'c1', previousStatus: 's' }],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts[0].severity).toBe('high')
    })

    it('should assign low severity for improved/resolved', () => {
      const diff: CurationDiff = {
        newBreaches: [],
        worsened: [],
        improved: [{ id: 'i1', constraint: 'c1' }],
        resolved: [{ id: 'r1', constraint: 'c2' }]
      }

      const alerts = buildAlerts(diff)

      alerts.forEach(alert => {
        expect(alert.severity).toBe('low')
      })
    })
  })

  describe('multiple alerts in single diff', () => {
    it('should generate all applicable alerts when all categories have changes', () => {
      const diff: CurationDiff = {
        newBreaches: [{ id: 'b1', constraint: 'c1' }],
        worsened: [{ id: 'w1', constraint: 'c2', previousStatus: 's' }],
        improved: [{ id: 'i1', constraint: 'c3' }],
        resolved: [{ id: 'r1', constraint: 'c4' }]
      }

      const alerts = buildAlerts(diff)

      expect(alerts).toHaveLength(4)
      const types = alerts.map(a => a.type)
      expect(types).toContain('newBreaches')
      expect(types).toContain('worsened')
      expect(types).toContain('improved')
      expect(types).toContain('resolved')
    })

    it('should prioritize critical alerts in mixed scenarios', () => {
      const diff: CurationDiff = {
        newBreaches: Array.from({ length: 3 }, (_, i) => ({
          id: `b${i}`,
          constraint: `c${i}`
        })),
        worsened: Array.from({ length: 2 }, (_, i) => ({
          id: `w${i}`,
          constraint: `c${i + 10}`,
          previousStatus: 's'
        })),
        improved: [{ id: 'i1', constraint: 'c20' }],
        resolved: [{ id: 'r1', constraint: 'c21' }]
      }

      const alerts = buildAlerts(diff)

      const criticalAlerts = alerts.filter(a => a.severity === 'critical')
      const highAlerts = alerts.filter(a => a.severity === 'high')
      const lowAlerts = alerts.filter(a => a.severity === 'low')

      expect(criticalAlerts.length).toBeGreaterThan(0)
      expect(highAlerts.length).toBeGreaterThanOrEqual(0)
      expect(lowAlerts.length).toBeGreaterThan(0)
    })
  })

  describe('alert payload serialization', () => {
    it('should produce JSON-serializable payload', () => {
      const diff: CurationDiff = {
        newBreaches: [{ id: 'b1', constraint: 'c1' }],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(() => JSON.stringify(alerts)).not.toThrow()
      const serialized = JSON.stringify(alerts)
      const deserialized = JSON.parse(serialized)

      expect(deserialized).toHaveLength(1)
      expect(deserialized[0].type).toBe('newBreaches')
    })

    it('should maintain data integrity through serialization round-trip', () => {
      const diff: CurationDiff = {
        newBreaches: [
          { id: 'breach-with-special-chars-!@#$%', constraint: 'constraint-123' }
        ],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)
      const serialized = JSON.stringify(alerts)
      const deserialized = JSON.parse(serialized)

      expect(deserialized[0].constraints).toContain('constraint-123')
    })
  })

  describe('constraint extraction', () => {
    it('should extract all unique constraints in alert', () => {
      const diff: CurationDiff = {
        newBreaches: [
          { id: 'b1', constraint: 'data-residency' },
          { id: 'b2', constraint: 'pii-encryption' },
          { id: 'b3', constraint: 'audit-logging' }
        ],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts[0].constraints).toHaveLength(3)
      expect(alerts[0].constraints).toContain('data-residency')
      expect(alerts[0].constraints).toContain('pii-encryption')
      expect(alerts[0].constraints).toContain('audit-logging')
    })

    it('should handle duplicate constraints', () => {
      const diff: CurationDiff = {
        newBreaches: [
          { id: 'b1', constraint: 'encryption' },
          { id: 'b2', constraint: 'encryption' },
          { id: 'b3', constraint: 'access-control' }
        ],
        worsened: [],
        improved: [],
        resolved: []
      }

      const alerts = buildAlerts(diff)

      expect(alerts[0].constraints).toHaveLength(2)
      expect(alerts[0].constraints.filter(c => c === 'encryption')).toHaveLength(1)
    })
  })
})
