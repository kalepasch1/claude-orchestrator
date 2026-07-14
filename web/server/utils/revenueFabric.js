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
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
exports.__esModule = true;
exports.getRevenueTimeline = exports.getPortfolioSummary = exports.fetchAppRevenue = void 0;
/**
 * Revenue Fabric — aggregates billing data from all apps into a unified P&L.
 * Queries each app's billing/transaction tables via the proxy layer (getAppClient).
 */
var appClients_1 = require("./appClients");
// Map each app to its billing table(s)
var BILLING_TABLES = {
    apparently: { table: 'billing_events', amountCol: 'amount', dateCol: 'created_at' },
    tomorrow: { table: 'transactions', amountCol: 'notional_value', dateCol: 'created_at', statusCol: 'status', refundStatus: 'refunded' },
    smarter: { table: 'billing_events', amountCol: 'amount', dateCol: 'created_at' },
    galop: { table: 'transactions', amountCol: 'amount', dateCol: 'created_at' },
    hisanta: { table: 'purchases', amountCol: 'amount', dateCol: 'created_at' },
    pareto: { table: 'transactions', amountCol: 'amount', dateCol: 'created_at' }
};
function monthsAgoISO(months) {
    var d = new Date();
    d.setMonth(d.getMonth() - months);
    d.setDate(1);
    d.setHours(0, 0, 0, 0);
    return d.toISOString();
}
function toYYYYMM(dateStr) {
    return dateStr.slice(0, 7);
}
/**
 * Fetch revenue data for a single app, grouped by month.
 * Returns empty array with a note if the app isn't configured or the table doesn't exist.
 */
function fetchAppRevenue(appId, months) {
    var _a;
    if (months === void 0) { months = 6; }
    return __awaiter(this, void 0, void 0, function () {
        var config, billing, client, since, _b, data, error, byMonth, _i, data_1, row, period, amount, isRefund, bucket, revenues, _c, byMonth_1, _d, period, bucket, err_1;
        return __generator(this, function (_e) {
            switch (_e.label) {
                case 0:
                    config = (0, appClients_1.getAppConfig)(appId);
                    billing = BILLING_TABLES[appId];
                    if (!billing) {
                        return [2 /*return*/, { revenues: [], gap: "".concat(appId, ": no billing table configured") }];
                    }
                    client = (0, appClients_1.getAppClient)(appId);
                    if (!client) {
                        return [2 /*return*/, { revenues: [], gap: "".concat(appId, ": not connected (missing env vars)") }];
                    }
                    since = monthsAgoISO(months);
                    _e.label = 1;
                case 1:
                    _e.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, client
                            .from(billing.table)
                            .select("".concat(billing.amountCol, ", ").concat(billing.dateCol).concat(billing.statusCol ? ', ' + billing.statusCol : ''))
                            .gte(billing.dateCol, since)
                            .order(billing.dateCol, { ascending: true })
                            .limit(10000)];
                case 2:
                    _b = _e.sent(), data = _b.data, error = _b.error;
                    if (error) {
                        // Table probably doesn't exist
                        return [2 /*return*/, { revenues: [], gap: "".concat(appId, ": query failed \u2014 ").concat(error.message) }];
                    }
                    if (!data || data.length === 0) {
                        return [2 /*return*/, { revenues: [], gap: "".concat(appId, ": no billing data in period") }];
                    }
                    byMonth = new Map();
                    for (_i = 0, data_1 = data; _i < data_1.length; _i++) {
                        row = data_1[_i];
                        period = toYYYYMM(row[billing.dateCol]);
                        amount = Number(row[billing.amountCol]) || 0;
                        isRefund = billing.statusCol && billing.refundStatus
                            ? row[billing.statusCol] === billing.refundStatus
                            : amount < 0;
                        if (!byMonth.has(period)) {
                            byMonth.set(period, { total: 0, count: 0, refunds: 0 });
                        }
                        bucket = byMonth.get(period);
                        if (isRefund) {
                            bucket.refunds += Math.abs(amount);
                        }
                        else {
                            bucket.total += amount;
                        }
                        bucket.count++;
                    }
                    revenues = [];
                    for (_c = 0, byMonth_1 = byMonth; _c < byMonth_1.length; _c++) {
                        _d = byMonth_1[_c], period = _d[0], bucket = _d[1];
                        revenues.push({
                            app: appId,
                            appName: config.name,
                            period: period,
                            mrr: bucket.total,
                            transactions: bucket.count,
                            refunds: bucket.refunds,
                            netRevenue: bucket.total - bucket.refunds,
                            currency: 'USD'
                        });
                    }
                    return [2 /*return*/, { revenues: revenues }];
                case 3:
                    err_1 = _e.sent();
                    return [2 /*return*/, { revenues: [], gap: "".concat(appId, ": ").concat((_a = err_1 === null || err_1 === void 0 ? void 0 : err_1.message) !== null && _a !== void 0 ? _a : 'unknown error') }];
                case 4: return [2 /*return*/];
            }
        });
    });
}
exports.fetchAppRevenue = fetchAppRevenue;
/**
 * Aggregate revenue across all apps into a portfolio summary.
 */
function getPortfolioSummary(months) {
    var _a, _b;
    if (months === void 0) { months = 6; }
    return __awaiter(this, void 0, void 0, function () {
        var gaps, allRevenues, results, _i, results_1, result, sortedPeriods, latestPeriod, latestMonth, totalMRR, totalTransactions, totalRefunds, totalNetRevenue, trendMap, _c, allRevenues_1, r, trend;
        return __generator(this, function (_d) {
            switch (_d.label) {
                case 0:
                    gaps = [];
                    allRevenues = [];
                    return [4 /*yield*/, Promise.allSettled(appClients_1.ALL_APP_IDS
                            .filter(function (id) { return id !== 'orchestrator'; }) // orchestrator has no billing
                            .map(function (id) { return fetchAppRevenue(id, months); }))];
                case 1:
                    results = _d.sent();
                    for (_i = 0, results_1 = results; _i < results_1.length; _i++) {
                        result = results_1[_i];
                        if (result.status === 'fulfilled') {
                            allRevenues.push.apply(allRevenues, result.value.revenues);
                            if (result.value.gap)
                                gaps.push(result.value.gap);
                        }
                        else {
                            gaps.push("fetch error: ".concat(result.reason));
                        }
                    }
                    sortedPeriods = __spreadArray([], new Set(allRevenues.map(function (r) { return r.period; })), true).sort();
                    latestPeriod = (_a = sortedPeriods[sortedPeriods.length - 1]) !== null && _a !== void 0 ? _a : '';
                    latestMonth = allRevenues.filter(function (r) { return r.period === latestPeriod; });
                    totalMRR = latestMonth.reduce(function (s, r) { return s + r.mrr; }, 0);
                    totalTransactions = allRevenues.reduce(function (s, r) { return s + r.transactions; }, 0);
                    totalRefunds = allRevenues.reduce(function (s, r) { return s + r.refunds; }, 0);
                    totalNetRevenue = allRevenues.reduce(function (s, r) { return s + r.netRevenue; }, 0);
                    trendMap = new Map();
                    for (_c = 0, allRevenues_1 = allRevenues; _c < allRevenues_1.length; _c++) {
                        r = allRevenues_1[_c];
                        trendMap.set(r.period, ((_b = trendMap.get(r.period)) !== null && _b !== void 0 ? _b : 0) + r.netRevenue);
                    }
                    trend = __spreadArray([], trendMap.entries(), true).sort(function (_a, _b) {
                        var a = _a[0];
                        var b = _b[0];
                        return a.localeCompare(b);
                    })
                        .map(function (_a) {
                        var period = _a[0], revenue = _a[1];
                        return ({ period: period, revenue: revenue });
                    });
                    return [2 /*return*/, {
                            totalMRR: totalMRR,
                            totalTransactions: totalTransactions,
                            totalRefunds: totalRefunds,
                            totalNetRevenue: totalNetRevenue,
                            byApp: allRevenues,
                            trend: trend,
                            gaps: gaps
                        }];
            }
        });
    });
}
exports.getPortfolioSummary = getPortfolioSummary;
/**
 * Revenue timeline for charting — monthly totals across all apps.
 */
function getRevenueTimeline(months) {
    var _a;
    if (months === void 0) { months = 12; }
    return __awaiter(this, void 0, void 0, function () {
        var summary, periodMap, _i, _b, r, bucket;
        return __generator(this, function (_c) {
            switch (_c.label) {
                case 0: return [4 /*yield*/, getPortfolioSummary(months)
                    // Build per-period, per-app breakdown
                ];
                case 1:
                    summary = _c.sent();
                    periodMap = new Map();
                    for (_i = 0, _b = summary.byApp; _i < _b.length; _i++) {
                        r = _b[_i];
                        if (!periodMap.has(r.period))
                            periodMap.set(r.period, {});
                        bucket = periodMap.get(r.period);
                        bucket[r.app] = ((_a = bucket[r.app]) !== null && _a !== void 0 ? _a : 0) + r.netRevenue;
                    }
                    return [2 /*return*/, summary.trend.map(function (t) {
                            var _a;
                            return ({
                                period: t.period,
                                revenue: t.revenue,
                                byApp: (_a = periodMap.get(t.period)) !== null && _a !== void 0 ? _a : {}
                            });
                        })];
            }
        });
    });
}
exports.getRevenueTimeline = getRevenueTimeline;
