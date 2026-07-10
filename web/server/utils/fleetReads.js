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
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
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
Object.defineProperty(exports, "__esModule", { value: true });
exports.resolvedHistory = resolvedHistory;
exports.approverDecisions = approverDecisions;
exports.exposureFor = exposureFor;
exports.appTypeStats = appTypeStats;
exports.executionOutcomes = executionOutcomes;
exports.historyWithOutcomes = historyWithOutcomes;
exports.settledDecisions = settledDecisions;
exports.pendingDecisions = pendingDecisions;
exports.ledgerEntries = ledgerEntries;
var OUTCOME = { approved: 'approve', modified: 'modify', rejected: 'reject' };
/** Human-resolved approvals joined to their action = the decision log for replay/learning. */
function resolvedHistory(sb) {
    return __awaiter(this, void 0, void 0, function () {
        var data;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, sb
                        .from('fleet_approvals')
                        .select('status, act:fleet_admin_actions(domain,type,amount_usd,reversibility,blast_radius,created_at)')
                        .neq('status', 'pending')
                        .limit(5000)];
                case 1:
                    data = (_a.sent()).data;
                    return [2 /*return*/, (data !== null && data !== void 0 ? data : [])
                            .filter(function (r) { return r.act && OUTCOME[r.status]; })
                            .map(function (r) {
                            var _a;
                            return ({
                                domain: r.act.domain, type: r.act.type, amountUsd: (_a = r.act.amount_usd) !== null && _a !== void 0 ? _a : undefined,
                                reversibility: r.act.reversibility, blastRadius: r.act.blast_radius,
                                outcome: OUTCOME[r.status], at: r.act.created_at,
                            });
                        })];
            }
        });
    });
}
function approverDecisions(sb) {
    return __awaiter(this, void 0, void 0, function () {
        var data;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, sb
                        .from('fleet_approvals')
                        .select('status, decided_at, note, act:fleet_admin_actions(domain,type)')
                        .neq('status', 'pending')
                        .limit(5000)];
                case 1:
                    data = (_a.sent()).data;
                    return [2 /*return*/, (data !== null && data !== void 0 ? data : [])
                            .filter(function (r) { return r.act && OUTCOME[r.status]; })
                            .map(function (r) {
                            var _a;
                            return ({
                                domain: r.act.domain, actionType: r.act.type, outcome: OUTCOME[r.status],
                                at: (_a = r.decided_at) !== null && _a !== void 0 ? _a : new Date().toISOString(),
                            });
                        })];
            }
        });
    });
}
/** Historical $ occurrences of an action-type across apps, to size the blast radius. */
function exposureFor(sb, domain, actionType) {
    return __awaiter(this, void 0, void 0, function () {
        var data;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, sb
                        .from('fleet_admin_actions')
                        .select('product,amount_usd,created_at')
                        .eq('domain', domain)
                        .eq('type', actionType)
                        .limit(5000)];
                case 1:
                    data = (_a.sent()).data;
                    return [2 /*return*/, (data !== null && data !== void 0 ? data : []).map(function (r) { var _a; return ({ product: r.product, amountUsd: (_a = r.amount_usd) !== null && _a !== void 0 ? _a : undefined, at: r.created_at }); })];
            }
        });
    });
}
/** Per-(app, domain, type) clean-rate stats → federated precedent (privacy-walled). */
function appTypeStats(sb) {
    return __awaiter(this, void 0, void 0, function () {
        var data, map, _i, _a, r, k, s;
        var _b;
        return __generator(this, function (_c) {
            switch (_c.label) {
                case 0: return [4 /*yield*/, sb
                        .from('fleet_approvals')
                        .select('status, act:fleet_admin_actions(product,domain,type)')
                        .neq('status', 'pending')
                        .limit(5000)];
                case 1:
                    data = (_c.sent()).data;
                    map = new Map();
                    for (_i = 0, _a = (data !== null && data !== void 0 ? data : []); _i < _a.length; _i++) {
                        r = _a[_i];
                        if (!r.act)
                            continue;
                        k = "".concat(r.act.product, "::").concat(r.act.domain, "::").concat(r.act.type);
                        s = (_b = map.get(k)) !== null && _b !== void 0 ? _b : { product: r.act.product, domain: r.act.domain, actionType: r.act.type, total: 0, cleanApprovals: 0 };
                        s.total += 1;
                        if (r.status === 'approved')
                            s.cleanApprovals += 1;
                        map.set(k, s);
                    }
                    return [2 /*return*/, __spreadArray([], map.values(), true)];
            }
        });
    });
}
/** Recent execute outcomes per app → adapter health. */
function executionOutcomes(sb) {
    return __awaiter(this, void 0, void 0, function () {
        var data;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, sb
                        .from('fleet_admin_actions')
                        .select('product,executed,error,executed_at,created_at')
                        .not('executed_at', 'is', null)
                        .order('executed_at', { ascending: false })
                        .limit(2000)];
                case 1:
                    data = (_a.sent()).data;
                    return [2 /*return*/, (data !== null && data !== void 0 ? data : []).map(function (r) { var _a, _b; return ({ product: r.product, ok: r.executed && !r.error, error: (_a = r.error) !== null && _a !== void 0 ? _a : undefined, at: (_b = r.executed_at) !== null && _b !== void 0 ? _b : r.created_at }); })];
            }
        });
    });
}
/** Actions + their human outcome (by id) → rule-market backtests. */
function historyWithOutcomes(sb) {
    return __awaiter(this, void 0, void 0, function () {
        var data, actions, outcomes, _i, _a, r;
        var _b, _c;
        return __generator(this, function (_d) {
            switch (_d.label) {
                case 0: return [4 /*yield*/, sb
                        .from('fleet_approvals')
                        .select('status, act:fleet_admin_actions(id,product,domain,type,actor,subject_id,amount_usd,confidence,reversibility,blast_radius,intent,created_at)')
                        .neq('status', 'pending')
                        .limit(3000)];
                case 1:
                    data = (_d.sent()).data;
                    actions = [];
                    outcomes = {};
                    for (_i = 0, _a = (data !== null && data !== void 0 ? data : []); _i < _a.length; _i++) {
                        r = _a[_i];
                        if (!r.act || !OUTCOME[r.status])
                            continue;
                        actions.push({
                            id: r.act.id, product: r.act.product, domain: r.act.domain, type: r.act.type, actor: r.act.actor,
                            subjectId: (_b = r.act.subject_id) !== null && _b !== void 0 ? _b : undefined, amountUsd: (_c = r.act.amount_usd) !== null && _c !== void 0 ? _c : undefined, confidence: Number(r.act.confidence),
                            reversibility: r.act.reversibility, blastRadius: r.act.blast_radius, intent: r.act.intent, at: r.act.created_at,
                        });
                        outcomes[r.act.id] = OUTCOME[r.status];
                    }
                    return [2 /*return*/, { actions: actions, outcomes: outcomes }];
            }
        });
    });
}
/** All routed actions (+ resolved outcome) → the treasury P&L. */
function settledDecisions(sb) {
    return __awaiter(this, void 0, void 0, function () {
        var data;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, sb
                        .from('fleet_admin_actions')
                        .select('domain,decision,tier,amount_usd, appr:fleet_approvals(status)')
                        .not('decision', 'is', null)
                        .limit(10000)];
                case 1:
                    data = (_a.sent()).data;
                    return [2 /*return*/, (data !== null && data !== void 0 ? data : []).map(function (r) {
                            var _a, _b, _c, _d;
                            return ({
                                domain: r.domain, tier: (_a = r.tier) !== null && _a !== void 0 ? _a : 'human', decision: r.decision, amountUsd: (_b = r.amount_usd) !== null && _b !== void 0 ? _b : undefined,
                                outcome: ((_d = (_c = r.appr) === null || _c === void 0 ? void 0 : _c[0]) === null || _d === void 0 ? void 0 : _d.status) ? OUTCOME[r.appr[0].status] : undefined,
                            });
                        })];
            }
        });
    });
}
/** Pending approvals (+ subject) → dependency-aware bundling. */
function pendingDecisions(sb) {
    return __awaiter(this, void 0, void 0, function () {
        var data;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, sb
                        .from('fleet_approvals')
                        .select('action_id, domain, priority, act:fleet_admin_actions(type,subject_id)')
                        .eq('status', 'pending')
                        .limit(500)];
                case 1:
                    data = (_a.sent()).data;
                    return [2 /*return*/, (data !== null && data !== void 0 ? data : []).filter(function (r) { return r.act; }).map(function (r) {
                            var _a;
                            return ({
                                actionId: r.action_id, subjectId: (_a = r.act.subject_id) !== null && _a !== void 0 ? _a : undefined, domain: r.domain, type: r.act.type, priority: r.priority,
                            });
                        })];
            }
        });
    });
}
function ledgerEntries(sb) {
    return __awaiter(this, void 0, void 0, function () {
        var data;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, sb.from('fleet_autonomy_ledger').select('*')];
                case 1:
                    data = (_a.sent()).data;
                    return [2 /*return*/, (data !== null && data !== void 0 ? data : []).map(function (r) {
                            var _a, _b;
                            return ({
                                actionType: r.action_type, domain: r.domain, streak: r.streak, total: r.total,
                                cleanApprovals: r.clean_approvals, edits: r.edits, rejections: r.rejections,
                                promotedTier: (_a = r.promoted_tier) !== null && _a !== void 0 ? _a : undefined, promotedAt: (_b = r.promoted_at) !== null && _b !== void 0 ? _b : undefined, updatedAt: r.updated_at,
                            });
                        })];
            }
        });
    });
}
