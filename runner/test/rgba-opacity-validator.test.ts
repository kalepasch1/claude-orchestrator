import { describe, it, expect, beforeEach } from 'vitest'

describe('rgba-opacity-validator', () => {
  describe('valid rgba with opacity specification', () => {
    it('should accept rgba with full opacity (1)', () => {
      const color = 'rgba(255, 0, 0, 1)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should accept rgba with zero opacity (0)', () => {
      const color = 'rgba(255, 0, 0, 0)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should accept rgba with decimal opacity', () => {
      const color = 'rgba(255, 0, 0, 0.5)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should accept rgba with leading-zero decimal opacity', () => {
      const color = 'rgba(0, 128, 255, 0.75)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should accept rgba with percentage opacity', () => {
      const color = 'rgba(100, 150, 200, 50%)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should accept rgba with spaces around values', () => {
      const color = 'rgba( 255 , 0 , 0 , 0.8 )'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should accept rgba with zero-padded color values', () => {
      const color = 'rgba(001, 002, 003, 0.9)'
      expect(isValidRgbaColor(color)).toBe(true)
    })
  })

  describe('invalid rgba without opacity specification', () => {
    it('should reject rgba with missing opacity parameter', () => {
      const color = 'rgba(255, 0, 0)'
      expect(isValidRgbaColor(color)).toBe(false)
    })

    it('should reject rgba with empty/whitespace opacity', () => {
      const color = 'rgba(255, 0, 0, )'
      expect(isValidRgbaColor(color)).toBe(false)
    })

    it('should reject rgba with missing closing paren', () => {
      const color = 'rgba(255, 0, 0'
      expect(isValidRgbaColor(color)).toBe(false)
    })

    it('should reject malformed rgba', () => {
      const color = 'rgba(255, 0, 0, invalid)'
      expect(isValidRgbaColor(color)).toBe(false)
    })

    it('should reject rgba with trailing comma only', () => {
      const color = 'rgba(255, 0, 0, ,)'
      expect(isValidRgbaColor(color)).toBe(false)
    })
  })

  describe('non-rgba colors (should pass through)', () => {
    it('should allow rgb (non-rgba) format', () => {
      const color = 'rgb(255, 0, 0)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should allow hex color notation', () => {
      const color = '#FF0000'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should allow hex with alpha', () => {
      const color = '#FF0000AA'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should allow named colors', () => {
      const colors = ['red', 'blue', 'green', 'transparent', 'inherit']
      colors.forEach(color => {
        expect(isValidRgbaColor(color)).toBe(true)
      })
    })

    it('should allow hsl notation', () => {
      const color = 'hsl(0, 100%, 50%)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should allow hsla with opacity', () => {
      const color = 'hsla(0, 100%, 50%, 0.5)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should allow empty/null values', () => {
      expect(isValidRgbaColor('')).toBe(true)
      expect(isValidRgbaColor(null)).toBe(true)
    })
  })

  describe('edge cases and whitespace handling', () => {
    it('should handle rgba with newlines in value', () => {
      const color = 'rgba(255,\n0,\n0,\n0.5)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should handle rgba with tabs', () => {
      const color = 'rgba(255,\t0,\t0,\t0.5)'
      expect(isValidRgbaColor(color)).toBe(true)
    })

    it('should reject rgba(255,0,0,) with trailing comma and no opacity', () => {
      const color = 'rgba(255,0,0,)'
      expect(isValidRgbaColor(color)).toBe(false)
    })

    it('should handle case-insensitive rgba', () => {
      const colors = ['RGBA(255, 0, 0, 0.5)', 'RgBa(255, 0, 0, 0.5)']
      colors.forEach(color => {
        expect(isValidRgbaColor(color)).toBe(true)
      })
    })
  })

  describe('batch color validation', () => {
    it('should validate multiple colors in an object', () => {
      const styles = {
        color: 'rgba(255, 0, 0, 0.8)',
        backgroundColor: 'rgba(0, 255, 0, 0.5)',
        borderColor: 'blue'
      }
      expect(validateStyleColors(styles)).toEqual({
        valid: true,
        invalidColors: []
      })
    })

    it('should reject object with invalid rgba', () => {
      const styles = {
        color: 'rgba(255, 0, 0)',
        backgroundColor: 'rgba(0, 255, 0, 0.5)'
      }
      const result = validateStyleColors(styles)
      expect(result.valid).toBe(false)
      expect(result.invalidColors).toContain('color')
    })

    it('should catch multiple invalid rgba values', () => {
      const styles = {
        color: 'rgba(255, 0, 0)',
        backgroundColor: 'rgba(0, 255, 0)',
        borderColor: 'blue'
      }
      const result = validateStyleColors(styles)
      expect(result.valid).toBe(false)
      expect(result.invalidColors.length).toBe(2)
    })
  })

  describe('security regression prevention', () => {
    it('should prevent rgba without opacity from injection', () => {
      const injected = 'rgba(255, 0, 0)'
      expect(isValidRgbaColor(injected)).toBe(false)
    })

    it('should allow rgba with proper opacity specification', () => {
      const safe = 'rgba(255, 0, 0, 0.5)'
      expect(isValidRgbaColor(safe)).toBe(true)
    })

    it('should preserve existing safe color formats', () => {
      const safeColors = [
        'red',
        '#FF0000',
        'rgb(255, 0, 0)',
        'rgba(255, 0, 0, 1)',
        'rgba(255, 0, 0, 0)',
        'hsl(0, 100%, 50%)',
        'hsla(0, 100%, 50%, 0.5)'
      ]
      safeColors.forEach(color => {
        expect(isValidRgbaColor(color)).toBe(true)
      })
    })

    it('should reject opacity-less rgba with various formats', () => {
      const invalidFormats = [
        'rgba(255,0,0)',
        'rgba(255, 0, 0)',
        'rgba( 255, 0, 0 )',
        'RGBA(255, 0, 0)'
      ]
      invalidFormats.forEach(format => {
        expect(isValidRgbaColor(format)).toBe(false)
      })
    })
  })

  describe('boundary conditions for opacity values', () => {
    it('should accept opacity exactly at 0', () => {
      expect(isValidRgbaColor('rgba(255, 0, 0, 0)')).toBe(true)
    })

    it('should accept opacity exactly at 1', () => {
      expect(isValidRgbaColor('rgba(255, 0, 0, 1)')).toBe(true)
    })

    it('should accept opacity exactly at 0.5', () => {
      expect(isValidRgbaColor('rgba(255, 0, 0, 0.5)')).toBe(true)
    })

    it('should accept opacity as percentage 0%', () => {
      expect(isValidRgbaColor('rgba(255, 0, 0, 0%)')).toBe(true)
    })

    it('should accept opacity as percentage 100%', () => {
      expect(isValidRgbaColor('rgba(255, 0, 0, 100%)')).toBe(true)
    })

    it('should accept very small decimal opacity', () => {
      expect(isValidRgbaColor('rgba(255, 0, 0, 0.001)')).toBe(true)
    })

    it('should accept many decimal places in opacity', () => {
      expect(isValidRgbaColor('rgba(255, 0, 0, 0.123456789)')).toBe(true)
    })
  })

  describe('color value boundaries', () => {
    it('should accept color values from 0 to 255', () => {
      expect(isValidRgbaColor('rgba(0, 0, 0, 0.5)')).toBe(true)
      expect(isValidRgbaColor('rgba(255, 255, 255, 0.5)')).toBe(true)
    })

    it('should accept mixed boundary color values', () => {
      expect(isValidRgbaColor('rgba(0, 128, 255, 0.5)')).toBe(true)
    })
  })
})

// Placeholder function signatures for test reference
function isValidRgbaColor(color: string | null | undefined): boolean {
  // Implementation should verify:
  // 1. If color starts with 'rgba(' (case-insensitive)
  // 2. It contains exactly 4 comma-separated values
  // 3. The 4th value (opacity) is present and valid (0-1, 0%-100%, or similar)
  // 4. All other colors pass through as valid
  throw new Error('Implementation required')
}

function validateStyleColors(styles: Record<string, string>): {
  valid: boolean
  invalidColors: string[]
} {
  // Implementation should validate all color properties
  // and collect any that have invalid rgba values
  throw new Error('Implementation required')
}
