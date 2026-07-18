/**
 * taskDecomposer.ts — Stub for AI-assisted task decomposition.
 */
export const TASK_DECOMPOSER_ENABLED = process.env.TASK_DECOMPOSER_ENABLED === '1'

export interface SubTask {
  title: string
  estimatedMinutes: number
  kind: string
}

export function decomposeStub(title: string): SubTask[] {
  return [{ title, estimatedMinutes: 15, kind: 'build' }]
}
