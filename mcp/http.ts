#!/usr/bin/env node
/**
 * HereTomorrow MCP — Streamable HTTP entrypoint (ChatGPT and other remote clients).
 *
 * The "ChatGPT MCP" in this repo was never an MCP server. tools/chatgpt-bridge/
 * watches a Dropbox folder for patch files, applies them with a shell script and
 * pokes a GitHub Action. That is a courier: one-way, file-shaped, no tools, no
 * schemas, nothing ChatGPT can call. This is the actual server, and it serves
 * the SAME registry as the stdio one — same tools, same proxying, same auth.
 *
 *   npm run http                    # listens on HT_HTTP_PORT (default 8848)
 *
 * Endpoints:
 *   POST /mcp     JSON-RPC over Streamable HTTP  (the MCP endpoint)
 *   GET  /mcp     SSE stream for server->client messages
 *   GET  /health  plain readiness, for a tunnel or load balancer
 *
 * Sessions are stateless by design: sessionIdGenerator is undefined, so every
 * request is self-contained. The registry is immutable and each call is a
 * pass-through to an app's HTTP API, so there is no per-session state worth
 * keeping — and stateless survives the process restarts a tunnel will cause.
 *
 * ── Exposure ─────────────────────────────────────────────────────────────
 * This binds to HT_HTTP_HOST, default 127.0.0.1. Do not bind it to 0.0.0.0 and
 * point a public tunnel at it without setting HT_HTTP_AUTH: the tools proxy to
 * apps using the operator's bearer token, so an unauthenticated caller here
 * inherits that token's reach across all six apps. With HT_HTTP_AUTH set, every
 * request must carry `Authorization: Bearer <that value>`.
 */
import { randomUUID } from 'node:crypto';
import { createServer as createHttpServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createServer, readyLine } from './core.js';

const PORT = Number(process.env.HT_HTTP_PORT) || 8848;
const HOST = process.env.HT_HTTP_HOST || '127.0.0.1';
const AUTH = process.env.HT_HTTP_AUTH || '';

function send(res: ServerResponse, status: number, body: unknown, type = 'application/json') {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': type, 'Content-Length': Buffer.byteLength(text) });
  res.end(text);
}

/** Constant-time-ish compare so a wrong token cannot be discovered byte by byte. */
function tokenOk(provided: string): boolean {
  if (!AUTH) return true;
  if (provided.length !== AUTH.length) return false;
  let diff = 0;
  for (let i = 0; i < AUTH.length; i++) diff |= provided.charCodeAt(i) ^ AUTH.charCodeAt(i);
  return diff === 0;
}

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += (chunk as Buffer).length;
    // A JSON-RPC tool call is small. Anything this size is a mistake or an attack.
    if (bytes > 4 * 1024 * 1024) throw new Error('request body too large');
    chunks.push(chunk as Buffer);
  }
  if (!chunks.length) return undefined;
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

const httpServer = createHttpServer(async (req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || HOST}`);

  if (url.pathname === '/health') {
    return send(res, 200, { status: 'ok', detail: readyLine().replace(/\n\[mcp\]\s+/g, ' | ') });
  }

  if (url.pathname !== '/mcp') return send(res, 404, { error: 'not found' });

  const header = req.headers.authorization || '';
  const bearer = header.startsWith('Bearer ') ? header.slice(7) : '';
  if (!tokenOk(bearer)) {
    return send(res, 401, {
      error: 'unauthorized',
      detail: 'HT_HTTP_AUTH is set on this server; send Authorization: Bearer <token>.',
    });
  }

  // One Server + transport per request. The SDK binds a transport to a Server
  // for its lifetime, so reusing either across concurrent requests would
  // interleave two clients' responses onto one stream.
  const server = createServer();
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });

  res.on('close', () => {
    transport.close().catch(() => {});
    server.close().catch(() => {});
  });

  try {
    await server.connect(transport);
    const body = req.method === 'POST' ? await readBody(req) : undefined;
    await transport.handleRequest(req, res, body);
  } catch (e: any) {
    console.error('[mcp-http] request failed:', e?.message || e);
    if (!res.headersSent) {
      send(res, 500, {
        jsonrpc: '2.0',
        error: { code: -32603, message: e?.message || 'internal error' },
        id: null,
      });
    }
  }
});

httpServer.listen(PORT, HOST, () => {
  console.error(`[mcp] heretomorrow ready (http) — ${readyLine()}`);
  console.error(`[mcp]   endpoint:  http://${HOST}:${PORT}/mcp`);
  console.error(`[mcp]   health:    http://${HOST}:${PORT}/health`);
  console.error(
    AUTH
      ? '[mcp]   auth:      HT_HTTP_AUTH set — Bearer token required'
      : '[mcp]   auth:      OPEN. Set HT_HTTP_AUTH before exposing this beyond localhost —\n' +
        '[mcp]              the tools carry the operator token into all six apps.',
  );
  void randomUUID; // reserved for stateful sessions if they are ever needed
});
