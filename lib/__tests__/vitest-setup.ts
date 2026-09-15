import { afterEach, beforeEach, afterAll } from 'vitest'
import { globalErrorCollector, setupTestIsolation, setupCleanupHooks } from './test-helpers'

setupTestIsolation()
setupCleanupHooks()

let testCount = 0
let failedTestCount = 0
let passedTestCount = 0

beforeEach((context) => {
  testCount++
  if (context.task.name) {
    globalErrorCollector.setCurrentTestName(context.task.name)
  }
})

afterEach((context) => {
  const failed = globalErrorCollector.hasErrors()
  if (failed) {
    failedTestCount++
  } else {
    passedTestCount++
  }
})

afterAll(() => {
  const summary = [
    `\n=== Test Execution Summary ===`,
    `Total tests: ${testCount}`,
    `Passed: ${passedTestCount}`,
    `Failed: ${failedTestCount}`,
    `Pass rate: ${testCount > 0 ? ((passedTestCount / testCount) * 100).toFixed(2) : 0}%`,
  ]
  console.log(summary.join('\n'))
})

process.on('uncaughtException', (error) => {
  globalErrorCollector.collectError(error, { source: 'uncaughtException' })
  console.error('Uncaught exception caught by fail-soft handler:', error)
})

process.on('unhandledRejection', (reason) => {
  const error = reason instanceof Error ? reason : new Error(String(reason))
  globalErrorCollector.collectError(error, { source: 'unhandledRejection' })
  console.error('Unhandled rejection caught by fail-soft handler:', reason)
})
