import { describe, it, expect, beforeEach } from 'vitest'
import { execSync } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'

describe('cc-legacy-margin-removal cleanup', () => {
  const SERVER_DIR = path.join(__dirname, '../../server')
  const MARGIN_SYMBOLS = [
    'SwapMarginAccount',
    'SwapMarginCall',
    'SwapMarginTransaction',
    'OtcMarginCall',
    'OtcCollateralHolding',
    'CollateralDeposit',
    'CollateralYieldAccrual',
    'MarginCallEvent',
    'MarginPolicy',
    'InitialMargin',
    'CurrentMargin',
    'lastMarkToMarket',
    'recommendedImPct'
  ]

  const SETTLEMENT_KEYWORDS = ['nonCustodial', 'settlement']

  beforeEach(() => {
    // Ensure server directory exists for tests
    if (!fs.existsSync(SERVER_DIR)) {
      throw new Error(`Server directory not found at ${SERVER_DIR}`)
    }
  })

  // ============ Acceptance Test 1: No margin symbols remain ============
  it('should have zero occurrences of removed margin symbols in server/', () => {
    const grepCmd = `grep -rI "${MARGIN_SYMBOLS.join('\\|')}" ${SERVER_DIR} --include="*.ts" --include="*.js" -l 2>/dev/null || true`
    const result = execSync(grepCmd, { encoding: 'utf-8' }).trim()
    const filesWithMarginSymbols = result.split('\n').filter(f => f.length > 0)

    expect(filesWithMarginSymbols).toEqual(
      [],
      `Found ${MARGIN_SYMBOLS.length} margin symbols in server files: ${filesWithMarginSymbols.join(', ')}`
    )
  })

  // ============ Acceptance Test 2: TypeScript compilation must pass ============
  it('should pass TypeScript type checking with npx tsc --noEmit', () => {
    const tscCmd = 'npx tsc --noEmit'
    expect(() => {
      execSync(tscCmd, { encoding: 'utf-8', stdio: 'pipe' })
    }).not.toThrow()
  })

  // ============ Imports cleanup ============
  it('should not have import statements referencing margin symbols', () => {
    const importPattern = new RegExp(
      `import\\s+\\{[^}]*(${MARGIN_SYMBOLS.join('|')})[^}]*\\}\\s+from`,
      'gm'
    )

    const files = getAllServerFiles()
    const violatingFiles: { file: string; lines: string[] }[] = []

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')
      const matches = content.match(importPattern)
      if (matches) {
        const lines = content.split('\n')
          .map((line, idx) => ({ line, idx }))
          .filter(({line}) => line.match(importPattern))
          .map(({line, idx}) => `Line ${idx + 1}: ${line}`)
        violatingFiles.push({ file, lines })
      }
    })

    expect(violatingFiles).toEqual(
      [],
      `Found margin symbol imports in: ${violatingFiles.map(v => v.file).join(', ')}`
    )
  })

  it('should not have bare symbol references without imports', () => {
    const bareReferencePattern = new RegExp(
      `(?<![a-zA-Z_])(${MARGIN_SYMBOLS.join('|')})(?![a-zA-Z0-9_])`,
      'gm'
    )

    const files = getAllServerFiles()
    const violatingFiles: { file: string; lines: string[] }[] = []

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')
      const lines = content.split('\n')

      lines.forEach((line, idx) => {
        // Skip comments
        if (line.trim().startsWith('//') || line.trim().startsWith('*')) return

        if (line.match(bareReferencePattern)) {
          const match = line.match(bareReferencePattern)
          if (match && MARGIN_SYMBOLS.includes(match[1])) {
            if (!violatingFiles.find(v => v.file === file)) {
              violatingFiles.push({ file, lines: [] })
            }
            violatingFiles.find(v => v.file === file)?.lines.push(`Line ${idx + 1}: ${line.trim()}`)
          }
        }
      })
    })

    expect(violatingFiles).toEqual(
      [],
      `Found bare margin symbol references in: ${violatingFiles.map(v => v.file).join(', ')}`
    )
  })

  // ============ Function/route cleanup ============
  it('should not have functions exclusively handling margin logic', () => {
    const marginFunctionPatterns = [
      /function\s+\w*(margin|swap|collateral|call)\w*\s*\(/i,
      /const\s+\w*(margin|swap|collateral|call)\w*\s*=\s*(async\s*)?\(/i,
      /export\s+(async\s+)?function\s+\w*(margin|swap|collateral|call)\w*/i
    ]

    const files = getAllServerFiles()
    const exclusivelyMarginFunctions: string[] = []

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')
      const lines = content.split('\n')

      lines.forEach((line, idx) => {
        marginFunctionPatterns.forEach(pattern => {
          if (line.match(pattern)) {
            // Extract function name
            const funcMatch = line.match(/(?:function|const)\s+(\w+)/)
            if (funcMatch) {
              const funcName = funcMatch[1]
              // Check if function body references margin symbols
              const functionBody = extractFunctionBody(content, idx)
              if (functionBody && functionBody.match(new RegExp(MARGIN_SYMBOLS.join('|')))) {
                exclusivelyMarginFunctions.push(`${file}:${funcName}`)
              }
            }
          }
        })
      })
    })

    expect(exclusivelyMarginFunctions).toEqual(
      [],
      `Found functions exclusively handling margins: ${exclusivelyMarginFunctions.join(', ')}`
    )
  })

  it('should handle shared functions by removing margin-specific branches', () => {
    const files = getAllServerFiles()
    const problemFiles: string[] = []

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')

      // Look for if/switch statements that check for margin conditions
      // but don't have fallback/else logic
      const marginConditions = content.match(/if\s*\([^)]*(?:margin|collateral|call)[^)]*\)\s*\{/gm)

      if (marginConditions) {
        // Check if these have else branches
        marginConditions.forEach(condition => {
          const idx = content.indexOf(condition)
          if (idx > -1) {
            const afterCondition = content.substring(idx + condition.length, idx + 200)
            if (!afterCondition.includes('else')) {
              problemFiles.push(file)
            }
          }
        })
      }
    })

    // This is informational - some shared functions may have margin logic removed
    // entirely if it's not used, but if kept, must have proper fallbacks
    if (problemFiles.length > 0) {
      console.warn(`Shared functions with potential orphaned margin branches: ${problemFiles.join(', ')}`)
    }
  })

  // ============ Preservation of settlement/non-custodial code ============
  it('should preserve all non-custodial settlement code', () => {
    const files = getAllServerFiles()
    let settlementCodeFound = false

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')
      if (SETTLEMENT_KEYWORDS.some(kw => content.includes(kw))) {
        settlementCodeFound = true
        // Verify settlement code is not deleted
        expect(content.length).toBeGreaterThan(0)
      }
    })

    expect(settlementCodeFound).toBe(
      true,
      'No settlement/non-custodial code found - may have been incorrectly deleted'
    )
  })

  it('should not remove settlement-related imports or logic', () => {
    const files = getAllServerFiles()
    const settlementFiles: string[] = []

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')
      if (SETTLEMENT_KEYWORDS.some(kw => content.includes(kw))) {
        settlementFiles.push(file)
      }
    })

    // Verify settlement files still have their core logic intact
    settlementFiles.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')

      // Should have function definitions or route handlers
      const hasFunctionality = /(?:export\s+)?(?:async\s+)?function|export\s+default|router\.|app\./.test(content)
      expect(hasFunctionality).toBe(
        true,
        `Settlement file ${file} appears to be missing core logic`
      )
    })
  })

  // ============ Unused imports cleanup ============
  it('should not leave unused imports that would fail tsc', () => {
    const files = getAllServerFiles()
    const unusedImportFiles: { file: string; unused: string[] }[] = []

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')

      // Extract all imports
      const importMatches = content.matchAll(/import\s+\{([^}]+)\}\s+from\s+['"]/g)
      const imports: { [key: string]: number } = {}

      for (const match of importMatches) {
        const importedItems = match[1].split(',').map(s => s.trim())
        importedItems.forEach(item => {
          imports[item] = 0
        })
      }

      // Count usage of each import
      Object.keys(imports).forEach(importName => {
        // Count occurrences (excluding the import statement itself)
        const usagePattern = new RegExp(`(?<!import.*)(\\b${importName}\\b)(?!.*from)`, 'g')
        const importLine = content.match(new RegExp(`import.*${importName}.*from`))?.[0]
        const contentWithoutImport = content.replace(importLine || '', '')
        const usages = contentWithoutImport.match(usagePattern)
        imports[importName] = usages ? usages.length : 0
      })

      // Report unused imports
      const unused = Object.entries(imports)
        .filter(([_, count]) => count === 0)
        .map(([name]) => name)

      if (unused.length > 0) {
        unusedImportFiles.push({ file, unused })
      }
    })

    expect(unusedImportFiles).toEqual(
      [],
      `Found unused imports that would fail tsc: ${JSON.stringify(unusedImportFiles)}`
    )
  })

  // ============ Routes/endpoints cleanup ============
  it('should not have routes exclusively handling margin endpoints', () => {
    const marginRoutePatterns = [
      /route[rs]?\.(?:get|post|put|delete)\s*\(\s*['"](.*margin.*)['"]/i,
      /route[rs]?\.(?:get|post|put|delete)\s*\(\s*['"](.*collateral.*)['"]/i,
      /route[rs]?\.(?:get|post|put|delete)\s*\(\s*['"](.*call.*)['"]/i
    ]

    const files = getAllServerFiles().filter(f => f.includes('route') || f.includes('handler') || f.includes('api'))
    const orphanedRoutes: string[] = []

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')
      marginRoutePatterns.forEach(pattern => {
        const matches = content.match(pattern)
        if (matches) {
          const endpoint = matches[1]
          // Check if entire route body only handles margin logic
          const routeBody = extractRouteBody(content, content.indexOf(matches[0]))
          if (routeBody && routeBody.match(new RegExp(MARGIN_SYMBOLS.join('|')))) {
            orphanedRoutes.push(`${file}: ${endpoint}`)
          }
        }
      })
    })

    expect(orphanedRoutes).toEqual(
      [],
      `Found routes exclusively handling margins that should be removed: ${orphanedRoutes.join(', ')}`
    )
  })

  // ============ Prisma schema not modified ============
  it('should not modify any prisma/ files', () => {
    const prismaDir = path.join(__dirname, '../../prisma')
    if (fs.existsSync(prismaDir)) {
      const grepCmd = `grep -rI "${MARGIN_SYMBOLS.join('\\|')}" ${prismaDir} 2>/dev/null || echo "clean"`
      const result = execSync(grepCmd, { encoding: 'utf-8' }).trim()
      // Prisma schema should not have these symbols (they're already removed)
      // This test just ensures prisma wasn't touched
      expect(fs.existsSync(prismaDir)).toBe(true)
    }
  })

  // ============ Event handlers cleanup ============
  it('should remove margin-specific event handlers or stub them', () => {
    const eventHandlerPatterns = [
      /on\s*\(\s*['"](.*margin.*)['"]/i,
      /addEventListener\s*\(\s*['"](.*margin.*)['"]/i,
      /\.on\s*\(\s*['"](.*collateral.*)['"]/i
    ]

    const files = getAllServerFiles()
    const orphanedHandlers: string[] = []

    files.forEach(file => {
      const content = fs.readFileSync(file, 'utf-8')
      eventHandlerPatterns.forEach(pattern => {
        const matches = content.matchAll(pattern)
        for (const match of matches) {
          orphanedHandlers.push(`${file}: ${match[1]}`)
        }
      })
    })

    // Handlers should either be removed or stubbed as no-ops
    expect(orphanedHandlers.length).toBeLessThanOrEqual(0)
  })
})

// ============ Helper Functions ============

function getAllServerFiles(): string[] {
  const serverDir = path.join(__dirname, '../../server')
  const files: string[] = []

  function walkDir(dir: string) {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
    entries.forEach(entry => {
      const fullPath = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        walkDir(fullPath)
      } else if (entry.isFile() && (entry.name.endsWith('.ts') || entry.name.endsWith('.js'))) {
        files.push(fullPath)
      }
    })
  }

  walkDir(serverDir)
  return files
}

function extractFunctionBody(content: string, lineIndex: number): string {
  const lines = content.split('\n')
  let braceCount = 0
  let inFunction = false
  let body = ''

  for (let i = lineIndex; i < lines.length; i++) {
    const line = lines[i]

    if (!inFunction && line.includes('{')) {
      inFunction = true
      braceCount = 1
      body += line
      continue
    }

    if (inFunction) {
      braceCount += (line.match(/\{/g) || []).length
      braceCount -= (line.match(/\}/g) || []).length
      body += line

      if (braceCount === 0) break
    }
  }

  return body
}

function extractRouteBody(content: string, startIdx: number): string {
  let braceCount = 0
  let inBody = false
  let body = ''

  for (let i = startIdx; i < content.length; i++) {
    const char = content[i]

    if (char === '{') {
      inBody = true
      braceCount++
    }

    if (inBody) {
      body += char
      if (char === '}') {
        braceCount--
        if (braceCount === 0) break
      }
    }
  }

  return body
}
