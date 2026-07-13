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
exports.exportSnapshotHTML = exports.getSnapshotById = exports.getRecentSnapshots = exports.generateSnapshot = exports.classifyOverallStatus = void 0;
/**
 * Regulatory Snapshot Generator — on-demand compliance report.
 * Pulls current state of all trust_safety events, legal holds, KYC statuses,
 * and audit logs across the fleet into a structured report.
 */
var appClients_1 = require("~/server/utils/appClients");
var COMPLIANCE_QUERIES = {
    apparently: [
        { table: 'admin_board', filters: [{ column: 'status', op: 'neq', value: 'resolved' }], type: 'compliance_alert' },
        { table: 'legal_holds', filters: [{ column: 'active', op: 'eq', value: true }], type: 'legal_hold' },
        { table: 'submission_reviews', filters: [{ column: 'status', op: 'eq', value: 'pending' }], type: 'kyc_pending' },
    ],
    tomorrow: [
        { table: 'disputes', filters: [{ column: 'status', op: 'neq', value: 'resolved' }], type: 'compliance_alert' },
        { table: 'users', filters: [{ column: 'status', op: 'eq', value: 'suspended' }], type: 'flagged_user' },
    ],
    galop: [
        { table: 'compliance_flags', filters: [{ column: 'resolved', op: 'eq', value: false }], type: 'compliance_alert' },
        { table: 'player_bans', filters: [{ column: 'active', op: 'eq', value: true }], type: 'flagged_user' },
    ],
    smarter: [
        { table: 'governance_events', filters: [{ column: 'type', op: 'eq', value: 'kill_switch' }], type: 'compliance_alert' },
    ],
    hisanta: [
        { table: 'flagged_interactions', filters: [{ column: 'resolved', op: 'eq', value: false }], type: 'compliance_alert' },
    ],
    pareto: [
        { table: 'agency_grants', filters: [{ column: 'revoked', op: 'eq', value: false }], type: 'compliance_alert' },
    ]
};
// ---------------------------------------------------------------------------
// Severity classification
// ---------------------------------------------------------------------------
function classifySeverity(type, _row) {
    if (type === 'legal_hold')
        return 'critical';
    if (type === 'flagged_user')
        return 'warning';
    if (type === 'kyc_pending')
        return 'warning';
    if (type === 'compliance_alert')
        return 'warning';
    if (type === 'audit_gap')
        return 'info';
    return 'info';
}
function describeItem(type, row, table) {
    var id = row.id || row.uuid || 'unknown';
    switch (type) {
        case 'legal_hold':
            return "Active legal hold #".concat(id, ": ").concat(row.reason || row.description || 'no description');
        case 'kyc_pending':
            return "Pending KYC review #".concat(id, ": ").concat(row.status || 'pending');
        case 'flagged_user':
            return "Flagged/suspended user #".concat(id, ": ").concat(row.reason || row.email || row.username || 'no details');
        case 'compliance_alert':
            return "Compliance alert from ".concat(table, " #").concat(id, ": ").concat(row.type || row.status || row.description || 'open issue');
        default:
            return "".concat(type, " in ").concat(table, " #").concat(id);
    }
}
// ---------------------------------------------------------------------------
// In-memory snapshot store (production would use DB)
// ---------------------------------------------------------------------------
var snapshotStore = new Map();
function generateId() {
    return "snap-".concat(Date.now(), "-").concat(Math.random().toString(36).slice(2, 8));
}
// ---------------------------------------------------------------------------
// Core functions
// ---------------------------------------------------------------------------
function queryAppCompliance(appId, queries, period) {
    return __awaiter(this, void 0, void 0, function () {
        var client, config, items, _i, queries_1, q, query, _a, _b, f, _c, data, error, retryQuery, _d, _e, f, retry, _f, _g, row, _h, data_1, row, _j, criticals, warnings, status, summary;
        return __generator(this, function (_k) {
            switch (_k.label) {
                case 0:
                    client = (0, appClients_1.getAppClient)(appId);
                    config = (0, appClients_1.getAppConfig)(appId);
                    items = [];
                    if (!client) {
                        return [2 /*return*/, {
                                title: config.name,
                                app: appId,
                                status: 'data_unavailable',
                                items: [],
                                summary: "".concat(config.name, ": Supabase client not configured \u2014 skipped.")
                            }];
                    }
                    _i = 0, queries_1 = queries;
                    _k.label = 1;
                case 1:
                    if (!(_i < queries_1.length)) return [3 /*break*/, 8];
                    q = queries_1[_i];
                    _k.label = 2;
                case 2:
                    _k.trys.push([2, 6, , 7]);
                    query = client.from(q.table).select('*').limit(100);
                    // Apply filters
                    for (_a = 0, _b = q.filters; _a < _b.length; _a++) {
                        f = _b[_a];
                        switch (f.op) {
                            case 'eq':
                                query = query.eq(f.column, f.value);
                                break;
                            case 'neq':
                                query = query.neq(f.column, f.value);
                                break;
                            case 'gt':
                                query = query.gt(f.column, f.value);
                                break;
                            case 'lt':
                                query = query.lt(f.column, f.value);
                                break;
                            case 'gte':
                                query = query.gte(f.column, f.value);
                                break;
                            case 'lte':
                                query = query.lte(f.column, f.value);
                                break;
                        }
                    }
                    // Try to filter by period if the table has a created_at column
                    query = query.gte('created_at', period.from).lte('created_at', period.to);
                    return [4 /*yield*/, query];
                case 3:
                    _c = _k.sent(), data = _c.data, error = _c.error;
                    if (!error) return [3 /*break*/, 5];
                    retryQuery = client.from(q.table).select('*').limit(100);
                    for (_d = 0, _e = q.filters; _d < _e.length; _d++) {
                        f = _e[_d];
                        switch (f.op) {
                            case 'eq':
                                retryQuery = retryQuery.eq(f.column, f.value);
                                break;
                            case 'neq':
                                retryQuery = retryQuery.neq(f.column, f.value);
                                break;
                            case 'gt':
                                retryQuery = retryQuery.gt(f.column, f.value);
                                break;
                            case 'lt':
                                retryQuery = retryQuery.lt(f.column, f.value);
                                break;
                            case 'gte':
                                retryQuery = retryQuery.gte(f.column, f.value);
                                break;
                            case 'lte':
                                retryQuery = retryQuery.lte(f.column, f.value);
                                break;
                        }
                    }
                    return [4 /*yield*/, retryQuery];
                case 4:
                    retry = _k.sent();
                    if (retry.error) {
                        // Table truly doesn't exist or another error — skip silently
                        return [3 /*break*/, 7];
                    }
                    if (retry.data) {
                        for (_f = 0, _g = retry.data; _f < _g.length; _f++) {
                            row = _g[_f];
                            items.push({
                                type: q.type,
                                severity: classifySeverity(q.type, row),
                                description: describeItem(q.type, row, q.table),
                                details: row,
                                timestamp: row.created_at || row.updated_at || new Date().toISOString()
                            });
                        }
                    }
                    return [3 /*break*/, 7];
                case 5:
                    if (data) {
                        for (_h = 0, data_1 = data; _h < data_1.length; _h++) {
                            row = data_1[_h];
                            items.push({
                                type: q.type,
                                severity: classifySeverity(q.type, row),
                                description: describeItem(q.type, row, q.table),
                                details: row,
                                timestamp: row.created_at || row.updated_at || new Date().toISOString()
                            });
                        }
                    }
                    return [3 /*break*/, 7];
                case 6:
                    _j = _k.sent();
                    return [3 /*break*/, 7];
                case 7:
                    _i++;
                    return [3 /*break*/, 1];
                case 8:
                    criticals = items.filter(function (i) { return i.severity === 'critical'; }).length;
                    warnings = items.filter(function (i) { return i.severity === 'warning'; }).length;
                    status = 'clean';
                    if (items.length > 0)
                        status = 'issues_found';
                    summary = "".concat(config.name, ": ").concat(items.length, " item(s) found");
                    if (criticals > 0)
                        summary += " \u2014 ".concat(criticals, " critical");
                    if (warnings > 0)
                        summary += ", ".concat(warnings, " warning(s)");
                    if (items.length === 0)
                        summary = "".concat(config.name, ": No compliance issues detected.");
                    return [2 /*return*/, { title: config.name, app: appId, status: status, items: items, summary: summary }];
            }
        });
    });
}
function classifyOverallStatus(sections) {
    var allItems = sections.flatMap(function (s) { return s.items; });
    var criticals = allItems.filter(function (i) { return i.severity === 'critical'; }).length;
    if (criticals > 0)
        return 'action_required';
    var warnings = allItems.filter(function (i) { return i.severity === 'warning'; }).length;
    if (warnings > 0)
        return 'issues_detected';
    return 'compliant';
}
exports.classifyOverallStatus = classifyOverallStatus;
function generateSnapshot(period) {
    return __awaiter(this, void 0, void 0, function () {
        var now, defaultFrom, resolvedPeriod, sections, appIds, results, _i, results_1, result, allItems, snapshot;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    now = new Date();
                    defaultFrom = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString();
                    resolvedPeriod = {
                        from: (period === null || period === void 0 ? void 0 : period.from) || defaultFrom,
                        to: (period === null || period === void 0 ? void 0 : period.to) || now.toISOString()
                    };
                    sections = [];
                    appIds = Object.keys(COMPLIANCE_QUERIES);
                    return [4 /*yield*/, Promise.allSettled(appIds.map(function (appId) { return queryAppCompliance(appId, COMPLIANCE_QUERIES[appId], resolvedPeriod); }))];
                case 1:
                    results = _a.sent();
                    for (_i = 0, results_1 = results; _i < results_1.length; _i++) {
                        result = results_1[_i];
                        if (result.status === 'fulfilled') {
                            sections.push(result.value);
                        }
                    }
                    allItems = sections.flatMap(function (s) { return s.items; });
                    snapshot = {
                        id: generateId(),
                        generatedAt: now.toISOString(),
                        generatedBy: 'orchestrator',
                        period: resolvedPeriod,
                        sections: sections,
                        summary: {
                            totalApps: sections.length,
                            appsWithIssues: sections.filter(function (s) { return s.status === 'issues_found'; }).length,
                            criticalItems: allItems.filter(function (i) { return i.severity === 'critical'; }).length,
                            warningItems: allItems.filter(function (i) { return i.severity === 'warning'; }).length,
                            overallStatus: classifyOverallStatus(sections)
                        }
                    };
                    snapshotStore.set(snapshot.id, snapshot);
                    return [2 /*return*/, snapshot];
            }
        });
    });
}
exports.generateSnapshot = generateSnapshot;
function getRecentSnapshots() {
    return __awaiter(this, void 0, void 0, function () {
        return __generator(this, function (_a) {
            return [2 /*return*/, __spreadArray([], snapshotStore.values(), true).sort(function (a, b) { return b.generatedAt.localeCompare(a.generatedAt); })
                    .slice(0, 50)
                    .map(function (s) { return ({
                    id: s.id,
                    generatedAt: s.generatedAt,
                    period: s.period,
                    summary: s.summary
                }); })];
        });
    });
}
exports.getRecentSnapshots = getRecentSnapshots;
function getSnapshotById(id) {
    var _a;
    return (_a = snapshotStore.get(id)) !== null && _a !== void 0 ? _a : null;
}
exports.getSnapshotById = getSnapshotById;
function exportSnapshotHTML(snapshot) {
    var statusColors = {
        compliant: '#22c55e',
        issues_detected: '#eab308',
        action_required: '#ef4444'
    };
    var statusLabels = {
        compliant: 'COMPLIANT',
        issues_detected: 'ISSUES DETECTED',
        action_required: 'ACTION REQUIRED'
    };
    var severityColors = {
        info: '#6b7280',
        warning: '#eab308',
        critical: '#ef4444'
    };
    var sectionStatusColors = {
        clean: '#22c55e',
        issues_found: '#eab308',
        data_unavailable: '#6b7280'
    };
    var sectionsHTML = snapshot.sections.map(function (s) { return "\n    <div style=\"margin-bottom:24px;border:1px solid #374151;border-radius:8px;overflow:hidden;\">\n      <div style=\"background:#1f2937;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;\">\n        <h3 style=\"margin:0;font-size:16px;color:#e5e7eb;\">".concat(s.title, "</h3>\n        <span style=\"font-size:12px;font-weight:600;color:").concat(sectionStatusColors[s.status] || '#6b7280', ";\">").concat(s.status.replace('_', ' ').toUpperCase(), "</span>\n      </div>\n      <div style=\"padding:16px;\">\n        ").concat(s.items.length === 0
        ? '<p style="color:#6b7280;font-size:14px;margin:0;">No issues found.</p>'
        : "<table style=\"width:100%;border-collapse:collapse;font-size:13px;\">\n              <thead><tr style=\"border-bottom:1px solid #374151;\">\n                <th style=\"text-align:left;padding:6px 8px;color:#9ca3af;\">Severity</th>\n                <th style=\"text-align:left;padding:6px 8px;color:#9ca3af;\">Type</th>\n                <th style=\"text-align:left;padding:6px 8px;color:#9ca3af;\">Description</th>\n                <th style=\"text-align:left;padding:6px 8px;color:#9ca3af;\">Timestamp</th>\n              </tr></thead>\n              <tbody>".concat(s.items.map(function (item) { return "\n                <tr style=\"border-bottom:1px solid #1f2937;\">\n                  <td style=\"padding:6px 8px;\"><span style=\"color:".concat(severityColors[item.severity], ";font-weight:600;text-transform:uppercase;font-size:11px;\">").concat(item.severity, "</span></td>\n                  <td style=\"padding:6px 8px;color:#d1d5db;\">").concat(item.type, "</td>\n                  <td style=\"padding:6px 8px;color:#d1d5db;\">").concat(item.description, "</td>\n                  <td style=\"padding:6px 8px;color:#9ca3af;font-size:12px;\">").concat(new Date(item.timestamp).toLocaleString(), "</td>\n                </tr>"); }).join(''), "\n              </tbody>\n            </table>"), "\n        <p style=\"margin:12px 0 0;font-size:13px;color:#9ca3af;\">").concat(s.summary, "</p>\n      </div>\n    </div>"); }).join('');
    return "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\">\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n  <title>Regulatory Compliance Snapshot \u2014 ".concat(new Date(snapshot.generatedAt).toLocaleDateString(), "</title>\n  <style>\n    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #111827; color: #e5e7eb; margin: 0; padding: 40px; }\n    @media print { body { background: white; color: #111827; } }\n  </style>\n</head>\n<body>\n  <div style=\"max-width:900px;margin:0 auto;\">\n    <div style=\"display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:32px;\">\n      <div>\n        <h1 style=\"margin:0 0 4px;font-size:24px;color:#e5e7eb;\">Regulatory Compliance Snapshot</h1>\n        <p style=\"margin:0;font-size:14px;color:#9ca3af;\">Generated: ").concat(new Date(snapshot.generatedAt).toLocaleString(), "</p>\n        <p style=\"margin:4px 0 0;font-size:13px;color:#6b7280;\">Period: ").concat(new Date(snapshot.period.from).toLocaleDateString(), " \u2014 ").concat(new Date(snapshot.period.to).toLocaleDateString(), "</p>\n      </div>\n      <div style=\"text-align:right;\">\n        <div style=\"font-size:14px;font-weight:700;color:").concat(statusColors[snapshot.summary.overallStatus], ";border:2px solid ").concat(statusColors[snapshot.summary.overallStatus], ";padding:8px 16px;border-radius:8px;\">\n          ").concat(statusLabels[snapshot.summary.overallStatus], "\n        </div>\n      </div>\n    </div>\n\n    <div style=\"display:grid;grid-template-columns:repeat(4, 1fr);gap:16px;margin-bottom:32px;\">\n      <div style=\"background:#1f2937;border-radius:8px;padding:16px;text-align:center;\">\n        <div style=\"font-size:24px;font-weight:700;color:#e5e7eb;\">").concat(snapshot.summary.totalApps, "</div>\n        <div style=\"font-size:12px;color:#9ca3af;margin-top:4px;\">Apps Scanned</div>\n      </div>\n      <div style=\"background:#1f2937;border-radius:8px;padding:16px;text-align:center;\">\n        <div style=\"font-size:24px;font-weight:700;color:#eab308;\">").concat(snapshot.summary.appsWithIssues, "</div>\n        <div style=\"font-size:12px;color:#9ca3af;margin-top:4px;\">Apps with Issues</div>\n      </div>\n      <div style=\"background:#1f2937;border-radius:8px;padding:16px;text-align:center;\">\n        <div style=\"font-size:24px;font-weight:700;color:#ef4444;\">").concat(snapshot.summary.criticalItems, "</div>\n        <div style=\"font-size:12px;color:#9ca3af;margin-top:4px;\">Critical Items</div>\n      </div>\n      <div style=\"background:#1f2937;border-radius:8px;padding:16px;text-align:center;\">\n        <div style=\"font-size:24px;font-weight:700;color:#eab308;\">").concat(snapshot.summary.warningItems, "</div>\n        <div style=\"font-size:12px;color:#9ca3af;margin-top:4px;\">Warning Items</div>\n      </div>\n    </div>\n\n    ").concat(sectionsHTML, "\n\n    <div style=\"margin-top:32px;padding-top:16px;border-top:1px solid #374151;font-size:11px;color:#6b7280;text-align:center;\">\n      SMRTER OPS \u2014 Regulatory Snapshot ID: ").concat(snapshot.id, " \u2014 Confidential\n    </div>\n  </div>\n</body>\n</html>");
}
exports.exportSnapshotHTML = exportSnapshotHTML;
