"use strict";
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
exports.pruneOlderThan = exports.getRetentionStats = exports.getMetricNames = exports.query = exports.ingestBatch = exports.ingestEvent = void 0;
/**
 * Fleet Telemetry Lake — time-series storage for all fleet events.
 * Stores events in a Supabase `fleet_telemetry` table with time-bucketed aggregation queries.
 * Enables "show me error rates over the last quarter" in NL Admin.
 *
 * Table schema (create via migration):
 *   id          uuid primary key default gen_random_uuid()
 *   timestamp   timestamptz not null
 *   app         text not null
 *   domain      text not null default ''
 *   metric      text not null
 *   value       double precision not null default 0
 *   tags        jsonb default '{}'
 *   created_at  timestamptz default now()
 *
 * Index: (timestamp, app, metric)
 */
var fleetSupabase_1 = require("./fleetSupabase");
var BUCKET_SQL = {
    '1h': 'hour',
    '1d': 'day',
    '1w': 'week',
    '1M': 'month'
};
/**
 * Ingest a single fleet event as a telemetry point.
 * Called from the fleet ingest pipeline on every event.
 */
function ingestEvent(event) {
    var _a;
    return __awaiter(this, void 0, void 0, function () {
        var sb, point;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    point = {
                        timestamp: event.at || event.timestamp || new Date().toISOString(),
                        app: event.product || event.app || 'unknown',
                        domain: event.domain || '',
                        metric: event.category || event.metric || 'event_count',
                        value: (_a = event.value) !== null && _a !== void 0 ? _a : 1,
                        tags: event.tags || {}
                    };
                    return [4 /*yield*/, sb.from('fleet_telemetry').insert(point)];
                case 1:
                    _b.sent();
                    return [2 /*return*/];
            }
        });
    });
}
exports.ingestEvent = ingestEvent;
/**
 * Ingest a batch of telemetry points.
 */
function ingestBatch(points) {
    return __awaiter(this, void 0, void 0, function () {
        var sb, rows, _a, error, count;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    if (!points.length)
                        return [2 /*return*/, { inserted: 0 }];
                    sb = (0, fleetSupabase_1.serviceClient)();
                    rows = points.map(function (p) {
                        var _a;
                        return ({
                            timestamp: p.timestamp,
                            app: p.app,
                            domain: p.domain || '',
                            metric: p.metric,
                            value: (_a = p.value) !== null && _a !== void 0 ? _a : 0,
                            tags: p.tags || {}
                        });
                    });
                    return [4 /*yield*/, sb.from('fleet_telemetry').insert(rows)];
                case 1:
                    _a = _b.sent(), error = _a.error, count = _a.count;
                    if (error)
                        throw new Error("Telemetry ingest failed: ".concat(error.message));
                    return [2 /*return*/, { inserted: rows.length }];
            }
        });
    });
}
exports.ingestBatch = ingestBatch;
/**
 * Query telemetry with time-bucketed aggregation.
 */
function query(q) {
    var _a, _b, _c;
    return __awaiter(this, void 0, void 0, function () {
        var sb, bucketUnit, rpcQuery, _d, data, error, rows, bucketMap, _i, rows_1, row, ts, bucketKey, metricKey, bucket, buckets, allValues, _e, _f, _g, ts, metrics, values, _h, _j, _k, key, vals, sum, summary;
        return __generator(this, function (_l) {
            switch (_l.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    bucketUnit = BUCKET_SQL[q.bucket] || 'day';
                    rpcQuery = sb
                        .from('fleet_telemetry')
                        .select('timestamp, app, metric, value')
                        .gte('timestamp', q.from)
                        .lte('timestamp', q.to)
                        .order('timestamp', { ascending: true });
                    if ((_a = q.apps) === null || _a === void 0 ? void 0 : _a.length)
                        rpcQuery = rpcQuery["in"]('app', q.apps);
                    if ((_b = q.metrics) === null || _b === void 0 ? void 0 : _b.length)
                        rpcQuery = rpcQuery["in"]('metric', q.metrics);
                    if ((_c = q.domains) === null || _c === void 0 ? void 0 : _c.length)
                        rpcQuery = rpcQuery["in"]('domain', q.domains);
                    return [4 /*yield*/, rpcQuery.limit(50000)];
                case 1:
                    _d = _l.sent(), data = _d.data, error = _d.error;
                    if (error)
                        throw new Error("Telemetry query failed: ".concat(error.message));
                    rows = data || [];
                    bucketMap = new Map();
                    for (_i = 0, rows_1 = rows; _i < rows_1.length; _i++) {
                        row = rows_1[_i];
                        ts = new Date(row.timestamp);
                        bucketKey = truncateDate(ts, bucketUnit);
                        metricKey = "".concat(row.app, ":").concat(row.metric);
                        if (!bucketMap.has(bucketKey))
                            bucketMap.set(bucketKey, {});
                        bucket = bucketMap.get(bucketKey);
                        if (!bucket[metricKey])
                            bucket[metricKey] = [];
                        bucket[metricKey].push(row.value);
                    }
                    buckets = [];
                    allValues = [];
                    for (_e = 0, _f = Array.from(bucketMap.entries()).sort(); _e < _f.length; _e++) {
                        _g = _f[_e], ts = _g[0], metrics = _g[1];
                        values = {};
                        for (_h = 0, _j = Object.entries(metrics); _h < _j.length; _h++) {
                            _k = _j[_h], key = _k[0], vals = _k[1];
                            sum = vals.reduce(function (a, b) { return a + b; }, 0);
                            values[key] = sum;
                            allValues.push(sum);
                        }
                        buckets.push({ timestamp: ts, values: values });
                    }
                    summary = allValues.length > 0
                        ? {
                            min: Math.min.apply(Math, allValues),
                            max: Math.max.apply(Math, allValues),
                            avg: Math.round((allValues.reduce(function (a, b) { return a + b; }, 0) / allValues.length) * 100) / 100,
                            total: allValues.reduce(function (a, b) { return a + b; }, 0)
                        }
                        : { min: 0, max: 0, avg: 0, total: 0 };
                    return [2 /*return*/, { buckets: buckets, summary: summary }];
            }
        });
    });
}
exports.query = query;
/**
 * List all distinct metric names in the telemetry table.
 */
function getMetricNames() {
    return __awaiter(this, void 0, void 0, function () {
        var sb, data, unique;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    return [4 /*yield*/, sb
                            .from('fleet_telemetry')
                            .select('metric')
                            .limit(1000)];
                case 1:
                    data = (_a.sent()).data;
                    if (!data)
                        return [2 /*return*/, []];
                    unique = new Set(data.map(function (r) { return r.metric; }));
                    return [2 /*return*/, Array.from(unique).sort()];
            }
        });
    });
}
exports.getMetricNames = getMetricNames;
/**
 * Get retention statistics about the telemetry lake.
 */
function getRetentionStats() {
    var _a, _b, _c, _d, _e;
    return __awaiter(this, void 0, void 0, function () {
        var sb, _f, countRes, oldestRes, newestRes, totalPoints, sizeBytes, sizeEstimate;
        return __generator(this, function (_g) {
            switch (_g.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    return [4 /*yield*/, Promise.all([
                            sb.from('fleet_telemetry').select('id', { count: 'exact', head: true }),
                            sb.from('fleet_telemetry').select('timestamp').order('timestamp', { ascending: true }).limit(1).maybeSingle(),
                            sb.from('fleet_telemetry').select('timestamp').order('timestamp', { ascending: false }).limit(1).maybeSingle(),
                        ])];
                case 1:
                    _f = _g.sent(), countRes = _f[0], oldestRes = _f[1], newestRes = _f[2];
                    totalPoints = (_a = countRes.count) !== null && _a !== void 0 ? _a : 0;
                    sizeBytes = totalPoints * 200;
                    sizeEstimate = sizeBytes < 1024 * 1024
                        ? "".concat(Math.round(sizeBytes / 1024), " KB")
                        : "".concat(Math.round(sizeBytes / (1024 * 1024)), " MB");
                    return [2 /*return*/, {
                            totalPoints: totalPoints,
                            oldestPoint: (_c = (_b = oldestRes.data) === null || _b === void 0 ? void 0 : _b.timestamp) !== null && _c !== void 0 ? _c : null,
                            newestPoint: (_e = (_d = newestRes.data) === null || _d === void 0 ? void 0 : _d.timestamp) !== null && _e !== void 0 ? _e : null,
                            sizeEstimate: sizeEstimate
                        }];
            }
        });
    });
}
exports.getRetentionStats = getRetentionStats;
/**
 * Delete telemetry data older than N days.
 */
function pruneOlderThan(days) {
    return __awaiter(this, void 0, void 0, function () {
        var sb, cutoff, count;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    cutoff = new Date(Date.now() - days * 86400000).toISOString();
                    return [4 /*yield*/, sb
                            .from('fleet_telemetry')["delete"]({ count: 'exact' })
                            .lt('timestamp', cutoff)];
                case 1:
                    count = (_a.sent()).count;
                    return [2 /*return*/, count !== null && count !== void 0 ? count : 0];
            }
        });
    });
}
exports.pruneOlderThan = pruneOlderThan;
// ---- helpers ----
function truncateDate(d, unit) {
    var iso = d.toISOString();
    switch (unit) {
        case 'hour':
            return iso.slice(0, 13) + ':00:00.000Z';
        case 'day':
            return iso.slice(0, 10) + 'T00:00:00.000Z';
        case 'week': {
            var day = d.getUTCDay();
            var diff = d.getUTCDate() - day + (day === 0 ? -6 : 1); // Monday start
            var monday = new Date(d);
            monday.setUTCDate(diff);
            return monday.toISOString().slice(0, 10) + 'T00:00:00.000Z';
        }
        case 'month':
            return iso.slice(0, 7) + '-01T00:00:00.000Z';
        default:
            return iso.slice(0, 10) + 'T00:00:00.000Z';
    }
}
