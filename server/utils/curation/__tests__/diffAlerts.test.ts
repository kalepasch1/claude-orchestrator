import { describe, it, expect, beforeEach } from 'vitest'
import {
  buildAlertFromDiff,
  escalateIfCritical,
  formatAlertPayload,
  type CurationDiff,
  type AlertPayload,
  type AlertSeverity,
} from '../diffAlerts'

describe('diffAlerts', () => {
  describe('buildAlertFromDiff', () => {
    it('creates alert from newBreaches diff', () => {
      const diff: CurationDiff = {
        tenantId: 'tenant-1',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'newBreaches',
        previousStatus: {},
        currentStatus: { breach_control_1: 'failed' },
        affectedControls: ['breach_control_1'],
        severity: 'high',
      }

      const alert = buildAlertFromDiff(diff)
      expect(alert).toMatchObject({
        tenantId: 'tenant-1',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'newBreaches',
        controlCount: 1,
        affectedControls: ['breach_control_1'],
      })
      expect(alert.severity).toBe('high')
    })

    it('creates alert from worsened diff', () => {
      const diff: CurationDiff = {
        tenantId: 'tenant-2',
        institutionType: 'fintech',
        posture: 'defensive',
        changeType: 'worsened',
        previousStatus: { control_a: 'passed', control_b: 'passed' },
        currentStatus: { control_a: 'failed', control_b: 'warning' },
        affectedControls: ['control_a', 'control_b'],
        severity: 'medium',
      }

      const alert = buildAlertFromDiff(diff)
      expect(alert.changeType).toBe('worsened')
      expect(alert.controlCount).toBe(2)
      expect(alert.severity).toBe('medium')
    })

    it('creates alert from improved diff', () => {
      const diff: CurationDiff = {
        tenantId: 'tenant-3',
        institutionType: 'insurance',
        posture: 'audit',
        changeType: 'improved',
        previousStatus: { control_x: 'failed' },
        currentStatus: { control_x: 'passed' },
        affectedControls: ['control_x'],
        severity: 'low',
      }

      const alert = buildAlertFromDiff(diff)
      expect(alert.severity).toBe('low')
      expect(alert.changeType).toBe('improved')
    })

    it('creates alert from resolved diff', () => {
      const diff: CurationDiff = {
        tenantId: 'tenant-4',
        institutionType: 'saas',
        posture: 'enforcement',
        changeType: 'resolved',
        previousStatus: { control_p: 'failed', control_q: 'failed' },
        currentStatus: { control_p: 'passed', control_q: 'passed' },
        affectedControls: ['control_p', 'control_q'],
        severity: 'low',
      }

      const alert = buildAlertFromDiff(diff)
      expect(alert.changeType).toBe('resolved')
      expect(alert.severity).toBe('low')
    })

    it('handles single control change', () => {
      const diff: CurationDiff = {
        tenantId: 'tenant-5',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'newBreaches',
        previousStatus: {},
        currentStatus: { single_control: 'failed' },
        affectedControls: ['single_control'],
        severity: 'medium',
      }

      const alert = buildAlertFromDiff(diff)
      expect(alert.controlCount).toBe(1)
      expect(alert.affectedControls).toHaveLength(1)
    })

    it('handles many control changes (boundary: 5)', () => {
      const controls = Array.from({ length: 5 }, (_, i) => `control_${i}`)
      const diff: CurationDiff = {
        tenantId: 'tenant-6',
        institutionType: 'fintech',
        posture: 'defensive',
        changeType: 'worsened',
        previousStatus: Object.fromEntries(controls.map(c => [c, 'passed'])),
        currentStatus: Object.fromEntries(controls.map(c => [c, 'failed'])),
        affectedControls: controls,
        severity: 'high',
      }

      const alert = buildAlertFromDiff(diff)
      expect(alert.controlCount).toBe(5)
    })

    it('handles many control changes (boundary: 6)', () => {
      const controls = Array.from({ length: 6 }, (_, i) => `control_${i}`)
      const diff: CurationDiff = {
        tenantId: 'tenant-7',
        institutionType: 'insurance',
        posture: 'audit',
        changeType: 'newBreaches',
        previousStatus: {},
        currentStatus: Object.fromEntries(controls.map(c => [c, 'failed'])),
        affectedControls: controls,
        severity: 'critical',
      }

      const alert = buildAlertFromDiff(diff)
      expect(alert.controlCount).toBe(6)
    })

    it('captures all institution types', () => {
      const types = ['bank', 'fintech', 'insurance', 'saas', 'other'] as const
      types.forEach(type => {
        const diff: CurationDiff = {
          tenantId: `tenant-${type}`,
          institutionType: type,
          posture: 'cooperative',
          changeType: 'improved',
          previousStatus: { c: 'failed' },
          currentStatus: { c: 'passed' },
          affectedControls: ['c'],
          severity: 'low',
        }

        const alert = buildAlertFromDiff(diff)
        expect(alert.institutionType).toBe(type)
      })
    })

    it('captures all postures', () => {
      const postures = ['cooperative', 'defensive', 'audit', 'enforcement'] as const
      postures.forEach(posture => {
        const diff: CurationDiff = {
          tenantId: `tenant-${posture}`,
          institutionType: 'bank',
          posture,
          changeType: 'worsened',
          previousStatus: { c: 'passed' },
          currentStatus: { c: 'failed' },
          affectedControls: ['c'],
          severity: 'medium',
        }

        const alert = buildAlertFromDiff(diff)
        expect(alert.posture).toBe(posture)
      })
    })
  })

  describe('escalateIfCritical', () => {
    it('escalates to critical when both newBreaches AND worsened', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-1',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'newBreaches',
        controlCount: 2,
        affectedControls: ['c1', 'c2'],
        severity: 'high',
        escalated: false,
        createdAt: new Date(),
      }

      const worsened: AlertPayload = {
        tenantId: 'tenant-1',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'worsened',
        controlCount: 3,
        affectedControls: ['c3', 'c4', 'c5'],
        severity: 'high',
        escalated: false,
        createdAt: new Date(),
      }

      const result = escalateIfCritical([alert, worsened])
      expect(result).toHaveLength(2)
      expect(result.every(a => a.severity === 'critical')).toBe(true)
      expect(result.every(a => a.escalated)).toBe(true)
    })

    it('does not escalate when only newBreaches present', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-2',
        institutionType: 'fintech',
        posture: 'defensive',
        changeType: 'newBreaches',
        controlCount: 2,
        affectedControls: ['c1', 'c2'],
        severity: 'high',
        escalated: false,
        createdAt: new Date(),
      }

      const result = escalateIfCritical([alert])
      expect(result[0].severity).toBe('high')
      expect(result[0].escalated).toBe(false)
    })

    it('does not escalate when only worsened present', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-3',
        institutionType: 'insurance',
        posture: 'audit',
        changeType: 'worsened',
        controlCount: 3,
        affectedControls: ['c1', 'c2', 'c3'],
        severity: 'high',
        escalated: false,
        createdAt: new Date(),
      }

      const result = escalateIfCritical([alert])
      expect(result[0].severity).toBe('high')
      expect(result[0].escalated).toBe(false)
    })

    it('escalates when any single alert has >5 control changes', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-4',
        institutionType: 'saas',
        posture: 'enforcement',
        changeType: 'worsened',
        controlCount: 6,
        affectedControls: ['c1', 'c2', 'c3', 'c4', 'c5', 'c6'],
        severity: 'high',
        escalated: false,
        createdAt: new Date(),
      }

      const result = escalateIfCritical([alert])
      expect(result[0].severity).toBe('critical')
      expect(result[0].escalated).toBe(true)
    })

    it('does not escalate when alert has exactly 5 control changes', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-5',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'worsened',
        controlCount: 5,
        affectedControls: ['c1', 'c2', 'c3', 'c4', 'c5'],
        severity: 'high',
        escalated: false,
        createdAt: new Date(),
      }

      const result = escalateIfCritical([alert])
      expect(result[0].severity).toBe('high')
      expect(result[0].escalated).toBe(false)
    })

    it('handles empty alert list', () => {
      const result = escalateIfCritical([])
      expect(result).toEqual([])
    })

    it('does not escalate improved or resolved alerts', () => {
      const improved: AlertPayload = {
        tenantId: 'tenant-6',
        institutionType: 'fintech',
        posture: 'defensive',
        changeType: 'improved',
        controlCount: 1,
        affectedControls: ['c1'],
        severity: 'low',
        escalated: false,
        createdAt: new Date(),
      }

      const resolved: AlertPayload = {
        tenantId: 'tenant-7',
        institutionType: 'insurance',
        posture: 'audit',
        changeType: 'resolved',
        controlCount: 1,
        affectedControls: ['c1'],
        severity: 'low',
        escalated: false,
        createdAt: new Date(),
      }

      const result = escalateIfCritical([improved, resolved])
      expect(result[0].severity).toBe('low')
      expect(result[1].severity).toBe('low')
    })

    it('handles mixed escalation scenarios', () => {
      const alerts: AlertPayload[] = [
        {
          tenantId: 'tenant-8',
          institutionType: 'bank',
          posture: 'cooperative',
          changeType: 'newBreaches',
          controlCount: 2,
          affectedControls: ['c1', 'c2'],
          severity: 'high',
          escalated: false,
          createdAt: new Date(),
        },
        {
          tenantId: 'tenant-8',
          institutionType: 'bank',
          posture: 'cooperative',
          changeType: 'worsened',
          controlCount: 3,
          affectedControls: ['c3', 'c4', 'c5'],
          severity: 'high',
          escalated: false,
          createdAt: new Date(),
        },
        {
          tenantId: 'tenant-8',
          institutionType: 'bank',
          posture: 'cooperative',
          changeType: 'improved',
          controlCount: 1,
          affectedControls: ['c6'],
          severity: 'low',
          escalated: false,
          createdAt: new Date(),
        },
      ]

      const result = escalateIfCritical(alerts)
      const escalated = result.filter(a => a.escalated)
      expect(escalated).toHaveLength(2)
      expect(escalated[0].changeType).toBe('newBreaches')
      expect(escalated[1].changeType).toBe('worsened')
      expect(result[2].escalated).toBe(false)
    })
  })

  describe('formatAlertPayload', () => {
    it('formats basic alert payload', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-1',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'newBreaches',
        controlCount: 2,
        affectedControls: ['control_a', 'control_b'],
        severity: 'critical',
        escalated: true,
        createdAt: new Date('2025-01-15T10:30:00Z'),
      }

      const formatted = formatAlertPayload(alert)
      expect(formatted).toMatchObject({
        tenantId: 'tenant-1',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'newBreaches',
        severity: 'critical',
        escalated: true,
      })
      expect(formatted.summary).toBeDefined()
      expect(typeof formatted.summary).toBe('string')
    })

    it('generates human-readable summary for newBreaches', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-2',
        institutionType: 'fintech',
        posture: 'defensive',
        changeType: 'newBreaches',
        controlCount: 3,
        affectedControls: ['breach_1', 'breach_2', 'breach_3'],
        severity: 'high',
        escalated: false,
        createdAt: new Date(),
      }

      const formatted = formatAlertPayload(alert)
      expect(formatted.summary).toContain('newBreaches')
      expect(formatted.summary).toContain('3')
    })

    it('generates human-readable summary for worsened', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-3',
        institutionType: 'insurance',
        posture: 'audit',
        changeType: 'worsened',
        controlCount: 2,
        affectedControls: ['control_x', 'control_y'],
        severity: 'medium',
        escalated: false,
        createdAt: new Date(),
      }

      const formatted = formatAlertPayload(alert)
      expect(formatted.summary).toContain('worsened')
    })

    it('generates human-readable summary for improved', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-4',
        institutionType: 'saas',
        posture: 'enforcement',
        changeType: 'improved',
        controlCount: 1,
        affectedControls: ['control_p'],
        severity: 'low',
        escalated: false,
        createdAt: new Date(),
      }

      const formatted = formatAlertPayload(alert)
      expect(formatted.summary).toContain('improved')
    })

    it('generates human-readable summary for resolved', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-5',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'resolved',
        controlCount: 1,
        affectedControls: ['control_q'],
        severity: 'low',
        escalated: false,
        createdAt: new Date(),
      }

      const formatted = formatAlertPayload(alert)
      expect(formatted.summary).toContain('resolved')
    })

    it('includes affected controls in summary when >0', () => {
      const alert: AlertPayload = {
        tenantId: 'tenant-6',
        institutionType: 'fintech',
        posture: 'defensive',
        changeType: 'newBreaches',
        controlCount: 2,
        affectedControls: ['control_1', 'control_2'],
        severity: 'high',
        escalated: false,
        createdAt: new Date(),
      }

      const formatted = formatAlertPayload(alert)
      expect(formatted.summary).toContain('control_1')
      expect(formatted.summary).toContain('control_2')
    })

    it('preserves severity in formatted output', () => {
      const severities: AlertSeverity[] = ['low', 'medium', 'high', 'critical']
      severities.forEach(severity => {
        const alert: AlertPayload = {
          tenantId: 'tenant-test',
          institutionType: 'bank',
          posture: 'cooperative',
          changeType: 'improved',
          controlCount: 1,
          affectedControls: ['c'],
          severity,
          escalated: false,
          createdAt: new Date(),
        }

        const formatted = formatAlertPayload(alert)
        expect(formatted.severity).toBe(severity)
      })
    })

    it('preserves escalated flag in formatted output', () => {
      const alertEscalated: AlertPayload = {
        tenantId: 'tenant-7',
        institutionType: 'insurance',
        posture: 'audit',
        changeType: 'worsened',
        controlCount: 6,
        affectedControls: ['c1', 'c2', 'c3', 'c4', 'c5', 'c6'],
        severity: 'critical',
        escalated: true,
        createdAt: new Date(),
      }

      const formatted = formatAlertPayload(alertEscalated)
      expect(formatted.escalated).toBe(true)

      const alertNotEscalated: AlertPayload = {
        tenantId: 'tenant-8',
        institutionType: 'saas',
        posture: 'enforcement',
        changeType: 'improved',
        controlCount: 1,
        affectedControls: ['c'],
        severity: 'low',
        escalated: false,
        createdAt: new Date(),
      }

      const formatted2 = formatAlertPayload(alertNotEscalated)
      expect(formatted2.escalated).toBe(false)
    })
  })

  describe('end-to-end alert generation pipeline', () => {
    it('processes newBreaches + worsened into critical escalated alerts', () => {
      const diff1: CurationDiff = {
        tenantId: 'tenant-e2e-1',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'newBreaches',
        previousStatus: {},
        currentStatus: { breach_1: 'failed', breach_2: 'failed' },
        affectedControls: ['breach_1', 'breach_2'],
        severity: 'high',
      }

      const diff2: CurationDiff = {
        tenantId: 'tenant-e2e-1',
        institutionType: 'bank',
        posture: 'cooperative',
        changeType: 'worsened',
        previousStatus: { control_x: 'passed' },
        currentStatus: { control_x: 'failed' },
        affectedControls: ['control_x'],
        severity: 'high',
      }

      const alert1 = buildAlertFromDiff(diff1)
      const alert2 = buildAlertFromDiff(diff2)
      const escalated = escalateIfCritical([alert1, alert2])

      expect(escalated).toHaveLength(2)
      expect(escalated.every(a => a.severity === 'critical')).toBe(true)
      expect(escalated.every(a => a.escalated)).toBe(true)

      const formatted1 = formatAlertPayload(escalated[0])
      const formatted2 = formatAlertPayload(escalated[1])

      expect(formatted1.summary).toBeDefined()
      expect(formatted2.summary).toBeDefined()
    })

    it('processes mixed improvements and breaches', () => {
      const diffs: CurationDiff[] = [
        {
          tenantId: 'tenant-e2e-2',
          institutionType: 'fintech',
          posture: 'defensive',
          changeType: 'newBreaches',
          previousStatus: {},
          currentStatus: { breach: 'failed' },
          affectedControls: ['breach'],
          severity: 'high',
        },
        {
          tenantId: 'tenant-e2e-2',
          institutionType: 'fintech',
          posture: 'defensive',
          changeType: 'improved',
          previousStatus: { control_a: 'failed' },
          currentStatus: { control_a: 'passed' },
          affectedControls: ['control_a'],
          severity: 'low',
        },
      ]

      const alerts = diffs.map(d => buildAlertFromDiff(d))
      const escalated = escalateIfCritical(alerts)

      expect(escalated).toHaveLength(2)
      expect(escalated[0].severity).toBe('high')
      expect(escalated[1].severity).toBe('low')

      const formatted = escalated.map(a => formatAlertPayload(a))
      expect(formatted.every(f => f.summary)).toBe(true)
    })

    it('handles high-volume breach scenario (>5 controls)', () => {
      const controls = Array.from({ length: 8 }, (_, i) => `breach_${i}`)
      const diff: CurationDiff = {
        tenantId: 'tenant-e2e-3',
        institutionType: 'insurance',
        posture: 'audit',
        changeType: 'newBreaches',
        previousStatus: {},
        currentStatus: Object.fromEntries(controls.map(c => [c, 'failed'])),
        affectedControls: controls,
        severity: 'high',
      }

      const alert = buildAlertFromDiff(diff)
      const escalated = escalateIfCritical([alert])

      expect(escalated[0].severity).toBe('critical')
      expect(escalated[0].escalated).toBe(true)
      expect(escalated[0].controlCount).toBe(8)

      const formatted = formatAlertPayload(escalated[0])
      expect(formatted.summary).toContain('8')
    })
  })
})
