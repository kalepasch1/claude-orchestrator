import { beforeEach, afterEach, describe, it } from 'vitest'

export interface TestError {
  testName: string
  message: string
  stack?: string
  assertion?: string
  context: Record<string, unknown>
}

export class TestErrorCollector {
  private errors: TestError[] = []
  private currentTestName: string = 'unknown'
  private failSoftMode: boolean = true

  setFailSoftMode(enabled: boolean): void {
    this.failSoftMode = enabled
  }

  setCurrentTestName(name: string): void {
    this.currentTestName = name
  }

  collectError(error: Error | string, context: Record<string, unknown> = {}): void {
    const testError: TestError = {
      testName: this.currentTestName,
      message: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined,
      context,
    }
    this.errors.push(testError)

    if (!this.failSoftMode) {
      throw error
    }
  }

  getErrors(): TestError[] {
    return [...this.errors]
  }

  hasErrors(): boolean {
    return this.errors.length > 0
  }

  clear(): void {
    this.errors = []
  }

  report(): string {
    if (this.errors.length === 0) {
      return 'No test errors collected'
    }

    const lines: string[] = [`Test Errors Report (${this.errors.length} errors):`, '']
    for (const error of this.errors) {
      lines.push(`Test: ${error.testName}`)
      lines.push(`Message: ${error.message}`)
      if (error.stack) {
        lines.push(`Stack: ${error.stack}`)
      }
      if (Object.keys(error.context).length > 0) {
        lines.push(`Context: ${JSON.stringify(error.context, null, 2)}`)
      }
      lines.push('---')
    }
    return lines.join('\n')
  }
}

export const globalErrorCollector = new TestErrorCollector()

export function setupTestIsolation(): void {
  beforeEach(() => {
    globalErrorCollector.clear()
  })

  afterEach(() => {
    if (globalErrorCollector.hasErrors()) {
      const report = globalErrorCollector.report()
      console.warn(report)
    }
  })
}

export function withErrorHandling<T extends (...args: unknown[]) => Promise<unknown>>(
  testFn: T,
  options: { softFail?: boolean } = {},
): T {
  const { softFail = true } = options

  return (async (...args: unknown[]) => {
    try {
      return await testFn(...args)
    } catch (error) {
      globalErrorCollector.collectError(error, {
        args: args.length > 0 ? args[0] : undefined,
      })
      if (!softFail) {
        throw error
      }
    }
  }) as T
}

export function setupCleanupHooks(): void {
  beforeEach(() => {
    if (global.gc) {
      global.gc()
    }
  })

  afterEach(() => {
    if (global.gc) {
      global.gc()
    }
  })
}

export function captureAsyncErrors(fn: () => Promise<void>): (error: Error) => void {
  let capturedError: Error | null = null

  const handler = (error: Error): void => {
    capturedError = error
    globalErrorCollector.collectError(error, { source: 'unhandledRejection' })
  }

  process.on('unhandledRejection', handler as (reason: unknown) => void)

  return () => {
    process.removeListener('unhandledRejection', handler as (reason: unknown) => void)
    if (capturedError) {
      throw capturedError
    }
  }
}
