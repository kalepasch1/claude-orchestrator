#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { APP_SOURCES } from './config.js';
import { APPARENTLY_TOOLS } from './groups/apparently.js';
import { PARETO_TOOLS } from './groups/pareto.js';
import { SMARTER_TOOLS } from './groups/smarter.js';
import { TOMORROW_TOOLS } from './groups/tomorrow.js';
import { ORCHESTRATOR_TOOLS } from './groups/orchestrator.js';
import type { ToolDefinition, ToolGroup, BillingEvent } from './types.js';

// ---------- Tool registry ----------

const TOOL_GROUPS: ToolGroup[] = [
  { appId: 'apparently', label: 'Apparently', icon: '◈', tools: APPARENTLY_TOOLS },
  { appId: 'pareto', label: 'Pareto 2080', icon: '⊕', tools: PARETO_TOOLS },
  { appId: 'smarter', label: 'Smarter', icon: '⚖', tools: SMARTER_TOOLS },
  { appId: 'tomorrow', label: 'Tomorrow', icon: '◎', tools: TOMORROW_TOOLS },
  { appId: 'orchestrator', label: 'Orchestrator', icon: '⌘', tools: ORCHESTRATOR_TOOLS },
];

const toolIndex = new Map<string, { tool: ToolDefinition; appId: string }>();
for (const group of TOOL_GROUPS) {
  for (const tool of group.tools) {
    toolIndex.set(tool.name, { tool, appId: group.appId });
  }
}

const enabledGroups = new Set<string>(TOOL_GROUPS.map((g) => g.appId));

// ---------- Configure meta-tool ----------

const CONFIGURE_TOOL = {
  name: 'heretomorrow.configure',
  description: 'Manage HereTomorrow MCP tool groups. Actions: list, enable, disable, enable_all, disable_all.',
  inputSchema: {
    type: 'object' as const,
    properties: {
      action: { type: 'string', enum: ['list', 'enable', 'disable', 'enable_all', 'disable_all'], description: 'Configuration action' },
      groupId: { type: 'string', description: 'Group ID (for enable/disable)' },
    },
    required: ['action'],
  },
};

// ---------- Server ----------

const server = new Server(
  { name: 'heretomorrow-mcp', version: '1.0.0' },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  const tools = [CONFIGURE_TOOL];
  for (const group of TOOL_GROUPS) {
    if (!enabledGroups.has(group.appId)) continue;
    for (const tool of group.tools) {
      tools.push({
        name: tool.name,
        description: `[${group.icon} ${group.label}] ${tool.description}`,
        inputSchema: tool.inputSchema,
      });
    }
  }
  return { tools };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === 'heretomorrow.configure') return handleConfigure(args as Record<string, unknown>);

  const entry = toolIndex.get(name);
  if (!entry) return { content: [{ type: 'text', text: `Unknown tool: ${name}` }], isError: true };
  if (!enabledGroups.has(entry.appId)) {
    return { content: [{ type: 'text', text: `Tool group '${entry.appId}' is disabled. Enable via heretomorrow.configure.` }], isError: true };
  }

  return proxyToApp(entry.tool, entry.appId, args as Record<string, unknown>);
});

// ---------- Configure ----------

function handleConfigure(args: Record<string, unknown>) {
  const action = args.action as string;
  const text = (t: string) => ({ content: [{ type: 'text' as const, text: t }] });

  switch (action) {
    case 'list':
      return text(JSON.stringify(TOOL_GROUPS.map((g) => ({
        id: g.appId, label: g.label, icon: g.icon, toolCount: g.tools.length, enabled: enabledGroups.has(g.appId),
      })), null, 2));
    case 'enable': {
      const id = args.groupId as string;
      if (!TOOL_GROUPS.find((g) => g.appId === id)) return { ...text(`Unknown group: ${id}`), isError: true };
      enabledGroups.add(id);
      return text(`Enabled: ${id}`);
    }
    case 'disable': { enabledGroups.delete(args.groupId as string); return text(`Disabled: ${args.groupId}`); }
    case 'enable_all': { TOOL_GROUPS.forEach((g) => enabledGroups.add(g.appId)); return text('All groups enabled'); }
    case 'disable_all': { enabledGroups.clear(); return text('All groups disabled'); }
    default: return { ...text(`Unknown action: ${action}`), isError: true };
  }
}

// ---------- Proxy ----------

async function proxyToApp(tool: ToolDefinition, appId: string, args: Record<string, unknown>) {
  const appConfig = APP_SOURCES[appId];
  if (!appConfig) return { content: [{ type: 'text' as const, text: `No app config: ${appId}` }], isError: true };

  const baseUrl = process.env.NODE_ENV === 'development' ? appConfig.devUrl : appConfig.baseUrl;
  const url = `${baseUrl}${tool.proxyTo.path}`;
  const startMs = Date.now();

  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-MCP-Tool': tool.name,
      'X-MCP-Source': 'heretomorrow-mcp',
    };
    if (process.env.MCP_API_KEY) headers.Authorization = `Bearer ${process.env.MCP_API_KEY}`;

    let response: Response;

    if (tool.proxyTo.method === 'GET') {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(args)) params.set(k, String(v));
      const sep = url.includes('?') ? '&' : '?';
      const fullUrl = Object.keys(args).length > 0 ? `${url}${sep}${params}` : url;
      response = await fetch(fullUrl, { method: 'GET', headers });
    } else {
      response = await fetch(url, { method: tool.proxyTo.method, headers, body: JSON.stringify(args) });
    }

    const data = await response.json();
    meterBilling(tool, appId, Date.now() - startMs, true);
    return { content: [{ type: 'text' as const, text: JSON.stringify(data, null, 2) }] };
  } catch (error) {
    meterBilling(tool, appId, Date.now() - startMs, false);
    const msg = error instanceof Error ? error.message : String(error);
    return { content: [{ type: 'text' as const, text: `Proxy error: ${msg}` }], isError: true };
  }
}

// ---------- Billing ----------

function meterBilling(tool: ToolDefinition, appId: string, durationMs: number, success: boolean) {
  const event: BillingEvent = {
    toolName: tool.name,
    appId,
    pricingCents: tool.pricingCents,
    timestamp: new Date().toISOString(),
    durationMs,
    success,
  };

  const billingUrl = process.env.MCP_BILLING_ENDPOINT;
  if (billingUrl) {
    fetch(billingUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event) }).catch(() => {});
  }
  if (process.env.NODE_ENV === 'development') {
    console.error(`[billing] ${tool.name} ${tool.pricingCents}c ${durationMs}ms ${success ? 'ok' : 'err'}`);
  }
}

// ---------- Start ----------

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('HereTomorrow MCP server running on stdio');
}

main().catch((error) => { console.error('Fatal:', error); process.exit(1); });
