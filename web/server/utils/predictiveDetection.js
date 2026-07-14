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
exports.getLastScanTime = exports.getCachedTrends = exports.resolvePrediction = exports.acknowledgePrediction = exports.getActivePredictions = exports.generatePredictions = exports.scanAllTrends = exports.analyzeTrend = exports.detectChangePoint = exports.exponentialSmoothing = exports.linearRegression = void 0;
/**
 * Predictive Incident Detection — analyzes telemetry trends to forecast incidents.
 * Uses linear regression on sliding windows to detect trends heading toward
 * anomaly thresholds. Triggers preemptive alerts and playbook suggestions.
 */
var telemetryLake_1 = require("./telemetryLake");
var anomalyRadar_1 = require("./anomalyRadar");
var autoRemediation_1 = require("./autoRemediation");
var appClients_1 = require("./appClients");
// ---- In-memory storage ----
var activePredictions = new Map();
var lastScanTime = null;
var cachedTrends = [];
function linearRegression(points) {
    var n = points.length;
    if (n < 2)
        return { slope: 0, intercept: 0, r2: 0 };
    var sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0, sumY2 = 0;
    for (var _i = 0, points_1 = points; _i < points_1.length; _i++) {
        var p = points_1[_i];
        sumX += p.x;
        sumY += p.y;
        sumXY += p.x * p.y;
        sumX2 += p.x * p.x;
        sumY2 += p.y * p.y;
    }
    var denom = n * sumX2 - sumX * sumX;
    if (denom === 0)
        return { slope: 0, intercept: sumY / n, r2: 0 };
    var slope = (n * sumXY - sumX * sumY) / denom;
    var intercept = (sumY - slope * sumX) / n;
    // R² calculation
    var yMean = sumY / n;
    var ssTot = 0, ssRes = 0;
    for (var _a = 0, points_2 = points; _a < points_2.length; _a++) {
        var p = points_2[_a];
        ssTot += Math.pow((p.y - yMean), 2);
        var predicted = slope * p.x + intercept;
        ssRes += Math.pow((p.y - predicted), 2);
    }
    var r2 = ssTot === 0 ? 0 : 1 - ssRes / ssTot;
    return { slope: slope, intercept: intercept, r2: r2 };
}
exports.linearRegression = linearRegression;
function exponentialSmoothing(values, alpha) {
    if (alpha === void 0) { alpha = 0.3; }
    if (values.length === 0)
        return [];
    var result = [values[0]];
    for (var i = 1; i < values.length; i++) {
        result.push(alpha * values[i] + (1 - alpha) * result[i - 1]);
    }
    return result;
}
exports.exponentialSmoothing = exponentialSmoothing;
function detectChangePoint(values) {
    if (values.length < 5)
        return null;
    var mean = values.reduce(function (a, b) { return a + b; }, 0) / values.length;
    var cumSum = [];
    var running = 0;
    for (var i = 0; i < values.length; i++) {
        running += values[i] - mean;
        cumSum.push(running);
    }
    // Find max absolute deviation in cumulative sum
    var maxAbs = 0;
    var maxIdx = -1;
    for (var i = 0; i < cumSum.length; i++) {
        var abs = Math.abs(cumSum[i]);
        if (abs > maxAbs) {
            maxAbs = abs;
            maxIdx = i;
        }
    }
    // Threshold: change point must be significant (> 2x mean absolute deviation)
    var meanAbsDev = cumSum.reduce(function (s, v) { return s + Math.abs(v); }, 0) / cumSum.length;
    if (maxAbs > meanAbsDev * 2 && maxIdx > 0 && maxIdx < values.length - 1) {
        return maxIdx;
    }
    return null;
}
exports.detectChangePoint = detectChangePoint;
// ---- Analysis functions ----
function analyzeTrend(app, metric, windowHours) {
    if (windowHours === void 0) { windowHours = 24; }
    return __awaiter(this, void 0, void 0, function () {
        var now, windowStart, baselineStart, recentValues, result, _i, _a, bucket, key, _b, baselineValues, baselineResult, _c, _d, bucket, key, _e, currentValue, rawValues, smoothed, startTime, points, _f, slope, r2, zResult, threshold, hoursToThreshold, projectedCrossing, lowerThreshold, confidence, status;
        return __generator(this, function (_g) {
            switch (_g.label) {
                case 0:
                    now = new Date();
                    windowStart = new Date(now.getTime() - windowHours * 3600000);
                    baselineStart = new Date(now.getTime() - 168 * 3600000) // 7 days
                    ;
                    recentValues = [];
                    _g.label = 1;
                case 1:
                    _g.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, (0, telemetryLake_1.query)({
                            apps: [app],
                            metrics: [metric],
                            from: windowStart.toISOString(),
                            to: now.toISOString(),
                            bucket: '1h'
                        })];
                case 2:
                    result = _g.sent();
                    for (_i = 0, _a = result.buckets; _i < _a.length; _i++) {
                        bucket = _a[_i];
                        key = "".concat(app, ":").concat(metric);
                        if (bucket.values[key] !== undefined) {
                            recentValues.push({ timestamp: bucket.timestamp, value: bucket.values[key] });
                        }
                    }
                    return [3 /*break*/, 4];
                case 3:
                    _b = _g.sent();
                    return [3 /*break*/, 4];
                case 4:
                    baselineValues = [];
                    _g.label = 5;
                case 5:
                    _g.trys.push([5, 7, , 8]);
                    return [4 /*yield*/, (0, telemetryLake_1.query)({
                            apps: [app],
                            metrics: [metric],
                            from: baselineStart.toISOString(),
                            to: now.toISOString(),
                            bucket: '1h'
                        })];
                case 6:
                    baselineResult = _g.sent();
                    for (_c = 0, _d = baselineResult.buckets; _c < _d.length; _c++) {
                        bucket = _d[_c];
                        key = "".concat(app, ":").concat(metric);
                        if (bucket.values[key] !== undefined) {
                            baselineValues.push(bucket.values[key]);
                        }
                    }
                    return [3 /*break*/, 8];
                case 7:
                    _e = _g.sent();
                    return [3 /*break*/, 8];
                case 8:
                    currentValue = recentValues.length > 0
                        ? recentValues[recentValues.length - 1].value
                        : 0;
                    if (recentValues.length < 3) {
                        return [2 /*return*/, {
                                app: app,
                                metric: metric,
                                currentValue: currentValue,
                                slope: 0, r2: 0,
                                projectedThreshold: 0,
                                confidence: 'low',
                                status: 'stable'
                            }];
                    }
                    rawValues = recentValues.map(function (v) { return v.value; });
                    smoothed = exponentialSmoothing(rawValues, 0.3);
                    startTime = new Date(recentValues[0].timestamp).getTime();
                    points = smoothed.map(function (y, i) { return ({
                        x: (new Date(recentValues[i].timestamp).getTime() - startTime) / 3600000,
                        y: y
                    }); });
                    _f = linearRegression(points), slope = _f.slope, r2 = _f.r2;
                    zResult = (0, anomalyRadar_1.computeZScore)(baselineValues, currentValue);
                    threshold = zResult.mean + 2.5 * zResult.stddev;
                    if (slope > 0 && threshold > currentValue) {
                        hoursToThreshold = (threshold - currentValue) / slope;
                        if (hoursToThreshold > 0 && hoursToThreshold < 168) { // within 7 days
                            projectedCrossing = new Date(now.getTime() + hoursToThreshold * 3600000).toISOString();
                        }
                    }
                    else if (slope < 0 && threshold < currentValue) {
                        lowerThreshold = zResult.mean - 2.5 * zResult.stddev;
                        if (lowerThreshold > 0) {
                            hoursToThreshold = (currentValue - lowerThreshold) / Math.abs(slope);
                            if (hoursToThreshold > 0 && hoursToThreshold < 168) {
                                projectedCrossing = new Date(now.getTime() + hoursToThreshold * 3600000).toISOString();
                            }
                        }
                    }
                    if (r2 >= 0.8 && recentValues.length >= 12)
                        confidence = 'high';
                    else if (r2 >= 0.5 && recentValues.length >= 6)
                        confidence = 'medium';
                    else
                        confidence = 'low';
                    if (hoursToThreshold !== undefined && hoursToThreshold <= 2 && confidence !== 'low') {
                        status = 'critical_trajectory';
                    }
                    else if (hoursToThreshold !== undefined && hoursToThreshold <= 12 && confidence !== 'low') {
                        status = 'approaching_threshold';
                    }
                    else if (Math.abs(slope) > 0.01 && slope > 0) {
                        status = 'trending_up';
                    }
                    else if (Math.abs(slope) > 0.01 && slope < 0) {
                        status = 'trending_down';
                    }
                    else {
                        status = 'stable';
                    }
                    return [2 /*return*/, {
                            app: app,
                            metric: metric,
                            currentValue: currentValue,
                            slope: Math.round(slope * 1000) / 1000,
                            r2: Math.round(r2 * 1000) / 1000,
                            projectedThreshold: Math.round(threshold * 100) / 100,
                            projectedCrossing: projectedCrossing,
                            hoursToThreshold: hoursToThreshold !== undefined ? Math.round(hoursToThreshold * 10) / 10 : undefined,
                            confidence: confidence,
                            status: status
                        }];
            }
        });
    });
}
exports.analyzeTrend = analyzeTrend;
function scanAllTrends() {
    return __awaiter(this, void 0, void 0, function () {
        var trends, metricNames, _a, tasks, _i, ALL_APP_IDS_1, appId, _b, metricNames_1, metric, results, _c, results_1, result, statusOrder;
        return __generator(this, function (_d) {
            switch (_d.label) {
                case 0:
                    trends = [];
                    metricNames = [];
                    _d.label = 1;
                case 1:
                    _d.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, (0, telemetryLake_1.getMetricNames)()];
                case 2:
                    metricNames = _d.sent();
                    return [3 /*break*/, 4];
                case 3:
                    _a = _d.sent();
                    metricNames = ['event_count', 'error_rate', 'rejection_rate'];
                    return [3 /*break*/, 4];
                case 4:
                    if (metricNames.length === 0) {
                        metricNames = ['event_count', 'error_rate', 'rejection_rate'];
                    }
                    tasks = [];
                    for (_i = 0, ALL_APP_IDS_1 = appClients_1.ALL_APP_IDS; _i < ALL_APP_IDS_1.length; _i++) {
                        appId = ALL_APP_IDS_1[_i];
                        for (_b = 0, metricNames_1 = metricNames; _b < metricNames_1.length; _b++) {
                            metric = metricNames_1[_b];
                            tasks.push(analyzeTrend(appId, metric));
                        }
                    }
                    return [4 /*yield*/, Promise.allSettled(tasks)];
                case 5:
                    results = _d.sent();
                    for (_c = 0, results_1 = results; _c < results_1.length; _c++) {
                        result = results_1[_c];
                        if (result.status === 'fulfilled' && result.value.status !== 'stable') {
                            trends.push(result.value);
                        }
                    }
                    statusOrder = {
                        critical_trajectory: 0,
                        approaching_threshold: 1,
                        trending_up: 2,
                        trending_down: 3,
                        stable: 4
                    };
                    trends.sort(function (a, b) { return statusOrder[a.status] - statusOrder[b.status]; });
                    cachedTrends = trends;
                    lastScanTime = new Date().toISOString();
                    return [2 /*return*/, trends];
            }
        });
    });
}
exports.scanAllTrends = scanAllTrends;
function generatePredictions() {
    var _a, _b;
    return __awaiter(this, void 0, void 0, function () {
        var trends, now, newPredictions, _i, trends_1, trend, predId, suggestedPlaybook, playbooks, _c, playbooks_1, pb, metricMatch, appMatch, _d, newPredictions_1, pred;
        return __generator(this, function (_e) {
            switch (_e.label) {
                case 0: return [4 /*yield*/, scanAllTrends()];
                case 1:
                    trends = _e.sent();
                    now = new Date().toISOString();
                    newPredictions = [];
                    for (_i = 0, trends_1 = trends; _i < trends_1.length; _i++) {
                        trend = trends_1[_i];
                        predId = "pred:".concat(trend.app, ":").concat(trend.metric, ":").concat(Date.now());
                        suggestedPlaybook = void 0;
                        try {
                            playbooks = (0, autoRemediation_1.getPlaybooks)();
                            for (_c = 0, playbooks_1 = playbooks; _c < playbooks_1.length; _c++) {
                                pb = playbooks_1[_c];
                                if (!pb.enabled)
                                    continue;
                                metricMatch = new RegExp(pb.trigger.metricPattern, 'i').test(trend.metric);
                                appMatch = !pb.trigger.appPattern || new RegExp(pb.trigger.appPattern, 'i').test(trend.app);
                                if (metricMatch && appMatch) {
                                    suggestedPlaybook = pb.id;
                                    break;
                                }
                            }
                        }
                        catch (_f) {
                            // No playbooks available
                        }
                        if (trend.status === 'critical_trajectory' && trend.confidence !== 'low') {
                            newPredictions.push({
                                id: predId,
                                app: trend.app,
                                metric: trend.metric,
                                type: 'incident_predicted',
                                severity: 'critical',
                                message: "".concat(trend.metric, " in ").concat(trend.app, " predicted to reach anomaly threshold in ").concat((_a = trend.hoursToThreshold) !== null && _a !== void 0 ? _a : '?', " hours (slope: ").concat(trend.slope, "/hr, R\u00B2: ").concat(trend.r2, ")"),
                                predictedAt: now,
                                predictedEvent: "".concat(trend.metric, " will exceed ").concat(trend.projectedThreshold, " (2.5\u03C3 threshold)"),
                                predictedTime: trend.projectedCrossing || now,
                                confidence: trend.r2,
                                suggestedPlaybook: suggestedPlaybook,
                                acknowledged: false
                            });
                        }
                        else if (trend.status === 'approaching_threshold' && trend.confidence !== 'low') {
                            newPredictions.push({
                                id: predId,
                                app: trend.app,
                                metric: trend.metric,
                                type: 'capacity_warning',
                                severity: 'warning',
                                message: "".concat(trend.metric, " in ").concat(trend.app, " trending toward threshold \u2014 estimated ").concat((_b = trend.hoursToThreshold) !== null && _b !== void 0 ? _b : '?', " hours (slope: ").concat(trend.slope, "/hr)"),
                                predictedAt: now,
                                predictedEvent: "".concat(trend.metric, " may exceed ").concat(trend.projectedThreshold),
                                predictedTime: trend.projectedCrossing || now,
                                confidence: trend.r2,
                                suggestedPlaybook: suggestedPlaybook,
                                acknowledged: false
                            });
                        }
                        else if (trend.status === 'trending_up' && trend.confidence !== 'low') {
                            newPredictions.push({
                                id: predId,
                                app: trend.app,
                                metric: trend.metric,
                                type: 'degradation_detected',
                                severity: 'info',
                                message: "".concat(trend.metric, " in ").concat(trend.app, " is trending upward (slope: ").concat(trend.slope, "/hr, R\u00B2: ").concat(trend.r2, ")"),
                                predictedAt: now,
                                predictedEvent: "Continued increase in ".concat(trend.metric),
                                predictedTime: trend.projectedCrossing || new Date(Date.now() + 24 * 3600000).toISOString(),
                                confidence: trend.r2 * 0.7,
                                suggestedPlaybook: suggestedPlaybook,
                                acknowledged: false
                            });
                        }
                        else if (trend.status === 'trending_down' && trend.currentValue > trend.projectedThreshold * 0.8) {
                            // Was elevated, now coming down
                            newPredictions.push({
                                id: predId,
                                app: trend.app,
                                metric: trend.metric,
                                type: 'recovery_expected',
                                severity: 'info',
                                message: "".concat(trend.metric, " in ").concat(trend.app, " is recovering \u2014 trending down from elevated levels (slope: ").concat(trend.slope, "/hr)"),
                                predictedAt: now,
                                predictedEvent: "".concat(trend.metric, " expected to return to baseline"),
                                predictedTime: new Date(Date.now() + Math.abs(trend.currentValue / trend.slope) * 3600000).toISOString(),
                                confidence: trend.r2 * 0.8,
                                acknowledged: false
                            });
                        }
                    }
                    // Store predictions
                    for (_d = 0, newPredictions_1 = newPredictions; _d < newPredictions_1.length; _d++) {
                        pred = newPredictions_1[_d];
                        activePredictions.set(pred.id, pred);
                    }
                    return [2 /*return*/, newPredictions];
            }
        });
    });
}
exports.generatePredictions = generatePredictions;
function getActivePredictions() {
    return Array.from(activePredictions.values())
        .filter(function (p) { return !p.resolvedAt; })
        .sort(function (a, b) {
        var sevOrder = { critical: 0, warning: 1, info: 2 };
        return sevOrder[a.severity] - sevOrder[b.severity];
    });
}
exports.getActivePredictions = getActivePredictions;
function acknowledgePrediction(id) {
    var pred = activePredictions.get(id);
    if (pred) {
        pred.acknowledged = true;
    }
}
exports.acknowledgePrediction = acknowledgePrediction;
function resolvePrediction(id) {
    var pred = activePredictions.get(id);
    if (pred) {
        pred.resolvedAt = new Date().toISOString();
    }
}
exports.resolvePrediction = resolvePrediction;
function getCachedTrends() {
    return cachedTrends;
}
exports.getCachedTrends = getCachedTrends;
function getLastScanTime() {
    return lastScanTime;
}
exports.getLastScanTime = getLastScanTime;
