import Anthropic from '@anthropic-ai/sdk'

// POST /api/terminal/execute
// Accepts { command: string, history?: Message[], sessionId?: string }
// Returns streamed or buffered response from Claude with dev-focused tool use.

function buildSystemPrompt(serverless: boolean): string {
  const envNote = serverless
    ? `\nENVIRONMENT: Production (Vercel serverless)
- File system is READ-ONLY — write_file and edit_file are disabled.
- Shell commands are limited to safe read-only operations (git log/status/diff, ls, cat, echo, node -e).
- For full dev capabilities (npm install, file edits, builds), the user should use dev mode locally.
- You can still: read files, search code, query Supabase, and check deployment status.`
    : `\nENVIRONMENT: Development (local)
- Full filesystem read/write access available.
- All shell commands available (with safety blocks for destructive operations).
- Node.js 24.x, Python 3.x available.`

  return `You are a development terminal inside the Madeus orchestrator control plane. You execute code, run commands, manage files, and help implement features — exactly like an interactive development terminal.

BEHAVIOR:
- When the user types a shell command (e.g., ls, git status, npm install), execute it directly using the run_command tool.
- When the user asks to write/edit code, use the write_file or edit_file tools.
- When the user asks to read a file, use the read_file tool.
- When the user asks to search code, use the search_code tool.
- For multi-step tasks, chain operations automatically — don't ask permission for each step.
- Show output faithfully including errors. Format code with syntax highlighting markers.
- Be concise: show the output, not explanations of what you're doing.
- For git operations, use run_command with the appropriate git commands.
- You have full access to the orchestrator repository.
${envNote}

CONTEXT:
- This is a Nuxt 3 + TypeScript web app (the orchestrator control plane)
- Python runner modules live in /runner/
- Web app code lives in /web/ (pages, components, server, composables)
- Supabase is the database backend
- Deployed to Vercel
- Node.js 24.x, Python 3.x available

When producing output, use terminal-style formatting:
- Prefix file paths with colors/markers
- Show command outputs verbatim
- Use \`\`\` blocks for code
- Keep responses actionable and terse`
}

const TOOLS: Anthropic.Tool[] = [
  {
    name: 'run_command',
    description: 'Execute a shell command in the project directory. Returns stdout, stderr, and exit code. Use for: git, npm, python, ls, grep, find, cat, etc.',
    input_schema: {
      type: 'object' as const,
      properties: {
        command: { type: 'string', description: 'Shell command to execute' },
        cwd: { type: 'string', description: 'Working directory relative to project root (default: project root)' },
        timeout: { type: 'number', description: 'Timeout in ms (default: 30000, max: 120000)' },
      },
      required: ['command'],
    },
  },
  {
    name: 'read_file',
    description: 'Read a file from the project. Returns file content with line numbers.',
    input_schema: {
      type: 'object' as const,
      properties: {
        path: { type: 'string', description: 'File path relative to project root' },
        startLine: { type: 'number', description: 'Start line (1-indexed, default: 1)' },
        endLine: { type: 'number', description: 'End line (default: entire file)' },
      },
      required: ['path'],
    },
  },
  {
    name: 'write_file',
    description: 'Write content to a file. Creates parent directories if needed. Use for creating new files or full rewrites.',
    input_schema: {
      type: 'object' as const,
      properties: {
        path: { type: 'string', description: 'File path relative to project root' },
        content: { type: 'string', description: 'Full file content to write' },
      },
      required: ['path', 'content'],
    },
  },
  {
    name: 'edit_file',
    description: 'Replace a specific string in a file. For surgical edits without rewriting the entire file.',
    input_schema: {
      type: 'object' as const,
      properties: {
        path: { type: 'string', description: 'File path relative to project root' },
        oldText: { type: 'string', description: 'Exact text to find and replace' },
        newText: { type: 'string', description: 'Replacement text' },
      },
      required: ['path', 'oldText', 'newText'],
    },
  },
  {
    name: 'search_code',
    description: 'Search for a pattern across the codebase using ripgrep-style search. Returns matching lines with file paths and line numbers.',
    input_schema: {
      type: 'object' as const,
      properties: {
        pattern: { type: 'string', description: 'Search pattern (regex supported)' },
        path: { type: 'string', description: 'Directory to search in, relative to project root (default: entire project)' },
        filePattern: { type: 'string', description: 'Glob pattern to filter files (e.g., "*.ts", "*.vue")' },
        maxResults: { type: 'number', description: 'Max results to return (default: 30)' },
      },
      required: ['pattern'],
    },
  },
  {
    name: 'list_directory',
    description: 'List contents of a directory with file types and sizes.',
    input_schema: {
      type: 'object' as const,
      properties: {
        path: { type: 'string', description: 'Directory path relative to project root (default: root)' },
        recursive: { type: 'boolean', description: 'List recursively (default: false, max depth 3)' },
      },
      required: [],
    },
  },
  {
    name: 'deploy_check',
    description: 'Check the status of the latest Vercel deployment, including any build errors.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'supabase_query',
    description: 'Execute a read-only SQL query against the orchestrator Supabase database.',
    input_schema: {
      type: 'object' as const,
      properties: {
        sql: { type: 'string', description: 'SQL query (SELECT only)' },
      },
      required: ['sql'],
    },
  },
]

// --- Tool execution layer ---

import { exec } from 'node:child_process'
import { readFile, writeFile, mkdir, readdir, stat, access } from 'node:fs/promises'
import { join, dirname, resolve } from 'node:path'
import { promisify } from 'node:util'
import { createClient } from '@supabase/supabase-js'

const execAsync = promisify(exec)

/** Detect whether we're running inside Vercel's serverless runtime. */
function isServerless(): boolean {
  return !!(process.env.VERCEL || process.env.AWS_LAMBDA_FUNCTION_NAME || process.env.VERCEL_ENV)
}

function projectRoot(): string {
  // In Vercel serverless, there's no full repo — return the build output dir
  if (isServerless()) return resolve(process.cwd())
  // In dev mode, navigate to the repo root
  const webDir = resolve(process.cwd())
  if (webDir.endsWith('/web') || webDir.endsWith('\\web')) return resolve(webDir, '..')
  const parent = resolve(webDir, '..')
  return parent
}

// Safety: prevent obviously dangerous commands
const BLOCKED_PATTERNS = [
  /\brm\s+-rf\s+[\/~]/i,
  /\bmkfs\b/i,
  /\bdd\s+if=/i,
  /\b:(){.*};:/,
  /\bshutdown\b/i,
  /\breboot\b/i,
  /\bcurl\b.*\|\s*(sh|bash)/i,
]

async function execTool(name: string, input: any): Promise<string> {
  const root = projectRoot()

  switch (name) {
    case 'run_command': {
      const cmd = String(input.command || '').trim()
      if (!cmd) return 'Error: empty command'
      if (BLOCKED_PATTERNS.some(p => p.test(cmd))) return 'Error: command blocked for safety'

      // In serverless (Vercel), shell execution is sandboxed. Allow safe read-only
      // commands but block anything that writes or installs.
      if (isServerless()) {
        // Allow a curated set of read-only commands in serverless
        const SERVERLESS_ALLOWED = /^\s*(echo|cat|head|tail|wc|sort|uniq|date|env|node\s+-e|node\s+--version|npm\s+--version|ls|pwd|which|whoami|printenv|git\s+(log|status|diff|show|branch|rev-parse|remote|config))/
        if (!SERVERLESS_ALLOWED.test(cmd)) {
          return `⚠ Shell command not available in production (Vercel serverless).\n` +
            `Available in production: git log/status/diff, ls, cat, echo, node -e, env inspection.\n` +
            `For full shell access, use the terminal in development mode (npm run dev).\n` +
            `Tip: Use the read_file, write_file, search_code tools instead — they work everywhere.`
        }
      }

      const cwd = input.cwd ? resolve(root, input.cwd) : root
      const timeout = Math.min(Number(input.timeout) || 30_000, isServerless() ? 10_000 : 120_000)

      try {
        const { stdout, stderr } = await execAsync(cmd, {
          cwd,
          timeout,
          maxBuffer: 2 * 1024 * 1024,
          env: { ...process.env, FORCE_COLOR: '0', NO_COLOR: '1' },
        })
        const parts: string[] = []
        if (stdout.trim()) parts.push(stdout.trim())
        if (stderr.trim()) parts.push(`[stderr]\n${stderr.trim()}`)
        return parts.join('\n') || '(no output)'
      } catch (e: any) {
        const out = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim()
        if (isServerless() && (e.code === 'ENOENT' || e.message?.includes('not found'))) {
          return `Command not available in serverless environment.\nUse the specialized tools (read_file, search_code) or run in dev mode.`
        }
        return `Exit code ${e.code ?? 1}\n${out}`
      }
    }

    case 'read_file': {
      const filePath = resolve(root, String(input.path || ''))
      if (!filePath.startsWith(root)) return 'Error: path outside project'
      try {
        const content = await readFile(filePath, 'utf8')
        const lines = content.split('\n')
        const start = Math.max(1, Number(input.startLine) || 1)
        const end = Number(input.endLine) || lines.length
        return lines
          .slice(start - 1, end)
          .map((line, i) => `${String(start + i).padStart(4)} | ${line}`)
          .join('\n')
      } catch (e: any) {
        return `Error reading file: ${e.message}`
      }
    }

    case 'write_file': {
      if (isServerless()) {
        return '⚠ File writing is disabled in production (read-only filesystem).\nUse the terminal in development mode (npm run dev) for file modifications.'
      }
      const filePath = resolve(root, String(input.path || ''))
      if (!filePath.startsWith(root)) return 'Error: path outside project'
      try {
        await mkdir(dirname(filePath), { recursive: true })
        await writeFile(filePath, input.content, 'utf8')
        const lines = String(input.content).split('\n').length
        return `Wrote ${lines} lines to ${input.path}`
      } catch (e: any) {
        return `Error writing file: ${e.message}`
      }
    }

    case 'edit_file': {
      if (isServerless()) {
        return '⚠ File editing is disabled in production (read-only filesystem).\nUse the terminal in development mode (npm run dev) for file modifications.'
      }
      const filePath = resolve(root, String(input.path || ''))
      if (!filePath.startsWith(root)) return 'Error: path outside project'
      try {
        const content = await readFile(filePath, 'utf8')
        if (!content.includes(input.oldText)) return `Error: old text not found in ${input.path}`
        const newContent = content.replace(input.oldText, input.newText)
        await writeFile(filePath, newContent, 'utf8')
        return `Edited ${input.path} — replaced ${input.oldText.split('\n').length} line(s)`
      } catch (e: any) {
        return `Error editing file: ${e.message}`
      }
    }

    case 'search_code': {
      const pattern = String(input.pattern || '')
      if (!pattern) return 'Error: empty search pattern'
      const searchPath = input.path ? resolve(root, input.path) : root
      if (!searchPath.startsWith(root)) return 'Error: path outside project'
      const maxResults = Math.min(Number(input.maxResults) || 30, 100)
      const fileFilter = input.filePattern ? `--include='${input.filePattern}'` : ''

      try {
        const { stdout } = await execAsync(
          `grep -rn ${fileFilter} --max-count=${maxResults} -E ${JSON.stringify(pattern)} . 2>/dev/null | head -${maxResults}`,
          { cwd: searchPath, timeout: 15_000, maxBuffer: 1024 * 1024 }
        )
        return stdout.trim() || 'No matches found'
      } catch (e: any) {
        if (e.code === 1) return 'No matches found'
        return `Search error: ${e.message}`
      }
    }

    case 'list_directory': {
      const dirPath = resolve(root, String(input.path || ''))
      if (!dirPath.startsWith(root)) return 'Error: path outside project'
      try {
        const entries = await readdir(dirPath, { withFileTypes: true })
        const results: string[] = []
        for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
          if (entry.name.startsWith('.') && entry.name !== '.env.example') continue
          const fullPath = join(dirPath, entry.name)
          if (entry.isDirectory()) {
            results.push(`  ${entry.name}/`)
            if (input.recursive) {
              try {
                const sub = await readdir(fullPath, { withFileTypes: true })
                for (const s of sub.slice(0, 20)) {
                  results.push(`    ${entry.name}/${s.name}${s.isDirectory() ? '/' : ''}`)
                }
                if (sub.length > 20) results.push(`    ... and ${sub.length - 20} more`)
              } catch {}
            }
          } else {
            const st = await stat(fullPath).catch(() => null)
            const size = st ? `${(st.size / 1024).toFixed(1)}K` : ''
            results.push(`  ${entry.name}  ${size}`)
          }
        }
        return results.join('\n') || '(empty directory)'
      } catch (e: any) {
        return `Error listing directory: ${e.message}`
      }
    }

    case 'deploy_check': {
      if (isServerless()) {
        const env = process.env.VERCEL_ENV || 'unknown'
        const region = process.env.VERCEL_REGION || 'unknown'
        const gitSha = process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 8) || 'unknown'
        const gitMsg = process.env.VERCEL_GIT_COMMIT_MESSAGE || 'unknown'
        const branch = process.env.VERCEL_GIT_COMMIT_REF || 'unknown'
        return [
          `Vercel Deployment Status`,
          `  Environment: ${env}`,
          `  Region:      ${region}`,
          `  Branch:      ${branch}`,
          `  Commit:      ${gitSha} — ${gitMsg}`,
          `  Runtime:     Node ${process.version}`,
          ``,
          `This is a live production deployment. Vercel deploys on push to master.`,
        ].join('\n')
      }
      try {
        const { stdout } = await execAsync('git log --oneline -5 && echo "---" && git status --short', {
          cwd: root,
          timeout: 10_000,
        })
        return `Latest commits & status:\n${stdout.trim()}\n\nNote: Vercel deploys on push to master. Use git push to trigger deployment.`
      } catch (e: any) {
        return `Deploy check error: ${e.message}`
      }
    }

    case 'supabase_query': {
      const sql = String(input.sql || '').trim()
      if (!sql.toLowerCase().startsWith('select')) return 'Error: only SELECT queries are allowed'
      const url = process.env.SUPABASE_URL || process.env.NUXT_SUPABASE_URL || ''
      const key = process.env.SUPABASE_SERVICE_KEY || process.env.NUXT_SUPABASE_SERVICE_KEY || ''
      if (!url || !key) return 'Error: Supabase not configured'
      try {
        const sb = createClient(url, key)
        const { data, error } = await sb.rpc('exec_sql', { query: sql })
        if (error) return `SQL error: ${error.message}`
        return JSON.stringify(data, null, 2)
      } catch (e: any) {
        return `Query error: ${e.message}`
      }
    }

    default:
      return `Unknown tool: ${name}`
  }
}

// --- Main handler ---

export default defineEventHandler(async (event) => {
  const body = await readBody<{
    command: string
    history?: Array<{ role: string; content: string }>
    sessionId?: string
  }>(event)

  if (!body?.command?.trim()) {
    throw createError({ statusCode: 400, message: 'command is required' })
  }

  const apiKey = process.env.ANTHROPIC_API_KEY || process.env.NUXT_ANTHROPIC_API_KEY
  if (!apiKey) {
    throw createError({ statusCode: 500, message: 'ANTHROPIC_API_KEY not configured — add it to your Vercel environment variables' })
  }

  const client = new Anthropic({ apiKey })
  const serverless = isServerless()

  // Build conversation from history
  const messages: Anthropic.MessageParam[] = []
  if (body.history) {
    for (const msg of body.history.slice(-20)) {
      if (msg.role === 'user' || msg.role === 'assistant') {
        messages.push({ role: msg.role, content: msg.content })
      }
    }
  }
  messages.push({ role: 'user', content: body.command })

  try {
    let currentMessages = [...messages]
    const outputs: Array<{ type: string; content: string; tool?: string; input?: any }> = []
    let iterations = 0
    const MAX_ITERATIONS = 15

    while (iterations < MAX_ITERATIONS) {
      iterations++

      const response = await client.messages.create({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 8192,
        system: buildSystemPrompt(serverless),
        tools: TOOLS,
        messages: currentMessages,
      })

      if (response.stop_reason === 'tool_use') {
        currentMessages.push({ role: 'assistant', content: response.content })

        const toolResults: Anthropic.ToolResultBlockParam[] = []
        for (const block of response.content) {
          if (block.type === 'tool_use') {
            const result = await execTool(block.name, block.input)
            outputs.push({
              type: 'tool',
              content: result,
              tool: block.name,
              input: block.input,
            })
            toolResults.push({
              type: 'tool_result',
              tool_use_id: block.id,
              content: result,
            })
          }
        }

        currentMessages.push({ role: 'user', content: toolResults })
      } else {
        // Final text response
        const textBlocks = response.content.filter(b => b.type === 'text')
        const text = textBlocks.map(b => (b as Anthropic.TextBlock).text).join('\n')
        if (text.trim()) {
          outputs.push({ type: 'text', content: text })
        }
        break
      }
    }

    if (iterations >= MAX_ITERATIONS) {
      outputs.push({ type: 'text', content: '\n[Reached maximum tool call limit]' })
    }

    return {
      outputs,
      iterations,
      sessionId: body.sessionId || crypto.randomUUID(),
    }
  } catch (e: any) {
    console.error('Terminal execute error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Terminal execution failed',
    })
  }
})
