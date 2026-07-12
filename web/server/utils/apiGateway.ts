/**
 * Fleet API Gateway — centralized entry point for all cross-app API calls.
 * Replaces direct FLEET_URL_<APP> calls with a single router that adds:
 * - Rate limiting per app/caller
 * - Circuit breaker (open after N consecutive failures)
 * - Request tracing (unique trace ID through the call chain)
 * - Retry with exponential backoff
 * - Response caching for read operations
 */

import { ALL_APP_IDS, type AppId, getAppConfig } from './appClients'
import { randomUUID } from 'crypto'

// --- Interfaces ---

interface GatewayConfig {
  rateLimits: {
    perApp: number
    perCaller: number
    global: number
  }
  circuitBreaker: {
    failureThreshold: number
    resetTimeMs: number
  }
  retry: {
    maxRetries: number
    backoffBaseMs: number
    backoffMaxMs: number
  }
  cache: {
    ttlMs: number
    maxEntries: number
  }
}

export interface CircuitState {
  app: string
  state: 'closed' | 'open' | 'half-open'
  failures: number
  lastFailure?: string
  lastSuccess?: string
  openedAt?: string
}

export interface GatewayRequest {
  traceId: string
  app: string
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  body?: any
  headers?: Record<string, string>
  caller: string
  timestamp: string
  cached: boolean
}

export interface GatewayResponse {
  traceId: string
  app: string
  status: number
  body: any
  latencyMs: number
  fromCache: boolean
  retryCount: number
  circuitState: string
}

export interface GatewayStats {
  totalRequests: number
  successCount: number
  failureCount: number
  cacheHits: number
  cacheMisses: number
  avgLatencyMs: number
  circuitStates: CircuitState[]
  rateLimitHits: number
  requestsByApp: Record<string, number>
  requestsByCaller: Record<string, number>
  recentRequests: GatewayRequest[]
}

// --- Config ---

const config: GatewayConfig = {
  rateLimits: {
    perApp: parseInt(process.env.ORCH_GATEWAY_RATE_PER_APP || '100'),
    perCaller: parseInt(process.env.ORCH_GATEWAY_RATE_PER_CALLER || '50'),
    global: parseInt(process.env.ORCH_GATEWAY_RATE_GLOBAL || '500'),
  },
  circuitBreaker: {
    failureThreshold: parseInt(process.env.ORCH_GATEWAY_CB_THRESHOLD || '5'),
    resetTimeMs: parseInt(process.env.ORCH_GATEWAY_CB_RESET_MS || '30000'),
  },
  retry: {
    maxRetries: parseInt(process.env.ORCH_GATEWAY_RETRY_MAX || '3'),
    backoffBaseMs: parseInt(process.env.ORCH_GATEWAY_BACKOFF_BASE_MS || '1000'),
    backoffMaxMs: parseInt(process.env.ORCH_GATEWAY_BACKOFF_MAX_MS || '10000'),
  },
  cache: {
    ttlMs: parseInt(process.env.ORCH_GATEWAY_CACHE_TTL_MS || '60000'),
    maxEntries: parseInt(process.env.ORCH_GATEWAY_CACHE_MAX || '1000'),
  },
}

// --- Rate Limiter (sliding window) ---

interface RateWindow {
  timestamps: number[]
}

const rateLimitWindows: Map<string, RateWindow> = new Map()
let globalRequestTimestamps: number[] = []
let rateLimitHitCount = 0

function pruneTimestamps(timestamps: number[], windowMs: number = 60000): number[] {
  const cutoff = Date.now() - windowMs
  return timestamps.filter(t => t > cutoff)
}

function checkRateLimit(app: string, caller: string): boolean {
  const now = Date.now()

  // Global limit
  globalRequestTimestamps = pruneTimestamps(globalRequestTimestamps)
  if (globalRequestTimestamps.length >= config.rateLimits.global) {
    rateLimitHitCount++
    return false
  }

  // Per-app limit
  const appKey = `app:${app}`
  const appWindow = rateLimitWindows.get(appKey) || { timestamps: [] }
  appWindow.timestamps = pruneTimestamps(appWindow.timestamps)
  if (appWindow.timestamps.length >= config.rateLimits.perApp) {
    rateLimitHitCount++
    return false
  }

  // Per-caller limit
  const callerKey = `caller:${caller}`
  const callerWindow = rateLimitWindows.get(callerKey) || { timestamps: [] }
  callerWindow.timestamps = pruneTimestamps(callerWindow.timestamps)
  if (callerWindow.timestamps.length >= config.rateLimits.perCaller) {
    rateLimitHitCount++
    return false
  }

  // Record
  globalRequestTimestamps.push(now)
  appWindow.timestamps.push(now)
  callerWindow.timestamps.push(now)
  rateLimitWindows.set(appKey, appWindow)
  rateLimitWindows.set(callerKey, callerWindow)

  return true
}

// --- Circuit Breaker ---

const circuitStates: Map<string, CircuitState> = new Map()

function initCircuitStates(): void {
  for (const appId of ALL_APP_IDS) {
    if (!circuitStates.has(appId)) {
      circuitStates.set(appId, {
        app: appId,
        state: 'closed',
        failures: 0,
      })
    }
  }
}

export function getCircuitState(app: string): CircuitState {
  initCircuitStates()
  return circuitStates.get(app) || { app, state: 'closed', failures: 0 }
}

export function getAllCircuitStates(): CircuitState[] {
  initCircuitStates()
  return Array.from(circuitStates.values())
}

function recordSuccess(app: string): void {
  const state = getCircuitState(app)
  state.state = 'closed'
  state.failures = 0
  state.lastSuccess = new Date().toISOString()
  circuitStates.set(app, state)
}

function recordFailure(app: string): void {
  const state = getCircuitState(app)
  state.failures++
  state.lastFailure = new Date().toISOString()
  if (state.failures >= config.circuitBreaker.failureThreshold) {
    state.state = 'open'
    state.openedAt = new Date().toISOString()
  }
  circuitStates.set(app, state)
}

function isCircuitOpen(app: string): boolean {
  const state = getCircuitState(app)
  if (state.state === 'closed') return false
  if (state.state === 'open' && state.openedAt) {
    const elapsed = Date.now() - new Date(state.openedAt).getTime()
    if (elapsed >= config.circuitBreaker.resetTimeMs) {
      state.state = 'half-open'
      circuitStates.set(app, state)
      return false // allow one probe request
    }
    return true
  }
  return false // half-open allows requests
}

export function resetCircuit(app: string): void {
  circuitStates.set(app, {
    app,
    state: 'closed',
    failures: 0,
    lastSuccess: new Date().toISOString(),
  })
}

// --- Cache (LRU with TTL) ---

interface CacheEntry {
  response: GatewayResponse
  expiresAt: number
  insertedAt: number
}

const cache: Map<string, CacheEntry> = new Map()
let cacheHits = 0
let cacheMisses = 0

function cacheKey(app: string, method: string, path: string): string {
  return `${app}:${method}:${path}`
}

function getCached(key: string): GatewayResponse | null {
  const entry = cache.get(key)
  if (!entry) {
    cacheMisses++
    return null
  }
  if (Date.now() > entry.expiresAt) {
    cache.delete(key)
    cacheMisses++
    return null
  }
  cacheHits++
  return { ...entry.response, fromCache: true }
}

function setCache(key: string, response: GatewayResponse): void {
  // Evict oldest if at capacity
  if (cache.size >= config.cache.maxEntries) {
    let oldestKey = ''
    let oldestTime = Infinity
    for (const [k, v] of cache) {
      if (v.insertedAt < oldestTime) {
        oldestTime = v.insertedAt
        oldestKey = k
      }
    }
    if (oldestKey) cache.delete(oldestKey)
  }
  cache.set(key, {
    response,
    expiresAt: Date.now() + config.cache.ttlMs,
    insertedAt: Date.now(),
  })
}

export function invalidateApp(app: string): void {
  for (const [key] of cache) {
    if (key.startsWith(`${app}:`)) cache.delete(key)
  }
}

// --- Stats ---

let totalRequests = 0
let successCount = 0
let failureCount = 0
let totalLatencyMs = 0
const requestsByApp: Record<string, number> = {}
const requestsByCaller: Record<string, number> = {}
const recentRequests: GatewayRequest[] = []
const traceLog: Map<string, { request: GatewayRequest; response?: GatewayResponse }> = new Map()

export function getStats(): GatewayStats {
  initCircuitStates()
  return {
    totalRequests,
    successCount,
    failureCount,
    cacheHits,
    cacheMisses,
    avgLatencyMs: totalRequests > 0 ? Math.round(totalLatencyMs / totalRequests) : 0,
    circuitStates: getAllCircuitStates(),
    rateLimitHits: rateLimitHitCount,
    requestsByApp: { ...requestsByApp },
    requestsByCaller: { ...requestsByCaller },
    recentRequests: recentRequests.slice(-100),
  }
}

export function resetStats(): void {
  totalRequests = 0
  successCount = 0
  failureCount = 0
  totalLatencyMs = 0
  cacheHits = 0
  cacheMisses = 0
  rateLimitHitCount = 0
  Object.keys(requestsByApp).forEach(k => delete requestsByApp[k])
  Object.keys(requestsByCaller).forEach(k => delete requestsByCaller[k])
  recentRequests.length = 0
  traceLog.clear()
}

export function getTraceLog(traceId: string): { request: GatewayRequest; response?: GatewayResponse } | null {
  return traceLog.get(traceId) || null
}

// --- Core Router ---

export async function route(input: {
  app: string
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  body?: any
  headers?: Record<string, string>
  caller?: string
}): Promise<GatewayResponse> {
  const traceId = randomUUID()
  const caller = input.caller || 'unknown'
  const startTime = Date.now()

  const request: GatewayRequest = {
    traceId,
    app: input.app,
    method: input.method,
    path: input.path,
    body: input.body,
    headers: input.headers,
    caller,
    timestamp: new Date().toISOString(),
    cached: false,
  }

  // Track
  totalRequests++
  requestsByApp[input.app] = (requestsByApp[input.app] || 0) + 1
  requestsByCaller[caller] = (requestsByCaller[caller] || 0) + 1
  recentRequests.push(request)
  if (recentRequests.length > 200) recentRequests.splice(0, recentRequests.length - 200)

  // 1. Rate limit check
  if (!checkRateLimit(input.app, caller)) {
    const resp: GatewayResponse = {
      traceId,
      app: input.app,
      status: 429,
      body: { error: 'Rate limit exceeded' },
      latencyMs: Date.now() - startTime,
      fromCache: false,
      retryCount: 0,
      circuitState: getCircuitState(input.app).state,
    }
    failureCount++
    traceLog.set(traceId, { request, response: resp })
    return resp
  }

  // 2. Circuit breaker check
  if (isCircuitOpen(input.app)) {
    const resp: GatewayResponse = {
      traceId,
      app: input.app,
      status: 503,
      body: { error: `Circuit breaker open for ${input.app}` },
      latencyMs: Date.now() - startTime,
      fromCache: false,
      retryCount: 0,
      circuitState: 'open',
    }
    failureCount++
    traceLog.set(traceId, { request, response: resp })
    return resp
  }

  // 3. Cache check (GET only)
  if (input.method === 'GET') {
    const key = cacheKey(input.app, input.method, input.path)
    const cached = getCached(key)
    if (cached) {
      cached.traceId = traceId
      request.cached = true
      const latency = Date.now() - startTime
      cached.latencyMs = latency
      totalLatencyMs += latency
      traceLog.set(traceId, { request, response: cached })
      return cached
    }
  }

  // 4. Resolve target URL
  const appConfig = getAppConfig(input.app as AppId)
  if (!appConfig.baseUrl) {
    const resp: GatewayResponse = {
      traceId,
      app: input.app,
      status: 502,
      body: { error: `No base URL configured for ${input.app}` },
      latencyMs: Date.now() - startTime,
      fromCache: false,
      retryCount: 0,
      circuitState: getCircuitState(input.app).state,
    }
    failureCount++
    traceLog.set(traceId, { request, response: resp })
    return resp
  }

  const targetUrl = `${appConfig.baseUrl.replace(/\/$/, '')}${input.path}`
  const fleetSecret = process.env.FLEET_SECRET || ''

  // 5. Execute with retry + backoff
  let lastError: any = null
  let retryCount = 0

  for (let attempt = 0; attempt <= config.retry.maxRetries; attempt++) {
    if (attempt > 0) {
      retryCount = attempt
      const delay = Math.min(
        config.retry.backoffBaseMs * Math.pow(2, attempt - 1),
        config.retry.backoffMaxMs,
      )
      await new Promise(r => setTimeout(r, delay))
    }

    try {
      const fetchOptions: RequestInit = {
        method: input.method,
        headers: {
          'Content-Type': 'application/json',
          'x-trace-id': traceId,
          'x-fleet-secret': fleetSecret,
          ...(input.headers || {}),
        },
      }
      if (input.body && input.method !== 'GET') {
        fetchOptions.body = JSON.stringify(input.body)
      }

      const res = await fetch(targetUrl, fetchOptions)
      let responseBody: any
      try {
        responseBody = await res.json()
      } catch {
        responseBody = await res.text().catch(() => null)
      }

      if (res.ok) {
        recordSuccess(input.app)
        successCount++
        const latency = Date.now() - startTime
        totalLatencyMs += latency

        const resp: GatewayResponse = {
          traceId,
          app: input.app,
          status: res.status,
          body: responseBody,
          latencyMs: latency,
          fromCache: false,
          retryCount,
          circuitState: getCircuitState(input.app).state,
        }

        // Cache GET responses
        if (input.method === 'GET') {
          setCache(cacheKey(input.app, input.method, input.path), resp)
        }

        traceLog.set(traceId, { request, response: resp })
        return resp
      }

      // Non-retryable status codes
      if (res.status >= 400 && res.status < 500) {
        recordFailure(input.app)
        failureCount++
        const latency = Date.now() - startTime
        totalLatencyMs += latency

        const resp: GatewayResponse = {
          traceId,
          app: input.app,
          status: res.status,
          body: responseBody,
          latencyMs: latency,
          fromCache: false,
          retryCount,
          circuitState: getCircuitState(input.app).state,
        }
        traceLog.set(traceId, { request, response: resp })
        return resp
      }

      // 5xx — retryable
      lastError = new Error(`${res.status}: ${JSON.stringify(responseBody)}`)
    } catch (e: any) {
      lastError = e
    }
  }

  // All retries exhausted
  recordFailure(input.app)
  failureCount++
  const latency = Date.now() - startTime
  totalLatencyMs += latency

  const resp: GatewayResponse = {
    traceId,
    app: input.app,
    status: 502,
    body: { error: lastError?.message || 'Request failed after retries' },
    latencyMs: latency,
    fromCache: false,
    retryCount,
    circuitState: getCircuitState(input.app).state,
  }
  traceLog.set(traceId, { request, response: resp })
  return resp
}
