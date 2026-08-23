/**
 * HereTomorrow unified MCP server — stdio transport.
 *
 * package.json has pointed at this file since the mcp/ package was created and
 * it has never existed: `git log --all -- mcp/server.ts` is empty. The tool
 * DEFINITIONS in groups/ were real; nothing could serve them. This is the
 * server they were written for.
 *
 * What it does: every ToolDefinition in groups/ declares a `proxyTo` — an HTTP
 * method and path on its owning app. This server exposes them as MCP tools and
 * forwards a call to that app's HTTP API. It holds no business logic of its
 * own, deliberately: the apps already enforce their own auth, tenancy and
 * rate limits, and a second implementation here would drift from them.
 *
 *   npm run dev      # stdio, for Claude Code / Claude Desktop
 *   npm run build && npm start
 *
 * Environment:
 *   HT_ENV=dev|prod        which URL from config.ts to call (default: prod)
 *   HT_TOKEN               bearer token used for every app
 *   HT_TOKEN_<APPID>       per-app override, e.g. HT_TOKEN_SMARTER
 *   HT_APPS=a,b            restrict to these app ids (default: all)
 *   HT_TIMEOUT_MS          per-call timeout (default: 60000)
 */
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from '@modelcontextprotocol/sdk/types.js';
import { APP_SOURCES, MARKETPLACE_LISTINGS } from './config.js';
import type { AppSource, ToolDefinition } from './types.js';

import { APPARENTLY_TOOLS } from './groups/apparently.js';
import { PARETO_TOOLS } from './groups/pareto.js';
import { SMARTER_TOOLS } from './groups/smarter.js';
import { VIGIL_TOOLS } from './groups/vigil.js';
import { TOMORROW_TOOLS } from './groups/tomorrow.js';
import { ORCHESTRATOR_TOOLS } from './groups/orchestrator.js';

/** Every group, keyed by the app id it belongs to in APP_SOURCES. */
const GROUPS: Record<string, ToolDefinition[]> = {
  apparently: APPARENTLY_TOOLS,
  pareto: PARETO_TOOLS,
  smarter: SMARTER_TOOLS,
  vigil: VIGIL_TOOLS,
  tomorrow: TOMORROW_TOOLS,
  orchestrator: ORCHESTRATOR_TOOLS,
};

const TIMEOUT_MS = Number(process.env.HT_TIMEOUT_MS) || 60_000;

/**
 * Above this many tools, an app is served through search instead of being
 * listed outright.
 *
 * Generating groups from real routes produced 2,562 tools across six apps —
 * Tomorrow alone has 2,224. Returning that from tools/list is not a large tool
 * list, it is a broken one: it exceeds what a model can hold and costs the
 * caller a fortune in context on every handshake. So each app is served one of
 * two ways, decided by its own size:
 *
 *   small app  -> its tools appear directly in tools/list
 *   large app  -> two meta tools, portfolio_search_tools and portfolio_call
 *
 * The long tail stays fully reachable; it just gets looked up instead of
 * recited. Raise HT_DIRECT_MAX if a client can genuinely take more.
 */
const DIRECT_MAX = Number(process.env.HT_DIRECT_MAX) || 40;
const USE_DEV = (process.env.HT_ENV || 'prod').toLowerCase() === 'dev';

/**
 * Tool names in groups/ read `smarter.warroom.copilot`. MCP tool names are
 * restricted to [A-Za-z0-9_-], so dots would be rejected by strict clients.
 * Underscore on the wire, dotted name kept for logs and error messages.
 */
function wireName(dotted: string): string {
  return dotted.replace(/\./g, '_');
}

interface Entry {
  app: AppSource;
  def: ToolDefinition;
}

/** Every tool, wire name -> tool + owning app. Includes searchable-only apps. */
function buildRegistry(): Map<string, Entry> {
  const only = process.env.HT_APPS?.split(',').map((s) => s.trim()).filter(Boolean);
  const reg = new Map<string, Entry>();

  for (const [appId, defs] of Object.entries(GROUPS)) {
    if (only?.length && !only.includes(appId)) continue;
    const app = APP_SOURCES[appId];
    if (!app) {
      console.error(`[mcp] group '${appId}' has no entry in APP_SOURCES — skipped`);
      continue;
    }
    for (const def of defs) {
      const name = wireName(def.name);
      const prior = reg.get(name);
      if (prior) {
        // Two apps claiming one tool name would make routing silent and wrong.
        console.error(
          `[mcp] duplicate tool '${name}': ${prior.app.id} and ${appId}. Keeping ${prior.app.id}.`,
        );
        continue;
      }
      reg.set(name, { app, def });
    }
  }
  return reg;
}

const REGISTRY = buildRegistry();

/** App ids small enough to list directly, and the rest. */
const { DIRECT_APPS, SEARCH_APPS } = (() => {
  const counts = new Map<string, number>();
  for (const { app } of REGISTRY.values()) counts.set(app.id, (counts.get(app.id) ?? 0) + 1);
  const direct = new Set<string>();
  const search = new Set<string>();
  for (const [id, n] of counts) (n <= DIRECT_MAX ? direct : search).add(id);
  return { DIRECT_APPS: direct, SEARCH_APPS: search };
})();

function baseUrlFor(app: AppSource): string {
  return USE_DEV ? app.devUrl : app.baseUrl;
}

function tokenFor(app: AppSource): string | undefined {
  return process.env[`HT_TOKEN_${app.id.toUpperCase()}`] || process.env.HT_TOKEN;
}

/** Path params are written `/api/thing/:id`; fill them from args and drop them from the body. */
function applyPathParams(path: string, args: Record<string, unknown>) {
  const used = new Set<string>();
  const filled = path.replace(/:([A-Za-z0-9_]+)/g, (whole, key: string) => {
    const v = args[key];
    if (v === undefined || v === null) return whole;
    used.add(key);
    return encodeURIComponent(String(v));
  });
  const rest: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(args)) if (!used.has(k)) rest[k] = v;
  return { path: filled, rest };
}

async function callTool(entry: Entry, args: Record<string, unknown>) {
  const { app, def } = entry;
  const { method } = def.proxyTo;
  const { path, rest } = applyPathParams(def.proxyTo.path, args);

  const url = new URL(path, baseUrlFor(app));
  const init: RequestInit = { method, headers: {} };
  const headers = init.headers as Record<string, string>;

  const token = tokenFor(app);
  if (token) headers.Authorization = `Bearer ${token}`;
  headers.Accept = 'application/json';
  // Named so an app's logs can tell MCP traffic from a browser session.
  headers['User-Agent'] = 'heretomorrow-mcp/1.0';

  if (method === 'GET' || method === 'DELETE') {
    for (const [k, v] of Object.entries(rest)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
    }
  } else {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(rest);
  }

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { ...init, signal: ac.signal });
    const text = await res.text();

    if (!res.ok) {
      // Return the app's own error rather than a generic one — a 401 here
      // almost always means HT_TOKEN is missing or expired, and saying so
      // saves the caller a debugging round trip.
      const hint =
        res.status === 401 || res.status === 403
          ? `\n\nThis app requires a bearer token. Set HT_TOKEN_${app.id.toUpperCase()} or HT_TOKEN.`
          : '';
      return {
        isError: true,
        content: [
          {
            type: 'text' as const,
            text: `${def.name} -> ${method} ${url.pathname} failed: ${res.status} ${res.statusText}\n${text.slice(0, 4000)}${hint}`,
          },
        ],
      };
    }

    return { content: [{ type: 'text' as const, text: text || '(empty response)' }] };
  } catch (e: any) {
    const reason =
      e?.name === 'AbortError'
        ? `timed out after ${TIMEOUT_MS}ms`
        : `${e?.message || e}`;
    return {
      isError: true,
      content: [
        {
          type: 'text' as const,
          text: `${def.name} -> ${method} ${url.href} failed: ${reason}`,
        },
      ],
    };
  }
}

/** A meta tool, so a caller can discover the portfolio without reading config.ts. */
const LIST_APPS: Tool = {
  name: 'portfolio_list_apps',
  description:
    'List the HereTomorrow apps this MCP server can reach, with their category, pricing tier, tool count and the base URL currently in use.',
  inputSchema: { type: 'object', properties: {}, required: [] },
};

function listAppsResult() {
  const counts = new Map<string, number>();
  for (const { app } of REGISTRY.values()) counts.set(app.id, (counts.get(app.id) ?? 0) + 1);

  const rows = MARKETPLACE_LISTINGS.filter((l) => counts.has(l.appId)).map((l) => {
    const app = APP_SOURCES[l.appId];
    return {
      id: l.appId,
      name: l.displayName,
      tagline: l.tagline,
      category: l.category,
      pricingTier: l.pricingTier,
      tools: counts.get(l.appId) ?? 0,
      target: baseUrlFor(app),
      authConfigured: Boolean(tokenFor(app)),
    };
  });

  return {
    content: [
      {
        type: 'text' as const,
        text: JSON.stringify({ env: USE_DEV ? 'dev' : 'prod', apps: rows }, null, 2),
      },
    ],
  };
}

/**
 * Rank tools against a query. Deliberately simple and dependency-free: exact
 * substring on the name beats a name-token hit, which beats a description hit.
 * The caller is a language model — it does not need BM25, it needs the right
 * twenty rows.
 */
function searchTools(query: string, appFilter?: string, limit = 25) {
  const q = query.toLowerCase().trim();
  const terms = q.split(/[^a-z0-9]+/).filter(Boolean);
  const scored: Array<{ score: number; name: string; entry: Entry }> = [];

  for (const [name, entry] of REGISTRY) {
    if (appFilter && entry.app.id !== appFilter) continue;
    const hay = name.toLowerCase();
    const desc = entry.def.description.toLowerCase();
    let score = 0;
    if (hay.includes(q)) score += 100;
    for (const t of terms) {
      if (hay.includes(t)) score += 10;
      if (desc.includes(t)) score += 3;
    }
    if (score > 0) scored.push({ score, name, entry });
  }

  scored.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
  return scored.slice(0, limit).map(({ name, entry }) => ({
    tool: name,
    app: entry.app.id,
    description: entry.def.description,
    method: entry.def.proxyTo.method,
    path: entry.def.proxyTo.path,
    inputSchema: entry.def.inputSchema,
  }));
}

const SEARCH_TOOLS: Tool = {
  name: 'portfolio_search_tools',
  description:
    'Find tools across the HereTomorrow portfolio by keyword. Apps with large API surfaces ' +
    '(Tomorrow, Vigil, Madeus/orchestrator) are not listed individually — search here, then ' +
    'invoke what you find with portfolio_call. Returns each match with its full input schema.',
  inputSchema: {
    type: 'object',
    properties: {
      query: { type: 'string', description: 'Keywords, e.g. "hedge position" or "approval queue".' },
      app: { type: 'string', description: 'Restrict to one app id.', enum: Object.keys(APP_SOURCES) },
      limit: { type: 'number', description: 'Max results (default 25).' },
    },
    required: ['query'],
  },
};

const CALL_TOOL: Tool = {
  name: 'portfolio_call',
  description:
    'Invoke any tool in the portfolio by name, including ones not listed individually. ' +
    'Get the name and its schema from portfolio_search_tools first.',
  inputSchema: {
    type: 'object',
    properties: {
      tool: { type: 'string', description: 'Tool name exactly as portfolio_search_tools returned it.' },
      arguments: { type: 'object', description: 'Arguments matching that tool\'s inputSchema.' },
    },
    required: ['tool'],
  },
};

const server = new Server(
  { name: 'heretomorrow', version: '1.0.0' },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  const tools: Tool[] = [LIST_APPS, SEARCH_TOOLS, CALL_TOOL];
  for (const [name, { app, def }] of REGISTRY) {
    if (!DIRECT_APPS.has(app.id)) continue; // large apps are reached via search
    tools.push({
      name,
      // The app label goes in the description so a model choosing between
      // six apps' similarly-named tools has something to choose on.
      description: `[${app.label}] ${def.description}`,
      inputSchema: def.inputSchema as Tool['inputSchema'],
    });
  }
  return { tools };
});

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  if (name === LIST_APPS.name) return listAppsResult();

  if (name === SEARCH_TOOLS.name) {
    const a = (args ?? {}) as { query?: string; app?: string; limit?: number };
    const hits = searchTools(String(a.query ?? ''), a.app, Number(a.limit) || 25);
    return {
      content: [{
        type: 'text' as const,
        text: hits.length
          ? JSON.stringify({ matches: hits.length, tools: hits }, null, 2)
          : `No tools matched "${a.query}". Try portfolio_list_apps to see what is reachable.`,
      }],
    };
  }

  if (name === CALL_TOOL.name) {
    const a = (args ?? {}) as { tool?: string; arguments?: Record<string, unknown> };
    const target = REGISTRY.get(String(a.tool ?? ''));
    if (!target) {
      return {
        isError: true,
        content: [{
          type: 'text' as const,
          text: `Unknown tool '${a.tool}'. Use portfolio_search_tools to find the exact name.`,
        }],
      };
    }
    return callTool(target, a.arguments ?? {});
  }

  const entry = REGISTRY.get(name);
  if (!entry) {
    return {
      isError: true,
      content: [{ type: 'text' as const, text: `Unknown tool: ${name}` }],
    };
  }
  return callTool(entry, (args ?? {}) as Record<string, unknown>);
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // stdout is the MCP channel; anything human-readable must go to stderr.
  console.error(
    `[mcp] heretomorrow ready — ${REGISTRY.size} tools across ` +
      `${DIRECT_APPS.size + SEARCH_APPS.size} apps (${USE_DEV ? 'dev' : 'prod'})\n` +
      `[mcp]   listed directly: ${[...DIRECT_APPS].join(', ') || '(none)'}\n` +
      `[mcp]   via search:      ${[...SEARCH_APPS].join(', ') || '(none)'}`,
  );
}

main().catch((e) => {
  console.error('[mcp] fatal:', e);
  process.exit(1);
});
