"use strict";
/**
 * Fleet API Gateway — centralized entry point for all cross-app API calls.
 * Replaces direct FLEET_URL_<APP> calls with a single router that adds:
 * - Rate limiting per app/caller
 * - Circuit breaker (open after N consecutive failures)
 * - Request tracing (unique trace ID through the call chain)
 * - Retry with exponential backoff
 * - Response caching for read operations
 */
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
exports.__esModule = true;
exports.route = exports.getTraceLog = exports.resetStats = exports.getStats = exports.invalidateApp = exports.resetCircuit = exports.getAllCircuitStates = exports.getCircuitState = void 0;
var appClients_1 = require("./appClients");
var crypto_1 = require("crypto");
// --- Config ---
var config = {
    rateLimits: {
        perApp: parseInt(process.env.ORCH_GATEWAY_RATE_PER_APP || '100'),
        perCaller: parseInt(process.env.ORCH_GATEWAY_RATE_PER_CALLER || '50'),
        global: parseInt(process.env.ORCH_GATEWAY_RATE_GLOBAL || '500')
    },
    circuitBreaker: {
        failureThreshold: parseInt(process.env.ORCH_GATEWAY_CB_THRESHOLD || '5'),
        resetTimeMs: parseInt(process.env.ORCH_GATEWAY_CB_RESET_MS || '30000')
    },
    retry: {
        maxRetries: parseInt(process.env.ORCH_GATEWAY_RETRY_MAX || '3'),
        backoffBaseMs: parseInt(process.env.ORCH_GATEWAY_BACKOFF_BASE_MS || '1000'),
        backoffMaxMs: parseInt(process.env.ORCH_GATEWAY_BACKOFF_MAX_MS || '10000')
    },
    cache: {
        ttlMs: parseInt(process.env.ORCH_GATEWAY_CACHE_TTL_MS || '60000'),
        maxEntries: parseInt(process.env.ORCH_GATEWAY_CACHE_MAX || '1000')
    }
};
var rateLimitWindows = new Map();
var globalRequestTimestamps = [];
var rateLimitHitCount = 0;
function pruneTimestamps(timestamps, windowMs) {
    if (windowMs === void 0) { windowMs = 60000; }
    var cutoff = Date.now() - windowMs;
    return timestamps.filter(function (t) { return t > cutoff; });
}
function checkRateLimit(app, caller) {
    var now = Date.now();
    // Global limit
    globalRequestTimestamps = pruneTimestamps(globalRequestTimestamps);
    if (globalRequestTimestamps.length >= config.rateLimits.global) {
        rateLimitHitCount++;
        return false;
    }
    // Per-app limit
    var appKey = "app:".concat(app);
    var appWindow = rateLimitWindows.get(appKey) || { timestamps: [] };
    appWindow.timestamps = pruneTimestamps(appWindow.timestamps);
    if (appWindow.timestamps.length >= config.rateLimits.perApp) {
        rateLimitHitCount++;
        return false;
    }
    // Per-caller limit
    var callerKey = "caller:".concat(caller);
    var callerWindow = rateLimitWindows.get(callerKey) || { timestamps: [] };
    callerWindow.timestamps = pruneTimestamps(callerWindow.timestamps);
    if (callerWindow.timestamps.length >= config.rateLimits.perCaller) {
        rateLimitHitCount++;
        return false;
    }
    // Record
    globalRequestTimestamps.push(now);
    appWindow.timestamps.push(now);
    callerWindow.timestamps.push(now);
    rateLimitWindows.set(appKey, appWindow);
    rateLimitWindows.set(callerKey, callerWindow);
    return true;
}
// --- Circuit Breaker ---
var circuitStates = new Map();
function initCircuitStates() {
    for (var _i = 0, ALL_APP_IDS_1 = appClients_1.ALL_APP_IDS; _i < ALL_APP_IDS_1.length; _i++) {
        var appId = ALL_APP_IDS_1[_i];
        if (!circuitStates.has(appId)) {
            circuitStates.set(appId, {
                app: appId,
                state: 'closed',
                failures: 0
            });
        }
    }
}
function getCircuitState(app) {
    initCircuitStates();
    return circuitStates.get(app) || { app: app, state: 'closed', failures: 0 };
}
exports.getCircuitState = getCircuitState;
function getAllCircuitStates() {
    initCircuitStates();
    return Array.from(circuitStates.values());
}
exports.getAllCircuitStates = getAllCircuitStates;
function recordSuccess(app) {
    var state = getCircuitState(app);
    state.state = 'closed';
    state.failures = 0;
    state.lastSuccess = new Date().toISOString();
    circuitStates.set(app, state);
}
function recordFailure(app) {
    var state = getCircuitState(app);
    state.failures++;
    state.lastFailure = new Date().toISOString();
    if (state.failures >= config.circuitBreaker.failureThreshold) {
        state.state = 'open';
        state.openedAt = new Date().toISOString();
    }
    circuitStates.set(app, state);
}
function isCircuitOpen(app) {
    var state = getCircuitState(app);
    if (state.state === 'closed')
        return false;
    if (state.state === 'open' && state.openedAt) {
        var elapsed = Date.now() - new Date(state.openedAt).getTime();
        if (elapsed >= config.circuitBreaker.resetTimeMs) {
            state.state = 'half-open';
            circuitStates.set(app, state);
            return false; // allow one probe request
        }
        return true;
    }
    return false; // half-open allows requests
}
function resetCircuit(app) {
    circuitStates.set(app, {
        app: app,
        state: 'closed',
        failures: 0,
        lastSuccess: new Date().toISOString()
    });
}
exports.resetCircuit = resetCircuit;
var cache = new Map();
var cacheHits = 0;
var cacheMisses = 0;
function cacheKey(app, method, path) {
    return "".concat(app, ":").concat(method, ":").concat(path);
}
function getCached(key) {
    var entry = cache.get(key);
    if (!entry) {
        cacheMisses++;
        return null;
    }
    if (Date.now() > entry.expiresAt) {
        cache["delete"](key);
        cacheMisses++;
        return null;
    }
    cacheHits++;
    return __assign(__assign({}, entry.response), { fromCache: true });
}
function setCache(key, response) {
    // Evict oldest if at capacity
    if (cache.size >= config.cache.maxEntries) {
        var oldestKey = '';
        var oldestTime = Infinity;
        for (var _i = 0, cache_1 = cache; _i < cache_1.length; _i++) {
            var _a = cache_1[_i], k = _a[0], v = _a[1];
            if (v.insertedAt < oldestTime) {
                oldestTime = v.insertedAt;
                oldestKey = k;
            }
        }
        if (oldestKey)
            cache["delete"](oldestKey);
    }
    cache.set(key, {
        response: response,
        expiresAt: Date.now() + config.cache.ttlMs,
        insertedAt: Date.now()
    });
}
function invalidateApp(app) {
    for (var _i = 0, cache_2 = cache; _i < cache_2.length; _i++) {
        var key = cache_2[_i][0];
        if (key.startsWith("".concat(app, ":")))
            cache["delete"](key);
    }
}
exports.invalidateApp = invalidateApp;
// --- Stats ---
var totalRequests = 0;
var successCount = 0;
var failureCount = 0;
var totalLatencyMs = 0;
var requestsByApp = {};
var requestsByCaller = {};
var recentRequests = [];
var traceLog = new Map();
function getStats() {
    initCircuitStates();
    return {
        totalRequests: totalRequests,
        successCount: successCount,
        failureCount: failureCount,
        cacheHits: cacheHits,
        cacheMisses: cacheMisses,
        avgLatencyMs: totalRequests > 0 ? Math.round(totalLatencyMs / totalRequests) : 0,
        circuitStates: getAllCircuitStates(),
        rateLimitHits: rateLimitHitCount,
        requestsByApp: __assign({}, requestsByApp),
        requestsByCaller: __assign({}, requestsByCaller),
        recentRequests: recentRequests.slice(-100)
    };
}
exports.getStats = getStats;
function resetStats() {
    totalRequests = 0;
    successCount = 0;
    failureCount = 0;
    totalLatencyMs = 0;
    cacheHits = 0;
    cacheMisses = 0;
    rateLimitHitCount = 0;
    Object.keys(requestsByApp).forEach(function (k) { return delete requestsByApp[k]; });
    Object.keys(requestsByCaller).forEach(function (k) { return delete requestsByCaller[k]; });
    recentRequests.length = 0;
    traceLog.clear();
}
exports.resetStats = resetStats;
function getTraceLog(traceId) {
    return traceLog.get(traceId) || null;
}
exports.getTraceLog = getTraceLog;
// --- Core Router ---
function route(input) {
    return __awaiter(this, void 0, void 0, function () {
        var traceId, caller, startTime, request, resp_1, resp_2, key, cached, latency_1, appConfig, resp_3, targetUrl, fleetSecret, lastError, retryCount, _loop_1, attempt, state_1, latency, resp;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    traceId = (0, crypto_1.randomUUID)();
                    caller = input.caller || 'unknown';
                    startTime = Date.now();
                    request = {
                        traceId: traceId,
                        app: input.app,
                        method: input.method,
                        path: input.path,
                        body: input.body,
                        headers: input.headers,
                        caller: caller,
                        timestamp: new Date().toISOString(),
                        cached: false
                    };
                    // Track
                    totalRequests++;
                    requestsByApp[input.app] = (requestsByApp[input.app] || 0) + 1;
                    requestsByCaller[caller] = (requestsByCaller[caller] || 0) + 1;
                    recentRequests.push(request);
                    if (recentRequests.length > 200)
                        recentRequests.splice(0, recentRequests.length - 200);
                    // 1. Rate limit check
                    if (!checkRateLimit(input.app, caller)) {
                        resp_1 = {
                            traceId: traceId,
                            app: input.app,
                            status: 429,
                            body: { error: 'Rate limit exceeded' },
                            latencyMs: Date.now() - startTime,
                            fromCache: false,
                            retryCount: 0,
                            circuitState: getCircuitState(input.app).state
                        };
                        failureCount++;
                        traceLog.set(traceId, { request: request, response: resp_1 });
                        return [2 /*return*/, resp_1];
                    }
                    // 2. Circuit breaker check
                    if (isCircuitOpen(input.app)) {
                        resp_2 = {
                            traceId: traceId,
                            app: input.app,
                            status: 503,
                            body: { error: "Circuit breaker open for ".concat(input.app) },
                            latencyMs: Date.now() - startTime,
                            fromCache: false,
                            retryCount: 0,
                            circuitState: 'open'
                        };
                        failureCount++;
                        traceLog.set(traceId, { request: request, response: resp_2 });
                        return [2 /*return*/, resp_2];
                    }
                    // 3. Cache check (GET only)
                    if (input.method === 'GET') {
                        key = cacheKey(input.app, input.method, input.path);
                        cached = getCached(key);
                        if (cached) {
                            cached.traceId = traceId;
                            request.cached = true;
                            latency_1 = Date.now() - startTime;
                            cached.latencyMs = latency_1;
                            totalLatencyMs += latency_1;
                            traceLog.set(traceId, { request: request, response: cached });
                            return [2 /*return*/, cached];
                        }
                    }
                    appConfig = (0, appClients_1.getAppConfig)(input.app);
                    if (!appConfig.baseUrl) {
                        resp_3 = {
                            traceId: traceId,
                            app: input.app,
                            status: 502,
                            body: { error: "No base URL configured for ".concat(input.app) },
                            latencyMs: Date.now() - startTime,
                            fromCache: false,
                            retryCount: 0,
                            circuitState: getCircuitState(input.app).state
                        };
                        failureCount++;
                        traceLog.set(traceId, { request: request, response: resp_3 });
                        return [2 /*return*/, resp_3];
                    }
                    targetUrl = "".concat(appConfig.baseUrl.replace(/\/$/, '')).concat(input.path);
                    fleetSecret = process.env.FLEET_SECRET || '';
                    lastError = null;
                    retryCount = 0;
                    _loop_1 = function (attempt) {
                        var delay_1, fetchOptions, res, responseBody, _b, latency_2, resp_4, latency_3, resp_5, e_1;
                        return __generator(this, function (_c) {
                            switch (_c.label) {
                                case 0:
                                    if (!(attempt > 0)) return [3 /*break*/, 2];
                                    retryCount = attempt;
                                    delay_1 = Math.min(config.retry.backoffBaseMs * Math.pow(2, attempt - 1), config.retry.backoffMaxMs);
                                    return [4 /*yield*/, new Promise(function (r) { return setTimeout(r, delay_1); })];
                                case 1:
                                    _c.sent();
                                    _c.label = 2;
                                case 2:
                                    _c.trys.push([2, 9, , 10]);
                                    fetchOptions = {
                                        method: input.method,
                                        headers: __assign({ 'Content-Type': 'application/json', 'x-trace-id': traceId, 'x-fleet-secret': fleetSecret }, (input.headers || {}))
                                    };
                                    if (input.body && input.method !== 'GET') {
                                        fetchOptions.body = JSON.stringify(input.body);
                                    }
                                    return [4 /*yield*/, fetch(targetUrl, fetchOptions)];
                                case 3:
                                    res = _c.sent();
                                    responseBody = void 0;
                                    _c.label = 4;
                                case 4:
                                    _c.trys.push([4, 6, , 8]);
                                    return [4 /*yield*/, res.json()];
                                case 5:
                                    responseBody = _c.sent();
                                    return [3 /*break*/, 8];
                                case 6:
                                    _b = _c.sent();
                                    return [4 /*yield*/, res.text()["catch"](function () { return null; })];
                                case 7:
                                    responseBody = _c.sent();
                                    return [3 /*break*/, 8];
                                case 8:
                                    if (res.ok) {
                                        recordSuccess(input.app);
                                        successCount++;
                                        latency_2 = Date.now() - startTime;
                                        totalLatencyMs += latency_2;
                                        resp_4 = {
                                            traceId: traceId,
                                            app: input.app,
                                            status: res.status,
                                            body: responseBody,
                                            latencyMs: latency_2,
                                            fromCache: false,
                                            retryCount: retryCount,
                                            circuitState: getCircuitState(input.app).state
                                        };
                                        // Cache GET responses
                                        if (input.method === 'GET') {
                                            setCache(cacheKey(input.app, input.method, input.path), resp_4);
                                        }
                                        traceLog.set(traceId, { request: request, response: resp_4 });
                                        return [2 /*return*/, { value: resp_4 }];
                                    }
                                    // Non-retryable status codes
                                    if (res.status >= 400 && res.status < 500) {
                                        recordFailure(input.app);
                                        failureCount++;
                                        latency_3 = Date.now() - startTime;
                                        totalLatencyMs += latency_3;
                                        resp_5 = {
                                            traceId: traceId,
                                            app: input.app,
                                            status: res.status,
                                            body: responseBody,
                                            latencyMs: latency_3,
                                            fromCache: false,
                                            retryCount: retryCount,
                                            circuitState: getCircuitState(input.app).state
                                        };
                                        traceLog.set(traceId, { request: request, response: resp_5 });
                                        return [2 /*return*/, { value: resp_5 }];
                                    }
                                    // 5xx — retryable
                                    lastError = new Error("".concat(res.status, ": ").concat(JSON.stringify(responseBody)));
                                    return [3 /*break*/, 10];
                                case 9:
                                    e_1 = _c.sent();
                                    lastError = e_1;
                                    return [3 /*break*/, 10];
                                case 10: return [2 /*return*/];
                            }
                        });
                    };
                    attempt = 0;
                    _a.label = 1;
                case 1:
                    if (!(attempt <= config.retry.maxRetries)) return [3 /*break*/, 4];
                    return [5 /*yield**/, _loop_1(attempt)];
                case 2:
                    state_1 = _a.sent();
                    if (typeof state_1 === "object")
                        return [2 /*return*/, state_1.value];
                    _a.label = 3;
                case 3:
                    attempt++;
                    return [3 /*break*/, 1];
                case 4:
                    // All retries exhausted
                    recordFailure(input.app);
                    failureCount++;
                    latency = Date.now() - startTime;
                    totalLatencyMs += latency;
                    resp = {
                        traceId: traceId,
                        app: input.app,
                        status: 502,
                        body: { error: (lastError === null || lastError === void 0 ? void 0 : lastError.message) || 'Request failed after retries' },
                        latencyMs: latency,
                        fromCache: false,
                        retryCount: retryCount,
                        circuitState: getCircuitState(input.app).state
                    };
                    traceLog.set(traceId, { request: request, response: resp });
                    return [2 /*return*/, resp];
            }
        });
    });
}
exports.route = route;
