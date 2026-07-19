/**
 * configTestSuite.ts — Enhanced testing utilities for configuration validation.
 */
export interface ConfigValidation {
  key: string
  valid: boolean
  reason: string
}

export function validateConfigKey(key: string, value: unknown): ConfigValidation {
  if (!key || typeof key !== 'string') return { key: key ?? '', valid: false, reason: 'Invalid key' }
  if (value === undefined || value === null) return { key, valid: false, reason: 'Value is null/undefined' }
  if (typeof value === 'string' && value.trim() === '') return { key, valid: false, reason: 'Empty string value' }
  return { key, valid: true, reason: 'OK' }
}

export function validateConfigBatch(config: Record<string, unknown>): ConfigValidation[] {
  return Object.entries(config).map(([k, v]) => validateConfigKey(k, v))
}
