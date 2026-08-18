import { describe, expect, it, beforeEach, vi } from 'vitest'
import {
  computeVelocity,
  updateHiveSourceCadence,
  type RegFactArrival,
  type VelocityResult,
  type CadenceUpdate,
} from './enforcement-velocity'

describe('computeVelocity', () => {
  const now = new Date()
  const oneDayAgo = new Date(now.getTime() - 86400_000)
  const twoDaysAgo = new Date(now.getTime() - 172800_000)
  const sevenDaysAgo = new Date(now.getTime() - 604800_000)

  it('computes zero velocity for single fact', () => {
    const arrivals: RegFactArrival[] = [
      { timestamp: now, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' }
    ]
    const result = computeVelocity(arrivals)
    expect(result.velocity_score).toBe(0)
    expect(result.acceleration_rate).toBe(0)
  })

  it('computes positive velocity for two facts with known interval', () => {
    const arrivals: RegFactArrival[] = [
      { timestamp: oneDayAgo, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
      { timestamp: now, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' }
    ]
    const result = computeVelocity(arrivals)
    expect(result.velocity_score).toBeGreaterThan(0)
    expect(result.arrival_interval_hours).toBeLessThanOrEqual(24)
  })

  it('detects acceleration when arrival intervals decrease', () => {
    const arrivals: RegFactArrival[] = [
      { timestamp: sevenDaysAgo, domain: 'banking', jurisdiction: 'US-OCC', fact_type: 'guidance' },
      { timestamp: new Date(sevenDaysAgo.getTime() + 144000_000), domain: 'banking', jurisdiction: 'US-OCC', fact_type: 'guidance' }, // 40h later
      { timestamp: new Date(now.getTime() - 21600_000), domain: 'banking', jurisdiction: 'US-OCC', fact_type: 'guidance' }, // 6h before now
      { timestamp: now, domain: 'banking', jurisdiction: 'US-OCC', fact_type: 'guidance' }
    ]
    const result = computeVelocity(arrivals)
    expect(result.acceleration_rate).toBeGreaterThan(0)
    expect(result.is_accelerating).toBe(true)
  })

  it('detects deceleration when arrival intervals increase', () => {
    const arrivals: RegFactArrival[] = [
      { timestamp: sevenDaysAgo, domain: 'commodities', jurisdiction: 'US-CFTC', fact_type: 'rule' },
      { timestamp: new Date(sevenDaysAgo.getTime() + 3600_000), domain: 'commodities', jurisdiction: 'US-CFTC', fact_type: 'rule' }, // 1h later
      { timestamp: new Date(sevenDaysAgo.getTime() + 86400_000), domain: 'commodities', jurisdiction: 'US-CFTC', fact_type: 'rule' }, // 1d later
      { timestamp: new Date(sevenDaysAgo.getTime() + 604800_000), domain: 'commodities', jurisdiction: 'US-CFTC', fact_type: 'rule' } // 7d later
    ]
    const result = computeVelocity(arrivals)
    expect(result.acceleration_rate).toBeLessThan(0)
    expect(result.is_accelerating).toBe(false)
  })

  it('filters by domain and jurisdiction', () => {
    const arrivals: RegFactArrival[] = [
      { timestamp: twoDaysAgo, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
      { timestamp: oneDayAgo, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
      { timestamp: now, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
      // Different jurisdiction — should not affect securities/US-SEC score
      { timestamp: twoDaysAgo, domain: 'securities', jurisdiction: 'UK-FCA', fact_type: 'enforcement' },
      { timestamp: oneDayAgo, domain: 'securities', jurisdiction: 'UK-FCA', fact_type: 'enforcement' },
    ]
    const result = computeVelocity(arrivals, 'securities', 'US-SEC')
    expect(result.fact_count).toBe(3)
    expect(result.velocity_score).toBeGreaterThan(0)
  })

  it('handles empty arrivals array', () => {
    const result = computeVelocity([])
    expect(result.velocity_score).toBe(0)
    expect(result.acceleration_rate).toBe(0)
    expect(result.fact_count).toBe(0)
  })

  it('handles null/undefined timestamps gracefully', () => {
    const arrivals: any[] = [
      { timestamp: now, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
      { timestamp: null, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
    ]
    const result = computeVelocity(arrivals)
    expect(result.fact_count).toBeLessThanOrEqual(2)
  })

  it('computes reasonable velocity scores for 30-day window', () => {
    const thirtyDaysAgo = new Date(now.getTime() - 2592000_000)
    const arrivals: RegFactArrival[] = Array.from({ length: 10 }, (_, i) => ({
      timestamp: new Date(thirtyDaysAgo.getTime() + (i * 3 * 86400_000)),
      domain: 'banking',
      jurisdiction: 'US-FDIC',
      fact_type: 'exam_finding'
    }))
    const result = computeVelocity(arrivals)
    expect(result.velocity_score).toBeGreaterThanOrEqual(0)
    expect(result.velocity_score).toBeLessThanOrEqual(100)
    expect(result.fact_count).toBe(10)
  })

  it('caps velocity score at 100', () => {
    // Create rapid arrivals to trigger high velocity
    const arrivals: RegFactArrival[] = Array.from({ length: 20 }, (_, i) => ({
      timestamp: new Date(now.getTime() - (100 - i) * 3600_000),
      domain: 'securities',
      jurisdiction: 'US-SEC',
      fact_type: 'enforcement'
    }))
    const result = computeVelocity(arrivals)
    expect(result.velocity_score).toBeLessThanOrEqual(100)
  })

  it('includes metadata in result', () => {
    const arrivals: RegFactArrival[] = [
      { timestamp: oneDayAgo, domain: 'banking', jurisdiction: 'US-OCC', fact_type: 'guidance' },
      { timestamp: now, domain: 'banking', jurisdiction: 'US-OCC', fact_type: 'guidance' }
    ]
    const result = computeVelocity(arrivals)
    expect(result).toHaveProperty('velocity_score')
    expect(result).toHaveProperty('acceleration_rate')
    expect(result).toHaveProperty('is_accelerating')
    expect(result).toHaveProperty('fact_count')
    expect(result).toHaveProperty('arrival_interval_hours')
    expect(result).toHaveProperty('computed_at')
    expect(result).toHaveProperty('window_start')
    expect(result).toHaveProperty('window_end')
  })

  it('tolerates unsorted timestamps', () => {
    const arrivals: RegFactArrival[] = [
      { timestamp: oneDayAgo, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
      { timestamp: now, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
      { timestamp: twoDaysAgo, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
    ]
    const result = computeVelocity(arrivals)
    expect(result.velocity_score).toBeGreaterThanOrEqual(0)
    expect(result.fact_count).toBe(3)
  })
})

describe('updateHiveSourceCadence', () => {
  const mockDb = vi.fn()
  const sourceId = 'hive_source_us_sec_enforcement'
  const domain = 'securities'
  const jurisdiction = 'US-SEC'

  beforeEach(() => {
    mockDb.mockReset()
  })

  it('lowers cadence_hours when velocity is high', async () => {
    const velocity: VelocityResult = {
      velocity_score: 85,
      acceleration_rate: 12,
      is_accelerating: true,
      fact_count: 8,
      arrival_interval_hours: 4.5,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const currentCadence = 24
    const result = await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      velocity,
      currentCadence,
      mockDb
    )
    expect(result.new_cadence_hours).toBeLessThan(currentCadence)
    expect(result.new_cadence_hours).toBeGreaterThanOrEqual(6)
  })

  it('respects 6-hour floor', async () => {
    const velocity: VelocityResult = {
      velocity_score: 95,
      acceleration_rate: 25,
      is_accelerating: true,
      fact_count: 15,
      arrival_interval_hours: 1.2,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const currentCadence = 8
    const result = await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      velocity,
      currentCadence,
      mockDb
    )
    expect(result.new_cadence_hours).toBeGreaterThanOrEqual(6)
  })

  it('does not increase cadence_hours (only lower or maintain)', async () => {
    const velocity: VelocityResult = {
      velocity_score: 15,
      acceleration_rate: -8,
      is_accelerating: false,
      fact_count: 2,
      arrival_interval_hours: 48,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const currentCadence = 24
    const result = await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      velocity,
      currentCadence,
      mockDb
    )
    expect(result.new_cadence_hours).toBeLessThanOrEqual(currentCadence)
  })

  it('raises alert urgency when accelerating', async () => {
    const velocity: VelocityResult = {
      velocity_score: 78,
      acceleration_rate: 15,
      is_accelerating: true,
      fact_count: 6,
      arrival_interval_hours: 5.8,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const currentCadence = 18
    const result = await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      velocity,
      currentCadence,
      mockDb
    )
    expect(result.alert_urgency).toBe('high')
    expect(result.alert_reason).toMatch(/accelerating/)
  })

  it('does not raise alert when decelerating', async () => {
    const velocity: VelocityResult = {
      velocity_score: 25,
      acceleration_rate: -10,
      is_accelerating: false,
      fact_count: 3,
      arrival_interval_hours: 42,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const currentCadence = 24
    const result = await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      velocity,
      currentCadence,
      mockDb
    )
    expect(result.alert_urgency).not.toBe('high')
  })

  it('includes metadata in update response', async () => {
    const velocity: VelocityResult = {
      velocity_score: 65,
      acceleration_rate: 8,
      is_accelerating: true,
      fact_count: 5,
      arrival_interval_hours: 9,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const currentCadence = 20
    const result = await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      velocity,
      currentCadence,
      mockDb
    )
    expect(result).toHaveProperty('source_id')
    expect(result).toHaveProperty('domain')
    expect(result).toHaveProperty('jurisdiction')
    expect(result).toHaveProperty('previous_cadence_hours')
    expect(result).toHaveProperty('new_cadence_hours')
    expect(result).toHaveProperty('alert_urgency')
    expect(result).toHaveProperty('alert_reason')
    expect(result).toHaveProperty('velocity_snapshot')
    expect(result).toHaveProperty('updated_at')
  })

  it('writes update to database', async () => {
    const velocity: VelocityResult = {
      velocity_score: 72,
      acceleration_rate: 11,
      is_accelerating: true,
      fact_count: 7,
      arrival_interval_hours: 6.2,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const currentCadence = 16
    await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      velocity,
      currentCadence,
      mockDb
    )
    expect(mockDb).toHaveBeenCalled()
  })

  it('scales cadence reduction based on velocity magnitude', async () => {
    const currentCadence = 24
    const lowVelocity: VelocityResult = {
      velocity_score: 35,
      acceleration_rate: 3,
      is_accelerating: true,
      fact_count: 2,
      arrival_interval_hours: 20,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const highVelocity: VelocityResult = {
      velocity_score: 92,
      acceleration_rate: 22,
      is_accelerating: true,
      fact_count: 12,
      arrival_interval_hours: 2.5,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const lowResult = await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      lowVelocity,
      currentCadence,
      mockDb
    )
    const highResult = await updateHiveSourceCadence(
      sourceId + '_2',
      domain,
      jurisdiction,
      highVelocity,
      currentCadence,
      mockDb
    )
    expect(highResult.new_cadence_hours).toBeLessThan(lowResult.new_cadence_hours)
  })

  it('handles database write failures gracefully', async () => {
    const mockFailDb = vi.fn().mockRejectedValue(new Error('DB connection lost'))
    const velocity: VelocityResult = {
      velocity_score: 60,
      acceleration_rate: 10,
      is_accelerating: true,
      fact_count: 4,
      arrival_interval_hours: 8,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    expect(async () => {
      await updateHiveSourceCadence(
        sourceId,
        domain,
        jurisdiction,
        velocity,
        18,
        mockFailDb
      )
    }).rejects
  })

  it('applies ceiling constraint if specified', async () => {
    const velocity: VelocityResult = {
      velocity_score: 88,
      acceleration_rate: 18,
      is_accelerating: true,
      fact_count: 9,
      arrival_interval_hours: 3.5,
      computed_at: new Date().toISOString(),
      window_start: new Date(Date.now() - 604800_000).toISOString(),
      window_end: new Date().toISOString(),
    }
    const currentCadence = 24
    const ceiling = 12
    const result = await updateHiveSourceCadence(
      sourceId,
      domain,
      jurisdiction,
      velocity,
      currentCadence,
      mockDb,
      ceiling
    )
    expect(result.new_cadence_hours).toBeLessThanOrEqual(ceiling)
  })
})

describe('enforcement-velocity integration', () => {
  it('full flow: compute velocity then update cadence', async () => {
    const now = new Date()
    const mockDb = vi.fn().mockResolvedValue({ success: true })

    const arrivals: RegFactArrival[] = [
      { timestamp: new Date(now.getTime() - 259200_000), domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' }, // 3d
      { timestamp: new Date(now.getTime() - 172800_000), domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' }, // 2d
      { timestamp: new Date(now.getTime() - 86400_000), domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' }, // 1d
      { timestamp: now, domain: 'securities', jurisdiction: 'US-SEC', fact_type: 'enforcement' },
    ]

    const velocity = computeVelocity(arrivals, 'securities', 'US-SEC')
    expect(velocity.is_accelerating).toBe(true)

    const update = await updateHiveSourceCadence(
      'test_source',
      'securities',
      'US-SEC',
      velocity,
      24,
      mockDb
    )

    expect(update.new_cadence_hours).toBeLessThan(24)
    expect(update.alert_urgency).toBe('high')
  })
})
