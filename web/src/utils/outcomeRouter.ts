/**
 * outcomeRouter.ts — Outcome-trained task router stub.
 * Routes tasks to coders based on historical outcome data.
 */
export interface RouteDecision {
  taskSlug: string
  recommendedCoder: string
  score: number
}

export function routeTask(taskSlug: string, availableCoders: string[]): RouteDecision {
  if (availableCoders.length === 0) {
    return { taskSlug, recommendedCoder: 'default', score: 0 }
  }
  // Stub: round-robin by slug hash
  const hash = taskSlug.split('').reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0)
  const idx = Math.abs(hash) % availableCoders.length
  return { taskSlug, recommendedCoder: availableCoders[idx], score: 0.5 }
}
