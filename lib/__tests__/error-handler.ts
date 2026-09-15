export interface ErrorContext {
  testName?: string
  stackTrace?: string
  assertion?: string
  timestamp: number
  duration?: number
  environment?: Record<string, unknown>
}

export class TestErrorHandler {
  private static instance: TestErrorHandler
  private errors: Array<{ error: Error; context: ErrorContext }> = []
  private startTime: Map<string, number> = new Map()

  private constructor() {}

  static getInstance(): TestErrorHandler {
    if (!TestErrorHandler.instance) {
      TestErrorHandler.instance = new TestErrorHandler()
    }
    return TestErrorHandler.instance
  }

  startTest(testName: string): void {
    this.startTime.set(testName, Date.now())
  }

  recordError(error: Error, context: Partial<ErrorContext> = {}): void {
    const errorContext: ErrorContext = {
      testName: context.testName,
      stackTrace: error.stack,
      assertion: context.assertion,
      timestamp: Date.now(),
      duration: context.testName ? Date.now() - (this.startTime.get(context.testName) || Date.now()) : undefined,
      environment: context.environment,
    }

    this.errors.push({ error, context: errorContext })
  }

  endTest(testName: string): void {
    this.startTime.delete(testName)
  }

  getErrors(): Array<{ error: Error; context: ErrorContext }> {
    return [...this.errors]
  }

  hasErrors(): boolean {
    return this.errors.length > 0
  }

  clear(): void {
    this.errors = []
    this.startTime.clear()
  }

  formatError(error: Error, context: ErrorContext): string {
    const parts: string[] = []

    if (context.testName) {
      parts.push(`Test: ${context.testName}`)
    }

    parts.push(`Error: ${error.name}: ${error.message}`)

    if (context.assertion) {
      parts.push(`Assertion: ${context.assertion}`)
    }

    if (context.duration !== undefined) {
      parts.push(`Duration: ${context.duration}ms`)
    }

    if (context.stackTrace) {
      parts.push(`\nStack trace:\n${context.stackTrace}`)
    }

    if (context.environment && Object.keys(context.environment).length > 0) {
      parts.push(`\nEnvironment:\n${JSON.stringify(context.environment, null, 2)}`)
    }

    return parts.join('\n')
  }

  generateReport(): string {
    if (this.errors.length === 0) {
      return 'No errors recorded'
    }

    const report: string[] = [
      `\n${'='.repeat(60)}`,
      'TEST ERROR REPORT',
      `${'='.repeat(60)}`,
      `Total Errors: ${this.errors.length}\n`,
    ]

    for (const { error, context } of this.errors) {
      report.push(this.formatError(error, context))
      report.push('\n' + '-'.repeat(60) + '\n')
    }

    return report.join('\n')
  }
}

export function createErrorHandler(): TestErrorHandler {
  return TestErrorHandler.getInstance()
}

export class AssertionError extends Error {
  constructor(
    public expected: unknown,
    public actual: unknown,
    message: string,
  ) {
    super(message)
    this.name = 'AssertionError'
  }

  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      message: this.message,
      expected: this.expected,
      actual: this.actual,
    }
  }
}

export function createAssertionError(expected: unknown, actual: unknown, message: string): AssertionError {
  return new AssertionError(expected, actual, message)
}
