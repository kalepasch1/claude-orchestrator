/**
 * ciWorkflowTemplates.ts — CI workflow template registry.
 */
export interface WorkflowTemplate {
  name: string
  steps: string[]
  timeoutMinutes: number
}

export const DEFAULT_TEMPLATES: WorkflowTemplate[] = [
  { name: 'build-and-test', steps: ['checkout', 'install', 'build', 'test'], timeoutMinutes: 15 },
  { name: 'lint-only', steps: ['checkout', 'install', 'lint'], timeoutMinutes: 5 },
  { name: 'deploy-staging', steps: ['checkout', 'install', 'build', 'deploy'], timeoutMinutes: 20 },
]

export function findTemplate(name: string): WorkflowTemplate | undefined {
  return DEFAULT_TEMPLATES.find(t => t.name === name)
}
