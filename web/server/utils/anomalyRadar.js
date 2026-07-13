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
exports.getRecentAlerts = exports.scanAllApps = exports.scanApp = exports.classifySeverity = exports.computeZScore = void 0;
/**
 * Anomaly Radar -- polls fleet_events and proxy data for statistical outliers.
 * Uses Z-score detection: if a metric deviates >2.5 sigma from its 7-day rolling mean, flag it.
 */
var appClients_1 = require("./appClients");
// In-memory cache for alerts between scans
var cachedAlerts = [];
var lastScanTime = null;
function computeZScore(values, current) {
    if (values.length === 0) {
        return { mean: 0, stddev: 0, zscore: 0 };
    }
    var mean = values.reduce(function (sum, v) { return sum + v; }, 0) / values.length;
    var variance = values.reduce(function (sum, v) { return sum + Math.pow((v - mean), 2); }, 0) / values.length;
    var stddev = Math.sqrt(variance);
    // If stddev is 0 (all values identical), zscore is 0 unless current differs
    if (stddev === 0) {
        return { mean: mean, stddev: 0, zscore: current === mean ? 0 : current > mean ? 4 : -4 };
    }
    var zscore = (current - mean) / stddev;
    return { mean: mean, stddev: stddev, zscore: zscore };
}
exports.computeZScore = computeZScore;
function classifySeverity(zscore) {
    var abs = Math.abs(zscore);
    if (abs >= 3.5)
        return 'critical';
    if (abs >= 2.5)
        return 'warning';
    return 'info';
}
exports.classifySeverity = classifySeverity;
function makeId(app, metric) {
    return "".concat(app, ":").concat(metric, ":").concat(Date.now());
}
/**
 * Query fleet_events for a given app over the last 7 days, group by hour,
 * and detect anomalies in event volume, error rate, and rejection rate.
 */
function scanApp(appId) {
    var _a;
    return __awaiter(this, void 0, void 0, function () {
        var client, config, appName, alerts, now, sevenDaysAgo, _b, events, error, hourlyBuckets_1, _i, events_1, evt, hourKey, bucket, eventType, payloadStr, sortedKeys, latestKey, historicalKeys, latest, historicalVolumes, volumeResult, severity, direction, historicalErrorRates, currentErrorRate, errorResult, severity, historicalRejectionRates, currentRejectionRate, rejectionResult, severity, e_1;
        return __generator(this, function (_c) {
            switch (_c.label) {
                case 0:
                    client = (0, appClients_1.getAppClient)(appId);
                    if (!client)
                        return [2 /*return*/, []];
                    config = (0, appClients_1.getAppConfig)(appId);
                    appName = config.name;
                    alerts = [];
                    now = new Date();
                    sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
                    _c.label = 1;
                case 1:
                    _c.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, client
                            .from('fleet_events')
                            .select('id, event_type, created_at, payload')
                            .gte('created_at', sevenDaysAgo.toISOString())
                            .order('created_at', { ascending: true })];
                case 2:
                    _b = _c.sent(), events = _b.data, error = _b.error;
                    if (error || !events)
                        return [2 /*return*/, []
                            // Group events by hour
                        ];
                    hourlyBuckets_1 = new Map();
                    for (_i = 0, events_1 = events; _i < events_1.length; _i++) {
                        evt = events_1[_i];
                        hourKey = (_a = evt.created_at) === null || _a === void 0 ? void 0 : _a.slice(0, 13) // YYYY-MM-DDTHH
                        ;
                        if (!hourKey)
                            continue;
                        if (!hourlyBuckets_1.has(hourKey)) {
                            hourlyBuckets_1.set(hourKey, { total: 0, errors: 0, rejections: 0 });
                        }
                        bucket = hourlyBuckets_1.get(hourKey);
                        bucket.total++;
                        eventType = (evt.event_type || '').toLowerCase();
                        payloadStr = JSON.stringify(evt.payload || {}).toLowerCase();
                        if (eventType.includes('error') || eventType.includes('fail') || payloadStr.includes('error')) {
                            bucket.errors++;
                        }
                        if (eventType.includes('reject') || eventType.includes('denied') || payloadStr.includes('rejected')) {
                            bucket.rejections++;
                        }
                    }
                    if (hourlyBuckets_1.size < 2)
                        return [2 /*return*/, []]; // Not enough data
                    sortedKeys = Array.from(hourlyBuckets_1.keys()).sort();
                    latestKey = sortedKeys[sortedKeys.length - 1];
                    historicalKeys = sortedKeys.slice(0, -1);
                    if (historicalKeys.length === 0)
                        return [2 /*return*/, []];
                    latest = hourlyBuckets_1.get(latestKey);
                    historicalVolumes = historicalKeys.map(function (k) { return hourlyBuckets_1.get(k).total; });
                    volumeResult = computeZScore(historicalVolumes, latest.total);
                    if (Math.abs(volumeResult.zscore) >= 2.5) {
                        severity = classifySeverity(volumeResult.zscore);
                        direction = volumeResult.zscore > 0 ? 'spike' : 'drop';
                        alerts.push({
                            id: makeId(appId, 'event_volume'),
                            app: appName,
                            metric: 'Event Volume',
                            current: latest.total,
                            baseline: Math.round(volumeResult.mean * 100) / 100,
                            stddev: Math.round(volumeResult.stddev * 100) / 100,
                            zscore: Math.round(volumeResult.zscore * 100) / 100,
                            severity: severity,
                            detected_at: now.toISOString(),
                            message: "".concat(appName, ": event volume ").concat(direction, " -- ").concat(latest.total, " events/hr vs baseline ").concat(Math.round(volumeResult.mean), "/hr (").concat(Math.abs(Math.round(volumeResult.zscore * 10) / 10), " sigma)")
                        });
                    }
                    historicalErrorRates = historicalKeys.map(function (k) {
                        var b = hourlyBuckets_1.get(k);
                        return b.total > 0 ? b.errors / b.total : 0;
                    });
                    currentErrorRate = latest.total > 0 ? latest.errors / latest.total : 0;
                    errorResult = computeZScore(historicalErrorRates, currentErrorRate);
                    if (Math.abs(errorResult.zscore) >= 2.5) {
                        severity = classifySeverity(errorResult.zscore);
                        alerts.push({
                            id: makeId(appId, 'error_rate'),
                            app: appName,
                            metric: 'Error Rate',
                            current: Math.round(currentErrorRate * 10000) / 100,
                            baseline: Math.round(errorResult.mean * 10000) / 100,
                            stddev: Math.round(errorResult.stddev * 10000) / 100,
                            zscore: Math.round(errorResult.zscore * 100) / 100,
                            severity: severity,
                            detected_at: now.toISOString(),
                            message: "".concat(appName, ": error rate at ").concat(Math.round(currentErrorRate * 100), "% vs baseline ").concat(Math.round(errorResult.mean * 100), "% (").concat(Math.abs(Math.round(errorResult.zscore * 10) / 10), " sigma)")
                        });
                    }
                    historicalRejectionRates = historicalKeys.map(function (k) {
                        var b = hourlyBuckets_1.get(k);
                        return b.total > 0 ? b.rejections / b.total : 0;
                    });
                    currentRejectionRate = latest.total > 0 ? latest.rejections / latest.total : 0;
                    rejectionResult = computeZScore(historicalRejectionRates, currentRejectionRate);
                    if (Math.abs(rejectionResult.zscore) >= 2.5) {
                        severity = classifySeverity(rejectionResult.zscore);
                        alerts.push({
                            id: makeId(appId, 'rejection_rate'),
                            app: appName,
                            metric: 'Rejection Rate',
                            current: Math.round(currentRejectionRate * 10000) / 100,
                            baseline: Math.round(rejectionResult.mean * 10000) / 100,
                            stddev: Math.round(rejectionResult.stddev * 10000) / 100,
                            zscore: Math.round(rejectionResult.zscore * 100) / 100,
                            severity: severity,
                            detected_at: now.toISOString(),
                            message: "".concat(appName, ": rejection rate at ").concat(Math.round(currentRejectionRate * 100), "% vs baseline ").concat(Math.round(rejectionResult.mean * 100), "% (").concat(Math.abs(Math.round(rejectionResult.zscore * 10) / 10), " sigma)")
                        });
                    }
                    return [3 /*break*/, 4];
                case 3:
                    e_1 = _c.sent();
                    // Fail-soft: skip apps that error out
                    console.warn("[AnomalyRadar] scan failed for ".concat(appId, ":"), e_1);
                    return [3 /*break*/, 4];
                case 4: return [2 /*return*/, alerts];
            }
        });
    });
}
exports.scanApp = scanApp;
/**
 * Scan all apps and return merged alerts sorted by severity.
 */
function scanAllApps() {
    return __awaiter(this, void 0, void 0, function () {
        var allAlerts, results, _i, results_1, result, severityOrder;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    allAlerts = [];
                    return [4 /*yield*/, Promise.allSettled(appClients_1.ALL_APP_IDS.map(function (appId) { return scanApp(appId); }))];
                case 1:
                    results = _a.sent();
                    for (_i = 0, results_1 = results; _i < results_1.length; _i++) {
                        result = results_1[_i];
                        if (result.status === 'fulfilled') {
                            allAlerts.push.apply(allAlerts, result.value);
                        }
                    }
                    severityOrder = { critical: 0, warning: 1, info: 2 };
                    allAlerts.sort(function (a, b) { return severityOrder[a.severity] - severityOrder[b.severity]; });
                    // Update cache
                    cachedAlerts = allAlerts;
                    lastScanTime = new Date().toISOString();
                    return [2 /*return*/, allAlerts];
            }
        });
    });
}
exports.scanAllApps = scanAllApps;
/**
 * Return cached alerts from the last scan.
 */
function getRecentAlerts() {
    return { alerts: cachedAlerts, lastScan: lastScanTime };
}
exports.getRecentAlerts = getRecentAlerts;
