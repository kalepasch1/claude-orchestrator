import Anthropic from '@anthropic-ai/sdk'

const SYSTEM_PROMPT = `You are an admin assistant for the SMRTER fleet orchestrator. You help operators query data across all managed apps.

Available apps: apparently, tomorrow, smarter, galop, hisanta, pareto, orchestrator

You have tools to query the proxy API layer. Use them to answer the operator's question, then summarize the results clearly.

When presenting data:
- Use markdown tables for tabular results
- Show counts and totals when relevant
- Highlight important findings
- If a query returns no data, say so clearly
- If a question is ambiguous, make your best interpretation and note your assumption`

const TOOLS: Anthropic.Tool[] = [
  {
    name: 'list_apps',
    description: 'List all configured apps in the fleet with their status',
    input_schema: { type: 'object' as const, properties: {}, required: [] },
  },
  {
    name: 'query_table',
    description: 'Query any database table in a specific app. Use this for data exploration.',
    input_schema: {
      type: 'object' as const,
      properties: {
        app: { type: 'string', description: 'App ID: apparently, tomorrow, smarter, galop, hisanta, pareto, orchestrator' },
        table: { type: 'string', description: 'Table name to query' },
        select: { type: 'string', description: 'Columns to select (default: *)' },
        filters: {
          type: 'array',
          description: 'Array of filter objects',
          items: {
            type: 'object',
            properties: {
              column: { type: 'string' },
              op: { type: 'string', enum: ['eq', 'neq', 'gt', 'lt', 'gte', 'lte', 'like', 'ilike', 'in'] },
              value: {},
            },
            required: ['column', 'op', 'value'],
          },
        },
        order: {
          type: 'object',
          properties: {
            column: { type: 'string' },
            ascending: { type: 'boolean' },
          },
        },
        limit: { type: 'number', description: 'Max rows to return (default: 50)' },
      },
      required: ['app', 'table'],
    },
  },
  {
    name: 'list_app_users',
    description: 'List or search users in a specific app. Optionally filter by email.',
    input_schema: {
      type: 'object' as const,
      properties: {
        app: { type: 'string', description: 'App ID' },
        email: { type: 'string', description: 'Optional email filter (partial match)' },
        limit: { type: 'number', description: 'Max users (default: 50)' },
      },
      required: ['app'],
    },
  },
  {
    name: 'cross_app_user_search',
    description: 'Search for a user by exact email across ALL apps. Returns which apps they have accounts in.',
    input_schema: {
      type: 'object' as const,
      properties: {
        email: { type: 'string', description: 'Exact email address to search' },
      },
      required: ['email'],
    },
  },
  {
    name: 'list_fleet_events',
    description: 'Get recent fleet events/incidents across all apps. Returns correlated incidents.',
    input_schema: {
      type: 'object' as const,
      properties: {
        windowMin: { type: 'number', description: 'Correlation window in minutes (default: 15)' },
      },
    },
  },
  {
    name: 'list_policies',
    description: 'List all auto-resolution policies in the fleet.',
    input_schema: { type: 'object' as const, properties: {}, required: [] },
  },
  {
    name: 'execute_fleet_action',
    description: 'Execute a fleet action on a specific app (e.g., disable user, run migration). Use with caution.',
    input_schema: {
      type: 'object' as const,
      properties: {
        app: { type: 'string', description: 'App ID' },
        action: { type: 'object', description: 'Action payload to execute' },
      },
      required: ['app', 'action'],
    },
  },
  {
    name: 'list_tables',
    description: 'List available tables in a specific app database.',
    input_schema: {
      type: 'object' as const,
      properties: {
        app: { type: 'string', description: 'App ID' },
      },
      required: ['app'],
    },
  },
]

async function executeTool(toolName: string, input: any): Promise<any> {
  try {
    switch (toolName) {
      case 'list_apps':
        return await $fetch('/api/proxy/apps')

      case 'query_table':
        return await $fetch(`/api/proxy/${input.app}/query`, {
          method: 'POST',
          body: {
            table: input.table,
            select: input.select,
            filters: input.filters,
            order: input.order,
            limit: input.limit ?? 50,
          },
        })

      case 'list_app_users':
        return await $fetch(`/api/proxy/${input.app}/users`, {
          params: { email: input.email, limit: input.limit },
        })

      case 'cross_app_user_search':
        return await $fetch('/api/proxy/cross-app/users', {
          params: { email: input.email },
        })

      case 'list_fleet_events':
        return await $fetch('/api/fleet/incidents', {
          params: { windowMin: input.windowMin },
        })

      case 'list_policies':
        return await $fetch('/api/fleet/policies')

      case 'execute_fleet_action':
        return await $fetch(`/api/proxy/${input.app}/execute`, {
          method: 'POST',
          body: { action: input.action },
        })

      case 'list_tables':
        return await $fetch(`/api/proxy/${input.app}/tables`)

      default:
        return { error: `Unknown tool: ${toolName}` }
    }
  } catch (e: any) {
    return { error: e.message || String(e) }
  }
}

export default defineEventHandler(async (event) => {
  const body = await readBody<{ query: string; history?: Array<{ role: string; content: string }> }>(event)

  if (!body?.query?.trim()) {
    throw createError({ statusCode: 400, message: 'query is required' })
  }

  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    throw createError({ statusCode: 500, message: 'ANTHROPIC_API_KEY not configured' })
  }

  const client = new Anthropic({ apiKey })

  // Build messages from history + new query
  const messages: Anthropic.MessageParam[] = []

  if (body.history) {
    for (const msg of body.history) {
      if (msg.role === 'user' || msg.role === 'assistant') {
        messages.push({ role: msg.role, content: msg.content })
      }
    }
  }

  messages.push({ role: 'user', content: body.query })

  try {
    // Agentic loop: let Claude call tools until it produces a final text response
    let currentMessages = [...messages]
    const allData: any[] = []
    let iterations = 0
    const MAX_ITERATIONS = 10

    while (iterations < MAX_ITERATIONS) {
      iterations++

      const response = await client.messages.create({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 4096,
        system: SYSTEM_PROMPT,
        tools: TOOLS,
        messages: currentMessages,
      })

      // Check if Claude wants to use tools
      if (response.stop_reason === 'tool_use') {
        // Add the assistant message with tool_use blocks
        currentMessages.push({ role: 'assistant', content: response.content })

        // Execute each tool call and build tool results
        const toolResults: Anthropic.ToolResultBlockParam[] = []
        for (const block of response.content) {
          if (block.type === 'tool_use') {
            const result = await executeTool(block.name, block.input)
            if (result && !result.error) {
              allData.push({ tool: block.name, input: block.input, result })
            }
            toolResults.push({
              type: 'tool_result',
              tool_use_id: block.id,
              content: JSON.stringify(result),
            })
          }
        }

        currentMessages.push({ role: 'user', content: toolResults })
      } else {
        // Final response — extract text
        const textBlocks = response.content.filter(b => b.type === 'text')
        const responseText = textBlocks.map(b => (b as Anthropic.TextBlock).text).join('\n')

        return {
          response: responseText,
          data: allData.length > 0 ? allData : undefined,
          toolCalls: iterations - 1,
        }
      }
    }

    // If we hit max iterations, return what we have
    return {
      response: 'I ran into the maximum number of tool calls. Here is what I found so far.',
      data: allData.length > 0 ? allData : undefined,
      toolCalls: iterations,
    }
  } catch (e: any) {
    console.error('NL query error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to process query',
    })
  }
})
