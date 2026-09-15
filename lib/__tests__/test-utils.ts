export async function waitFor(
  predicate: () => boolean | Promise<boolean>,
  options: { timeout?: number; interval?: number } = {},
): Promise<void> {
  const { timeout = 5000, interval = 100 } = options
  const startTime = Date.now()

  while (Date.now() - startTime < timeout) {
    try {
      const result = await Promise.resolve(predicate())
      if (result) {
        return
      }
    } catch {
      // Continue waiting
    }
    await new Promise((resolve) => setTimeout(resolve, interval))
  }

  throw new Error(`waitFor timeout after ${timeout}ms`)
}

export async function retry<T>(
  fn: () => Promise<T>,
  options: { maxAttempts?: number; delay?: number } = {},
): Promise<T> {
  const { maxAttempts = 3, delay = 100 } = options

  let lastError: Error | null = null
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn()
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))
      if (attempt < maxAttempts) {
        await new Promise((resolve) => setTimeout(resolve, delay * attempt))
      }
    }
  }

  throw lastError || new Error('retry failed')
}

export function createTestContext(): { cleanup: () => void; addCleanup: (fn: () => void) => void } {
  const cleanupFunctions: Array<() => void> = []

  return {
    addCleanup(fn: () => void) {
      cleanupFunctions.push(fn)
    },
    cleanup() {
      for (const fn of cleanupFunctions.reverse()) {
        try {
          fn()
        } catch (error) {
          console.error('Error during cleanup:', error)
        }
      }
    },
  }
}

export async function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  message: string = 'Operation timed out',
): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error(message)), timeoutMs),
    ),
  ])
}

export class MockCleanupStack {
  private stack: Array<() => Promise<void> | void> = []

  push(fn: () => Promise<void> | void): void {
    this.stack.push(fn)
  }

  async clean(): Promise<void> {
    const errors: Error[] = []
    for (const fn of this.stack.reverse()) {
      try {
        await fn()
      } catch (error) {
        errors.push(error instanceof Error ? error : new Error(String(error)))
      }
    }
    if (errors.length > 0) {
      const combined = new Error(`${errors.length} error(s) during cleanup`)
      combined.cause = errors
      throw combined
    }
  }
}

export async function suppressConsoleOutput<T>(
  fn: () => Promise<T>,
  methods: ('log' | 'error' | 'warn' | 'info')[] = ['log', 'error', 'warn', 'info'],
): Promise<T> {
  const originals = new Map<string, unknown>()
  for (const method of methods) {
    originals.set(method, console[method as keyof typeof console])
    console[method as keyof typeof console] = () => {} as unknown
  }

  try {
    return await fn()
  } finally {
    for (const [method, original] of originals) {
      console[method as keyof typeof console] = original as unknown
    }
  }
}
