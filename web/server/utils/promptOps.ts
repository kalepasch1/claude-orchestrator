/**
 * Prompt-Driven Ops — processes PROMPT-*.md files as admin commands.
 * Integrates with the existing intake_watcher pattern from the orchestrator's Python runner.
 *
 * When a PROMPT file is detected, it:
 * 1. Parses the markdown for intent (using Claude)
 * 2. Maps intent to proxy API calls or fleet execute commands
 * 3. Executes with the same approval flow as NL Admin
 * 4. Writes results back to a RESULT-*.md file
 */

import Anthropic from '@anthropic-ai/sdk'

interface PromptAction {
  endpoint: string
  method: string
  body: any
  description?: string
}

export interface PromptOp {
  id: string
  filename: string
  content: string
  intent?: string
  actions?: PromptAction[]
  status: 'pending' | 'parsed' | 'approved' | 'executing' | 'complete' | 'failed'
  result?: string
  error?: string
  createdAt: string
  completedAt?: string
}

// In-memory prompt ops store
const promptOps: PromptOp[] = []

function generateId(): string {
  return `prompt-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

const PARSE_SYSTEM = `You are an operations command parser for the SMRTER fleet orchestrator.
Given a prompt-ops markdown file, extract:
1. The operator's intent (a concise summary)
2. A list of API actions to execute

Available API endpoints:
- GET /api/proxy/apps — list all apps
- GET /api/proxy/{app}/users — list users for an app
- POST /api/proxy/{app}/query — query a database table (body: { table, select?, filters?, limit? })
- POST /api/proxy/{app}/execute — execute a fleet action (body: { action: { type, ... } })
- GET /api/fleet/incidents — list fleet incidents
- GET /api/fleet/policies — list auto-policies
- POST /api/fleet/policies — create a policy
- GET /api/admin/deploys — deploy history
- POST /api/admin/deploys/create — create a deploy plan

Respond with JSON only (no markdown fences):
{
  "intent": "short summary of what the operator wants",
  "actions": [
    { "endpoint": "/api/...", "method": "GET|POST", "body": {...} or null, "description": "what this does" }
  ]
}`

export async function parsePromptFile(content: string): Promise<{ intent: string; actions: PromptAction[] }> {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    return {
      intent: 'Could not parse — ANTHROPIC_API_KEY not configured',
      actions: [],
    }
  }

  try {
    const client = new Anthropic({ apiKey })
    const response = await client.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 2048,
      system: PARSE_SYSTEM,
      messages: [{ role: 'user', content }],
    })

    const text = response.content
      .filter(b => b.type === 'text')
      .map(b => (b as Anthropic.TextBlock).text)
      .join('')

    const parsed = JSON.parse(text)
    return {
      intent: parsed.intent || 'Unknown intent',
      actions: Array.isArray(parsed.actions) ? parsed.actions : [],
    }
  } catch (e: any) {
    return {
      intent: `Parse error: ${e.message}`,
      actions: [],
    }
  }
}

export async function executePromptOp(op: PromptOp): Promise<PromptOp> {
  if (!op.actions || op.actions.length === 0) {
    op.status = 'failed'
    op.error = 'No actions to execute'
    op.completedAt = new Date().toISOString()
    return op
  }

  op.status = 'executing'
  const results: string[] = []

  for (const action of op.actions) {
    try {
      const fetchOptions: any = {
        method: action.method,
      }
      if (action.body && action.method !== 'GET') {
        fetchOptions.body = action.body
      }

      const result = await $fetch(action.endpoint, fetchOptions)
      results.push(`[OK] ${action.description || action.endpoint}: ${JSON.stringify(result).slice(0, 500)}`)
    } catch (e: any) {
      results.push(`[ERR] ${action.description || action.endpoint}: ${e.message || String(e)}`)
    }
  }

  op.result = results.join('\n\n')
  op.status = 'complete'
  op.completedAt = new Date().toISOString()
  return op
}

export async function processPromptFile(filename: string, content: string): Promise<PromptOp> {
  const op: PromptOp = {
    id: generateId(),
    filename,
    content,
    status: 'pending',
    createdAt: new Date().toISOString(),
  }
  promptOps.unshift(op)

  // Parse intent
  const { intent, actions } = await parsePromptFile(content)
  op.intent = intent
  op.actions = actions
  op.status = 'parsed'

  return op
}

export function listPromptOps(): PromptOp[] {
  return promptOps
}

export function getPromptOp(id: string): PromptOp | undefined {
  return promptOps.find(op => op.id === id)
}

export async function approveAndExecute(id: string): Promise<PromptOp> {
  const op = promptOps.find(o => o.id === id)
  if (!op) throw new Error(`Prompt op ${id} not found`)
  if (op.status !== 'parsed') throw new Error(`Op ${id} is not in parsed state (status: ${op.status})`)

  op.status = 'approved'
  return executePromptOp(op)
}
