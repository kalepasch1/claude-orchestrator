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
exports.compareUsers = exports.getRecentSessions = exports.traceUser = void 0;
/**
 * Cross-App Session Replay — traces user activity across the fleet.
 * Given an email or userId, queries all apps for events involving that user
 * and builds a unified chronological timeline.
 */
var appClients_1 = require("./appClients");
var fleetSupabase_1 = require("./fleetSupabase");
/**
 * Trace a user's activity across all fleet apps.
 * 1. Searches each app for the user by email
 * 2. Queries fleet_admin_events for events mentioning that user
 * 3. Queries fleet_approvals for approval events by that user
 * 4. Merges into a unified timeline
 */
function traceUser(email) {
    var _a, _b, _c;
    return __awaiter(this, void 0, void 0, function () {
        var presence, events, appSearches, sb, fleetEvents, _i, fleetEvents_1, e, _d, approvals, _e, approvals_1, a, _f, auditSearches, apps;
        var _this = this;
        return __generator(this, function (_g) {
            switch (_g.label) {
                case 0:
                    presence = [];
                    events = [];
                    appSearches = appClients_1.ALL_APP_IDS.map(function (appId) { return __awaiter(_this, void 0, void 0, function () {
                        var client, _i, _a, table, data, _b;
                        return __generator(this, function (_c) {
                            switch (_c.label) {
                                case 0:
                                    client = (0, appClients_1.getAppClient)(appId);
                                    if (!client)
                                        return [2 /*return*/];
                                    _c.label = 1;
                                case 1:
                                    _c.trys.push([1, 6, , 7]);
                                    _i = 0, _a = ['users', 'profiles', 'auth_users'];
                                    _c.label = 2;
                                case 2:
                                    if (!(_i < _a.length)) return [3 /*break*/, 5];
                                    table = _a[_i];
                                    return [4 /*yield*/, client
                                            .from(table)
                                            .select('id, email, created_at, last_sign_in_at')
                                            .eq('email', email)
                                            .limit(1)
                                            .maybeSingle()];
                                case 3:
                                    data = (_c.sent()).data;
                                    if (data) {
                                        presence.push({ app: appId, userId: data.id, email: email });
                                        // Add login/signup events if we have timestamps
                                        if (data.created_at) {
                                            events.push({
                                                app: appId,
                                                timestamp: data.created_at,
                                                type: 'login',
                                                description: "Account created in ".concat(appId),
                                                severity: 'info'
                                            });
                                        }
                                        if (data.last_sign_in_at) {
                                            events.push({
                                                app: appId,
                                                timestamp: data.last_sign_in_at,
                                                type: 'login',
                                                description: "Last sign-in to ".concat(appId),
                                                severity: 'info'
                                            });
                                        }
                                        return [3 /*break*/, 5]; // Found user in this app, no need to check other tables
                                    }
                                    _c.label = 4;
                                case 4:
                                    _i++;
                                    return [3 /*break*/, 2];
                                case 5: return [3 /*break*/, 7];
                                case 6:
                                    _b = _c.sent();
                                    return [3 /*break*/, 7];
                                case 7: return [2 /*return*/];
                            }
                        });
                    }); });
                    return [4 /*yield*/, Promise.allSettled(appSearches)
                        // 2. Query fleet_admin_events for events mentioning this user
                    ];
                case 1:
                    _g.sent();
                    sb = (0, fleetSupabase_1.serviceClient)();
                    _g.label = 2;
                case 2:
                    _g.trys.push([2, 4, , 5]);
                    return [4 /*yield*/, sb
                            .from('fleet_admin_events')
                            .select('*')
                            .or("subject_id.eq.".concat(email, ",details->>email.eq.").concat(email, ",details->>actor.eq.").concat(email))
                            .order('at', { ascending: false })
                            .limit(500)];
                case 3:
                    fleetEvents = (_g.sent()).data;
                    if (fleetEvents) {
                        for (_i = 0, fleetEvents_1 = fleetEvents; _i < fleetEvents_1.length; _i++) {
                            e = fleetEvents_1[_i];
                            events.push({
                                app: e.product || 'orchestrator',
                                timestamp: e.at || e.created_at,
                                type: 'fleet_event',
                                description: e.title || e.summary || "".concat(e.category, " event"),
                                details: e.details,
                                severity: e.severity === 'critical' ? 'critical' : e.severity === 'high' ? 'warning' : 'info'
                            });
                        }
                    }
                    return [3 /*break*/, 5];
                case 4:
                    _d = _g.sent();
                    return [3 /*break*/, 5];
                case 5:
                    _g.trys.push([5, 7, , 8]);
                    return [4 /*yield*/, sb
                            .from('fleet_approvals')
                            .select('*')
                            .eq('approver', email)
                            .order('decided_at', { ascending: false })
                            .limit(200)];
                case 6:
                    approvals = (_g.sent()).data;
                    if (approvals) {
                        for (_e = 0, approvals_1 = approvals; _e < approvals_1.length; _e++) {
                            a = approvals_1[_e];
                            events.push({
                                app: a.product || 'orchestrator',
                                timestamp: a.decided_at || a.created_at,
                                type: 'approval',
                                description: "".concat(a.status, ": ").concat(a.title),
                                details: { tier: a.tier, domain: a.domain, note: a.note },
                                severity: a.status === 'rejected' ? 'warning' : 'info'
                            });
                        }
                    }
                    return [3 /*break*/, 8];
                case 7:
                    _f = _g.sent();
                    return [3 /*break*/, 8];
                case 8:
                    auditSearches = presence.map(function (p) { return __awaiter(_this, void 0, void 0, function () {
                        var client, auditRows, _i, auditRows_1, row, _a;
                        return __generator(this, function (_b) {
                            switch (_b.label) {
                                case 0:
                                    client = (0, appClients_1.getAppClient)(p.app);
                                    if (!client)
                                        return [2 /*return*/];
                                    _b.label = 1;
                                case 1:
                                    _b.trys.push([1, 3, , 4]);
                                    return [4 /*yield*/, client
                                            .from('audit_log')
                                            .select('action, created_at, details, severity')
                                            .eq('user_id', p.userId || '')
                                            .order('created_at', { ascending: false })
                                            .limit(100)];
                                case 2:
                                    auditRows = (_b.sent()).data;
                                    if (auditRows) {
                                        for (_i = 0, auditRows_1 = auditRows; _i < auditRows_1.length; _i++) {
                                            row = auditRows_1[_i];
                                            events.push({
                                                app: p.app,
                                                timestamp: row.created_at,
                                                type: 'action',
                                                description: row.action || 'User action',
                                                details: row.details,
                                                severity: row.severity || 'info'
                                            });
                                        }
                                    }
                                    return [3 /*break*/, 4];
                                case 3:
                                    _a = _b.sent();
                                    return [3 /*break*/, 4];
                                case 4: return [2 /*return*/];
                            }
                        });
                    }); });
                    return [4 /*yield*/, Promise.allSettled(auditSearches)
                        // Sort timeline chronologically
                    ];
                case 9:
                    _g.sent();
                    // Sort timeline chronologically
                    events.sort(function (a, b) { return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(); });
                    apps = __spreadArray([], new Set(presence.map(function (p) { return p.app; })), true);
                    return [2 /*return*/, {
                            email: email,
                            userId: (_a = presence[0]) === null || _a === void 0 ? void 0 : _a.userId,
                            apps: apps,
                            timeline: events,
                            firstSeen: ((_b = events[0]) === null || _b === void 0 ? void 0 : _b.timestamp) || '',
                            lastSeen: ((_c = events[events.length - 1]) === null || _c === void 0 ? void 0 : _c.timestamp) || '',
                            totalEvents: events.length
                        }];
            }
        });
    });
}
exports.traceUser = traceUser;
/**
 * Get summaries of recently active users across the fleet.
 */
function getRecentSessions(limit) {
    var _a, _b;
    if (limit === void 0) { limit = 20; }
    return __awaiter(this, void 0, void 0, function () {
        var sb, results, recentEvents, seen, _i, recentEvents_1, e, email, _c, recentApprovals, seen, _d, recentApprovals_1, a, _e;
        return __generator(this, function (_f) {
            switch (_f.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    results = [];
                    _f.label = 1;
                case 1:
                    _f.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, sb
                            .from('fleet_admin_events')
                            .select('product, subject_id, title, category, at, details')
                            .order('at', { ascending: false })
                            .limit(200)];
                case 2:
                    recentEvents = (_f.sent()).data;
                    if (recentEvents) {
                        seen = new Set();
                        for (_i = 0, recentEvents_1 = recentEvents; _i < recentEvents_1.length; _i++) {
                            e = recentEvents_1[_i];
                            email = e.subject_id || ((_a = e.details) === null || _a === void 0 ? void 0 : _a.email) || ((_b = e.details) === null || _b === void 0 ? void 0 : _b.actor);
                            if (!email || typeof email !== 'string' || !email.includes('@'))
                                continue;
                            if (seen.has(email))
                                continue;
                            seen.add(email);
                            results.push({
                                email: email,
                                lastSeen: e.at,
                                app: e.product || 'orchestrator',
                                eventType: e.category || 'event',
                                description: e.title || 'Fleet event'
                            });
                            if (results.length >= limit)
                                break;
                        }
                    }
                    return [3 /*break*/, 4];
                case 3:
                    _c = _f.sent();
                    return [3 /*break*/, 4];
                case 4:
                    _f.trys.push([4, 6, , 7]);
                    return [4 /*yield*/, sb
                            .from('fleet_approvals')
                            .select('approver, product, title, status, decided_at')
                            .not('approver', 'is', null)
                            .order('decided_at', { ascending: false })
                            .limit(50)];
                case 5:
                    recentApprovals = (_f.sent()).data;
                    if (recentApprovals) {
                        seen = new Set(results.map(function (r) { return r.email; }));
                        for (_d = 0, recentApprovals_1 = recentApprovals; _d < recentApprovals_1.length; _d++) {
                            a = recentApprovals_1[_d];
                            if (!a.approver || seen.has(a.approver))
                                continue;
                            seen.add(a.approver);
                            results.push({
                                email: a.approver,
                                lastSeen: a.decided_at,
                                app: a.product || 'orchestrator',
                                eventType: 'approval',
                                description: "".concat(a.status, ": ").concat(a.title)
                            });
                            if (results.length >= limit)
                                break;
                        }
                    }
                    return [3 /*break*/, 7];
                case 6:
                    _e = _f.sent();
                    return [3 /*break*/, 7];
                case 7: return [2 /*return*/, results.slice(0, limit)];
            }
        });
    });
}
exports.getRecentSessions = getRecentSessions;
/**
 * Compare activity timelines for multiple users side by side.
 */
function compareUsers(emails) {
    return __awaiter(this, void 0, void 0, function () {
        var sessions;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, Promise.all(emails.map(function (e) { return traceUser(e); }))];
                case 1:
                    sessions = _a.sent();
                    return [2 /*return*/, sessions];
            }
        });
    });
}
exports.compareUsers = compareUsers;
