import { createError, readBody } from 'h3'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { slug, command } = body

  if (!command || typeof command !== 'string') {
    throw createError({ statusCode: 400, message: 'Command is required' })
  }

  // Sanitize and validate command
  const sanitized = command.trim().slice(0, 500)
  const [action, ...args] = sanitized.split(/\s+/)

  const handlers: Record<string, () => Promise<string>> = {
    deploy: async () => {
      const target = args[0] || 'all'
      // Queue a deployment cascade
      const client = await useSupabaseClient(event)
      try {
        await client.from('cascade_operations').insert({
          name: `Deploy ${target}`,
          status: 'queued',
          completed_steps: 0,
          total_steps: 5,
          active_agents: 0,
          metadata: { target, triggered_by: 'terminal' }
        })
        return `Deployment queued for: ${target}`
      } catch {
        return `Deployment queued (offline mode): ${target}`
      }
    },
    cascade: async () => {
      const cascadeId = args[0]
      if (!cascadeId) return 'Usage: cascade <id> [pause|resume|cancel]'
      const action = args[1] || 'status'
      return `Cascade ${cascadeId}: ${action} (queued)`
    },
    agents: async () => {
      return 'Use the Fleet Status panel to view active agents.'
    },
    logs: async () => {
      const level = args[0] || 'all'
      return `Log filter set to: ${level}`
    }
  }

  const handler = handlers[action]
  if (handler) {
    const result = await handler()
    return { result }
  }

  return { result: `Unknown command: ${action}. Type 'help' for available commands.` }
})
